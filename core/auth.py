import json
import os
import re
import threading
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path
from typing import Optional, Tuple

from flask import session, request, flash, redirect, url_for
from flask_login import LoginManager, UserMixin, current_user
from werkzeug.security import generate_password_hash, check_password_hash

login_manager = LoginManager()

# File-based rate limit storage (persists across workers)
_RATE_LIMIT_FILE = Path("data/login_attempts.json")
_RATE_LIMIT_LOCK = threading.Lock()
MAX_LOGIN_ATTEMPTS = 5
LOGIN_WINDOW = timedelta(minutes=15)
SESSION_TIMEOUT = timedelta(hours=2)


def _load_rate_limits() -> dict:
    try:
        if _RATE_LIMIT_FILE.exists():
            return json.loads(_RATE_LIMIT_FILE.read_text())
    except Exception:
        pass
    return {}


def _save_rate_limits(data: dict) -> None:
    try:
        _RATE_LIMIT_FILE.parent.mkdir(parents=True, exist_ok=True)
        _RATE_LIMIT_FILE.write_text(json.dumps(data))
    except Exception:
        pass

# Tenant manager reference — set by init_auth()
_tm = None


class User(UserMixin):
    def __init__(self, row_id: int, email: str, password_hash: str,
                 role: str, display_name: str, tenant_id: str):
        self.id = f"{tenant_id}:{row_id}"
        self.db_id = row_id
        self.email = email
        self.password_hash = password_hash
        self.role = role
        self.display_name = display_name
        self.tenant_id = tenant_id

    def get_id(self) -> str:
        return self.id

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    @property
    def is_active(self) -> bool:
        return True


def init_auth(app, tenant_manager):
    """Initialize Flask-Login with the application and tenant manager.

    Args:
        app: The Flask application.
        tenant_manager: The TenantManager instance for database access.
    """
    global _tm
    _tm = tenant_manager

    login_manager.init_app(app)
    login_manager.login_view = None
    login_manager.login_message = "Please log in to continue."

    @login_manager.user_loader
    def load_user(user_id: str) -> Optional[User]:
        parts = user_id.split(":", 1)
        if len(parts) != 2:
            return None
        tenant_id, user_db_id = parts
        try:
            conn = _tm.get_connection(tenant_id)
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE id = ?", (int(user_db_id),))
            row = cursor.fetchone()
            if row:
                return User(
                    row_id=row["id"],
                    email=row["email"],
                    password_hash=row["password_hash"],
                    role=row["role"],
                    display_name=row["display_name"],
                    tenant_id=tenant_id,
                )
        except Exception:
            pass
        return None

    return login_manager


def _check_rate_limit() -> bool:
    ip = request.remote_addr or "unknown"
    now = datetime.now()
    with _RATE_LIMIT_LOCK:
        data = _load_rate_limits()
        if ip not in data:
            data[ip] = []
        data[ip] = [
            t for t in data[ip] if (now - datetime.fromisoformat(t)).total_seconds() < LOGIN_WINDOW.total_seconds()
        ]
        _save_rate_limits(data)
        return len(data[ip]) < MAX_LOGIN_ATTEMPTS


def _record_attempt(success: bool = True) -> None:
    ip = request.remote_addr or "unknown"
    with _RATE_LIMIT_LOCK:
        data = _load_rate_limits()
        if success:
            data.pop(ip, None)
        else:
            data.setdefault(ip, []).append(datetime.now().isoformat())
        _save_rate_limits(data)


def find_user_by_email(email: str):
    """Search all tenant databases for a user by email.

    Returns:
        Tuple of (user_row_dict, tenant_id, tenant_type) or (None, None, None).
    """
    if not _tm:
        return None, None, None

    email_lower = email.lower().strip()

    direct_tenants = _tm.list_tenants("direct")
    for tenant_id in direct_tenants:
        try:
            conn = _tm.get_connection(tenant_id)
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE LOWER(email) = ?", (email_lower,))
            row = cursor.fetchone()
            if row:
                return dict(row), tenant_id, "direct"
        except Exception:
            continue

    return None, None, None


def add_user_to_tenant(email: str, password: str, role: str = "user",
                       display_name: str = "", tenant_id: str = "",
                       tenant_type: str = "direct") -> dict:
    """Create a new user in the specified tenant database.

    Args:
        email: User email address.
        password: Plain text password (will be hashed).
        role: User role (default 'user').
        display_name: Human-readable name.
        tenant_id: The tenant identifier.
        tenant_type: 'direct'.

    Returns:
        Dict with 'success': True and 'user_id' on success,
        or 'success': False and 'error' message.
    """
    _validate_password(password)

    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        raise ValueError("Invalid email format.")

    if not _tm:
        raise RuntimeError("Tenant manager not initialized.")

    password_hash = generate_password_hash(password)
    now = datetime.utcnow().isoformat()

    try:
        conn = _tm.get_connection(tenant_id, tenant_type)
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO users (email, password_hash, role, display_name, tenant_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (email.lower().strip(), password_hash, role, display_name, tenant_id, now),
        )
        conn.commit()
        return {"success": True, "user_id": cursor.lastrowid}
    except Exception as e:
        if "UNIQUE constraint" in str(e):
            raise ValueError("A user with this email already exists in this tenant.")
        raise RuntimeError(f"Failed to create user: {e}")


def _validate_password(password: str) -> None:
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters.")
    if not re.search(r"\d", password):
        raise ValueError("Password must contain at least one number.")
    if not re.search(r"[!@#$%^&*(),.?\":{}|<>_\-+=\[\]\\;'/`~]", password):
        raise ValueError("Password must contain at least one special character.")


def validate_password(password: str) -> Tuple[bool, str]:
    """Validate password strength. Returns (is_valid, error_message)."""
    try:
        _validate_password(password)
        return True, ""
    except ValueError as e:
        return False, str(e)


# ---------------------------------------------------------------------------
# Decorators
# ---------------------------------------------------------------------------

def login_required(f):
    """Decorator that requires the user to be authenticated (any role)."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            flash("Please log in to continue.")
            return redirect(url_for("client_login"))
        return f(*args, **kwargs)
    return decorated

# Backward compatibility alias
client_required = login_required


def create_user_and_tenant(email: str, password: str, display_name: str = "") -> dict:
    """Create a new tenant database and user account in one step.

    Args:
        email: User email address.
        password: Plain text password (will be hashed).
        display_name: Human-readable name.

    Returns:
        Dict with 'success', 'user_id', 'tenant_id', and 'password' or 'error'.
    """
    import secrets

    if not _tm:
        raise RuntimeError("Tenant manager not initialized.")

    tenant_id = email.lower().split('@')[0].replace('.', '-').replace('_', '-')[:40]

    try:
        _tm.create_tenant_database(tenant_id, "direct")
    except Exception as e:
        return {"success": False, "error": f"Failed to create tenant: {str(e)}"}

    try:
        result = add_user_to_tenant(
            email=email,
            password=password,
            role="user",
            display_name=display_name or email.split('@')[0],
            tenant_id=tenant_id,
            tenant_type="direct"
        )
        result["tenant_id"] = tenant_id
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}

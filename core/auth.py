import re
from datetime import datetime, timedelta
from functools import wraps
from typing import Optional, Tuple

from flask import session, request, flash, redirect, url_for
from flask_login import LoginManager, UserMixin, current_user
from werkzeug.security import generate_password_hash, check_password_hash

login_manager = LoginManager()

_login_attempts: dict = {}
MAX_LOGIN_ATTEMPTS = 5
LOGIN_WINDOW = timedelta(minutes=15)
SESSION_TIMEOUT = timedelta(hours=2)

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
    if ip not in _login_attempts:
        _login_attempts[ip] = []
    _login_attempts[ip] = [
        t for t in _login_attempts[ip] if now - t < LOGIN_WINDOW
    ]
    return len(_login_attempts[ip]) < MAX_LOGIN_ATTEMPTS


def _record_attempt(success: bool = True) -> None:
    ip = request.remote_addr or "unknown"
    if success:
        _login_attempts.pop(ip, None)
    else:
        _login_attempts.setdefault(ip, []).append(datetime.now())


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


def add_user_to_tenant(email: str, password: str, role: str,
                       display_name: str, tenant_id: str,
                       tenant_type: str = "direct") -> dict:
    """Create a new user in the specified tenant database.

    Args:
        email: User email address.
        password: Plain text password (will be hashed).
        role: 'client' or 'affiliate'.
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

    valid_roles = ("client", "affiliate")
    if role not in valid_roles:
        raise ValueError(f"Role must be one of {valid_roles}.")

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
# Role-based decorators
# ---------------------------------------------------------------------------

def client_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            flash("Please log in to continue.")
            return redirect(url_for("client_login"))
        if current_user.role != "client":
            flash("Client access required.")
            return redirect(url_for("client_login"))
        return f(*args, **kwargs)
    return decorated


def affiliate_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            flash("Please log in to continue.")
            return redirect(url_for("affiliate_login"))
        if current_user.role != "affiliate":
            flash("Affiliate access required.")
            return redirect(url_for("affiliate_login"))
        return f(*args, **kwargs)
    return decorated


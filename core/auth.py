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

from core import database

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


class User(UserMixin):
    def __init__(self, row_id: int, email: str, password_hash: str,
                 role: str, display_name: str):
        self.id = row_id
        self.email = email
        self.password_hash = password_hash
        self.role = role
        self.display_name = display_name

    def get_id(self) -> str:
        return str(self.id)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    @property
    def is_active(self) -> bool:
        return True

    @property
    def tenant_id(self) -> str:
        return str(self.id)


def init_auth(app):
    """Initialize Flask-Login with the application."""
    login_manager.init_app(app)
    login_manager.login_view = None
    login_manager.login_message = "Please log in to continue."

    @login_manager.user_loader
    def load_user(user_id: str) -> Optional[User]:
        try:
            row = database.get_user_by_id(int(user_id))
            if row:
                return User(
                    row_id=row["id"],
                    email=row["email"],
                    password_hash=row["password_hash"],
                    role=row["role"],
                    display_name=row["display_name"],
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


def find_user_by_email(email: str) -> Optional[dict]:
    """Find a user by email in the single platform database."""
    return database.get_user_by_email(email.lower().strip())


def add_user_to_tenant(email: str, password: str, role: str = "user",
                       display_name: str = "", tenant_id: str = "",
                       tenant_type: str = "direct") -> dict:
    """Create a new user in the platform database."""
    return create_user(email, password, role, display_name)


def create_user(email: str, password: str, role: str = "user",
                display_name: str = "") -> dict:
    """Validate password, hash it, and create a user in the platform DB."""
    _validate_password(password)

    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        raise ValueError("Invalid email format.")

    password_hash = generate_password_hash(password)

    try:
        uid = database.create_user(email.lower().strip(), password_hash, role, display_name)
        return {"success": True, "user_id": uid}
    except Exception as e:
        if "UNIQUE" in str(e):
            raise ValueError("A user with this email already exists.")
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


client_required = login_required


def create_user_and_tenant(email: str, password: str, display_name: str = "") -> dict:
    """Create a user account (no separate tenant DB anymore)."""
    try:
        result = create_user(email, password, "user", display_name)
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}

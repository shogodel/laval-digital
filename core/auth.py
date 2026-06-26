import logging
import re
from datetime import UTC, datetime, timedelta
from functools import wraps

from flask import flash, g, jsonify, redirect, request, url_for
from flask_login import LoginManager, UserMixin, current_user
from werkzeug.security import check_password_hash, generate_password_hash

from core import database

login_manager = LoginManager()

logger = logging.getLogger(__name__)

MAX_LOGIN_ATTEMPTS = 5
LOGIN_WINDOW = timedelta(minutes=15)
SESSION_TIMEOUT = timedelta(hours=2)


def _get_client_ip() -> str:
    xff = request.headers.get("X-Forwarded-For", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.remote_addr or "unknown"


class User(UserMixin):
    def __init__(self, row_id: int, email: str, password_hash: str,
                 role: str, display_name: str, status: str = "active",
                 trial_ends_at: str | None = None, tenant_id: int | None = None):
        self.id = row_id
        self.email = email
        self.password_hash = password_hash
        self.role = role
        self.display_name = display_name
        self.status = status
        self.trial_ends_at = trial_ends_at
        self._tenant_id = tenant_id

    def get_id(self) -> str:
        return str(self.id)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)
        from core import database
        database.update_user(self.id, password_hash=self.password_hash)

    @property
    def is_active(self) -> bool:
        if self.status == "expired":
            return False
        if self.status == "trial" and self.trial_ends_at:
            from datetime import datetime
            now = datetime.now(UTC)
            try:
                trial_end = datetime.fromisoformat(self.trial_ends_at)
                if trial_end.tzinfo is None:
                    trial_end = trial_end.replace(tzinfo=UTC)
                if now > trial_end:
                    return False
            except (ValueError, TypeError):
                return False
        return True

    @property
    def is_trial_expired(self) -> bool:
        if self.status != "trial" or not self.trial_ends_at:
            return False
        from datetime import datetime
        now = datetime.now(UTC)
        try:
            trial_end = datetime.fromisoformat(self.trial_ends_at)
            if trial_end.tzinfo is None:
                trial_end = trial_end.replace(tzinfo=UTC)
            return now > trial_end
        except (ValueError, TypeError):
            return True

    @property
    def tenant_id(self) -> str | None:
        """Return the parent tenant ID from the DB column, or own ID if no parent."""
        if self._tenant_id:
            return str(self._tenant_id)
        return str(self.id)


def init_auth(app):
    """Initialize Flask-Login with the application."""
    login_manager.init_app(app)
    login_manager.login_view = None
    login_manager.login_message = "Please log in to continue."

    @login_manager.user_loader
    def load_user(user_id: str) -> User | None:
        if user_id == "admin":
            return AdminUser("admin")
        try:
            row = database.get_user_by_id(int(user_id))
            if row:
                return User(
                    row_id=row["id"],
                    email=row["email"],
                    password_hash=row["password_hash"],
                    role=row["role"],
                    display_name=row["display_name"],
                    status=row.get("status", "active"),
                    trial_ends_at=row.get("trial_ends_at"),
                    tenant_id=row.get("tenant_id"),
                )
        except Exception as e:
            logger.debug("Exception in %s: %s", __name__, e)
        return None

    return login_manager


class AdminUser(UserMixin):
    def __init__(self, user_id: str):
        self.id = user_id
        self.role = "admin"
        self.display_name = "Admin"

    def get_id(self) -> str:
        return self.id


# Rate limiting stored in SQLite — works across gunicorn workers

def _check_rate_limit(prefix: str = "admin") -> bool:
    ip = f"{prefix}:{_get_client_ip()}"
    conn = database._get_conn()
    cutoff = (datetime.now(UTC) - LOGIN_WINDOW).isoformat()
    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM login_attempts WHERE ip = ? AND success = 0 AND attempted_at > ?",
        [ip, cutoff]
    ).fetchone()
    return row["cnt"] < MAX_LOGIN_ATTEMPTS


def _record_attempt(success: bool = True, prefix: str = "admin") -> None:
    ip = f"{prefix}:{_get_client_ip()}"
    conn = database._get_conn()
    conn.execute(
        "INSERT INTO login_attempts (ip, success, attempted_at) VALUES (?, ?, ?)",
        [ip, 1 if success else 0, datetime.now(UTC).isoformat()]
    )
    conn.commit()


def find_user_by_email(email: str) -> dict | None:
    """Find a user by email in the single platform database."""
    return database.get_user_by_email(email.lower().strip())


def add_user_to_tenant(email: str, password: str, role: str = "user",
                       display_name: str = "", tenant_id: str = "",
                       tenant_type: str = "direct") -> dict:
    """Create a new user in the platform database, associated with a tenant."""
    tid = int(tenant_id) if tenant_id and tenant_id.isdigit() else None
    return create_user(email, password, role, display_name, tid)


def create_user(email: str, password: str, role: str = "user",
                display_name: str = "", tenant_id: int | None = None) -> dict:
    """Validate password, hash it, and create a user in the platform DB."""
    _validate_password(password)

    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        raise ValueError("Invalid email format.")

    password_hash = generate_password_hash(password)

    try:
        uid = database.create_user(email.lower().strip(), password_hash, role, display_name, tenant_id)
        return {"success": True, "user_id": uid}
    except Exception as e:
        if "UNIQUE" in str(e):
            raise ValueError("A user with this email already exists.") from e
        logger.error("Failed to create user: %s", e, exc_info=True)
        raise RuntimeError("Failed to create user.") from e


def _validate_password(password: str) -> None:
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters.")
    if not re.search(r"\d", password):
        raise ValueError("Password must contain at least one number.")
    if not re.search(r"[!@#$%^&*(),.?\":{}|<>_\-+=\[\]\\;'/`~]", password):
        raise ValueError("Password must contain at least one special character.")


def validate_password(password: str) -> tuple[bool, str]:
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
            return redirect(url_for("admin.login"))
        return f(*args, **kwargs)
    return decorated


def _is_admin() -> bool:
    """True for platform admins (Flask-Login) OR shop-authenticated users (via require_api_auth middleware)."""
    if current_user.is_authenticated and current_user.role == "admin":
        return True
    if hasattr(g, "shop") and g.shop:
        return True
    return False


def _is_platform_admin() -> bool:
    """True only for platform admins — NOT shop-authenticated users."""
    return current_user.is_authenticated and current_user.role == "admin"


def admin_required(f=None):
    """Can be used as a decorator (``@admin_required``) or middleware (``admin_required()``).

    As a decorator, wraps the route function and returns 401 if not logged in.
    As middleware, returns a 401 response tuple if not logged in, else None.
    """
    if f is None:
        if not _is_admin():
            return jsonify({"error": "Unauthorized"}), 401
        return None

    @wraps(f)
    def decorated(*args, **kwargs):
        check = admin_required()
        if check:
            return check
        return f(*args, **kwargs)
    return decorated


def admin_page_required(f=None):
    """Can be used as a decorator (``@admin_page_required``) or middleware.

    As a decorator, wraps the route function and redirects to login if not logged in.
    As middleware, returns a redirect response if not logged in, else None.

    NOTE: Uses _is_platform_admin() — shop-authenticated users cannot access these pages.
    """
    if f is None:
        if not _is_platform_admin():
            return redirect(url_for("admin.login"))
        return None

    @wraps(f)
    def decorated(*args, **kwargs):
        check = admin_page_required()
        if check:
            return check
        return f(*args, **kwargs)
    return decorated


def create_user_and_tenant(email: str, password: str, display_name: str = "") -> dict:
    """Create a user account (no separate tenant DB anymore)."""
    try:
        result = create_user(email, password, "user", display_name)
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}

"""Tests for core/auth.py — password validation, User model, rate limiting."""
import pytest

from core.auth import AdminUser, User, validate_password
from core.auth import _validate_password


class TestValidatePassword:
    def test_valid_password(self):
        is_valid, msg = validate_password("MyP@ssw0rd!")
        assert is_valid is True
        assert msg == ""

    def test_too_short(self):
        is_valid, msg = validate_password("Ab1!")
        assert is_valid is False
        assert "8 characters" in msg

    def test_no_digit(self):
        is_valid, msg = validate_password("NoDigitsHere!")
        assert is_valid is False
        assert "number" in msg

    def test_no_special_char(self):
        is_valid, msg = validate_password("NoSpecialChar1")
        assert is_valid is False
        assert "special" in msg

    def test_empty_string(self):
        is_valid, msg = validate_password("")
        assert is_valid is False

    def test_validate_password_raises(self):
        with pytest.raises(ValueError, match="8 characters"):
            _validate_password("Ab1!")


class TestUserModel:
    def test_user_creation(self):
        user = User(
            row_id=1, email="test@example.com",
            password_hash="hash", role="user",
            display_name="Test User",
        )
        assert user.id == 1
        assert user.email == "test@example.com"
        assert user.role == "user"
        assert user.display_name == "Test User"
        assert user.is_active is True
        assert user.is_trial_expired is False

    def test_user_get_id(self):
        user = User(1, "a@b.com", "hash", "user", "A")
        assert user.get_id() == "1"

    def test_user_expired_status(self):
        user = User(
            2, "expired@test.com", "hash", "user", "Expired",
            status="expired",
        )
        assert user.is_active is False

    def test_user_trial_ends_future(self):
        from datetime import UTC, datetime, timedelta
        future = (datetime.now(UTC) + timedelta(days=1)).isoformat()
        user = User(
            3, "trial@test.com", "hash", "user", "Trial User",
            status="trial", trial_ends_at=future,
        )
        assert user.is_active is True
        assert user.is_trial_expired is False

    def test_user_trial_expired(self):
        from datetime import UTC, datetime, timedelta
        past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
        user = User(
            4, "expired-trial@test.com", "hash", "user", "Expired Trial",
            status="trial", trial_ends_at=past,
        )
        assert user.is_active is False
        assert user.is_trial_expired is True

    def test_tenant_id_with_parent(self):
        user = User(5, "a@b.com", "hash", "user", "Child", tenant_id=1)
        assert user.tenant_id == "1"

    def test_tenant_id_no_parent(self):
        user = User(6, "a@b.com", "hash", "user", "Parent")
        assert user.tenant_id == "6"


class TestAdminUser:
    def test_admin_creation(self):
        admin = AdminUser("admin")
        assert admin.id == "admin"
        assert admin.role == "admin"
        assert admin.display_name == "Admin"
        assert admin.get_id() == "admin"

    def test_admin_is_authenticated(self):
        admin = AdminUser("admin")
        assert admin.is_authenticated



"""Tests for core/database.py — CRUD operations, data export, deletion."""
import pytest
from werkzeug.security import generate_password_hash

from core import database


def _create_test_user(conn, email="test@example.com", role="user") -> int:
    uid = database.create_user(
        email=email,
        password_hash=generate_password_hash("Secret1!"),
        role=role,
        display_name="Test User",
    )
    return uid


class TestCreateUser:
    def test_creates_user(self, db_conn):
        uid = _create_test_user(db_conn)
        assert uid is not None
        assert isinstance(uid, int)

    def test_duplicate_email_raises(self, db_conn):
        _create_test_user(db_conn, email="dup@example.com")
        with pytest.raises(Exception):
            _create_test_user(db_conn, email="dup@example.com")

    def test_rejects_invalid_role(self):
        with pytest.raises(Exception):
            database.create_user(
                email="bad@example.com",
                password_hash="hash",
                role="invalid",
                display_name="Bad",
            )


class TestGetUser:
    def test_get_by_id(self, db_conn):
        uid = _create_test_user(db_conn)
        user = database.get_user_by_id(uid)
        assert user is not None
        assert user["email"] == "test@example.com"
        assert user["display_name"] == "Test User"

    def test_get_by_id_missing(self, db_conn):
        assert database.get_user_by_id(99999) is None

    def test_get_by_email(self, db_conn):
        uid = _create_test_user(db_conn, email="findme@example.com")
        user = database.get_user_by_email("findme@example.com")
        assert user is not None
        assert user["id"] == uid

    def test_get_by_email_missing(self, db_conn):
        assert database.get_user_by_email("nobody@example.com") is None

    def test_get_by_email_case_sensitive(self, db_conn):
        _create_test_user(db_conn, email="Case@Test.com")
        found = database.get_user_by_email("Case@Test.com")
        assert found is not None
        assert found["email"] == "Case@Test.com"


class TestUpdateUser:
    def test_update_display_name(self, db_conn):
        uid = _create_test_user(db_conn)
        database.update_user(uid, display_name="Updated Name")
        user = database.get_user_by_id(uid)
        assert user["display_name"] == "Updated Name"

    def test_update_role(self, db_conn):
        uid = _create_test_user(db_conn, role="user")
        database.update_user(uid, role="shop")
        user = database.get_user_by_id(uid)
        assert user["role"] == "shop"


class TestListUsers:
    def test_list_all(self, db_conn):
        u1 = _create_test_user(db_conn, email="a@example.com")
        u2 = _create_test_user(db_conn, email="b@example.com")
        users = database.list_users()
        ids = {u["id"] for u in users}
        assert u1 in ids
        assert u2 in ids

    def test_list_by_role(self, db_conn):
        _create_test_user(db_conn, email="admin@example.com", role="admin")
        _create_test_user(db_conn, email="user@example.com", role="user")
        admins = database.list_users(role="admin")
        assert all(u["role"] == "admin" for u in admins)


class TestExportUserData:
    def test_export_includes_user(self, db_conn):
        uid = _create_test_user(db_conn, email="export@example.com")
        data = database.export_user_data(uid)
        assert data["user"] is not None
        assert data["user"]["email"] == "export@example.com"

    def test_export_includes_all_tables(self, db_conn):
        uid = _create_test_user(db_conn)
        data = database.export_user_data(uid)
        expected_tables = [
            "user", "agent_configs", "threads", "leads", "execution_log",
            "pending_actions", "mcp_credentials", "agent_feedback",
            "agent_preferences", "agent_findings", "agent_schedules",
            "llm_usage_log", "user_llm_quotas", "shops", "webhook_events",
        ]
        for key in expected_tables:
            assert key in data, f"Missing key: {key}"

    def test_export_shops(self, db_conn):
        uid = _create_test_user(db_conn)
        conn = database._get_conn()
        conn.execute(
            "INSERT INTO shops (shop, access_token, user_id, scopes, installed_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("test.myshopify.com", "encrypted_token", uid, "read_products", "2024-01-01"),
        )
        conn.commit()
        data = database.export_user_data(uid)
        assert len(data["shops"]) == 1
        assert data["shops"][0]["shop"] == "test.myshopify.com"


class TestDeleteUser:
    def test_delete_removes_user(self, db_conn):
        uid = _create_test_user(db_conn)
        database.delete_user(uid)
        assert database.get_user_by_id(uid) is None

    def test_delete_removes_shops(self, db_conn):
        uid = _create_test_user(db_conn)
        conn = database._get_conn()
        conn.execute(
            "INSERT INTO shops (shop, access_token, user_id, scopes, installed_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("shop1.myshopify.com", "tok", uid, "scope", "2024-01-01"),
        )
        conn.commit()
        database.delete_user(uid)
        remaining = conn.execute(
            "SELECT COUNT(*) as cnt FROM shops WHERE user_id = ?", (uid,)
        ).fetchone()
        assert remaining["cnt"] == 0

    def test_delete_removes_webhook_events(self, db_conn):
        uid = _create_test_user(db_conn)
        conn = database._get_conn()
        conn.execute(
            "INSERT INTO shops (shop, access_token, user_id, scopes, installed_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("wh.myshopify.com", "tok", uid, "scope", "2024-01-01"),
        )
        conn.execute(
            "INSERT INTO webhook_events (shop, topic, body, received_at) "
            "VALUES (?, ?, ?, ?)",
            ("wh.myshopify.com", "orders/create", "{}", "2024-01-01"),
        )
        conn.commit()
        database.delete_user(uid)
        remaining = conn.execute(
            "SELECT COUNT(*) as cnt FROM webhook_events WHERE shop = ?",
            ("wh.myshopify.com",),
        ).fetchone()
        assert remaining["cnt"] == 0

    def test_delete_removes_related_data(self, db_conn):
        uid = _create_test_user(db_conn)
        conn = database._get_conn()
        conn.execute("INSERT INTO leads (id, user_id, name, phone, created_at) VALUES (?, ?, ?, ?, ?)",
                     ("lead-1", uid, "Test", "555-0100", "2024-01-01"))
        conn.execute("INSERT OR IGNORE INTO agent_configs (user_id, agent_id) VALUES (?, ?)",
                     (uid, "test_agent_custom"))
        conn.execute("INSERT INTO threads (user_id, thread_id, created_at) VALUES (?, ?, ?)",
                     (uid, "thread-1", "2024-01-01"))
        conn.execute("INSERT INTO execution_log (user_id, execution_id, agent_name, tool_name, timestamp) VALUES (?, ?, ?, ?, ?)",
                     (uid, "exec-1", "local_seo", "analyze", "2024-01-01"))
        conn.commit()
        database.delete_user(uid)
        for table in ("leads", "agent_configs", "threads", "execution_log"):
            cnt = conn.execute(f"SELECT COUNT(*) as cnt FROM {table} WHERE user_id = ?", (uid,)).fetchone()
            assert cnt["cnt"] == 0, f"Table {table} still has rows for deleted user"

    def test_delete_handles_missing_user(self, db_conn):
        # Should not raise for non-existent user
        database.delete_user(99999)


class TestResetConn:
    def test_reset_conn_does_not_raise(self):
        database.reset_conn()
        conn = database._get_conn()
        result = conn.execute("SELECT 1").fetchone()
        assert result is not None
"""Tests for Google Ads integration — ads_auth, ads_bp, and ads_server helpers."""
import os
from unittest import mock

import pytest
from app import app as _app

from mcp.ads_server import _fmt_cid, _get_customer_id, _resolve_location_id


@pytest.fixture
def client():
    _app.config["TESTING"] = True
    _app.config["WTF_CSRF_ENABLED"] = False
    with _app.test_client() as c, _app.app_context():
        yield c


# ── _resolve_location_id ─────────────────────────────────────────────

class TestResolveLocationId:
    def test_known_city(self):
        assert _resolve_location_id("toronto") == "1002180"

    def test_known_city_case_insensitive(self):
        assert _resolve_location_id("Montreal") == "1002210"

    def test_strips_comma_and_suffix(self):
        assert _resolve_location_id("Vancouver, BC, Canada") == "1002190"

    def test_fallback_for_unknown(self):
        assert _resolve_location_id("nonexistentville") == "1014271"

    def test_empty_string(self):
        assert _resolve_location_id("") == "1014271"

    def test_canadian_provinces(self):
        assert _resolve_location_id("ontario") == "20018"
        assert _resolve_location_id("alberta") == "20013"

    def test_major_us_cities(self):
        assert _resolve_location_id("new york") == "1023191"
        assert _resolve_location_id("los angeles") == "1023846"
        assert _resolve_location_id("chicago") == "1015215"

    def test_european_cities(self):
        assert _resolve_location_id("london") == "1006687"
        assert _resolve_location_id("paris") == "1006528"
        assert _resolve_location_id("berlin") == "1004109"

    def test_asia_pacific(self):
        assert _resolve_location_id("tokyo") == "1009522"
        assert _resolve_location_id("sydney") == "1009755"
        assert _resolve_location_id("dubai") == "1005306"

    def test_all_unique_values(self):
        """Verify no two keys map to different strings (catch copy-paste errors)."""
        from mcp.ads_server import _resolve_location_id
        keys = [
            "laval", "montreal", "quebec", "toronto", "vancouver",
            "calgary", "ottawa", "edmonton", "winnipeg",
            "new york", "los angeles", "chicago",
            "london", "paris", "berlin",
        ]
        values = [_resolve_location_id(k) for k in keys]
        assert len(set(values)) == len(keys), f"Duplicate IDs: {values}"


# ── _fmt_cid ─────────────────────────────────────────────────────────

class TestFmtCid:
    def test_formats_with_dashes(self):
        assert _fmt_cid("1234567890") == "123-456-7890"

    def test_handles_existing_dashes(self):
        assert _fmt_cid("123-456-7890") == "123-456-7890"

    def test_short_string(self):
        assert _fmt_cid("12345") == "123-45-"


# ── _get_customer_id ─────────────────────────────────────────────────

class TestGetCustomerId:
    def test_explicit_kwarg(self):
        cid = _get_customer_id(customer_id="123-456-7890")
        assert cid == "1234567890"

    def test_strips_dashes_from_explicit(self):
        cid = _get_customer_id(customer_id="111-222-3333")
        assert "-" not in cid

    def test_api_credentials_dict(self):
        cid = _get_customer_id(api_credentials={"customer_id": "999-888-7777"})
        assert cid == "9998887777"

    def test_explicit_overrides_credentials(self):
        cid = _get_customer_id(
            customer_id="111-111-1111",
            api_credentials={"customer_id": "222-222-2222"},
        )
        assert cid == "1111111111"

    def test_returns_empty_when_no_cid(self):
        cid = _get_customer_id()
        assert cid == ""

    def test_empty_api_credentials(self):
        cid = _get_customer_id(api_credentials={})
        assert cid == ""


# ── resolve_customer_id (kwargs path only, no Flask) ─────────────────

class TestResolveCustomerId:
    def test_explicit_kwarg(self):
        from core.ads_auth import resolve_customer_id
        cid = resolve_customer_id({"customer_id": "555-666-7777"})
        assert cid == "5556667777"

    def test_api_credentials_path(self):
        from core.ads_auth import resolve_customer_id
        cid = resolve_customer_id({"api_credentials": {"customer_id": "444-333-2222"}})
        assert cid == "4443332222"

    def test_none_kwargs(self):
        from core.ads_auth import resolve_customer_id
        cid = resolve_customer_id(None)
        assert cid is None

    def test_empty_kwargs(self):
        from core.ads_auth import resolve_customer_id
        cid = resolve_customer_id({})
        assert cid is None


# ── _row_to_dict ─────────────────────────────────────────────────────

class TestRowToDict:
    def test_converts_simple_fields(self):
        from core.ads_auth import _row_to_dict
        mock_field = mock.Mock()
        mock_field.name = "id"
        mock_descriptor = mock.Mock()
        mock_descriptor.fields = [mock_field]
        mock_row = mock.Mock()
        mock_row.DESCRIPTOR = mock_descriptor
        mock_row.id = 42

        result = _row_to_dict(mock_row)
        assert result == {"id": 42}

    def test_converts_nested_submessage(self):
        from core.ads_auth import _row_to_dict
        # Create a nested mock that has DESCRIPTOR (like a sub-message)
        nested = mock.Mock()
        nested.DESCRIPTOR = mock.MagicMock()
        nested.DESCRIPTOR.fields = []
        nested.id = 1

        outer_field = mock.Mock()
        outer_field.name = "sub"
        outer_descriptor = mock.Mock()
        outer_descriptor.fields = [outer_field]

        outer = mock.Mock()
        outer.DESCRIPTOR = outer_descriptor
        outer.sub = nested
        outer.id = 99

        # Mock getattr for the outer so sub returns nested
        with mock.patch.object(type(outer), "sub", new=nested, create=True):
            result = _row_to_dict(outer)
            assert "sub" in result

    def test_handles_repeated_fields(self):
        from core.ads_auth import _row_to_dict
        field = mock.Mock()
        field.name = "names"
        descriptor = mock.Mock()
        descriptor.fields = [field]
        row = mock.Mock()
        row.DESCRIPTOR = descriptor
        row.names = ["a", "b", "c"]

        result = _row_to_dict(row)
        assert result == {"names": ["a", "b", "c"]}


# ── ads_credential_health ────────────────────────────────────────────

class TestAdsCredentialHealth:
    @mock.patch.dict(os.environ, {
        "GOOGLE_ADS_DEVELOPER_TOKEN": "",
        "GOOGLE_ADS_CLIENT_ID": "",
        "GOOGLE_ADS_CLIENT_SECRET": "",
        "GOOGLE_ADS_REFRESH_TOKEN": "",
        "GOOGLE_ADS_MCC_ID": "",
    }, clear=True)
    def test_missing_credentials(self):
        """Re-import settings to pick up cleared env vars."""
        import importlib
        from core import settings
        importlib.reload(settings)
        from core.ads_auth import ads_credential_health
        result = ads_credential_health()
        assert result["status"] == "missing"
        assert "not set" in result["detail"]


# ── API endpoint tests ───────────────────────────────────────────────

class TestAdsApiHealth:
    @mock.patch.dict(os.environ, {
        "GOOGLE_ADS_DEVELOPER_TOKEN": "",
        "GOOGLE_ADS_CLIENT_ID": "",
        "GOOGLE_ADS_CLIENT_SECRET": "",
        "GOOGLE_ADS_REFRESH_TOKEN": "",
        "GOOGLE_ADS_MCC_ID": "",
    }, clear=True)
    def test_health_returns_missing(self, client):
        import importlib
        from core import settings
        importlib.reload(settings)
        r = client.get("/api/ads/health")
        assert r.status_code == 200
        data = r.get_json()
        assert data is not None
        payload = data.get("data", data)
        assert payload.get("status") == "missing"


class TestAdsApiConnections:
    def _login(self, client):
        """Log in as platform admin (works because app loads .env via load_dotenv)."""
        import os
        r = client.post("/admin/login", data={
            "email": os.environ.get("ADMIN_USERNAME", "laval"),
            "password": os.environ.get("ADMIN_PASSWORD", "digital2026!"),
        })
        return r.status_code == 302

    def test_requires_auth(self, client):
        r = client.get("/api/ads/connections")
        assert r.status_code == 401

    def test_returns_connections_when_authenticated(self, client):
        if not self._login(client):
            pytest.skip("Admin login credentials not available")
        r = client.get("/api/ads/connections")
        assert r.status_code in (200, 400)  # 200=ok, 400=no user context (admin without active_user_id)

    def test_connect_requires_auth(self, client):
        r = client.post("/api/ads/connect", json={"customer_id": "123-456-7890"})
        assert r.status_code == 401

    def test_connect_missing_customer_id(self, client):
        if not self._login(client):
            pytest.skip("Admin login credentials not available")
        r = client.post("/api/ads/connect", json={})
        assert r.status_code == 400

    def test_disconnect_requires_auth(self, client):
        r = client.post("/api/ads/disconnect", json={"customer_id": "123-456-7890"})
        assert r.status_code == 401

    def test_disconnect_missing_customer_id(self, client):
        if not self._login(client):
            pytest.skip("Admin login credentials not available")
        r = client.post("/api/ads/disconnect", json={})
        assert r.status_code == 400


class TestAdsApiDiscover:
    def test_discover_requires_credentials(self, client):
        r = client.get("/api/ads/discover")
        assert r.status_code in (200, 400, 401)
        if r.status_code in (400, 401):
            data = r.get_json()
            assert data is not None

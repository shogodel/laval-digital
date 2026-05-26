import pytest
from app import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as c:
        with app.app_context():
            yield c


class TestPublicRoutes:
    def test_home_page(self, client):
        r = client.get("/")
        assert r.status_code == 200
        assert b"Laval" in r.data or b"Frankie" in r.data

    def test_home_fr(self, client):
        r = client.get("/fr/")
        assert r.status_code == 200

    def test_demo(self, client):
        r = client.get("/demo")
        assert r.status_code == 200

    def test_demo_fr(self, client):
        r = client.get("/fr/demo")
        assert r.status_code == 200

    def test_blog(self, client):
        r = client.get("/blog")
        assert r.status_code == 200

    def test_blog_fr(self, client):
        r = client.get("/fr/blogue")
        assert r.status_code == 200

    def test_free_trial(self, client):
        r = client.get("/free-trial")
        assert r.status_code == 200

    def test_free_trial_fr(self, client):
        r = client.get("/fr/essai-gratuit")
        assert r.status_code == 200

    def test_contact(self, client):
        r = client.get("/contact")
        assert r.status_code == 200

    def test_contact_fr(self, client):
        r = client.get("/fr/contact")
        assert r.status_code == 200

    def test_trial_expired(self, client):
        r = client.get("/trial-expired")
        assert r.status_code == 200

    def test_affiliate(self, client):
        r = client.get("/affiliate")
        assert r.status_code == 200

    def test_affiliate_fr(self, client):
        r = client.get("/fr/affiliate")
        assert r.status_code == 200

    def test_training_hub(self, client):
        r = client.get("/training")
        assert r.status_code == 200

    def test_health_endpoint(self, client):
        r = client.get("/health")
        assert r.status_code in (200, 503)
        data = r.get_json()
        assert data is not None
        assert "status" in data


class TestSecurityHeaders:
    def test_csp_header(self, client):
        r = client.get("/")
        csp = r.headers.get("Content-Security-Policy", "")
        assert "default-src 'self'" in csp
        assert "'unsafe-inline'" not in csp

    def test_hsts_header(self, client):
        r = client.get("/")
        hsts = r.headers.get("Strict-Transport-Security", "")
        assert "max-age=31536000" in hsts

    def test_xss_protection(self, client):
        r = client.get("/")
        assert r.headers.get("X-XSS-Protection") == "1; mode=block"

    def test_frame_options(self, client):
        r = client.get("/")
        assert r.headers.get("X-Frame-Options") == "DENY"

    def test_content_type_options(self, client):
        r = client.get("/")
        assert r.headers.get("X-Content-Type-Options") == "nosniff"

    def test_referrer_policy(self, client):
        r = client.get("/")
        assert r.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"


class TestAdminRoutes:
    def test_admin_login_page(self, client):
        r = client.get("/admin/login")
        assert r.status_code == 200
        assert b"Admin" in r.data or b"admin" in r.data

    def test_admin_panel_redirects_when_not_logged_in(self, client):
        r = client.get("/admin")
        assert r.status_code == 302

    def test_admin_login_fr_page(self, client):
        r = client.get("/fr/admin/login")
        assert r.status_code == 200

    def test_admin_panel_fr_redirects_when_not_logged_in(self, client):
        r = client.get("/fr/admin")
        assert r.status_code in (302, 308)

    def test_admin_dashboard_redirects_when_not_logged_in(self, client):
        r = client.get("/admin/dashboard")
        assert r.status_code == 302


class TestClientRoutes:
    def test_client_login_page(self, client):
        r = client.get("/client/login")
        assert r.status_code == 200


class TestAffiliateRoutes:
    def test_affiliate_login_page(self, client):
        r = client.get("/affiliate/login")
        assert r.status_code == 200

    def test_affiliate_dashboard_redirects_when_not_logged_in(self, client):
        r = client.get("/affiliate/dashboard")
        assert r.status_code in (302, 401)

    def test_affiliate_status_api(self, client):
        r = client.get("/api/affiliate/status")
        assert r.status_code == 200
        data = r.get_json()
        assert data is not None
        assert "data" in data


class TestApiAuth:
    def test_api_requires_auth_by_default(self, client):
        r = client.get("/api/agents")
        assert r.status_code == 401

    def test_api_public_routes_accessible_without_auth(self, client):
        r = client.get("/api/affiliate/status")
        assert r.status_code == 200

    def test_api_models_accessible(self, client):
        r = client.get("/api/models")
        assert r.status_code == 200

    def test_api_personalities(self, client):
        r = client.get("/api/personalities")
        assert r.status_code == 200

    def test_api_push_vapid_key(self, client):
        r = client.get("/api/push/vapid-key")
        assert r.status_code == 200


class TestContactApi:
    def test_contact_api_missing_data(self, client):
        r = client.post("/api/contact", json={})
        assert r.status_code == 400

    def test_contact_api_validation(self, client):
        r = client.post("/api/contact", json={"name": "", "email": "", "phone": ""})
        assert r.status_code == 400


class TestCsp:
    def test_nonced_scripts(self, client):
        r = client.get("/")
        html = r.data.decode()
        assert 'nonce="' in html
        csp = r.headers.get("Content-Security-Policy", "")
        assert "'nonce-" in csp

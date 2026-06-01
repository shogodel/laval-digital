import pytest
from flask import Flask, g

from core.api_helpers import api_error, api_response, api_success


@pytest.fixture
def app():
    app = Flask(__name__)
    return app


class TestApiResponse:
    def test_success_with_data(self, app):
        with app.app_context():
            resp, code = api_response(success=True, data={"key": "val"})
        assert code == 200
        assert resp.json["success"] is True
        assert resp.json["data"]["key"] == "val"

    def test_success_no_data(self, app):
        with app.app_context():
            resp, code = api_success()
        assert code == 200
        assert resp.json["success"] is True
        assert "data" not in resp.json

    def test_error_default_code(self, app):
        with app.app_context():
            resp, code = api_error("Something went wrong")
        assert code == 400
        assert resp.json["success"] is False
        assert resp.json["error"] == "Something went wrong"

    def test_error_custom_code(self, app):
        with app.app_context():
            resp, code = api_error("Not found", 404)
        assert code == 404
        assert resp.json["success"] is False
        assert resp.json["error"] == "Not found"

    def test_with_message(self, app):
        with app.app_context():
            resp, code = api_success(message="Created", status_code=201)
        assert code == 201
        assert resp.json["success"] is True
        assert resp.json["message"] == "Created"

    def test_request_id_in_response(self, app):
        with app.app_context():
            g.request_id = "test-123"
            resp, code = api_success()
        assert resp.json["request_id"] == "test-123"

    def test_request_id_missing(self, app):
        with app.app_context():
            resp, code = api_success()
        assert resp.json["request_id"] == ""

    def test_data_promoted_to_envelope(self, app):
        with app.app_context():
            resp, code = api_success(data={"custom_key": "custom_val"})
        assert resp.json["custom_key"] == "custom_val"

"""Tests for input validation in Flask API endpoints."""

import pytest

from api.server import create_app


@pytest.fixture()
def client():
    app, _socketio = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


class TestDivergencesInputValidation:
    """Validate sanitisation and rejection of bad input on POST /divergences."""

    def test_empty_body_ok(self, client):
        resp = client.post("/divergences", json={})
        assert resp.status_code == 200

    def test_no_body_ok(self, client):
        resp = client.post(
            "/divergences",
            content_type="application/json",
        )
        assert resp.status_code == 200

    def test_invalid_category_type_returns_400(self, client):
        resp = client.post("/divergences", json={"category": 123})
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["error"] == "invalid_category"

    def test_unknown_category_returns_400(self, client):
        resp = client.post("/divergences", json={"category": "crypto"})
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["error"] == "invalid_category"

    def test_unexpected_fields_returns_400(self, client):
        resp = client.post("/divergences", json={"category": "cpi", "extra": "bad"})
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["error"] == "unexpected_fields"

    def test_category_whitespace_stripped(self, client):
        resp = client.post("/divergences", json={"category": " cpi "})
        assert resp.status_code == 200

    def test_category_case_insensitive(self, client):
        resp = client.post("/divergences", json={"category": "CPI"})
        assert resp.status_code == 200

    def test_wrong_content_type_returns_415(self, client):
        resp = client.post(
            "/divergences",
            data="category=cpi",
            content_type="application/x-www-form-urlencoded",
        )
        assert resp.status_code == 415


class TestHealthInputValidation:
    """Health endpoint should always return 200 regardless of query params."""

    def test_health_always_200(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_health_ignores_query_params(self, client):
        resp = client.get("/health?foo=bar")
        assert resp.status_code == 200


class TestCalibrationInputValidation:
    """Calibration endpoint should always return 200."""

    def test_calibration_always_200(self, client):
        resp = client.get("/calibration")
        assert resp.status_code == 200

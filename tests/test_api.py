"""Tests for api/server.py using the Flask test client."""

import pytest

from api.server import create_app


@pytest.fixture()
def client():
    app, _socketio = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


class TestHealth:
    def test_returns_200(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_has_expected_keys(self, client):
        resp = client.get("/health")
        data = resp.get_json()
        assert "status" in data
        assert "timestamp" in data
        assert "data_source" in data
        assert "contract_count" in data
        assert "categories" in data


class TestDivergences:
    def test_returns_200(self, client):
        resp = client.post("/divergences", json={})
        assert resp.status_code == 200

    def test_expected_structure(self, client):
        resp = client.post("/divergences", json={})
        data = resp.get_json()
        assert "timestamp" in data
        assert "contracts" in data
        assert "metadata" in data
        assert isinstance(data["contracts"], list)

    def test_filter_by_valid_category(self, client):
        resp = client.post("/divergences", json={"category": "cpi"})
        assert resp.status_code == 200
        data = resp.get_json()
        for contract in data["contracts"]:
            assert contract["category"] == "cpi"

    def test_invalid_category_returns_400(self, client):
        resp = client.post("/divergences", json={"category": "nonexistent"})
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["error"] == "invalid_category"


class TestCalibration:
    def test_returns_200(self, client):
        resp = client.get("/calibration")
        assert resp.status_code == 200

    def test_has_calibration_data(self, client):
        resp = client.get("/calibration")
        data = resp.get_json()
        assert "categories" in data
        assert "overall" in data
        assert "brier_summary" in data

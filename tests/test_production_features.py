"""Tests for new production features: auth, pagination, caching, database, monitoring."""

import os
import tempfile
import time

import pytest

from api.server import create_app
from data.cache import FredCache
from data.database import ResultStore


# ═══════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture()
def client():
    app, _socketio = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture()
def auth_client(monkeypatch):
    """Flask test client with API_KEY authentication enabled."""
    monkeypatch.setattr("api.server.API_KEY", "test-secret-key")
    app, _socketio = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture()
def db(tmp_path):
    """A temporary ResultStore backed by an ephemeral SQLite DB."""
    db_path = tmp_path / "test.db"
    store = ResultStore(database_url=f"sqlite:///{db_path}")
    yield store
    store.close()


# ═══════════════════════════════════════════════════════════════════════════
# API Authentication
# ═══════════════════════════════════════════════════════════════════════════


class TestAPIAuth:
    def test_no_auth_required_when_api_key_unset(self, client):
        """Without API_KEY configured, endpoints are open."""
        resp = client.post("/divergences", json={})
        assert resp.status_code == 200

    def test_health_no_auth_required(self, auth_client):
        """/health is always open (no auth decorator)."""
        resp = auth_client.get("/health")
        assert resp.status_code == 200

    def test_missing_token_returns_401(self, auth_client):
        resp = auth_client.post("/divergences", json={})
        assert resp.status_code == 401
        data = resp.get_json()
        assert data["error"] == "unauthorized"

    def test_wrong_token_returns_401(self, auth_client):
        resp = auth_client.post(
            "/divergences",
            json={},
            headers={"Authorization": "Bearer wrong-key"},
        )
        assert resp.status_code == 401

    def test_correct_token_returns_200(self, auth_client):
        resp = auth_client.post(
            "/divergences",
            json={},
            headers={"Authorization": "Bearer test-secret-key"},
        )
        assert resp.status_code == 200

    def test_calibration_requires_auth(self, auth_client):
        resp = auth_client.get("/calibration")
        assert resp.status_code == 401

    def test_calibration_with_auth(self, auth_client):
        resp = auth_client.get(
            "/calibration",
            headers={"Authorization": "Bearer test-secret-key"},
        )
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════
# Pagination
# ═══════════════════════════════════════════════════════════════════════════


class TestPagination:
    def test_default_pagination_metadata(self, client):
        resp = client.post("/divergences", json={})
        data = resp.get_json()
        assert "pagination" in data
        pag = data["pagination"]
        assert "page" in pag
        assert "page_size" in pag
        assert "total_items" in pag
        assert "total_pages" in pag

    def test_custom_page_size(self, client):
        resp = client.post("/divergences", json={"page_size": 2})
        data = resp.get_json()
        assert len(data["contracts"]) <= 2
        assert data["pagination"]["page_size"] == 2

    def test_page_beyond_total_returns_empty(self, client):
        resp = client.post("/divergences", json={"page": 999})
        data = resp.get_json()
        assert data["contracts"] == []

    def test_invalid_page_returns_400(self, client):
        resp = client.post("/divergences", json={"page": -1})
        assert resp.status_code == 400

    def test_invalid_page_size_returns_400(self, client):
        resp = client.post("/divergences", json={"page_size": 0})
        assert resp.status_code == 400

    def test_page_size_over_max_returns_400(self, client):
        resp = client.post("/divergences", json={"page_size": 200})
        assert resp.status_code == 400


# ═══════════════════════════════════════════════════════════════════════════
# FRED Cache
# ═══════════════════════════════════════════════════════════════════════════


class TestFredCache:
    def test_set_and_get(self):
        cache = FredCache(ttl=60)
        cache.set("key1", [1, 2, 3])
        assert cache.get("key1") == [1, 2, 3]

    def test_miss_returns_none(self):
        cache = FredCache(ttl=60)
        assert cache.get("nonexistent") is None

    def test_expired_entry_returns_none(self):
        cache = FredCache(ttl=0)  # Immediate expiration
        cache.set("key1", "value")
        time.sleep(0.01)
        assert cache.get("key1") is None

    def test_clear_evicts_all(self):
        cache = FredCache(ttl=60)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.clear()
        assert cache.get("a") is None
        assert cache.get("b") is None

    def test_stats(self):
        cache = FredCache(ttl=60)
        cache.set("x", 1)
        cache.get("x")      # hit
        cache.get("y")      # miss
        stats = cache.stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["size"] == 1

    def test_make_key_deterministic(self):
        k1 = FredCache._make_key("obs", "CPIAUCSL", "2020-01-01")
        k2 = FredCache._make_key("obs", "CPIAUCSL", "2020-01-01")
        assert k1 == k2

    def test_make_key_different_for_different_args(self):
        k1 = FredCache._make_key("obs", "CPIAUCSL")
        k2 = FredCache._make_key("obs", "FEDFUNDS")
        assert k1 != k2


# ═══════════════════════════════════════════════════════════════════════════
# Database (SQLite)
# ═══════════════════════════════════════════════════════════════════════════


class TestResultStore:
    def test_save_and_retrieve_run(self, db):
        sample = {
            "active": [
                {
                    "ticker": "CPI-001",
                    "category": "cpi",
                    "title": "CPI test",
                    "kalshi_price": 0.50,
                    "model_probability": 0.60,
                    "divergence": 0.10,
                    "direction": "kalshi_underpriced",
                    "model_confidence": "low",
                },
            ],
            "brier_summary": {"overall": {"kalshi_brier": 0.20, "model_brier": 0.18}},
        }
        run_id = db.save_run(sample, label="test-run")
        assert run_id >= 1

        result = db.get_run(run_id)
        assert result is not None
        assert len(result["active"]) == 1

    def test_get_latest_run(self, db):
        db.save_run({"active": [], "brier_summary": {}, "label": "run-1"})
        db.save_run({"active": [], "brier_summary": {}, "label": "run-2"})
        latest = db.get_latest_run()
        assert latest is not None
        assert latest["label"] == "run-2"

    def test_list_runs(self, db):
        db.save_run({"active": []}, label="a")
        db.save_run({"active": []}, label="b")
        runs = db.list_runs()
        assert len(runs) == 2
        assert runs[0]["label"] == "b"  # most recent first

    def test_divergences_stored(self, db):
        sample = {
            "active": [
                {
                    "ticker": "JOBS-001",
                    "category": "jobs",
                    "title": "NFP test",
                    "kalshi_price": 0.40,
                    "model_probability": 0.55,
                    "divergence": 0.15,
                    "direction": "kalshi_underpriced",
                    "model_confidence": "medium",
                },
            ],
        }
        db.save_run(sample)
        divs = db.get_divergences(category="jobs")
        assert len(divs) == 1
        assert divs[0]["ticker"] == "JOBS-001"

    def test_count_divergences(self, db):
        sample = {
            "active": [
                {"ticker": "A", "category": "cpi"},
                {"ticker": "B", "category": "jobs"},
            ],
        }
        db.save_run(sample)
        assert db.count_divergences() == 2
        assert db.count_divergences(category="cpi") == 1

    def test_get_nonexistent_run(self, db):
        assert db.get_run(9999) is None

    def test_empty_latest(self, db):
        assert db.get_latest_run() is None


# ═══════════════════════════════════════════════════════════════════════════
# Monitoring / Metrics
# ═══════════════════════════════════════════════════════════════════════════


class TestMonitoring:
    def test_health_includes_uptime(self, client):
        resp = client.get("/health")
        data = resp.get_json()
        assert "uptime_seconds" in data
        assert data["uptime_seconds"] >= 0

    def test_metrics_endpoint(self, client):
        resp = client.get("/metrics")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "uptime_seconds" in data
        assert "data_source" in data
        assert "contract_count" in data

    def test_response_time_header(self, client):
        resp = client.get("/health")
        assert "X-Response-Time-Ms" in resp.headers


# ═══════════════════════════════════════════════════════════════════════════
# Config new values
# ═══════════════════════════════════════════════════════════════════════════


class TestNewConfig:
    def test_cors_origins_default(self):
        from config import CORS_ORIGINS
        assert isinstance(CORS_ORIGINS, list)
        assert len(CORS_ORIGINS) >= 1

    def test_fred_cache_ttl_positive(self):
        from config import FRED_CACHE_TTL
        assert FRED_CACHE_TTL > 0

    def test_database_url_default(self):
        from config import DATABASE_URL
        assert DATABASE_URL.startswith("sqlite:///")


# ═══════════════════════════════════════════════════════════════════════════
# Pipeline benchmark flag
# ═══════════════════════════════════════════════════════════════════════════


class TestPipelineBenchmark:
    def test_benchmark_flag_accepted(self):
        from run_pipeline import _parse_args
        args = _parse_args(["--fred-key", "test", "--benchmark"])
        assert args.benchmark is True

    def test_benchmark_default_false(self):
        from run_pipeline import _parse_args
        args = _parse_args(["--fred-key", "test"])
        assert args.benchmark is False

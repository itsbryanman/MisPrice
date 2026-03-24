"""Tests for structured logging, data freshness checks, and model persistence."""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd
import pytest

from config import (
    DATA_FRESHNESS_THRESHOLD_HOURS,
    MODEL_DIR,
    check_data_freshness,
)
from analysis.model import MispriceModel


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FEATURE_COLS = ["feat_1", "feat_2", "feat_3", "feat_4", "feat_5"]


@pytest.fixture()
def synthetic_df():
    """100-row DataFrame with random features, market prices, and outcomes."""
    rng = np.random.default_rng(42)
    n = 100
    data = {
        "ticker": [f"TEST-{i:04d}" for i in range(n)],
        "category": ["cpi"] * n,
        "kalshi_price_final": rng.uniform(0.0, 1.0, size=n),
        "actual_outcome": rng.integers(0, 2, size=n).astype(float),
    }
    for col in FEATURE_COLS:
        data[col] = rng.standard_normal(n)
    return pd.DataFrame(data)


# ═══════════════════════════════════════════════════════════════════════════
# Config defaults
# ═══════════════════════════════════════════════════════════════════════════

class TestConfigDefaults:
    def test_freshness_threshold_is_positive(self):
        assert DATA_FRESHNESS_THRESHOLD_HOURS > 0

    def test_model_dir_is_path(self):
        assert isinstance(MODEL_DIR, Path)


# ═══════════════════════════════════════════════════════════════════════════
# Data freshness checks
# ═══════════════════════════════════════════════════════════════════════════

class TestCheckDataFreshness:
    def test_returns_true_for_nonexistent_file(self, tmp_path):
        assert check_data_freshness(tmp_path / "nope.json") is True

    def test_returns_true_for_fresh_file(self, tmp_path):
        p = tmp_path / "results.json"
        p.write_text("{}")
        assert check_data_freshness(p, threshold_hours=1.0) is True

    def test_returns_false_for_stale_file(self, tmp_path):
        p = tmp_path / "results.json"
        p.write_text("{}")
        # Set mtime to 48 hours ago
        old_mtime = time.time() - 48 * 3600
        os.utime(p, (old_mtime, old_mtime))
        assert check_data_freshness(p, threshold_hours=24.0) is False

    def test_warns_for_stale_file(self, tmp_path, caplog):
        p = tmp_path / "results.json"
        p.write_text("{}")
        old_mtime = time.time() - 48 * 3600
        os.utime(p, (old_mtime, old_mtime))
        with caplog.at_level(logging.WARNING, logger="config"):
            check_data_freshness(p, threshold_hours=24.0)
        assert any("hours old" in r.message for r in caplog.records)

    def test_respects_custom_threshold(self, tmp_path):
        p = tmp_path / "results.json"
        p.write_text("{}")
        old_mtime = time.time() - 2 * 3600  # 2 hours old
        os.utime(p, (old_mtime, old_mtime))
        assert check_data_freshness(p, threshold_hours=1.0) is False
        assert check_data_freshness(p, threshold_hours=3.0) is True


# ═══════════════════════════════════════════════════════════════════════════
# Model persistence (save / load round-trip)
# ═══════════════════════════════════════════════════════════════════════════

class TestModelPersistence:
    def test_save_and_load_round_trip(self, synthetic_df, tmp_path):
        model = MispriceModel(category="cpi")
        model.train(synthetic_df, model_type="logistic")
        save_path = str(tmp_path / "cpi_logistic.joblib")
        model.save_model(save_path)

        loaded = MispriceModel(category="cpi")
        loaded.load_model(save_path)

        assert loaded.model is not None
        assert loaded.category == "cpi"
        assert loaded.feature_names == model.feature_names

        X, _ = model.prepare_features(synthetic_df)
        np.testing.assert_array_almost_equal(
            model.predict(X), loaded.predict(X)
        )

    def test_loaded_model_has_cv_scores(self, synthetic_df, tmp_path):
        model = MispriceModel(category="cpi")
        model.train(synthetic_df, model_type="logistic")
        save_path = str(tmp_path / "model.joblib")
        model.save_model(save_path)

        loaded = MispriceModel(category="cpi")
        loaded.load_model(save_path)
        assert loaded.cv_scores == model.cv_scores


# ═══════════════════════════════════════════════════════════════════════════
# Logging — verify no print() in key modules
# ═══════════════════════════════════════════════════════════════════════════

class TestNoPrintStatements:
    """Ensure print() has been replaced with logging in key modules."""

    @pytest.mark.parametrize(
        "module_path",
        [
            "run_pipeline.py",
            "validate_data.py",
        ],
    )
    def test_no_print_calls(self, module_path):
        """Scan source for bare print() calls — they should use logger."""
        import ast

        path = Path(__file__).resolve().parent.parent / module_path
        tree = ast.parse(path.read_text())
        prints = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "print"
        ]
        assert prints == [], (
            f"{module_path} still contains {len(prints)} print() call(s)"
        )


# ═══════════════════════════════════════════════════════════════════════════
# Pipeline --skip-cache flag
# ═══════════════════════════════════════════════════════════════════════════

class TestPipelineArgs:
    def test_skip_cache_flag_accepted(self):
        from run_pipeline import _parse_args

        args = _parse_args(["--fred-key", "test", "--skip-cache"])
        assert args.skip_cache is True

    def test_skip_cache_default_false(self):
        from run_pipeline import _parse_args

        args = _parse_args(["--fred-key", "test"])
        assert args.skip_cache is False

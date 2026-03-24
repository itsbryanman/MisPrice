#!/usr/bin/env python
"""Crowd vs. Model — full pipeline runner.

Usage
-----
    python run_pipeline.py --fred-key YOUR_KEY [--categories cpi fed_rate jobs] [--model-type logistic]
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from config import FRED_SERIES_BY_CATEGORY, MODEL_DIR
from data.kalshi_client import KalshiClient
from data.fred_client import FredClient
from data.alignment import DataAligner
from analysis.model import MispriceModel
from analysis.ensemble import EnsembleModel
from analysis.calibration import CalibrationAnalyzer
from analysis.comparison import ModelMarketComparison
from analysis.feature_engineering import FeatureEngineer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("run_pipeline")

ALL_CATEGORIES = list(FRED_SERIES_BY_CATEGORY.keys())
RESULTS_PATH = Path(__file__).resolve().parent / "data" / "results.json"


class _NumpyEncoder(json.JSONEncoder):
    """JSON encoder that handles NumPy/Pandas types."""

    def default(self, obj: Any) -> Any:
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, pd.Timestamp):
            return obj.isoformat()
        if isinstance(obj, float) and (np.isnan(obj) or np.isinf(obj)):
            return None
        return super().default(obj)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the Crowd vs. Model pipeline end-to-end.",
    )
    parser.add_argument(
        "--fred-key",
        required=True,
        help="FRED API key (will also be set as FRED_API_KEY env var).",
    )
    parser.add_argument(
        "--categories",
        nargs="+",
        default=ALL_CATEGORIES,
        choices=ALL_CATEGORIES,
        help="Kalshi categories to process (default: all).",
    )
    parser.add_argument(
        "--model-type",
        default="logistic",
        choices=["logistic", "gradient_boosting", "ensemble"],
        help="Classifier type (default: logistic).",
    )
    parser.add_argument(
        "--skip-cache",
        action="store_true",
        default=False,
        help="Force retraining even if a cached model exists.",
    )
    parser.add_argument(
        "--benchmark",
        action="store_true",
        default=False,
        help="Profile and log timing for each pipeline stage.",
    )
    parser.add_argument(
        "--feature-engineering",
        action="store_true",
        default=False,
        help="Apply feature engineering (momentum, rolling averages, cross-features).",
    )
    return parser.parse_args(argv)


def run_pipeline(args: argparse.Namespace) -> dict[str, Any]:
    """Execute the full pipeline and return aggregated results."""
    os.environ["FRED_API_KEY"] = args.fred_key
    benchmark = getattr(args, "benchmark", False)
    timings: dict[str, float] = {}
    pipeline_start = time.monotonic()

    # ---- Step 1: initialise clients --------------------------------------
    logger.info("Initialising Kalshi and FRED clients …")
    kalshi = KalshiClient()
    fred = FredClient(api_key=args.fred_key)
    aligner = DataAligner(kalshi, fred)

    results: dict[str, Any] = {"categories": {}}

    for category in args.categories:
        logger.info("=" * 60)
        logger.info("Processing category: %s", category)
        logger.info("=" * 60)
        cat_result: dict[str, Any] = {}

        # ---- Step 2a: build aligned dataset ------------------------------
        logger.info("[%s] Building aligned dataset …", category)
        step_start = time.monotonic()
        try:
            df_aligned = aligner.build_aligned_dataset(category)
            cat_result["n_aligned_rows"] = len(df_aligned)
            elapsed = time.monotonic() - step_start
            if benchmark:
                timings[f"{category}_alignment"] = round(elapsed, 3)
                logger.info(
                    "[%s] Aligned dataset: %d rows, %d columns (%.2fs)",
                    category, len(df_aligned), len(df_aligned.columns), elapsed,
                )
            else:
                logger.info(
                    "[%s] Aligned dataset: %d rows, %d columns",
                    category, len(df_aligned), len(df_aligned.columns),
                )
        except Exception:
            logger.exception("[%s] Failed to build aligned dataset", category)
            cat_result["error"] = "alignment_failed"
            results["categories"][category] = cat_result
            continue

        if df_aligned.empty:
            logger.warning("[%s] Aligned dataset is empty – skipping", category)
            cat_result["error"] = "empty_dataset"
            results["categories"][category] = cat_result
            continue

        # ---- Step 2a½: feature engineering (optional) --------------------
        if getattr(args, "feature_engineering", False):
            logger.info("[%s] Applying feature engineering …", category)
            fe = FeatureEngineer()
            df_aligned = fe.transform(df_aligned)
            logger.info(
                "[%s] Dataset now has %d columns after feature engineering",
                category, len(df_aligned.columns),
            )

        # ---- Step 2b: train model ----------------------------------------
        model_path = MODEL_DIR / f"{category}_{args.model_type}.joblib"

        if args.model_type == "ensemble":
            model = EnsembleModel(category=category)
        else:
            model = MispriceModel(category=category)

        if not args.skip_cache and model_path.exists():
            logger.info("[%s] Loading cached model from %s", category, model_path)
            try:
                model.load_model(str(model_path))
                cat_result["train_metrics"] = {
                    "cv_mean_brier": float("nan"),
                    "cv_std_brier": float("nan"),
                    "feature_importances": model.get_feature_importance(),
                    "loaded_from_cache": True,
                }
                logger.info("[%s] Model loaded from cache", category)
            except Exception:
                logger.warning(
                    "[%s] Failed to load cached model – retraining", category,
                )
                if args.model_type == "ensemble":
                    model = EnsembleModel(category=category)
                else:
                    model = MispriceModel(category=category)

        is_trained = (
            model._trained if isinstance(model, EnsembleModel)
            else model.model is not None
        )
        if not is_trained:
            logger.info("[%s] Training %s model …", category, args.model_type)
            step_start = time.monotonic()
            try:
                if isinstance(model, EnsembleModel):
                    train_metrics = model.train(df_aligned)
                else:
                    train_metrics = model.train(df_aligned, model_type=args.model_type)
                cat_result["train_metrics"] = train_metrics
                elapsed = time.monotonic() - step_start
                brier_key = (
                    "ensemble_cv_mean_brier"
                    if isinstance(model, EnsembleModel)
                    else "cv_mean_brier"
                )
                std_key = (
                    "ensemble_cv_std_brier"
                    if isinstance(model, EnsembleModel)
                    else "cv_std_brier"
                )
                if benchmark:
                    timings[f"{category}_training"] = round(elapsed, 3)
                    logger.info(
                        "[%s] Model trained — CV Brier: %.4f ± %.4f (%.2fs)",
                        category,
                        train_metrics.get(brier_key, float("nan")),
                        train_metrics.get(std_key, float("nan")),
                        elapsed,
                    )
                else:
                    logger.info(
                        "[%s] Model trained — CV Brier: %.4f ± %.4f",
                        category,
                        train_metrics.get(brier_key, float("nan")),
                        train_metrics.get(std_key, float("nan")),
                    )
                # Persist trained model
                save_path = MODEL_DIR / f"{category}_{args.model_type}.joblib"
                try:
                    model.save_model(str(save_path))
                except Exception:
                    logger.warning("[%s] Could not save model to %s", category, save_path)
            except Exception:
                logger.exception("[%s] Model training failed", category)
                cat_result["error"] = "training_failed"
                results["categories"][category] = cat_result
                continue

        # ---- Step 2c: calibration analysis -------------------------------
        logger.info("[%s] Running calibration analysis …", category)
        try:
            calibrator = CalibrationAnalyzer(df_aligned)
            cat_result["calibration"] = calibrator.get_summary()
            logger.info(
                "[%s] Brier score: %.4f  |  ECE: %.4f",
                category,
                cat_result["calibration"]["brier_score"],
                cat_result["calibration"]["calibration_error"],
            )
        except Exception:
            logger.exception("[%s] Calibration analysis failed", category)
            cat_result["calibration_error"] = "calibration_failed"

        # ---- Step 2d: comparison analysis --------------------------------
        logger.info("[%s] Running comparison analysis …", category)
        try:
            comparator = ModelMarketComparison(df_aligned, model)
            h2h_df, h2h_summary = comparator.compute_head_to_head()
            div_df, div_summary = comparator.find_divergences()
            cat_result["head_to_head"] = h2h_summary
            cat_result["divergences"] = div_summary
            logger.info(
                "[%s] Divergences: %d  |  Model wins: %s  |  Kalshi wins: %s",
                category,
                div_summary.get("n_divergences", 0),
                div_summary.get("model_right", "N/A"),
                div_summary.get("kalshi_right", "N/A"),
            )
        except Exception:
            logger.exception("[%s] Comparison analysis failed", category)
            cat_result["comparison_error"] = "comparison_failed"

        # ---- Step 2e: active market divergences --------------------------
        logger.info("[%s] Fetching active market divergences …", category)
        try:
            active_markets = kalshi.get_active_markets(category)
            if active_markets is not None and not active_markets.empty:
                fred_features = fred.get_latest_features(category)
                active_div = comparator.get_active_divergences(
                    active_markets, fred_features,
                )
                cat_result["active_divergences"] = active_div.to_dict(orient="records")
                logger.info(
                    "[%s] %d active market divergences found",
                    category, len(active_div),
                )
            else:
                cat_result["active_divergences"] = []
                logger.info("[%s] No active markets found", category)
        except Exception:
            logger.exception("[%s] Active divergences failed", category)
            cat_result["active_divergences_error"] = "active_divergences_failed"

        results["categories"][category] = cat_result

    # ---- Step 3: save results --------------------------------------------
    logger.info("Saving results to %s", RESULTS_PATH)
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(RESULTS_PATH, "w") as f:
        json.dump(results, f, indent=2, cls=_NumpyEncoder)

    # ---- Step 4: print summary -------------------------------------------
    _print_summary(results)

    # ---- Step 5: benchmark summary ---------------------------------------
    if benchmark:
        total = time.monotonic() - pipeline_start
        timings["total"] = round(total, 3)
        results["benchmark"] = timings
        logger.info("")
        logger.info("  ⏱  BENCHMARK RESULTS")
        logger.info("  %s", "─" * 40)
        for stage, secs in timings.items():
            logger.info("    %-30s  %7.3fs", stage, secs)
        logger.info("  %s", "─" * 40)

    return results


def _print_summary(results: dict[str, Any]) -> None:
    """Log a human-readable summary to the console."""
    logger.info("")
    logger.info("=" * 60)
    logger.info("  PIPELINE SUMMARY")
    logger.info("=" * 60)

    for cat, data in results.get("categories", {}).items():
        logger.info("")
        logger.info("  Category: %s", cat)
        logger.info("  %s", "─" * 40)

        if "error" in data:
            logger.warning("    ⚠  Error: %s", data["error"])
            continue

        logger.info("    Aligned rows:  %s", data.get("n_aligned_rows", "?"))

        metrics = data.get("train_metrics", {})
        brier = metrics.get("cv_mean_brier")
        if brier is not None:
            logger.info("    CV Brier:      %.4f", brier)

        cal = data.get("calibration", {})
        if cal:
            logger.info("    Brier score:   %s", cal.get("brier_score", "?"))
            logger.info("    ECE:           %s", cal.get("calibration_error", "?"))

        h2h = data.get("head_to_head", {})
        if h2h:
            logger.info("    Model wins:    %s", h2h.get("model_wins", "?"))
            logger.info("    Kalshi wins:   %s", h2h.get("kalshi_wins", "?"))

        divs = data.get("divergences", {})
        if divs:
            logger.info("    Divergences:   %s", divs.get("n_divergences", 0))

    logger.info("")
    logger.info("=" * 60)
    logger.info("  Results saved to: %s", RESULTS_PATH)
    logger.info("=" * 60)


if __name__ == "__main__":
    run_pipeline(_parse_args())

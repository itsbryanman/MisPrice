"""Tests for environment variable validation."""

import os
from unittest import mock

import pytest

from config import validate_env


class TestValidateEnv:
    """Ensure validate_env() fails fast with clear messages."""

    def test_raises_when_fred_key_missing(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            os.environ.pop("FRED_API_KEY", None)
            with pytest.raises(EnvironmentError, match="FRED_API_KEY"):
                validate_env()

    def test_raises_when_fred_key_blank(self):
        with mock.patch.dict(os.environ, {"FRED_API_KEY": ""}):
            with pytest.raises(EnvironmentError, match="FRED_API_KEY"):
                validate_env()

    def test_raises_when_fred_key_whitespace(self):
        with mock.patch.dict(os.environ, {"FRED_API_KEY": "   "}):
            with pytest.raises(EnvironmentError, match="FRED_API_KEY"):
                validate_env()

    def test_passes_when_fred_key_set(self):
        with mock.patch.dict(os.environ, {"FRED_API_KEY": "valid-key-123"}):
            validate_env()  # should not raise

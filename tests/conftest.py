"""Fixtures for Tigo Energy integration tests."""

import sys
from pathlib import Path

import pytest

# Ensure repository root is importable for `custom_components`.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integration loading in tests."""
    yield

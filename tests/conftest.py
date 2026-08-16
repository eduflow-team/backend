"""Shared pytest fixtures for EduFlow backend tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def stage2_langflow_baseline_fixture() -> dict[str, Any]:
    """Baseline Langflow I/O snapshot (jangyeongsil, pre-refactor Flow)."""
    path = FIXTURES_DIR / "stage2_langflow_jangyeongsil_baseline.json"
    return json.loads(path.read_text(encoding="utf-8"))

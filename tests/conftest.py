from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

from dcf_engine.loader import parse_model
from dcf_engine.model import CompanyModel

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"

# A deliberately round-numbered model whose results are worked out by hand in
# tests/test_valuation.py. Growth equals WACC (10%), so every year's PV of UFCF is equal.
SIMPLE: dict[str, Any] = {
    "company": {"name": "Test Co", "ticker": "TST", "base_year": 2025},
    "financials": {"revenue": 100.0, "net_debt": 50.0, "diluted_shares": 10.0},
    "settings": {"projection_years": 3, "mid_year_convention": False},
    "assumptions": {
        "revenue_growth": 0.10,
        "ebitda_margin": 0.20,
        "da_pct_revenue": 0.05,
        "capex_pct_revenue": 0.06,
        "nwc_pct_revenue": 0.10,
        "tax_rate": 0.25,
        "wacc": {
            "risk_free_rate": 0.04,
            "beta": 1.0,
            "equity_risk_premium": 0.06,
            "pre_tax_cost_of_debt": 0.06,
            "target_debt_to_equity": 0.0,
        },
        "terminal": {"growth_rate": 0.02, "exit_multiple": 8.0},
    },
}


@pytest.fixture
def simple_raw() -> dict[str, Any]:
    return copy.deepcopy(SIMPLE)


@pytest.fixture
def simple_model(simple_raw: dict[str, Any]) -> CompanyModel:
    return parse_model(simple_raw)


@pytest.fixture
def examples_dir() -> Path:
    return EXAMPLES

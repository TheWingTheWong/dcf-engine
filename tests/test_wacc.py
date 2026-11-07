import pytest

from dcf_engine.model import CostOfCapital
from dcf_engine.wacc import compute_wacc, relever_beta


def capital(**overrides) -> CostOfCapital:
    base = {
        "risk_free_rate": 0.04,
        "beta": 1.0,
        "equity_risk_premium": 0.06,
        "pre_tax_cost_of_debt": 0.06,
        "target_debt_to_equity": 0.25,
    }
    base.update(overrides)
    return CostOfCapital(**base)


def test_wacc_by_hand():
    # k_e = 4% + 1.0 * 6% = 10%; k_d after tax = 6% * 0.75 = 4.5%
    # D/E = 0.25 -> E/V = 0.8, D/V = 0.2 -> WACC = 0.8*10% + 0.2*4.5% = 8.9%
    w = compute_wacc(capital(), tax_rate=0.25)
    assert w.cost_of_equity == pytest.approx(0.10)
    assert w.after_tax_cost_of_debt == pytest.approx(0.045)
    assert w.equity_weight == pytest.approx(0.8)
    assert w.debt_weight == pytest.approx(0.2)
    assert w.wacc == pytest.approx(0.089)


def test_size_premium_adds_to_cost_of_equity():
    w = compute_wacc(capital(size_premium=0.015, target_debt_to_equity=0.0), tax_rate=0.25)
    assert w.cost_of_equity == pytest.approx(0.115)
    assert w.wacc == pytest.approx(0.115)


def test_hamada_relevering():
    # beta_L = 0.9 * (1 + 0.75 * 0.5) = 1.2375
    assert relever_beta(0.9, 0.5, 0.25) == pytest.approx(1.2375)
    w = compute_wacc(
        capital(beta=0.9, beta_is_unlevered=True, target_debt_to_equity=0.5), tax_rate=0.25
    )
    assert w.levered_beta == pytest.approx(1.2375)
    assert w.cost_of_equity == pytest.approx(0.04 + 1.2375 * 0.06)


def test_levered_beta_is_used_as_given():
    w = compute_wacc(capital(beta=1.3, target_debt_to_equity=0.5), tax_rate=0.25)
    assert w.levered_beta == 1.3

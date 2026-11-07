"""Valuation checked against figures worked out by hand for the SIMPLE model in conftest.

WACC = 10% (no debt), so with 10% revenue growth every year's PV of UFCF is
10.275 / 1.1 = 9.340909..., and the PV of the 3-year sum is 3x that.
"""

import pytest

from dcf_engine.loader import parse_model
from dcf_engine.valuation import (
    ValuationError,
    axis,
    implied_perpetual_growth,
    implied_share_price,
    value_model,
    value_scenario,
)

PV_YEAR = 10.275 / 1.1
PV_SUM = 3 * PV_YEAR


def test_discounting_by_hand(simple_model):
    sv = value_scenario(simple_model, simple_model.primary)
    assert sv.wacc.wacc == pytest.approx(0.10)
    assert sv.discount_factors == pytest.approx((1 / 1.1, 1 / 1.21, 1 / 1.331))
    assert sv.pv_of_fcf_by_year == pytest.approx((PV_YEAR,) * 3)
    assert sv.perpetuity.pv_of_fcf == pytest.approx(PV_SUM)


def test_perpetuity_growth_by_hand(simple_model):
    v = value_scenario(simple_model, simple_model.primary).perpetuity
    # TV = 12.43275 * 1.02 / (0.10 - 0.02) = 158.5175625, discounted 3 years
    assert v.terminal_value == pytest.approx(158.5175625)
    assert v.tv_discount_period == 3.0
    assert v.pv_of_terminal_value == pytest.approx(158.5175625 / 1.331)
    ev = PV_SUM + 158.5175625 / 1.331  # 147.1193...
    assert v.enterprise_value == pytest.approx(ev)
    assert v.equity_value == pytest.approx(ev - 50.0)
    assert v.share_price == pytest.approx((ev - 50.0) / 10.0)
    assert v.share_price == pytest.approx(9.71193, abs=1e-5)
    # Implied EV/EBITDA: 158.5175625 / 26.62
    assert v.implied_metric == pytest.approx(158.5175625 / 26.62)
    assert v.upside is None


def test_exit_multiple_by_hand(simple_model):
    v = value_scenario(simple_model, simple_model.primary).exit_multiple
    # TV = 26.62 * 8 = 212.96; 26.62 / 1.331 = 20 exactly, so PV of TV = 160
    assert v.terminal_value == pytest.approx(212.96)
    assert v.pv_of_terminal_value == pytest.approx(160.0)
    assert v.enterprise_value == pytest.approx(PV_SUM + 160.0)
    assert v.share_price == pytest.approx((PV_SUM + 160.0 - 50.0) / 10.0)
    # Implied g = (212.96 * 0.10 - 12.43275) / (212.96 + 12.43275)
    assert v.implied_metric == pytest.approx(8.86325 / 225.39275)
    assert v.tv_share_of_ev == pytest.approx(160.0 / (PV_SUM + 160.0))


def test_mid_year_terminal_timing(simple_raw):
    simple_raw["settings"]["mid_year_convention"] = True
    m = parse_model(simple_raw)
    sv = value_scenario(m, m.primary)
    assert sv.perpetuity.tv_discount_period == 2.5  # Gordon follows the cash flows
    assert sv.exit_multiple.tv_discount_period == 3.0  # exit happens at year end
    assert sv.perpetuity.pv_of_fcf == pytest.approx(PV_SUM * 1.1**0.5)


def test_cross_checks_are_inverse(simple_raw):
    """The multiple implied by Gordon, fed back as an exit multiple, implies the same g."""
    simple_raw["settings"]["mid_year_convention"] = True
    m = parse_model(simple_raw)
    sv = value_scenario(m, m.primary)
    final = sv.projection.final
    exit_tv = sv.perpetuity.implied_metric * final.ebitda
    g = implied_perpetual_growth(exit_tv, final.ufcf, sv.wacc.wacc, 2.5, 3.0)
    assert g == pytest.approx(0.02)
    # And both methods then give the same present value of terminal value.
    pv_exit = exit_tv / (1 + sv.wacc.wacc) ** 3.0
    assert pv_exit == pytest.approx(sv.perpetuity.pv_of_terminal_value)


def test_upside_vs_current_price(simple_raw):
    simple_raw["financials"]["share_price"] = 8.0
    m = parse_model(simple_raw)
    v = value_scenario(m, m.primary).perpetuity
    assert v.upside == pytest.approx(v.share_price / 8.0 - 1)


def test_wacc_must_exceed_growth(simple_raw):
    simple_raw["assumptions"]["terminal"]["growth_rate"] = 0.10
    m = parse_model(simple_raw)
    with pytest.raises(ValuationError, match="must exceed terminal growth"):
        value_scenario(m, m.primary)


def test_sensitivity_center_matches_headline(simple_model):
    r = value_model(simple_model)
    sv = r.primary
    g_table, m_table = r.growth_sensitivity, r.multiple_sensitivity
    assert len(g_table.values) == 5 and all(len(row) == 5 for row in g_table.values)
    assert g_table.values[2][2] == pytest.approx(sv.perpetuity.share_price)
    assert m_table.values[2][2] == pytest.approx(sv.exit_multiple.share_price)
    assert g_table.row_values == pytest.approx((0.09, 0.095, 0.10, 0.105, 0.11))
    assert m_table.col_values == pytest.approx((6.0, 7.0, 8.0, 9.0, 10.0))


def test_sensitivity_monotonic(simple_model):
    r = value_model(simple_model)
    g_rows = r.growth_sensitivity.values
    for row in g_rows:  # higher terminal growth -> higher price
        assert list(row) == sorted(row)
    for col in zip(*g_rows):  # higher WACC -> lower price
        assert list(col) == sorted(col, reverse=True)


def test_sensitivity_marks_undefined_cells(simple_raw):
    simple_raw["assumptions"]["terminal"]["growth_rate"] = 0.095
    simple_raw["sensitivity"] = {"growth_step": 0.005}
    m = parse_model(simple_raw)
    t = value_model(m).growth_sensitivity
    # WACC 9.0% row against growth 9.5% / 10.0% / 10.5% columns is undefined.
    assert t.values[0][2:] == (None, None, None)
    assert t.low < t.high


def test_implied_share_price_requires_one_terminal_input(simple_model):
    sv = value_scenario(simple_model, simple_model.primary)
    with pytest.raises(ValueError):
        implied_share_price(sv.projection, 0.1, net_debt=0, diluted_shares=1)


def test_axis():
    assert axis(0.1, 0.01, 2) == pytest.approx((0.08, 0.09, 0.10, 0.11, 0.12))

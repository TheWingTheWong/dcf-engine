import pytest

from dcf_engine.loader import parse_model
from dcf_engine.projections import project


def test_fcf_build_by_hand(simple_model):
    p = project(simple_model, simple_model.primary)
    y1, y2, y3 = p.years

    # Year 1: revenue 110, EBITDA 22, D&A 5.5, EBIT 16.5, tax 4.125, NOPAT 12.375,
    # capex 6.6, NWC 11.0 vs base 10.0 -> UFCF = 12.375 + 5.5 - 6.6 - 1.0 = 10.275
    assert y1.year == 2026
    assert y1.revenue == pytest.approx(110.0)
    assert y1.ebitda == pytest.approx(22.0)
    assert y1.ebit == pytest.approx(16.5)
    assert y1.taxes == pytest.approx(4.125)
    assert y1.nopat == pytest.approx(12.375)
    assert y1.capex == pytest.approx(6.6)
    assert y1.change_in_nwc == pytest.approx(1.0)
    assert y1.ufcf == pytest.approx(10.275)

    # Year 2: 121 revenue -> UFCF = 13.6125 + 6.05 - 7.26 - 1.1 = 11.3025
    assert y2.revenue == pytest.approx(121.0)
    assert y2.ufcf == pytest.approx(11.3025)

    # Year 3: 133.1 revenue -> UFCF = 14.97375 + 6.655 - 7.986 - 1.21 = 12.43275
    assert y3.revenue == pytest.approx(133.1)
    assert y3.ebitda == pytest.approx(26.62)
    assert y3.ufcf == pytest.approx(12.43275)

    assert p.discount_periods == (1.0, 2.0, 3.0)


def test_mid_year_periods(simple_raw):
    simple_raw["settings"]["mid_year_convention"] = True
    m = parse_model(simple_raw)
    assert project(m, m.primary).discount_periods == (0.5, 1.5, 2.5)


def test_explicit_base_nwc_drives_first_year_change(simple_raw):
    simple_raw["financials"]["net_working_capital"] = 8.0
    m = parse_model(simple_raw)
    y1 = project(m, m.primary).years[0]
    assert y1.change_in_nwc == pytest.approx(11.0 - 8.0)


def test_no_tax_on_operating_losses(simple_raw):
    simple_raw["assumptions"]["ebitda_margin"] = 0.02  # EBIT = 2% - 5% < 0
    m = parse_model(simple_raw)
    for y in project(m, m.primary).years:
        assert y.ebit < 0
        assert y.taxes == 0.0
        assert y.nopat == pytest.approx(y.ebit)

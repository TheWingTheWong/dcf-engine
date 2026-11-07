"""Terminal value, enterprise value, equity value and implied share price.

Two terminal value methods are computed side by side:

* **Perpetuity growth (Gordon)**: ``TV = UFCF_N * (1 + g) / (WACC - g)``.
  It values cash flows that arrive on the same schedule as the projection, so it is
  discounted with the final year's discount period (``N - 0.5`` under the mid-year
  convention).
* **Exit multiple**: ``TV = EBITDA_N * multiple``. A sale is assumed at the end of year N,
  so it is discounted a full ``N`` periods regardless of convention.

Each method reports its cross-check: the EV/EBITDA multiple implied by the Gordon value
and the perpetual growth rate implied by the exit multiple, both on a timing-consistent
basis.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from dcf_engine.model import CompanyModel, Scenario
from dcf_engine.projections import Projection, project
from dcf_engine.wacc import WaccResult, compute_wacc

Method = Literal["perpetuity_growth", "exit_multiple"]


class ValuationError(ValueError):
    """Raised when inputs make a valuation undefined (e.g. WACC <= terminal growth)."""


@dataclass(frozen=True)
class MethodValuation:
    method: Method
    wacc: float
    pv_of_fcf: float
    terminal_value: float
    tv_discount_period: float
    pv_of_terminal_value: float
    enterprise_value: float
    net_debt: float
    equity_value: float
    diluted_shares: float
    share_price: float
    implied_metric: float  # implied exit multiple (Gordon) or implied growth (exit multiple)
    upside: float | None  # vs. current share price, if provided

    @property
    def tv_share_of_ev(self) -> float:
        return self.pv_of_terminal_value / self.enterprise_value


@dataclass(frozen=True)
class ScenarioValuation:
    scenario: Scenario
    wacc: WaccResult
    projection: Projection
    discount_factors: tuple[float, ...]
    pv_of_fcf_by_year: tuple[float, ...]
    perpetuity: MethodValuation
    exit_multiple: MethodValuation

    @property
    def name(self) -> str:
        return self.scenario.name


@dataclass(frozen=True)
class SensitivityTable:
    title: str
    row_label: str
    col_label: str
    row_values: tuple[float, ...]  # WACC
    col_values: tuple[float, ...]  # terminal growth or exit multiple
    values: tuple[tuple[float | None, ...], ...]  # implied share price; None = not meaningful

    def finite_values(self) -> list[float]:
        return [v for row in self.values for v in row if v is not None]

    @property
    def low(self) -> float:
        return min(self.finite_values())

    @property
    def high(self) -> float:
        return max(self.finite_values())


@dataclass(frozen=True)
class ValuationResult:
    model: CompanyModel
    scenarios: tuple[ScenarioValuation, ...]
    growth_sensitivity: SensitivityTable
    multiple_sensitivity: SensitivityTable

    def scenario(self, name: str) -> ScenarioValuation:
        for s in self.scenarios:
            if s.name == name:
                return s
        raise KeyError(name)

    @property
    def primary(self) -> ScenarioValuation:
        return self.scenario(self.model.primary_scenario)


# --------------------------------------------------------------------------- primitives


def discount_factor(rate: float, period: float) -> float:
    return 1.0 / (1.0 + rate) ** period


def pv_of_fcf(projection: Projection, wacc: float) -> float:
    return sum(y.ufcf * discount_factor(wacc, y.discount_period) for y in projection.years)


def gordon_terminal_value(final_fcf: float, wacc: float, growth: float) -> float:
    if wacc <= growth:
        raise ValuationError(
            f"WACC ({wacc:.2%}) must exceed terminal growth ({growth:.2%}) for a perpetuity"
        )
    return final_fcf * (1.0 + growth) / (wacc - growth)


def exit_terminal_value(final_ebitda: float, multiple: float) -> float:
    return final_ebitda * multiple


def implied_exit_multiple(
    gordon_tv: float, final_ebitda: float, wacc: float, gordon_period: float, exit_period: float
) -> float:
    """EV/EBITDA a buyer at the end of year N would pay to match the Gordon value."""
    return gordon_tv * (1.0 + wacc) ** (exit_period - gordon_period) / final_ebitda


def implied_perpetual_growth(
    exit_tv: float, final_fcf: float, wacc: float, gordon_period: float, exit_period: float
) -> float:
    """Growth rate g solving ``final_fcf * (1 + g) / (wacc - g) == exit TV`` (same timing)."""
    x = exit_tv / (1.0 + wacc) ** (exit_period - gordon_period)
    return (x * wacc - final_fcf) / (x + final_fcf)


def implied_share_price(
    projection: Projection,
    wacc: float,
    *,
    net_debt: float,
    diluted_shares: float,
    growth: float | None = None,
    multiple: float | None = None,
) -> float:
    """Share price for one (WACC, terminal assumption) pair. Used by the sensitivity grids."""
    if (growth is None) == (multiple is None):
        raise ValueError("pass exactly one of growth or multiple")
    final = projection.final
    if growth is not None:
        tv = gordon_terminal_value(final.ufcf, wacc, growth)
        period = final.discount_period
    else:
        assert multiple is not None
        tv = exit_terminal_value(final.ebitda, multiple)
        period = float(final.period_index)
    ev = pv_of_fcf(projection, wacc) + tv * discount_factor(wacc, period)
    return (ev - net_debt) / diluted_shares


# --------------------------------------------------------------------------- valuation


def value_scenario(model: CompanyModel, scenario: Scenario) -> ScenarioValuation:
    w = compute_wacc(scenario.capital, scenario.tax_rate)
    projection = project(model, scenario)
    r = w.wacc
    factors = tuple(discount_factor(r, p) for p in projection.discount_periods)
    pvs = tuple(f * cf for f, cf in zip(factors, projection.ufcf, strict=True))
    pv_sum = sum(pvs)

    final = projection.final
    gordon_period = final.discount_period
    exit_period = float(final.period_index)

    gordon_tv = gordon_terminal_value(final.ufcf, r, scenario.terminal.growth_rate)
    exit_tv = exit_terminal_value(final.ebitda, scenario.terminal.exit_multiple)

    perpetuity = _method(
        model,
        "perpetuity_growth",
        r,
        pv_sum,
        gordon_tv,
        gordon_period,
        implied_exit_multiple(gordon_tv, final.ebitda, r, gordon_period, exit_period),
    )
    exit_multiple = _method(
        model,
        "exit_multiple",
        r,
        pv_sum,
        exit_tv,
        exit_period,
        implied_perpetual_growth(exit_tv, final.ufcf, r, gordon_period, exit_period),
    )
    return ScenarioValuation(
        scenario=scenario,
        wacc=w,
        projection=projection,
        discount_factors=factors,
        pv_of_fcf_by_year=pvs,
        perpetuity=perpetuity,
        exit_multiple=exit_multiple,
    )


def _method(
    model: CompanyModel,
    method: Method,
    wacc: float,
    pv_sum: float,
    tv: float,
    period: float,
    implied: float,
) -> MethodValuation:
    pv_tv = tv * discount_factor(wacc, period)
    ev = pv_sum + pv_tv
    equity = ev - model.net_debt
    price = equity / model.diluted_shares
    upside = (
        price / model.current_share_price - 1.0 if model.current_share_price is not None else None
    )
    return MethodValuation(
        method=method,
        wacc=wacc,
        pv_of_fcf=pv_sum,
        terminal_value=tv,
        tv_discount_period=period,
        pv_of_terminal_value=pv_tv,
        enterprise_value=ev,
        net_debt=model.net_debt,
        equity_value=equity,
        diluted_shares=model.diluted_shares,
        share_price=price,
        implied_metric=implied,
        upside=upside,
    )


def axis(center: float, step: float, steps: int) -> tuple[float, ...]:
    return tuple(center + k * step for k in range(-steps, steps + 1))


def sensitivity_tables(
    model: CompanyModel, sv: ScenarioValuation
) -> tuple[SensitivityTable, SensitivityTable]:
    cfg = model.sensitivity
    waccs = axis(sv.wacc.wacc, cfg.wacc_step, cfg.steps)
    growths = axis(sv.scenario.terminal.growth_rate, cfg.growth_step, cfg.steps)
    multiples = axis(sv.scenario.terminal.exit_multiple, cfg.multiple_step, cfg.steps)
    kw = {"net_debt": model.net_debt, "diluted_shares": model.diluted_shares}

    def growth_cell(w: float, g: float) -> float | None:
        if w <= g:
            return None
        return implied_share_price(sv.projection, w, growth=g, **kw)

    growth_table = SensitivityTable(
        title=f"Implied share price: WACC vs. terminal growth ({sv.scenario.label})",
        row_label="WACC",
        col_label="Terminal growth rate",
        row_values=waccs,
        col_values=growths,
        values=tuple(tuple(growth_cell(w, g) for g in growths) for w in waccs),
    )
    multiple_table = SensitivityTable(
        title=f"Implied share price: WACC vs. exit multiple ({sv.scenario.label})",
        row_label="WACC",
        col_label="Exit EV / EBITDA",
        row_values=waccs,
        col_values=multiples,
        values=tuple(
            tuple(implied_share_price(sv.projection, w, multiple=m, **kw) for m in multiples)
            for w in waccs
        ),
    )
    return growth_table, multiple_table


def value_model(model: CompanyModel) -> ValuationResult:
    scenarios = tuple(value_scenario(model, s) for s in model.scenarios)
    primary = next(s for s in scenarios if s.name == model.primary_scenario)
    growth_table, multiple_table = sensitivity_tables(model, primary)
    return ValuationResult(
        model=model,
        scenarios=scenarios,
        growth_sensitivity=growth_table,
        multiple_sensitivity=multiple_table,
    )

"""Typed, immutable description of a company DCF model.

Everything here is pure data. Parsing lives in :mod:`dcf_engine.loader`, the maths in
:mod:`dcf_engine.wacc`, :mod:`dcf_engine.projections` and :mod:`dcf_engine.valuation`.

Conventions
-----------
* Monetary amounts are in the model's ``units`` (e.g. millions) of ``currency``.
* Rates are decimals: ``0.25`` means 25%.
* Year-indexed series always have exactly ``projection_years`` entries; index ``0`` is the
  first projected year (base year + 1).
"""

from __future__ import annotations

from dataclasses import dataclass, field

Series = tuple[float, ...]


@dataclass(frozen=True)
class CompanyInfo:
    name: str
    ticker: str
    base_year: int
    currency: str = "USD"
    units: str = "millions"
    description: str = ""
    illustrative: bool = True


@dataclass(frozen=True)
class OperatingAssumptions:
    """Per-year operating drivers, all expressed as a fraction of revenue (except growth)."""

    revenue_growth: Series
    ebitda_margin: Series
    da_pct_revenue: Series
    capex_pct_revenue: Series
    nwc_pct_revenue: Series

    def __post_init__(self) -> None:
        lengths = {len(s) for s in self._series()}
        if len(lengths) != 1:
            raise ValueError("all operating series must have the same length")

    def _series(self) -> tuple[Series, ...]:
        return (
            self.revenue_growth,
            self.ebitda_margin,
            self.da_pct_revenue,
            self.capex_pct_revenue,
            self.nwc_pct_revenue,
        )

    @property
    def years(self) -> int:
        return len(self.revenue_growth)


@dataclass(frozen=True)
class CostOfCapital:
    """CAPM / WACC inputs.

    If ``beta_is_unlevered`` is true, ``beta`` is an asset (unlevered) beta and is relevered
    at the target capital structure with the Hamada equation.
    """

    risk_free_rate: float
    beta: float
    equity_risk_premium: float
    pre_tax_cost_of_debt: float
    target_debt_to_equity: float
    size_premium: float = 0.0
    beta_is_unlevered: bool = False


@dataclass(frozen=True)
class TerminalAssumptions:
    growth_rate: float
    exit_multiple: float  # EV / EBITDA applied to final projected year EBITDA


@dataclass(frozen=True)
class Scenario:
    name: str
    operating: OperatingAssumptions
    capital: CostOfCapital
    terminal: TerminalAssumptions
    tax_rate: float

    @property
    def label(self) -> str:
        return f"{self.name.replace('_', ' ').title()} case"


@dataclass(frozen=True)
class SensitivityConfig:
    """Grid spacing for the sensitivity tables; ``steps`` is the number of steps each side."""

    wacc_step: float = 0.005
    growth_step: float = 0.0025
    multiple_step: float = 1.0
    steps: int = 2

    @property
    def size(self) -> int:
        return 2 * self.steps + 1


@dataclass(frozen=True)
class CompanyModel:
    company: CompanyInfo
    base_revenue: float
    net_debt: float
    diluted_shares: float
    scenarios: tuple[Scenario, ...]
    primary_scenario: str
    base_nwc: float | None = None
    current_share_price: float | None = None
    mid_year_convention: bool = True
    sensitivity: SensitivityConfig = field(default_factory=SensitivityConfig)

    def __post_init__(self) -> None:
        if not self.scenarios:
            raise ValueError("a model needs at least one scenario")
        names = [s.name for s in self.scenarios]
        if len(set(names)) != len(names):
            raise ValueError(f"duplicate scenario names: {names}")
        if self.primary_scenario not in names:
            raise ValueError(f"primary scenario {self.primary_scenario!r} not in {names}")
        if len({s.operating.years for s in self.scenarios}) != 1:
            raise ValueError("all scenarios must project the same number of years")

    @property
    def projection_years(self) -> int:
        return self.scenarios[0].operating.years

    @property
    def projection_year_labels(self) -> tuple[int, ...]:
        base = self.company.base_year
        return tuple(base + i for i in range(1, self.projection_years + 1))

    def scenario(self, name: str) -> Scenario:
        for s in self.scenarios:
            if s.name == name:
                return s
        raise KeyError(f"unknown scenario {name!r}; available: {[s.name for s in self.scenarios]}")

    @property
    def primary(self) -> Scenario:
        return self.scenario(self.primary_scenario)

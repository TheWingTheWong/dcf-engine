"""Unlevered free cash flow build.

For each projected year t (1..N):

    revenue_t   = revenue_{t-1} * (1 + g_t)
    EBITDA_t    = revenue_t * ebitda_margin_t
    D&A_t       = revenue_t * da_pct_t
    EBIT_t      = EBITDA_t - D&A_t
    taxes_t     = max(EBIT_t, 0) * tax_rate           (no tax credit on operating losses)
    NOPAT_t     = EBIT_t - taxes_t
    capex_t     = revenue_t * capex_pct_t
    NWC_t       = revenue_t * nwc_pct_t
    dNWC_t      = NWC_t - NWC_{t-1}
    UFCF_t      = NOPAT_t + D&A_t - capex_t - dNWC_t

NWC_0 is the base-year balance from the model file, or ``revenue_0 * nwc_pct_1`` when
omitted (i.e. assume the year-1 ratio already held in the base year).

Discount periods are ``t - 0.5`` under the mid-year convention and ``t`` otherwise.
All amounts are stored as positive magnitudes; the Excel build shows outflows negative.
"""

from __future__ import annotations

from dataclasses import dataclass

from dcf_engine.model import CompanyModel, Scenario


@dataclass(frozen=True)
class YearProjection:
    year: int
    period_index: int  # 1..N
    discount_period: float
    revenue: float
    revenue_growth: float
    ebitda: float
    da: float
    ebit: float
    taxes: float
    nopat: float
    capex: float
    nwc: float
    change_in_nwc: float
    ufcf: float

    @property
    def ebitda_margin(self) -> float:
        return self.ebitda / self.revenue


@dataclass(frozen=True)
class Projection:
    base_year: int
    base_revenue: float
    base_nwc: float
    years: tuple[YearProjection, ...]

    @property
    def final(self) -> YearProjection:
        return self.years[-1]

    @property
    def ufcf(self) -> tuple[float, ...]:
        return tuple(y.ufcf for y in self.years)

    @property
    def discount_periods(self) -> tuple[float, ...]:
        return tuple(y.discount_period for y in self.years)


def base_nwc(model: CompanyModel, scenario: Scenario) -> float:
    if model.base_nwc is not None:
        return model.base_nwc
    return model.base_revenue * scenario.operating.nwc_pct_revenue[0]


def project(model: CompanyModel, scenario: Scenario) -> Projection:
    op = scenario.operating
    prev_revenue = model.base_revenue
    prev_nwc = base_nwc(model, scenario)
    offset = 0.5 if model.mid_year_convention else 0.0
    years: list[YearProjection] = []
    for i in range(op.years):
        t = i + 1
        revenue = prev_revenue * (1.0 + op.revenue_growth[i])
        ebitda = revenue * op.ebitda_margin[i]
        da = revenue * op.da_pct_revenue[i]
        ebit = ebitda - da
        taxes = max(ebit, 0.0) * scenario.tax_rate
        nopat = ebit - taxes
        capex = revenue * op.capex_pct_revenue[i]
        nwc = revenue * op.nwc_pct_revenue[i]
        change_in_nwc = nwc - prev_nwc
        years.append(
            YearProjection(
                year=model.company.base_year + t,
                period_index=t,
                discount_period=t - offset,
                revenue=revenue,
                revenue_growth=op.revenue_growth[i],
                ebitda=ebitda,
                da=da,
                ebit=ebit,
                taxes=taxes,
                nopat=nopat,
                capex=capex,
                nwc=nwc,
                change_in_nwc=change_in_nwc,
                ufcf=nopat + da - capex - change_in_nwc,
            )
        )
        prev_revenue, prev_nwc = revenue, nwc
    return Projection(
        base_year=model.company.base_year,
        base_revenue=model.base_revenue,
        base_nwc=base_nwc(model, scenario),
        years=tuple(years),
    )

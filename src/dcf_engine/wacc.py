"""Weighted average cost of capital from CAPM.

levered beta      = beta_u * (1 + (1 - t) * D/E)          (Hamada, only if beta is unlevered)
cost of equity    = r_f + beta_L * ERP + size premium
after-tax k_d     = k_d * (1 - t)
E / (D + E)       = 1 / (1 + D/E)
D / (D + E)       = (D/E) / (1 + D/E)
WACC              = E/(D+E) * k_e + D/(D+E) * k_d * (1 - t)
"""

from __future__ import annotations

from dataclasses import dataclass

from dcf_engine.model import CostOfCapital


@dataclass(frozen=True)
class WaccResult:
    levered_beta: float
    cost_of_equity: float
    after_tax_cost_of_debt: float
    equity_weight: float
    debt_weight: float
    wacc: float


def relever_beta(unlevered_beta: float, debt_to_equity: float, tax_rate: float) -> float:
    return unlevered_beta * (1.0 + (1.0 - tax_rate) * debt_to_equity)


def compute_wacc(capital: CostOfCapital, tax_rate: float) -> WaccResult:
    de = capital.target_debt_to_equity
    beta = relever_beta(capital.beta, de, tax_rate) if capital.beta_is_unlevered else capital.beta
    cost_of_equity = (
        capital.risk_free_rate + beta * capital.equity_risk_premium + capital.size_premium
    )
    after_tax_kd = capital.pre_tax_cost_of_debt * (1.0 - tax_rate)
    equity_weight = 1.0 / (1.0 + de)
    debt_weight = de / (1.0 + de)
    return WaccResult(
        levered_beta=beta,
        cost_of_equity=cost_of_equity,
        after_tax_cost_of_debt=after_tax_kd,
        equity_weight=equity_weight,
        debt_weight=debt_weight,
        wacc=equity_weight * cost_of_equity + debt_weight * after_tax_kd,
    )

"""Load and validate company models from YAML.

The file has a base set of ``assumptions`` and an optional ``scenarios`` mapping. Each
scenario is a *partial override* that is deep-merged over the base assumptions, so a bear
case only needs to state what differs::

    assumptions:
      revenue_growth: [0.12, 0.10, 0.08, 0.06, 0.05]
      ebitda_margin: 0.22
      ...
    scenarios:
      bear:
        revenue_growth: [0.06, 0.05, 0.04, 0.03, 0.03]
        wacc: {beta: 1.35}

Year-indexed drivers accept either a scalar (held flat) or a list of exactly
``projection_years`` values. All validation errors are raised as :class:`ModelError`
with a dotted path to the offending key.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from dcf_engine.model import (
    CompanyInfo,
    CompanyModel,
    CostOfCapital,
    OperatingAssumptions,
    Scenario,
    SensitivityConfig,
    TerminalAssumptions,
)

BASE_SCENARIO = "base"
# Well-known scenario names are ordered pessimistic -> optimistic; others keep file order.
_SCENARIO_RANK = {"bear": 0, "downside": 0, "base": 1, "bull": 2, "upside": 2}


class ModelError(ValueError):
    """Raised when a model file is malformed or economically invalid."""


def load_model(path: str | Path) -> CompanyModel:
    path = Path(path)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ModelError(f"model file not found: {path}") from exc
    except yaml.YAMLError as exc:
        raise ModelError(f"{path}: invalid YAML: {exc}") from exc
    return parse_model(raw)


def parse_model(raw: Any) -> CompanyModel:
    data = _mapping(raw, "<root>")

    company_raw = _mapping(data.get("company"), "company")
    company = CompanyInfo(
        name=_str(company_raw, "name", "company"),
        ticker=_str(company_raw, "ticker", "company"),
        base_year=int(_number(company_raw, "base_year", "company")),
        currency=str(company_raw.get("currency", "USD")),
        units=str(company_raw.get("units", "millions")),
        description=str(company_raw.get("description", "")).strip(),
        illustrative=bool(company_raw.get("illustrative", True)),
    )

    fin = _mapping(data.get("financials"), "financials")
    base_revenue = _number(fin, "revenue", "financials", positive=True)
    net_debt = _number(fin, "net_debt", "financials")
    shares = _number(fin, "diluted_shares", "financials", positive=True)
    base_nwc = _optional_number(fin, "net_working_capital", "financials")
    share_price = _optional_number(fin, "share_price", "financials", positive=True)

    settings = _mapping(data.get("settings", {}), "settings")
    years = int(_number(settings, "projection_years", "settings", default=5))
    if not 1 <= years <= 30:
        raise ModelError(f"settings.projection_years: must be between 1 and 30, got {years}")
    mid_year = bool(settings.get("mid_year_convention", True))

    base_assumptions = _mapping(data.get("assumptions"), "assumptions")
    overrides = _mapping(data.get("scenarios") or {}, "scenarios")
    scenario_raw: dict[str, Mapping[str, Any]] = {BASE_SCENARIO: base_assumptions}
    for name, override in overrides.items():
        name = str(name)
        merged = _deep_merge(base_assumptions, _mapping(override or {}, f"scenarios.{name}"))
        scenario_raw[name] = merged

    ordered = sorted(scenario_raw, key=lambda n: _SCENARIO_RANK.get(n, 1.5))
    scenarios = tuple(
        _parse_scenario(
            name,
            scenario_raw[name],
            years,
            "assumptions" if name == BASE_SCENARIO else f"scenarios.{name}",
        )
        for name in ordered
    )

    primary = str(settings.get("primary_scenario", BASE_SCENARIO))
    if primary not in scenario_raw:
        raise ModelError(
            f"settings.primary_scenario: {primary!r} is not one of {sorted(scenario_raw)}"
        )

    sens_raw = _mapping(data.get("sensitivity", {}), "sensitivity")
    defaults = SensitivityConfig()
    sensitivity = SensitivityConfig(
        wacc_step=_number(sens_raw, "wacc_step", "sensitivity", default=defaults.wacc_step),
        growth_step=_number(sens_raw, "growth_step", "sensitivity", default=defaults.growth_step),
        multiple_step=_number(
            sens_raw, "multiple_step", "sensitivity", default=defaults.multiple_step
        ),
        steps=int(_number(sens_raw, "steps", "sensitivity", default=defaults.steps)),
    )
    if not 1 <= sensitivity.steps <= 5:
        raise ModelError("sensitivity.steps: must be between 1 and 5")

    return CompanyModel(
        company=company,
        base_revenue=base_revenue,
        net_debt=net_debt,
        diluted_shares=shares,
        scenarios=scenarios,
        primary_scenario=primary,
        base_nwc=base_nwc,
        current_share_price=share_price,
        mid_year_convention=mid_year,
        sensitivity=sensitivity,
    )


def _parse_scenario(name: str, raw: Mapping[str, Any], years: int, path: str) -> Scenario:
    operating = OperatingAssumptions(
        revenue_growth=_series(raw, "revenue_growth", path, years, lower=-0.99),
        ebitda_margin=_series(raw, "ebitda_margin", path, years, lower=-1.0, upper=1.0),
        da_pct_revenue=_series(raw, "da_pct_revenue", path, years, lower=0.0, upper=1.0),
        capex_pct_revenue=_series(raw, "capex_pct_revenue", path, years, lower=0.0, upper=1.0),
        nwc_pct_revenue=_series(raw, "nwc_pct_revenue", path, years, lower=-1.0, upper=1.0),
    )
    tax_rate = _number(raw, "tax_rate", path)
    if not 0.0 <= tax_rate < 1.0:
        raise ModelError(f"{path}.tax_rate: must be in [0, 1), got {tax_rate}")

    w = _mapping(raw.get("wacc"), f"{path}.wacc")
    wpath = f"{path}.wacc"
    has_levered = "beta" in w
    has_unlevered = "unlevered_beta" in w
    if has_levered == has_unlevered:
        raise ModelError(f"{wpath}: specify exactly one of 'beta' or 'unlevered_beta'")
    capital = CostOfCapital(
        risk_free_rate=_number(w, "risk_free_rate", wpath),
        beta=_number(w, "unlevered_beta" if has_unlevered else "beta", wpath, positive=True),
        equity_risk_premium=_number(w, "equity_risk_premium", wpath),
        pre_tax_cost_of_debt=_number(w, "pre_tax_cost_of_debt", wpath),
        target_debt_to_equity=_number(w, "target_debt_to_equity", wpath),
        size_premium=_number(w, "size_premium", wpath, default=0.0),
        beta_is_unlevered=has_unlevered,
    )
    if capital.target_debt_to_equity < 0:
        raise ModelError(f"{wpath}.target_debt_to_equity: must be >= 0")

    t = _mapping(raw.get("terminal"), f"{path}.terminal")
    terminal = TerminalAssumptions(
        growth_rate=_number(t, "growth_rate", f"{path}.terminal"),
        exit_multiple=_number(t, "exit_multiple", f"{path}.terminal", positive=True),
    )
    return Scenario(
        name=name, operating=operating, capital=capital, terminal=terminal, tax_rate=tax_rate
    )


# --------------------------------------------------------------------------- helpers


def _deep_merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(dict(base))
    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(merged.get(key), Mapping):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    # A scenario that switches beta flavour must not inherit the other one from the base.
    wacc_override = override.get("wacc")
    if isinstance(wacc_override, Mapping) and isinstance(merged.get("wacc"), dict):
        if "beta" in wacc_override:
            merged["wacc"].pop("unlevered_beta", None)
        if "unlevered_beta" in wacc_override:
            merged["wacc"].pop("beta", None)
    return merged


def _mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        found = "nothing" if value is None else type(value).__name__
        raise ModelError(f"{path}: expected a mapping, found {found}")
    return value


def _str(data: Mapping[str, Any], key: str, path: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ModelError(f"{path}.{key}: expected a non-empty string")
    return value.strip()


_MISSING = object()


def _number(
    data: Mapping[str, Any],
    key: str,
    path: str,
    *,
    default: Any = _MISSING,
    positive: bool = False,
) -> float:
    if key not in data or data[key] is None:
        if default is _MISSING:
            raise ModelError(f"{path}.{key}: required")
        return float(default)
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ModelError(f"{path}.{key}: expected a number, got {value!r}")
    if positive and value <= 0:
        raise ModelError(f"{path}.{key}: must be positive, got {value}")
    return float(value)


def _optional_number(
    data: Mapping[str, Any], key: str, path: str, *, positive: bool = False
) -> float | None:
    if data.get(key) is None:
        return None
    return _number(data, key, path, positive=positive)


def _series(
    data: Mapping[str, Any],
    key: str,
    path: str,
    years: int,
    *,
    lower: float | None = None,
    upper: float | None = None,
) -> tuple[float, ...]:
    if key not in data:
        raise ModelError(f"{path}.{key}: required")
    value = data[key]
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        values = [float(value)] * years
    elif isinstance(value, list):
        if len(value) != years:
            raise ModelError(f"{path}.{key}: expected {years} values, got {len(value)}")
        values = []
        for i, v in enumerate(value):
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise ModelError(f"{path}.{key}[{i}]: expected a number, got {v!r}")
            values.append(float(v))
    else:
        raise ModelError(f"{path}.{key}: expected a number or a list of {years} numbers")
    for i, v in enumerate(values):
        if (lower is not None and v < lower) or (upper is not None and v > upper):
            raise ModelError(f"{path}.{key}[{i}]: {v} outside allowed range [{lower}, {upper}]")
    return tuple(values)

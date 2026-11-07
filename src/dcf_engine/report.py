"""Plain-text console summary of a valuation."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from dcf_engine.valuation import MethodValuation, SensitivityTable, ValuationResult

_SYMBOLS = {"USD": "$", "EUR": "€", "GBP": "£", "JPY": "¥", "CAD": "$", "AUD": "$"}


def _amount(x: float) -> str:
    return f"({abs(x):,.1f})" if x < 0 else f"{x:,.1f}"


def _pct(x: float, digits: int = 1) -> str:
    return f"({abs(x):.{digits}%})" if x < 0 else f"{x:.{digits}%}"


def _table(rows: Sequence[Sequence[str]], *, label_width: int, col_width: int) -> list[str]:
    lines = []
    for row in rows:
        label, *cells = row
        lines.append(label.ljust(label_width) + "".join(c.rjust(col_width) for c in cells))
    return [line.rstrip() for line in lines]


class _Fmt:
    def __init__(self, currency: str):
        self.symbol = _SYMBOLS.get(currency.upper(), "")

    def price(self, x: float | None) -> str:
        if x is None:
            return "n/m"
        sign = "-" if x < 0 else ""
        return f"{sign}{self.symbol}{abs(x):,.2f}"


def render(result: ValuationResult) -> str:
    m = result.model
    c = m.company
    fmt = _Fmt(c.currency)
    out: list[str] = []

    out.append(f"{c.name} ({c.ticker})")
    if c.illustrative:
        out.append("Illustrative model of a fictional company. Not investment advice.")
    convention = "mid-year discounting" if m.mid_year_convention else "end-of-year discounting"
    out.append(
        f"{c.currency} {c.units} | base year FY{c.base_year}A | "
        f"{m.projection_years}-year projection | {convention}"
    )
    out.append("")

    # Free cash flow for the primary scenario.
    sv = result.primary
    years = sv.projection.years
    header = ["", f"{c.base_year}A", *(f"{y.year}E" for y in years)]
    fcf_rows: list[list[str]] = [
        header,
        ["Revenue", _amount(m.base_revenue), *(_amount(y.revenue) for y in years)],
        ["  growth", "", *(_pct(y.revenue_growth) for y in years)],
        ["EBITDA", "", *(_amount(y.ebitda) for y in years)],
        ["  margin", "", *(_pct(y.ebitda_margin) for y in years)],
        ["EBIT", "", *(_amount(y.ebit) for y in years)],
        ["Unlevered FCF", "", *(_amount(y.ufcf) for y in years)],
        ["PV of UFCF", "", *(_amount(v) for v in sv.pv_of_fcf_by_year)],
    ]
    out.append(f"Free cash flow, {sv.scenario.label.lower()}")
    out += _table(fcf_rows, label_width=16, col_width=10)
    out.append("")

    # Valuation by scenario.
    scen = result.scenarios

    def row(label: str, f: Callable[[MethodValuation], str], method: str) -> list[str]:
        return [label, *(f(getattr(s, method)) for s in scen)]

    val_rows: list[list[str]] = [
        ["", *(s.scenario.label for s in scen)],
        ["WACC", *(_pct(s.wacc.wacc, 2) for s in scen)],
        ["Terminal growth", *(_pct(s.scenario.terminal.growth_rate, 2) for s in scen)],
        ["Exit multiple", *(f"{s.scenario.terminal.exit_multiple:.1f}x" for s in scen)],
        ["Enterprise value"],
        row("  Perpetuity growth", lambda v: _amount(v.enterprise_value), "perpetuity"),
        row("  Exit multiple", lambda v: _amount(v.enterprise_value), "exit_multiple"),
        ["Implied share price"],
        row("  Perpetuity growth", lambda v: fmt.price(v.share_price), "perpetuity"),
        row("  Exit multiple", lambda v: fmt.price(v.share_price), "exit_multiple"),
    ]
    if m.current_share_price is not None:
        val_rows += [
            [f"Upside vs. {fmt.price(m.current_share_price)}"],
            row("  Perpetuity growth", lambda v: _pct(v.upside or 0.0), "perpetuity"),
            row("  Exit multiple", lambda v: _pct(v.upside or 0.0), "exit_multiple"),
        ]
    val_rows += [
        ["Cross-checks"],
        row("  Implied exit multiple", lambda v: f"{v.implied_metric:.1f}x", "perpetuity"),
        row("  Implied perpetual growth", lambda v: _pct(v.implied_metric, 2), "exit_multiple"),
        row("  PV of TV / EV (perpetuity)", lambda v: _pct(v.tv_share_of_ev), "perpetuity"),
    ]
    out.append("Valuation")
    out += _table(val_rows, label_width=28, col_width=12)
    out.append("")

    for table in (result.growth_sensitivity, result.multiple_sensitivity):
        out += _sensitivity(table, fmt)
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def _sensitivity(table: SensitivityTable, fmt: _Fmt) -> list[str]:
    is_multiple = table.col_label.startswith("Exit")
    center = len(table.row_values) // 2

    def col_header(x: float) -> str:
        return f"{x:.1f}x" if is_multiple else _pct(x, 2)

    rows: list[list[str]] = [[f"WACC \\ {'multiple' if is_multiple else 'growth'}"]]
    rows[0] += [col_header(x) for x in table.col_values]
    for i, (w, values) in enumerate(zip(table.row_values, table.values, strict=True)):
        cells = []
        for j, v in enumerate(values):
            text = fmt.price(v)
            cells.append(f"[{text}]" if i == center and j == center else f"{text} ")
        rows.append([f"{_pct(w, 2):>8}", *cells])
    return [table.title, *_table(rows, label_width=18, col_width=11)]

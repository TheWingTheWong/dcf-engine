"""Write a valuation to an .xlsx workbook made of live Excel formulas.

Only the Assumptions sheet (and the three sensitivity step sizes) hold hard-coded numbers.
Every other figure is a formula that traces back to those inputs, so the workbook can be
audited, flexed and re-solved in Excel without re-running Python.

Sheets, in order: Summary (with football field), Assumptions, WACC, FCF Build, Valuation,
Sensitivity.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from dcf_engine.excel import styles as st
from dcf_engine.excel.layout import (
    BASE_YEAR_COL,
    LABEL_COL,
    UNITS_COL,
    Cell,
    Layout,
    ref,
    scenario_col,
    year_col,
)
from dcf_engine.model import CompanyModel, Scenario
from dcf_engine.valuation import ValuationResult

SUMMARY = "Summary"
ASSUMPTIONS = "Assumptions"
WACC = "WACC"
FCF = "FCF Build"
VALUATION = "Valuation"
SENSITIVITY = "Sensitivity"


class _Sheet:
    """Thin wrapper over a worksheet that applies the house style."""

    def __init__(self, ws: Worksheet, *, label_width: float = 42, data_width: float = 11.5):
        self.ws = ws
        self.name = ws.title
        ws.sheet_view.showGridLines = False
        ws.sheet_view.zoomScale = 90
        ws.column_dimensions["A"].width = label_width
        ws.column_dimensions["B"].width = 7
        for col in range(3, 30):
            ws.column_dimensions[get_column_letter(col)].width = data_width
        ws.page_setup.orientation = "landscape"
        ws.page_setup.fitToWidth = 1
        ws.page_setup.fitToHeight = 0
        ws.sheet_properties.pageSetUpPr.fitToPage = True

    def title(self, model: CompanyModel, heading: str) -> int:
        c = model.company
        self.text(1, LABEL_COL, f"{c.name} ({c.ticker})", bold=True, size=12)
        self.text(2, LABEL_COL, heading, bold=True)
        units = f"{c.currency} in {c.units}, except per-share amounts"
        if c.illustrative:
            units += ". Illustrative model of a fictional company; not investment advice."
        self.text(3, LABEL_COL, units, italic=True, color=st.MUTED)
        return 5

    def text(
        self,
        row: int,
        col: int,
        value: str,
        *,
        bold: bool = False,
        italic: bool = False,
        size: int = st.FONT_SIZE,
        color: str = st.BLACK,
        indent: int = 0,
        align: str | None = None,
    ) -> None:
        cell = self.ws.cell(row=row, column=col, value=value)
        cell.font = st.font(color, bold=bold, italic=italic, size=size)
        if indent:
            cell.alignment = st.LEFT_INDENT
        elif align == "right":
            cell.alignment = st.RIGHT
        elif align == "center":
            cell.alignment = st.CENTER

    def label(
        self,
        row: int,
        text: str,
        units: str = "",
        *,
        bold: bool = False,
        italic: bool = False,
        indent: bool = False,
    ) -> None:
        self.text(row, LABEL_COL, text, bold=bold, italic=italic, indent=int(indent))
        if units:
            self.text(row, UNITS_COL, units, italic=True, color=st.MUTED)

    def section(self, row: int, text: str, last_col: int) -> None:
        self.text(row, LABEL_COL, text, bold=True)
        for col in range(LABEL_COL, last_col + 1):
            self.ws.cell(row=row, column=col).border = st.BORDER_BOTTOM

    def put(
        self,
        row: int,
        col: int,
        value: Any,
        fmt: str,
        *,
        role: str | None = None,
        bold: bool = False,
        italic: bool = False,
    ) -> Cell:
        """Write a value or formula. ``role`` is inferred: numbers are inputs (blue),
        single cross-sheet references are links (green), other formulas are black."""
        if role is None:
            if isinstance(value, str) and value.startswith("="):
                role = "link" if st.is_cross_sheet_link(value) else "calc"
            else:
                role = "input"
        color = {"input": st.INPUT_BLUE, "link": st.LINK_GREEN, "calc": st.BLACK}[role]
        cell = self.ws.cell(row=row, column=col, value=value)
        cell.font = st.font(color, bold=bold, italic=italic)
        cell.number_format = fmt
        cell.alignment = st.RIGHT
        return Cell(self.name, col, row)

    def rule_above(self, row: int, first_col: int, last_col: int) -> None:
        for col in range(first_col, last_col + 1):
            self.ws.cell(row=row, column=col).border = st.BORDER_TOP

    def box(self, row: int, col: int) -> None:
        self.ws.cell(row=row, column=col).border = st.BORDER_BOX

    def header_cells(self, row: int, first_col: int, values: Sequence[str]) -> None:
        for i, v in enumerate(values):
            self.text(row, first_col + i, v, bold=True, align="right")
            self.ws.cell(row=row, column=first_col + i).border = st.BORDER_BOTTOM


class WorkbookBuilder:
    def __init__(self, result: ValuationResult):
        self.result = result
        self.model = result.model
        self.layout = Layout()
        self.wb = Workbook()
        self.price_fmt = st.price_format(self.model.company.currency)
        self.n_years = self.model.projection_years
        self.last_year_col = year_col(self.n_years - 1)
        self.scenarios: tuple[Scenario, ...] = self.model.scenarios
        self.last_scen_col = scenario_col(len(self.scenarios) - 1)

        first = self.wb.active
        first.title = SUMMARY
        self.sheets = {SUMMARY: _Sheet(first, label_width=48, data_width=12.5)}
        for name in (ASSUMPTIONS, WACC, FCF, VALUATION, SENSITIVITY):
            self.sheets[name] = _Sheet(self.wb.create_sheet(name))

    # ------------------------------------------------------------------ helpers

    def c(self, key: str) -> Cell:
        return self.layout.cell(key)

    def r(self, key: str) -> int:
        return self.layout.row(key)

    def _scenario_header(self, sh: _Sheet, row: int) -> None:
        sh.header_cells(row, scenario_col(0), [s.label for s in self.scenarios])

    # ------------------------------------------------------------------ build

    def build(self) -> tuple[Workbook, Layout]:
        self._assumptions()
        self._wacc()
        self._fcf()
        self._valuation()
        self._sensitivity()
        self._summary()
        self.wb.active = 0
        # openpyxl stores no cached results, so ask the spreadsheet app to calculate on open.
        self.wb.calculation.fullCalcOnLoad = True
        return self.wb, self.layout

    # ------------------------------------------------------------------ Assumptions

    def _assumptions(self) -> None:
        sh = self.sheets[ASSUMPTIONS]
        m, L = self.model, self.layout
        row = sh.title(m, "Assumptions")

        sh.text(row, LABEL_COL, "Key:", italic=True, color=st.MUTED)
        sh.text(row, BASE_YEAR_COL, "Input", color=st.INPUT_BLUE, align="right")
        sh.text(row, BASE_YEAR_COL + 1, "Formula", align="right")
        sh.text(row, BASE_YEAR_COL + 2, "Link", color=st.LINK_GREEN, align="right")
        row += 2

        sh.section(row, "Company and capitalisation", BASE_YEAR_COL)
        row += 1
        cur = m.company.currency
        items: list[tuple[str, str, str, Any, str]] = [
            ("base_year", "Last actual fiscal year", "", m.company.base_year, st.FMT_YEAR),
            ("base_revenue", "Revenue, last actual year", cur, m.base_revenue, st.FMT_AMOUNT),
        ]
        if m.base_nwc is not None:
            items.append(
                (
                    "base_nwc",
                    "Net working capital, last actual year",
                    cur,
                    m.base_nwc,
                    st.FMT_AMOUNT,
                )
            )
        items += [
            ("net_debt", "Net debt (debt less cash)", cur, m.net_debt, st.FMT_AMOUNT),
            ("shares", "Diluted shares outstanding", "mm", m.diluted_shares, st.FMT_AMOUNT),
        ]
        if m.current_share_price is not None:
            items.append(
                ("share_price", "Current share price", cur, m.current_share_price, self.price_fmt)
            )
        items.append(
            (
                "mid_year",
                "Mid-year discounting (1 = on, 0 = off)",
                "flag",
                int(m.mid_year_convention),
                st.FMT_FLAG,
            )
        )
        for key, text, units, value, fmt in items:
            sh.label(row, text, units)
            sh.put(row, BASE_YEAR_COL, value, fmt)
            L.add_cell(f"assumptions/{key}", ASSUMPTIONS, BASE_YEAR_COL, row)
            row += 1
        row += 1

        sh.section(row, "Scenario assumptions", self.last_scen_col)
        self._scenario_header(sh, row)
        row += 1
        scalar_rows: list[tuple[str, str, str, str, Any]] = [
            ("tax_rate", "Tax rate", "%", st.FMT_PCT, lambda s: s.tax_rate),
            (
                "risk_free_rate",
                "Risk-free rate",
                "%",
                st.FMT_PCT2,
                lambda s: s.capital.risk_free_rate,
            ),
            ("beta", "Beta", "", st.FMT_BETA, lambda s: s.capital.beta),
            (
                "beta_is_unlevered",
                "Beta is unlevered (1 = relever at target D/E)",
                "flag",
                st.FMT_FLAG,
                lambda s: int(s.capital.beta_is_unlevered),
            ),
            (
                "equity_risk_premium",
                "Equity risk premium",
                "%",
                st.FMT_PCT2,
                lambda s: s.capital.equity_risk_premium,
            ),
            ("size_premium", "Size premium", "%", st.FMT_PCT2, lambda s: s.capital.size_premium),
            (
                "pre_tax_cost_of_debt",
                "Pre-tax cost of debt",
                "%",
                st.FMT_PCT2,
                lambda s: s.capital.pre_tax_cost_of_debt,
            ),
            (
                "target_debt_to_equity",
                "Target debt / equity",
                "%",
                st.FMT_PCT,
                lambda s: s.capital.target_debt_to_equity,
            ),
            (
                "terminal_growth",
                "Terminal growth rate",
                "%",
                st.FMT_PCT2,
                lambda s: s.terminal.growth_rate,
            ),
            (
                "exit_multiple",
                "Exit multiple (EV / EBITDA)",
                "x",
                st.FMT_MULTIPLE,
                lambda s: s.terminal.exit_multiple,
            ),
        ]
        for key, text, units, fmt, getter in scalar_rows:
            sh.label(row, text, units)
            for j, s in enumerate(self.scenarios):
                sh.put(row, scenario_col(j), getter(s), fmt)
                L.add_cell(f"assumptions/{s.name}/{key}", ASSUMPTIONS, scenario_col(j), row)
            row += 1
        row += 1

        base_year = self.c("assumptions/base_year").ref(ASSUMPTIONS)
        op_rows = [
            ("revenue_growth", "Revenue growth", lambda s: s.operating.revenue_growth),
            ("ebitda_margin", "EBITDA margin", lambda s: s.operating.ebitda_margin),
            ("da_pct_revenue", "D&A % of revenue", lambda s: s.operating.da_pct_revenue),
            ("capex_pct_revenue", "Capex % of revenue", lambda s: s.operating.capex_pct_revenue),
            (
                "nwc_pct_revenue",
                "Net working capital % of revenue",
                lambda s: s.operating.nwc_pct_revenue,
            ),
        ]
        for s in self.scenarios:
            sh.section(row, f"Operating assumptions: {s.label}", self.last_year_col)
            for i in range(self.n_years):
                sh.put(row, year_col(i), f"={base_year}+{i + 1}", st.FMT_YEAR_ESTIMATE, bold=True)
            row += 1
            for key, text, getter in op_rows:
                sh.label(row, text, "%")
                for i, v in enumerate(getter(s)):
                    sh.put(row, year_col(i), v, st.FMT_PCT)
                L.add_row(f"assumptions/{s.name}/{key}", ASSUMPTIONS, row)
                row += 1
            row += 1
        sh.ws.freeze_panes = "C5"

    # ------------------------------------------------------------------ WACC

    def _wacc(self) -> None:
        sh = self.sheets[WACC]
        L = self.layout
        row = sh.title(self.model, "Weighted average cost of capital")
        sh.section(row, "Cost of capital build (CAPM)", self.last_scen_col)
        self._scenario_header(sh, row)
        row += 1

        def a(s: Scenario, key: str) -> str:
            return self.c(f"assumptions/{s.name}/{key}").ref(WACC)

        def w(s: Scenario, key: str) -> str:
            return self.c(f"wacc/{s.name}/{key}").ref(WACC, absolute=False)

        lines: list[tuple[str, str, str, str, Any, dict[str, bool]]] = [
            (
                "risk_free_rate",
                "Risk-free rate",
                "%",
                st.FMT_PCT2,
                lambda s: f"={a(s, 'risk_free_rate')}",
                {},
            ),
            ("beta_input", "Beta (as input)", "", st.FMT_BETA, lambda s: f"={a(s, 'beta')}", {}),
            (
                "beta_is_unlevered",
                "Beta is unlevered flag",
                "flag",
                st.FMT_FLAG,
                lambda s: f"={a(s, 'beta_is_unlevered')}",
                {},
            ),
            ("tax_rate", "Tax rate", "%", st.FMT_PCT, lambda s: f"={a(s, 'tax_rate')}", {}),
            (
                "debt_to_equity",
                "Target debt / equity",
                "%",
                st.FMT_PCT,
                lambda s: f"={a(s, 'target_debt_to_equity')}",
                {},
            ),
            (
                "levered_beta",
                "Levered beta",
                "",
                st.FMT_BETA,
                lambda s: (
                    f"=IF({w(s, 'beta_is_unlevered')}=1,"
                    f"{w(s, 'beta_input')}*(1+(1-{w(s, 'tax_rate')})*{w(s, 'debt_to_equity')}),"
                    f"{w(s, 'beta_input')})"
                ),
                {},
            ),
            (
                "equity_risk_premium",
                "Equity risk premium",
                "%",
                st.FMT_PCT2,
                lambda s: f"={a(s, 'equity_risk_premium')}",
                {},
            ),
            (
                "size_premium",
                "Size premium",
                "%",
                st.FMT_PCT2,
                lambda s: f"={a(s, 'size_premium')}",
                {},
            ),
            (
                "cost_of_equity",
                "Cost of equity",
                "%",
                st.FMT_PCT2,
                lambda s: (
                    f"={w(s, 'risk_free_rate')}"
                    f"+{w(s, 'levered_beta')}*{w(s, 'equity_risk_premium')}"
                    f"+{w(s, 'size_premium')}"
                ),
                {"bold": True, "rule": True},
            ),
            (None, "", "", "", None, {}),
            (
                "pre_tax_cost_of_debt",
                "Pre-tax cost of debt",
                "%",
                st.FMT_PCT2,
                lambda s: f"={a(s, 'pre_tax_cost_of_debt')}",
                {},
            ),
            (
                "after_tax_cost_of_debt",
                "After-tax cost of debt",
                "%",
                st.FMT_PCT2,
                lambda s: f"={w(s, 'pre_tax_cost_of_debt')}*(1-{w(s, 'tax_rate')})",
                {"bold": True, "rule": True},
            ),
            (None, "", "", "", None, {}),
            (
                "equity_weight",
                "Equity / total capital",
                "%",
                st.FMT_PCT,
                lambda s: f"=1/(1+{w(s, 'debt_to_equity')})",
                {},
            ),
            (
                "debt_weight",
                "Debt / total capital",
                "%",
                st.FMT_PCT,
                lambda s: f"={w(s, 'debt_to_equity')}/(1+{w(s, 'debt_to_equity')})",
                {},
            ),
            (None, "", "", "", None, {}),
            (
                "wacc",
                "WACC",
                "%",
                st.FMT_PCT2,
                lambda s: (
                    f"={w(s, 'equity_weight')}*{w(s, 'cost_of_equity')}"
                    f"+{w(s, 'debt_weight')}*{w(s, 'after_tax_cost_of_debt')}"
                ),
                {"bold": True, "box": True},
            ),
        ]
        # Register every row first so formulas can refer to rows defined further down.
        start = row
        for offset, (key, *_rest) in enumerate(lines):
            if key:
                for j, s in enumerate(self.scenarios):
                    L.add_cell(f"wacc/{s.name}/{key}", WACC, scenario_col(j), start + offset)
        for offset, (key, text, units, fmt, build, opts) in enumerate(lines):
            r = start + offset
            if not key:
                continue
            sh.label(r, text, units, bold=opts.get("bold", False))
            for j, s in enumerate(self.scenarios):
                sh.put(r, scenario_col(j), build(s), fmt, bold=opts.get("bold", False))
                if opts.get("box"):
                    sh.box(r, scenario_col(j))
            if opts.get("rule"):
                sh.rule_above(r, scenario_col(0), self.last_scen_col)

    # ------------------------------------------------------------------ FCF Build

    def _fcf(self) -> None:
        sh = self.sheets[FCF]
        L = self.layout
        row = sh.title(self.model, "Unlevered free cash flow build")
        base_year = self.c("assumptions/base_year").ref(FCF)
        base_revenue = self.c("assumptions/base_revenue").ref(FCF)
        mid_year = self.c("assumptions/mid_year").ref(FCF)
        base_nwc = (
            self.c("assumptions/base_nwc").ref(FCF) if "assumptions/base_nwc" in L.cells else None
        )
        col_letter = get_column_letter
        last = self.last_year_col

        for s in self.scenarios:
            keys = [
                "header",
                "revenue",
                "growth",
                "ebitda",
                "margin",
                "da",
                "ebit",
                "taxes",
                "nopat",
                "plus_da",
                "capex",
                "change_nwc",
                "ufcf",
                "_",
                "nwc",
                "_",
                "period",
                "factor",
                "pv",
            ]
            rows = {k: row + i for i, k in enumerate(keys) if k != "_"}
            for k, r in rows.items():
                L.add_row(f"fcf/{s.name}/{k}", FCF, r)

            def arow(key: str, s: Scenario = s) -> int:
                return self.r(f"assumptions/{s.name}/{key}")

            tax = self.c(f"assumptions/{s.name}/tax_rate").ref(FCF)
            wacc = self.c(f"wacc/{s.name}/wacc").ref(FCF)

            h = rows["header"]
            sh.section(h, s.label, last)
            sh.put(h, BASE_YEAR_COL, f"={base_year}", st.FMT_YEAR_ACTUAL, bold=True)
            for i in range(self.n_years):
                prev = col_letter(year_col(i) - 1)
                sh.put(h, year_col(i), f"={prev}{h}+1", st.FMT_YEAR_ESTIMATE, bold=True)

            labels = {
                "revenue": ("Revenue", False, False),
                "growth": ("% growth", False, True),
                "ebitda": ("EBITDA", False, False),
                "margin": ("% margin", False, True),
                "da": ("Less: depreciation & amortisation", False, False),
                "ebit": ("EBIT", True, False),
                "taxes": ("Less: cash taxes on EBIT", False, False),
                "nopat": ("NOPAT", True, False),
                "plus_da": ("Plus: depreciation & amortisation", False, False),
                "capex": ("Less: capital expenditures", False, False),
                "change_nwc": ("Less: increase in net working capital", False, False),
                "ufcf": ("Unlevered free cash flow", True, False),
                "nwc": ("Memo: net working capital", False, True),
                "period": ("Discount period (years)", False, False),
                "factor": ("Discount factor", False, False),
                "pv": ("Present value of UFCF", True, False),
            }
            for k, (text, bold, italic) in labels.items():
                sh.label(rows[k], text, bold=bold, italic=italic, indent=italic)

            sh.put(rows["revenue"], BASE_YEAR_COL, f"={base_revenue}", st.FMT_AMOUNT)
            if base_nwc:
                sh.put(rows["nwc"], BASE_YEAR_COL, f"={base_nwc}", st.FMT_AMOUNT, italic=True)
            else:
                first_pct = ref(ASSUMPTIONS, year_col(0), arow("nwc_pct_revenue"), from_sheet=FCF)
                sh.put(
                    rows["nwc"],
                    BASE_YEAR_COL,
                    f"=C{rows['revenue']}*{first_pct}",
                    st.FMT_AMOUNT,
                    italic=True,
                )

            for i in range(self.n_years):
                col = year_col(i)
                c, p = col_letter(col), col_letter(col - 1)

                def A(key: str, col: int = col) -> str:
                    return ref(ASSUMPTIONS, col, arow(key), from_sheet=FCF, abs_col=False)

                R = rows
                formulas = {
                    "revenue": (f"={p}{R['revenue']}*(1+{A('revenue_growth')})", st.FMT_AMOUNT),
                    "growth": (f"={c}{R['revenue']}/{p}{R['revenue']}-1", st.FMT_PCT),
                    "ebitda": (f"={c}{R['revenue']}*{A('ebitda_margin')}", st.FMT_AMOUNT),
                    "margin": (f"={c}{R['ebitda']}/{c}{R['revenue']}", st.FMT_PCT),
                    "da": (f"=-{c}{R['revenue']}*{A('da_pct_revenue')}", st.FMT_AMOUNT),
                    "ebit": (f"={c}{R['ebitda']}+{c}{R['da']}", st.FMT_AMOUNT),
                    "taxes": (f"=-MAX({c}{R['ebit']},0)*{tax}", st.FMT_AMOUNT),
                    "nopat": (f"={c}{R['ebit']}+{c}{R['taxes']}", st.FMT_AMOUNT),
                    "plus_da": (f"=-{c}{R['da']}", st.FMT_AMOUNT),
                    "capex": (f"=-{c}{R['revenue']}*{A('capex_pct_revenue')}", st.FMT_AMOUNT),
                    "change_nwc": (f"=-({c}{R['nwc']}-{p}{R['nwc']})", st.FMT_AMOUNT),
                    "ufcf": (
                        f"={c}{R['nopat']}+{c}{R['plus_da']}+{c}{R['capex']}+{c}{R['change_nwc']}",
                        st.FMT_AMOUNT,
                    ),
                    "nwc": (f"={c}{R['revenue']}*{A('nwc_pct_revenue')}", st.FMT_AMOUNT),
                    "period": (f"={c}{R['header']}-{base_year}-0.5*{mid_year}", st.FMT_PERIOD),
                    "factor": (f"=1/(1+{wacc})^{c}{R['period']}", st.FMT_FACTOR),
                    "pv": (f"={c}{R['ufcf']}*{c}{R['factor']}", st.FMT_AMOUNT),
                }
                for k, (formula, fmt) in formulas.items():
                    _, bold, italic = labels[k]
                    sh.put(rows[k], col, formula, fmt, bold=bold, italic=italic)

            for k in ("ebit", "nopat", "ufcf"):
                sh.rule_above(rows[k], year_col(0), last)
            L.ranges[f"fcf/{s.name}/ufcf"] = (
                Cell(FCF, year_col(0), rows["ufcf"]),
                Cell(FCF, last, rows["ufcf"]),
            )
            L.ranges[f"fcf/{s.name}/period"] = (
                Cell(FCF, year_col(0), rows["period"]),
                Cell(FCF, last, rows["period"]),
            )
            L.ranges[f"fcf/{s.name}/pv"] = (
                Cell(FCF, year_col(0), rows["pv"]),
                Cell(FCF, last, rows["pv"]),
            )
            row = rows["pv"] + 3
        sh.ws.freeze_panes = sh.ws.cell(row=5, column=BASE_YEAR_COL)

    # ------------------------------------------------------------------ Valuation

    def _valuation(self) -> None:
        sh = self.sheets[VALUATION]
        L, m = self.layout, self.model
        row = sh.title(m, "Valuation")
        has_price = m.current_share_price is not None
        last = self.last_year_col

        def v(s: Scenario, key: str) -> str:
            return self.c(f"valuation/{s.name}/{key}").ref(VALUATION, absolute=False)

        def fcf_final(s: Scenario, key: str) -> str:
            return ref(FCF, last, self.r(f"fcf/{s.name}/{key}"), from_sheet=VALUATION)

        base_year = self.c("assumptions/base_year").ref(VALUATION)
        price_fmt = self.price_fmt

        Line = tuple[str | None, str, str, str, Any, dict[str, bool]]
        inputs: list[Line] = [
            (
                "wacc",
                "WACC",
                "%",
                st.FMT_PCT2,
                lambda s: f"={self.c(f'wacc/{s.name}/wacc').ref(VALUATION)}",
                {},
            ),
            (
                "growth",
                "Terminal growth rate",
                "%",
                st.FMT_PCT2,
                lambda s: f"={self.c(f'assumptions/{s.name}/terminal_growth').ref(VALUATION)}",
                {},
            ),
            (
                "multiple",
                "Exit multiple (EV / EBITDA)",
                "x",
                st.FMT_MULTIPLE,
                lambda s: f"={self.c(f'assumptions/{s.name}/exit_multiple').ref(VALUATION)}",
                {},
            ),
            (
                "final_ufcf",
                "Final-year unlevered FCF",
                "",
                st.FMT_AMOUNT,
                lambda s: f"={fcf_final(s, 'ufcf')}",
                {},
            ),
            (
                "final_ebitda",
                "Final-year EBITDA",
                "",
                st.FMT_AMOUNT,
                lambda s: f"={fcf_final(s, 'ebitda')}",
                {},
            ),
            (
                "sum_pv",
                "Sum of PV of unlevered FCF",
                "",
                st.FMT_AMOUNT,
                lambda s: f"=SUM({L.range_ref(f'fcf/{s.name}/pv', VALUATION)})",
                {},
            ),
            (
                "gordon_period",
                "Discount period, final cash flow",
                "yrs",
                st.FMT_PERIOD,
                lambda s: f"={fcf_final(s, 'period')}",
                {},
            ),
            (
                "exit_period",
                "Discount period, exit at end of final year",
                "yrs",
                st.FMT_PERIOD,
                lambda s: f"={fcf_final(s, 'header')}-{base_year}",
                {},
            ),
            (
                "net_debt",
                "Net debt",
                "",
                st.FMT_AMOUNT,
                lambda s: f"={self.c('assumptions/net_debt').ref(VALUATION)}",
                {},
            ),
            (
                "shares",
                "Diluted shares outstanding",
                "mm",
                st.FMT_AMOUNT,
                lambda s: f"={self.c('assumptions/shares').ref(VALUATION)}",
                {},
            ),
        ]
        if has_price:
            inputs.append(
                (
                    "current_price",
                    "Current share price",
                    "",
                    price_fmt,
                    lambda s: f"={self.c('assumptions/share_price').ref(VALUATION)}",
                    {},
                )
            )

        def method_lines(prefix: str, tv_formula, tv_period_key: str, implied) -> list[Line]:
            lines: list[Line] = [
                (f"{prefix}/terminal_value", "Terminal value", "", st.FMT_AMOUNT, tv_formula, {}),
                (
                    f"{prefix}/pv_terminal_value",
                    "PV of terminal value",
                    "",
                    st.FMT_AMOUNT,
                    lambda s: (
                        f"={v(s, f'{prefix}/terminal_value')}"
                        f"/(1+{v(s, 'wacc')})^{v(s, tv_period_key)}"
                    ),
                    {},
                ),
                (
                    f"{prefix}/sum_pv",
                    "Plus: sum of PV of unlevered FCF",
                    "",
                    st.FMT_AMOUNT,
                    lambda s: f"={v(s, 'sum_pv')}",
                    {},
                ),
                (
                    f"{prefix}/enterprise_value",
                    "Enterprise value",
                    "",
                    st.FMT_AMOUNT,
                    lambda s: f"={v(s, f'{prefix}/pv_terminal_value')}+{v(s, f'{prefix}/sum_pv')}",
                    {"bold": True, "rule": True},
                ),
                (
                    f"{prefix}/less_net_debt",
                    "Less: net debt",
                    "",
                    st.FMT_AMOUNT,
                    lambda s: f"=-{v(s, 'net_debt')}",
                    {},
                ),
                (
                    f"{prefix}/equity_value",
                    "Equity value",
                    "",
                    st.FMT_AMOUNT,
                    lambda s: (
                        f"={v(s, f'{prefix}/enterprise_value')}+{v(s, f'{prefix}/less_net_debt')}"
                    ),
                    {"bold": True, "rule": True},
                ),
                (
                    f"{prefix}/share_price",
                    "Implied share price",
                    "",
                    price_fmt,
                    lambda s: f"={v(s, f'{prefix}/equity_value')}/{v(s, 'shares')}",
                    {"bold": True, "box": True},
                ),
            ]
            if has_price:
                lines.append(
                    (
                        f"{prefix}/upside",
                        "Upside / (downside) to current price",
                        "%",
                        st.FMT_PCT,
                        lambda s: f"={v(s, f'{prefix}/share_price')}/{v(s, 'current_price')}-1",
                        {},
                    )
                )
            lines.append(
                (
                    f"{prefix}/tv_share",
                    "PV of terminal value as % of EV",
                    "%",
                    st.FMT_PCT,
                    lambda s: (
                        f"={v(s, f'{prefix}/pv_terminal_value')}"
                        f"/{v(s, f'{prefix}/enterprise_value')}"
                    ),
                    {},
                )
            )
            lines.append(implied)
            return lines

        def timing(s: Scenario) -> str:
            # Moves a value between Gordon timing and exit timing (0.5 years under mid-year).
            return f"(1+{v(s, 'wacc')})^({v(s, 'exit_period')}-{v(s, 'gordon_period')})"

        perpetuity = method_lines(
            "perpetuity",
            lambda s: (
                f"={v(s, 'final_ufcf')}*(1+{v(s, 'growth')})/({v(s, 'wacc')}-{v(s, 'growth')})"
            ),
            "gordon_period",
            (
                "perpetuity/implied",
                "Implied exit multiple (EV / EBITDA)",
                "x",
                st.FMT_MULTIPLE,
                lambda s: (
                    f"={v(s, 'perpetuity/terminal_value')}*{timing(s)}/{v(s, 'final_ebitda')}"
                ),
                {"italic": True},
            ),
        )

        def implied_growth(s: Scenario) -> str:
            x = f"{v(s, 'exit/terminal_value')}/{timing(s)}"
            fcf = v(s, "final_ufcf")
            return f"=({x}*{v(s, 'wacc')}-{fcf})/({x}+{fcf})"

        exit_lines = method_lines(
            "exit",
            lambda s: f"={v(s, 'final_ebitda')}*{v(s, 'multiple')}",
            "exit_period",
            (
                "exit/implied",
                "Implied perpetual growth rate",
                "%",
                st.FMT_PCT2,
                implied_growth,
                {"italic": True},
            ),
        )

        blocks = [
            ("Valuation inputs", inputs),
            ("Perpetuity growth method", perpetuity),
            ("Exit multiple method", exit_lines),
        ]
        # Pass 1: assign rows so any line can reference any other.
        r = row
        placed: list[tuple[int, str, list[Line]]] = []
        for title, lines in blocks:
            placed.append((r, title, lines))
            for i, (key, *_rest) in enumerate(lines):
                if key:
                    for j, s in enumerate(self.scenarios):
                        L.add_cell(
                            f"valuation/{s.name}/{key}", VALUATION, scenario_col(j), r + 1 + i
                        )
            r += len(lines) + 2
        # Pass 2: write.
        for start, title, lines in placed:
            sh.section(start, title, self.last_scen_col)
            self._scenario_header(sh, start)
            for i, (_key, text, units, fmt, build, opts) in enumerate(lines):
                rr = start + 1 + i
                sh.label(
                    rr, text, units, bold=opts.get("bold", False), italic=opts.get("italic", False)
                )
                for j, s in enumerate(self.scenarios):
                    sh.put(
                        rr,
                        scenario_col(j),
                        build(s),
                        fmt,
                        bold=opts.get("bold", False),
                        italic=opts.get("italic", False),
                    )
                    if opts.get("box"):
                        sh.box(rr, scenario_col(j))
                if opts.get("rule"):
                    sh.rule_above(rr, scenario_col(0), self.last_scen_col)

    # ------------------------------------------------------------------ Sensitivity

    def _sensitivity(self) -> None:
        sh = self.sheets[SENSITIVITY]
        L, m = self.layout, self.model
        cfg = m.sensitivity
        s = m.primary
        row = sh.title(m, f"Sensitivity analysis: {s.label}")

        sh.section(row, "Step sizes", BASE_YEAR_COL)
        row += 1
        steps = [
            ("wacc_step", "WACC step", st.FMT_PCT2, cfg.wacc_step),
            ("growth_step", "Terminal growth step", st.FMT_PCT2, cfg.growth_step),
            ("multiple_step", "Exit multiple step", st.FMT_MULTIPLE, cfg.multiple_step),
        ]
        for key, text, fmt, value in steps:
            sh.label(row, text)
            sh.put(row, BASE_YEAR_COL, value, fmt)
            L.add_cell(f"sensitivity/{key}", SENSITIVITY, BASE_YEAR_COL, row)
            row += 1
        row += 1

        def val(key: str) -> str:
            return self.c(f"valuation/{s.name}/{key}").ref(SENSITIVITY)

        ufcf = L.range_ref(f"fcf/{s.name}/ufcf", SENSITIVITY)
        periods = L.range_ref(f"fcf/{s.name}/period", SENSITIVITY)
        pv_sum_at = f"SUMPRODUCT({ufcf}/(1+{{w}})^{periods})"
        net_debt, shares = val("net_debt"), val("shares")

        def growth_cell(w: str, x: str) -> str:
            tv = f"{val('final_ufcf')}*(1+{x})/({w}-{x})/(1+{w})^{val('gordon_period')}"
            body = f"({pv_sum_at.format(w=w)}+{tv}-{net_debt})/{shares}"
            return f'=IF({w}<={x},"n/m",{body})'

        def multiple_cell(w: str, x: str) -> str:
            tv = f"{val('final_ebitda')}*{x}/(1+{w})^{val('exit_period')}"
            return f"=({pv_sum_at.format(w=w)}+{tv}-{net_debt})/{shares}"

        tables = [
            (
                "growth",
                f"Implied share price: WACC vs. terminal growth rate ({s.label})",
                "Terminal growth rate",
                val("growth"),
                "growth_step",
                st.FMT_PCT2,
                growth_cell,
            ),
            (
                "multiple",
                f"Implied share price: WACC vs. exit multiple ({s.label})",
                "Exit multiple (EV / EBITDA)",
                val("multiple"),
                "multiple_step",
                st.FMT_MULTIPLE,
                multiple_cell,
            ),
        ]
        size = cfg.size
        wacc_center = val("wacc")
        wacc_step = self.c("sensitivity/wacc_step").ref(SENSITIVITY)
        first_col = BASE_YEAR_COL + 1  # D: grid starts right of the WACC axis in C

        def offset_formula(center: str, step: str, k: int) -> str:
            if k == 0:
                return f"={center}"
            sign = "+" if k > 0 else "-"
            mult = "" if abs(k) == 1 else f"{abs(k)}*"
            return f"={center}{sign}{mult}{step}"

        for key, title, col_title, center, step_key, fmt, cell_formula in tables:
            step = self.c(f"sensitivity/{step_key}").ref(SENSITIVITY)
            sh.section(row, title, first_col + size - 1)
            row += 1
            sh.text(
                row, first_col + size // 2, col_title, italic=True, color=st.MUTED, align="center"
            )
            row += 1
            header_row = row
            sh.text(header_row, BASE_YEAR_COL, "WACC", italic=True, color=st.MUTED, align="right")
            sh.ws.cell(row=header_row, column=BASE_YEAR_COL).border = st.BORDER_BOTTOM
            for k in range(size):
                col = first_col + k
                sh.put(header_row, col, offset_formula(center, step, k - cfg.steps), fmt, bold=True)
                sh.ws.cell(row=header_row, column=col).border = st.BORDER_BOTTOM
            for i in range(size):
                rr = header_row + 1 + i
                sh.put(
                    rr,
                    BASE_YEAR_COL,
                    offset_formula(wacc_center, wacc_step, i - cfg.steps),
                    st.FMT_PCT2,
                    bold=True,
                )
                w_ref = ref(SENSITIVITY, BASE_YEAR_COL, rr, from_sheet=SENSITIVITY, abs_row=False)
                for k in range(size):
                    col = first_col + k
                    x_ref = ref(SENSITIVITY, col, header_row, from_sheet=SENSITIVITY, abs_col=False)
                    center_cell = i == cfg.steps and k == cfg.steps
                    sh.put(rr, col, cell_formula(w_ref, x_ref), self.price_fmt, bold=center_cell)
                    if center_cell:
                        sh.box(rr, col)
            L.add_row(f"sensitivity/{key}/header", SENSITIVITY, header_row)
            L.ranges[f"sensitivity/{key}"] = (
                Cell(SENSITIVITY, first_col, header_row + 1),
                Cell(SENSITIVITY, first_col + size - 1, header_row + size),
            )
            row = header_row + size + 3
        note = (
            "Each cell recomputes the DCF from the FCF Build at that WACC and terminal "
            "assumption. n/m = WACC at or below terminal growth."
        )
        sh.text(row - 1, LABEL_COL, note, italic=True, color=st.MUTED)

    # ------------------------------------------------------------------ Summary

    def _summary(self) -> None:
        sh = self.sheets[SUMMARY]
        L, m = self.layout, self.model
        row = sh.title(m, "Valuation summary")
        if m.company.description:
            sh.text(4, LABEL_COL, m.company.description, italic=True, color=st.MUTED)
            row = 6

        sh.section(row, "Discounted cash flow outputs", self.last_scen_col)
        self._scenario_header(sh, row)
        row += 1

        def link(key: str):
            return lambda s: f"={self.c(f'valuation/{s.name}/{key}').ref(SUMMARY)}"

        lines = [
            ("WACC", "%", st.FMT_PCT2, link("wacc"), False),
            ("Terminal growth rate", "%", st.FMT_PCT2, link("growth"), False),
            ("Exit multiple (EV / EBITDA)", "x", st.FMT_MULTIPLE, link("multiple"), False),
            (
                "Enterprise value: perpetuity growth",
                "",
                st.FMT_AMOUNT,
                link("perpetuity/enterprise_value"),
                False,
            ),
            (
                "Enterprise value: exit multiple",
                "",
                st.FMT_AMOUNT,
                link("exit/enterprise_value"),
                False,
            ),
            (
                "Implied share price: perpetuity growth",
                "",
                self.price_fmt,
                link("perpetuity/share_price"),
                True,
            ),
            (
                "Implied share price: exit multiple",
                "",
                self.price_fmt,
                link("exit/share_price"),
                True,
            ),
        ]
        if m.current_share_price is not None:
            lines += [
                (
                    "Upside / (downside): perpetuity growth",
                    "%",
                    st.FMT_PCT,
                    link("perpetuity/upside"),
                    False,
                ),
                ("Upside / (downside): exit multiple", "%", st.FMT_PCT, link("exit/upside"), False),
            ]
        for text, units, fmt, build, bold in lines:
            sh.label(row, text, units, bold=bold)
            for j, s in enumerate(self.scenarios):
                sh.put(row, scenario_col(j), build(s), fmt, bold=bold)
            row += 1
        if m.current_share_price is not None:
            sh.label(row, "Current share price")
            for j in range(len(self.scenarios)):
                sh.put(
                    row,
                    scenario_col(j),
                    f"={self.c('assumptions/share_price').ref(SUMMARY)}",
                    self.price_fmt,
                )
            row += 1
        row += 1

        # Football field: low / high per methodology, plotted as a floating bar.
        low_col, high_col, spread_col = scenario_col(0), scenario_col(1), scenario_col(2)
        sh.section(row, "Football field: implied share price", spread_col)
        sh.header_cells(row, low_col, ["Low", "High", "Range"])
        row += 1
        first_scen = scenario_col(0)

        def scen_range(key: str) -> str:
            first = Cell(
                VALUATION, first_scen, self.c(f"valuation/{m.scenarios[0].name}/{key}").row
            )
            end = ref(VALUATION, self.last_scen_col, first.row, from_sheet=VALUATION)
            return f"{first.ref(SUMMARY)}:{end}"

        # Scenario bars only make sense with a spread of cases; a single case would plot
        # as a zero-width bar, so it is represented by the sensitivity grids alone.
        bars: list[tuple[str, str, str]] = []
        if len(m.scenarios) > 1:
            span = f"{m.scenarios[0].label.lower()} to {m.scenarios[-1].label.lower()}"
            bars += [
                (
                    "ff/perpetuity",
                    f"DCF perpetuity growth, {span}",
                    scen_range("perpetuity/share_price"),
                ),
                ("ff/exit", f"DCF exit multiple, {span}", scen_range("exit/share_price")),
            ]
        bars += [
            (
                "ff/growth_sensitivity",
                "Sensitivity: WACC vs. terminal growth",
                L.range_ref("sensitivity/growth", SUMMARY),
            ),
            (
                "ff/multiple_sensitivity",
                "Sensitivity: WACC vs. exit multiple",
                L.range_ref("sensitivity/multiple", SUMMARY),
            ),
        ]
        first_bar_row = row
        for key, text, rng in bars:
            sh.label(row, text)
            sh.put(row, low_col, f"=MIN({rng})", self.price_fmt)
            sh.put(row, high_col, f"=MAX({rng})", self.price_fmt)
            lo = ref(SUMMARY, low_col, row, from_sheet=SUMMARY, abs_col=False, abs_row=False)
            hi = ref(SUMMARY, high_col, row, from_sheet=SUMMARY, abs_col=False, abs_row=False)
            sh.put(row, spread_col, f"={hi}-{lo}", self.price_fmt)
            L.add_cell(f"summary/{key}/low", SUMMARY, low_col, row)
            L.add_cell(f"summary/{key}/high", SUMMARY, high_col, row)
            row += 1
        last_bar_row = row - 1

        chart = BarChart()
        chart.type = "bar"
        chart.grouping = "stacked"
        chart.overlap = 100
        chart.gapWidth = 60
        chart.title = None
        chart.legend = None
        chart.height = 7.5
        chart.width = 17
        cats = Reference(sh.ws, min_col=LABEL_COL, min_row=first_bar_row, max_row=last_bar_row)
        for col in (low_col, spread_col):
            chart.add_data(
                Reference(sh.ws, min_col=col, min_row=first_bar_row, max_row=last_bar_row),
                titles_from_data=False,
            )
        chart.set_categories(cats)
        invisible, visible = chart.series
        invisible.graphicalProperties.noFill = True
        invisible.graphicalProperties.line.noFill = True
        visible.graphicalProperties.solidFill = "1F3A5F"
        visible.graphicalProperties.line.solidFill = "1F3A5F"
        chart.x_axis.scaling.orientation = "maxMin"  # first row at the top
        chart.y_axis.crosses = "max"  # keep the price axis at the bottom after flipping
        chart.x_axis.delete = False
        chart.y_axis.delete = False
        chart.y_axis.numFmt = st.axis_price_format(m.company.currency)
        chart.y_axis.majorGridlines = None
        chart.y_axis.title = f"Implied share price ({m.company.currency})"
        sh.ws.add_chart(chart, f"A{last_bar_row + 2}")


def build_workbook(result: ValuationResult) -> tuple[Workbook, Layout]:
    return WorkbookBuilder(result).build()


def write_workbook(result: ValuationResult, path: str | Path) -> Layout:
    wb, layout = build_workbook(result)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return layout

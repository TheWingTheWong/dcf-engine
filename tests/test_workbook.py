"""The workbook must be a faithful, live re-implementation of the engine.

Three layers of checks:
1. Structure: specific formulas reference exactly the cells they should.
2. Conventions: hard-coded numbers only on the Assumptions sheet (plus the three
   sensitivity step sizes), coloured blue; formulas black or green.
3. Evaluation: every formula is computed with pycel and compared to the Python engine,
   including after editing inputs in the workbook, which proves nothing is pasted.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import formulas
import pytest
from openpyxl import load_workbook

from dcf_engine.excel import Layout, build_workbook, write_workbook
from dcf_engine.excel.layout import year_col
from dcf_engine.excel.styles import INPUT_BLUE, LINK_GREEN
from dcf_engine.loader import load_model, parse_model
from dcf_engine.model import CompanyModel
from dcf_engine.valuation import ValuationResult, value_model

SHEETS = ["Summary", "Assumptions", "WACC", "FCF Build", "Valuation", "Sensitivity"]


class Evaluator:
    """Recalculates every formula in a saved workbook with the ``formulas`` package."""

    def __init__(self, path: Path, layout: Layout):
        model = formulas.ExcelModel().loads(str(path)).finish()
        solution = model.calculate()
        self.values: dict[str, object] = {}
        for key, ranges in solution.items():
            # Keys look like "'[model.xlsx]FCF BUILD'!D12"; keep single cells only.
            sheet_part, _, coordinate = key.rpartition("!")
            if ":" in coordinate:
                continue
            sheet = sheet_part.strip("'").split("]", 1)[1]
            value = ranges.value[0, 0]
            self.values[f"{sheet.upper()}!{coordinate}"] = (
                value if isinstance(value, str) else float(value)
            )
        self.layout = layout

    def at(self, sheet: str, coordinate: str):
        return self.values[f"{sheet.upper()}!{coordinate}"]

    def __call__(self, key: str):
        c = self.layout.cell(key)
        return self.at(c.sheet, c.coordinate)

    def row(self, key: str, col: int):
        sheet, row = self.layout.rows[key]
        return self.at(sheet, _a1(col, row))


def _a1(col: int, row: int) -> str:
    from openpyxl.utils import get_column_letter

    return f"{get_column_letter(col)}{row}"


def _write(model: CompanyModel, tmp_path: Path, name: str = "model.xlsx"):
    result = value_model(model)
    path = tmp_path / name
    layout = write_workbook(result, path)
    return result, path, layout


@pytest.fixture
def acme(examples_dir, tmp_path):
    model = load_model(examples_dir / "acme.yaml")
    result, path, layout = _write(model, tmp_path)
    return result, path, layout


# --------------------------------------------------------------------------- structure


def test_sheet_order(acme):
    _, path, _ = acme
    assert load_workbook(path).sheetnames == SHEETS


def test_fcf_formulas_reference_assumptions(acme):
    _, path, layout = acme
    ws = load_workbook(path)["FCF Build"]
    r = {k: layout.row(f"fcf/base/{k}") for k in ("revenue", "ebit", "taxes", "nwc", "ufcf")}
    growth_row = layout.row("assumptions/base/revenue_growth")

    # First projected year grows last actual revenue by the year-1 growth input.
    assert ws[f"D{r['revenue']}"].value == f"=C{r['revenue']}*(1+Assumptions!D${growth_row})"
    # Year 3 points at year 3's growth input (same column on both sheets).
    assert ws[f"F{r['revenue']}"].value == f"=E{r['revenue']}*(1+Assumptions!F${growth_row})"
    # Last actual revenue is a link to the input.
    base_rev = layout.cell("assumptions/base_revenue")
    assert ws[f"C{r['revenue']}"].value == f"=Assumptions!$C${base_rev.row}"
    # Taxes use the scenario's tax rate as an absolute reference.
    tax_cell = layout.cell("assumptions/base/tax_rate")
    assert tax_cell.coordinate == f"D{tax_cell.row}"  # base is the second scenario column
    assert ws[f"E{r['taxes']}"].value == f"=-MAX(E{r['ebit']},0)*Assumptions!$D${tax_cell.row}"
    # Change in NWC is the difference of adjacent balances.
    change = layout.row("fcf/base/change_nwc")
    assert ws[f"D{change}"].value == f"=-(D{r['nwc']}-C{r['nwc']})"


def test_discounting_formulas(acme):
    _, path, layout = acme
    ws = load_workbook(path)["FCF Build"]
    period = layout.row("fcf/bull/period")
    factor = layout.row("fcf/bull/factor")
    header = layout.row("fcf/bull/header")
    wacc = layout.cell("wacc/bull/wacc")
    mid = layout.cell("assumptions/mid_year")
    base_year = layout.cell("assumptions/base_year")
    assert wacc.coordinate == "E" + str(wacc.row)  # bull is the third scenario column
    assert ws[f"H{period}"].value == (
        f"=H{header}-Assumptions!$C${base_year.row}-0.5*Assumptions!$C${mid.row}"
    )
    assert ws[f"H{factor}"].value == f"=1/(1+WACC!$E${wacc.row})^H{period}"


def test_wacc_formula(acme):
    _, path, layout = acme
    ws = load_workbook(path)["WACC"]
    c = {
        k: layout.cell(f"wacc/base/{k}").coordinate
        for k in (
            "wacc",
            "equity_weight",
            "cost_of_equity",
            "debt_weight",
            "after_tax_cost_of_debt",
            "risk_free_rate",
            "levered_beta",
            "equity_risk_premium",
            "size_premium",
        )
    }
    assert ws[c["wacc"]].value == (
        f"={c['equity_weight']}*{c['cost_of_equity']}"
        f"+{c['debt_weight']}*{c['after_tax_cost_of_debt']}"
    )
    assert ws[c["cost_of_equity"]].value == (
        f"={c['risk_free_rate']}+{c['levered_beta']}*{c['equity_risk_premium']}+{c['size_premium']}"
    )


def test_valuation_formulas(acme):
    _, path, layout = acme
    ws = load_workbook(path)["Valuation"]

    def c(key):
        return layout.cell(f"valuation/base/{key}").coordinate

    assert ws[c("perpetuity/terminal_value")].value == (
        f"={c('final_ufcf')}*(1+{c('growth')})/({c('wacc')}-{c('growth')})"
    )
    assert ws[c("perpetuity/pv_terminal_value")].value == (
        f"={c('perpetuity/terminal_value')}/(1+{c('wacc')})^{c('gordon_period')}"
    )
    assert ws[c("exit/pv_terminal_value")].value == (
        f"={c('exit/terminal_value')}/(1+{c('wacc')})^{c('exit_period')}"
    )
    assert ws[c("exit/terminal_value")].value == f"={c('final_ebitda')}*{c('multiple')}"
    pv_row = layout.row("fcf/base/pv")
    assert ws[c("sum_pv")].value == f"=SUM('FCF Build'!$D${pv_row}:$H${pv_row})"
    ufcf_row = layout.row("fcf/base/ufcf")
    assert ws[c("final_ufcf")].value == f"='FCF Build'!$H${ufcf_row}"


def test_sensitivity_cells_recompute_from_fcf_build(acme):
    _, path, layout = acme
    ws = load_workbook(path)["Sensitivity"]
    first, _ = layout.ranges["sensitivity/growth"]
    formula = ws.cell(row=first.row, column=first.col).value
    ufcf_row, period_row = layout.row("fcf/base/ufcf"), layout.row("fcf/base/period")
    assert formula.startswith(f'=IF($C{first.row}<=D${first.row - 1},"n/m",')
    assert (
        f"SUMPRODUCT('FCF Build'!$D${ufcf_row}:$H${ufcf_row}/(1+$C{first.row})"
        f"^'FCF Build'!$D${period_row}:$H${period_row})"
    ) in formula


def test_football_field_spans_sensitivity_grids(acme):
    _, path, layout = acme
    ws = load_workbook(path)["Summary"]
    low = layout.cell("summary/ff/growth_sensitivity/low")
    assert ws[low.coordinate].value == f"=MIN({layout.range_ref('sensitivity/growth', 'Summary')})"
    assert ws._charts, "football field chart missing"


# --------------------------------------------------------------------------- conventions


def test_hard_codes_only_on_assumptions_and_are_blue(acme):
    _, path, layout = acme
    wb = load_workbook(path)
    step_cells = {
        layout.cell(f"sensitivity/{k}").coordinate
        for k in ("wacc_step", "growth_step", "multiple_step")
    }
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                v = cell.value
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    allowed = ws.title == "Assumptions" or (
                        ws.title == "Sensitivity" and cell.coordinate in step_cells
                    )
                    assert allowed, f"hard-coded {v!r} at {ws.title}!{cell.coordinate}"
                    assert cell.font.color.rgb.endswith(INPUT_BLUE)
                elif isinstance(v, str) and v.startswith("="):
                    assert not cell.font.color.rgb.endswith(INPUT_BLUE), (
                        f"formula styled as input at {ws.title}!{cell.coordinate}"
                    )


def test_cross_sheet_links_are_green(acme):
    _, path, layout = acme
    ws = load_workbook(path)["Valuation"]
    wacc_link = ws[layout.cell("valuation/base/wacc").coordinate]
    assert wacc_link.value.startswith("=WACC!")
    assert wacc_link.font.color.rgb.endswith(LINK_GREEN)
    price = ws[layout.cell("valuation/base/perpetuity/share_price").coordinate]
    assert price.font.color.rgb.endswith("000000")


# --------------------------------------------------------------------------- evaluation


def _assert_matches_engine(ev: Evaluator, result: ValuationResult) -> None:
    approx = lambda x: pytest.approx(x, rel=1e-9, abs=1e-9)  # noqa: E731
    for sv in result.scenarios:
        n = sv.name
        w = sv.wacc
        assert ev(f"wacc/{n}/levered_beta") == approx(w.levered_beta)
        assert ev(f"wacc/{n}/cost_of_equity") == approx(w.cost_of_equity)
        assert ev(f"wacc/{n}/wacc") == approx(w.wacc)

        for i, y in enumerate(sv.projection.years):
            col = year_col(i)
            expected = {
                "revenue": y.revenue,
                "ebitda": y.ebitda,
                "da": -y.da,
                "ebit": y.ebit,
                "taxes": -y.taxes,
                "nopat": y.nopat,
                "capex": -y.capex,
                "nwc": y.nwc,
                "change_nwc": -y.change_in_nwc,
                "ufcf": y.ufcf,
                "period": y.discount_period,
                "factor": sv.discount_factors[i],
                "pv": sv.pv_of_fcf_by_year[i],
            }
            for key, value in expected.items():
                assert ev.row(f"fcf/{n}/{key}", col) == approx(value), (n, key, y.year)

        for prefix, mv in (("perpetuity", sv.perpetuity), ("exit", sv.exit_multiple)):
            assert ev(f"valuation/{n}/{prefix}/terminal_value") == approx(mv.terminal_value)
            assert ev(f"valuation/{n}/{prefix}/pv_terminal_value") == approx(
                mv.pv_of_terminal_value
            )
            assert ev(f"valuation/{n}/{prefix}/enterprise_value") == approx(mv.enterprise_value)
            assert ev(f"valuation/{n}/{prefix}/equity_value") == approx(mv.equity_value)
            assert ev(f"valuation/{n}/{prefix}/share_price") == approx(mv.share_price)
            assert ev(f"valuation/{n}/{prefix}/implied") == approx(mv.implied_metric)
            if mv.upside is not None:
                assert ev(f"valuation/{n}/{prefix}/upside") == approx(mv.upside)

    for key, table in (
        ("growth", result.growth_sensitivity),
        ("multiple", result.multiple_sensitivity),
    ):
        first, _ = ev.layout.ranges[f"sensitivity/{key}"]
        for i, row in enumerate(table.values):
            for j, expected in enumerate(row):
                got = ev.at("Sensitivity", _a1(first.col + j, first.row + i))
                assert got == ("n/m" if expected is None else approx(expected)), (key, i, j)
        assert ev(f"summary/ff/{key}_sensitivity/low") == approx(table.low)
        assert ev(f"summary/ff/{key}_sensitivity/high") == approx(table.high)

    if len(result.scenarios) > 1:
        prices = [s.perpetuity.share_price for s in result.scenarios]
        assert ev("summary/ff/perpetuity/low") == approx(min(prices))
        assert ev("summary/ff/perpetuity/high") == approx(max(prices))
    else:
        assert "summary/ff/perpetuity/low" not in ev.layout.cells


def test_workbook_evaluates_to_engine_values(acme):
    result, path, layout = acme
    _assert_matches_engine(Evaluator(path, layout), result)


@pytest.mark.parametrize("example", ["acme.yaml", "cobalt_cloud.yaml", "harborview_foods.yaml"])
def test_every_example_workbook_matches_engine(examples_dir, tmp_path, example):
    model = load_model(examples_dir / example)
    result, path, layout = _write(model, tmp_path)
    _assert_matches_engine(Evaluator(path, layout), result)


def test_formulas_are_live_after_editing_inputs(examples_dir, tmp_path):
    """Edit inputs in the saved workbook; the formulas must reproduce a re-run engine."""
    model = load_model(examples_dir / "acme.yaml")
    _, path, layout = _write(model, tmp_path)

    wb = load_workbook(path)
    ws = wb["Assumptions"]
    ws[layout.cell("assumptions/base_revenue").coordinate] = 1400.0
    ws[layout.cell("assumptions/mid_year").coordinate] = 0
    ws[layout.cell("assumptions/bear/beta").coordinate] = 1.5
    growth_row = layout.row("assumptions/base/revenue_growth")
    ws.cell(row=growth_row, column=year_col(2), value=0.20)
    edited = tmp_path / "edited.xlsx"
    wb.save(edited)

    raw_model = dataclasses.replace(model, base_revenue=1400.0, mid_year_convention=False)
    bear = raw_model.scenario("bear")
    base = raw_model.scenario("base")
    growth = list(base.operating.revenue_growth)
    growth[2] = 0.20
    new_bear = dataclasses.replace(bear, capital=dataclasses.replace(bear.capital, beta=1.5))
    new_base = dataclasses.replace(
        base,
        operating=dataclasses.replace(base.operating, revenue_growth=tuple(growth)),
    )
    expected_model = dataclasses.replace(
        raw_model,
        scenarios=tuple(
            {"bear": new_bear, "base": new_base}.get(s.name, s) for s in raw_model.scenarios
        ),
    )
    expected = value_model(expected_model)
    assert expected.primary.perpetuity.share_price != pytest.approx(
        value_model(model).primary.perpetuity.share_price
    )
    _assert_matches_engine(Evaluator(edited, layout), expected)


def test_unlevered_beta_relevers_in_excel(simple_raw, tmp_path):
    simple_raw["assumptions"]["wacc"].pop("beta")
    simple_raw["assumptions"]["wacc"]["unlevered_beta"] = 0.9
    simple_raw["assumptions"]["wacc"]["target_debt_to_equity"] = 0.5
    model = parse_model(simple_raw)
    result, path, layout = _write(model, tmp_path)
    ev = Evaluator(path, layout)
    assert ev("wacc/base/levered_beta") == pytest.approx(0.9 * (1 + 0.75 * 0.5))
    _assert_matches_engine(ev, result)


def test_optional_rows_absent_without_inputs(simple_model):
    _, layout = build_workbook(value_model(simple_model))
    assert "assumptions/share_price" not in layout.cells
    assert "assumptions/base_nwc" not in layout.cells
    assert "valuation/base/perpetuity/upside" not in layout.cells


def test_hand_computed_model_in_excel(simple_model, tmp_path):
    _, path, layout = _write(simple_model, tmp_path)
    ev = Evaluator(path, layout)
    # Same hand-computed figures as tests/test_valuation.py, now from Excel formulas.
    pv_sum = 3 * 10.275 / 1.1
    assert ev("valuation/base/exit/pv_terminal_value") == pytest.approx(160.0)
    assert ev("valuation/base/exit/share_price") == pytest.approx((pv_sum + 160 - 50) / 10)
    assert ev("valuation/base/perpetuity/terminal_value") == pytest.approx(158.5175625)

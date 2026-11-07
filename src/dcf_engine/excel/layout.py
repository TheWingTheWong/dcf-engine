"""Registry of where every named quantity lives in the workbook.

The writer records each cell or row it creates under a stable key, and formulas are built
from those keys rather than from hard-coded coordinates. Tests use the same registry to
check that formulas point at the right cells.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from openpyxl.utils import get_column_letter

# Column layout shared by Assumptions (operating block) and FCF Build so that year t sits
# in the same column letter on both sheets.
LABEL_COL = 1  # A
UNITS_COL = 2  # B
BASE_YEAR_COL = 3  # C: last actual year
FIRST_YEAR_COL = 4  # D: first projected year
FIRST_SCENARIO_COL = 3  # C: scenario-by-column tables


def year_col(index: int) -> int:
    """Column of projected year ``index`` (0-based)."""
    return FIRST_YEAR_COL + index


def scenario_col(index: int) -> int:
    return FIRST_SCENARIO_COL + index


def quote_sheet(sheet: str) -> str:
    if sheet.replace("_", "").isalnum():
        return sheet
    return "'" + sheet.replace("'", "''") + "'"


def ref(
    sheet: str,
    col: int,
    row: int,
    *,
    from_sheet: str | None = None,
    abs_col: bool = True,
    abs_row: bool = True,
) -> str:
    """A1 reference, sheet-qualified unless it lives on ``from_sheet``."""
    a1 = f"{'$' if abs_col else ''}{get_column_letter(col)}{'$' if abs_row else ''}{row}"
    if sheet == from_sheet:
        return a1
    return f"{quote_sheet(sheet)}!{a1}"


@dataclass(frozen=True)
class Cell:
    sheet: str
    col: int
    row: int

    @property
    def coordinate(self) -> str:
        return f"{get_column_letter(self.col)}{self.row}"

    def ref(self, from_sheet: str | None = None, *, absolute: bool = True) -> str:
        return ref(
            self.sheet,
            self.col,
            self.row,
            from_sheet=from_sheet,
            abs_col=absolute,
            abs_row=absolute,
        )


@dataclass
class Layout:
    cells: dict[str, Cell] = field(default_factory=dict)
    rows: dict[str, tuple[str, int]] = field(default_factory=dict)
    ranges: dict[str, tuple[Cell, Cell]] = field(default_factory=dict)

    def add_cell(self, key: str, sheet: str, col: int, row: int) -> Cell:
        if key in self.cells:
            raise KeyError(f"duplicate layout key {key!r}")
        cell = Cell(sheet, col, row)
        self.cells[key] = cell
        return cell

    def add_row(self, key: str, sheet: str, row: int) -> int:
        if key in self.rows:
            raise KeyError(f"duplicate layout key {key!r}")
        self.rows[key] = (sheet, row)
        return row

    def cell(self, key: str) -> Cell:
        return self.cells[key]

    def row(self, key: str) -> int:
        return self.rows[key][1]

    def range_ref(self, key: str, from_sheet: str | None = None) -> str:
        first, last = self.ranges[key]
        end = ref(last.sheet, last.col, last.row, from_sheet=last.sheet)
        return f"{first.ref(from_sheet)}:{end}"

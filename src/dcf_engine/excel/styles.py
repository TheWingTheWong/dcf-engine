"""Cell styles following sell-side modelling conventions.

Colour carries meaning and nothing else: blue font for hard-coded inputs, black for
formulas, green for formulas that only pull a value from another sheet. No fills on
data cells, gridlines off, thin rules under headers and above totals.
"""

from __future__ import annotations

import re

from openpyxl.styles import Alignment, Border, Font, Side

FONT_NAME = "Arial"
FONT_SIZE = 10

INPUT_BLUE = "0000FF"
LINK_GREEN = "008000"
BLACK = "000000"
MUTED = "595959"

THIN = Side(style="thin", color=BLACK)
HAIR = Side(style="hair", color="808080")

BORDER_BOTTOM = Border(bottom=THIN)
BORDER_TOP = Border(top=THIN)
BORDER_BOX = Border(top=THIN, bottom=THIN, left=THIN, right=THIN)

RIGHT = Alignment(horizontal="right")
CENTER = Alignment(horizontal="center")
LEFT_INDENT = Alignment(horizontal="left", indent=1)

# Number formats. Negative numbers in parentheses, zero as an en dash, and a trailing
# space so positives line up with parenthesised negatives.
_ZERO = '"\u2013"_)'  # en dash
FMT_AMOUNT = f"#,##0.0_);(#,##0.0);{_ZERO}"
FMT_PCT = f"0.0%_);(0.0%);{_ZERO}"
FMT_PCT2 = f"0.00%_);(0.00%);{_ZERO}"
FMT_MULTIPLE = '0.0"x"_)'
FMT_BETA = "0.00_)"
FMT_FACTOR = "0.0000_)"
FMT_PERIOD = "0.0_)"
FMT_FLAG = "0_)"
FMT_YEAR = "0"
FMT_YEAR_ACTUAL = '0"A"'
FMT_YEAR_ESTIMATE = '0"E"'

_CURRENCY_SYMBOLS = {"USD": "$", "EUR": "€", "GBP": "£", "JPY": "¥", "CAD": "$", "AUD": "$"}


def price_format(currency: str) -> str:
    symbol = _CURRENCY_SYMBOLS.get(currency.upper())
    if symbol is None:
        return "#,##0.00_);(#,##0.00)"
    return f'"{symbol}"#,##0.00_);("{symbol}"#,##0.00)'


def font(color: str = BLACK, *, bold: bool = False, italic: bool = False, size: int = FONT_SIZE):
    return Font(name=FONT_NAME, size=size, bold=bold, italic=italic, color=color)


# A formula that is nothing but a reference to a single cell on another sheet,
# e.g. =Assumptions!$C$8 or ='FCF Build'!H20.
_PURE_LINK = re.compile(r"^=(?:'[^']+'|[A-Za-z0-9_]+)!\$?[A-Z]{1,3}\$?\d+$")


def is_cross_sheet_link(formula: str) -> bool:
    return bool(_PURE_LINK.match(formula))

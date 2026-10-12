"""
Run this script locally to create user 2's estimated expenses for next month.

    python create_estimate_user2.py

Reads .env for credentials. Creates the 'Estimado_2' tab: the estimate is the average of
the last 3 complete months found in the user 2 summary tab, in total and per category.
It does not depend on the month selected in 'Charts_2', and it moves forward by itself
each month. Safe to run again: it rewrites the same cells.
"""

import logging

import gspread

from config import USER2_SUMMARY_SHEET
from create_charts_user2 import formula_request, localize_formula
from services.sheets_service import MONTHS_ES, _get_spreadsheet

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

ESTIMATE_TAB = "Estimado_2"
MONTHS_BACK = 3
MONTH_ROWS = (5, 6, 7)       # 1-indexed rows with the 3 months of the window
ESTIMATE_ROW = 9
CATEGORY_HEADER_ROW = 11
CATEGORY_FIRST_ROW = 12
MAX_CATEGORIES = 15
TOTAL_COL_CELL = "$H$2"      # column number of "Total ($)" in the summary tab
FIRST_CATEGORY_COLUMN = 4    # column D in the summary tab: Año, Mes, Nro. Tickets, then categories
TOTAL_HEADER = "Total ($)"
GRID = "$A$1:$Z$1000"


def _summary(summary_tab: str) -> str:
    return f"'{summary_tab}'"


def month_name_formula(back: int) -> str:
    """Spanish name of the month `back` months ago (negative: months ahead)."""
    names = ",".join(f'"{MONTHS_ES[m]}"' for m in range(1, 13))
    return f"=CHOOSE(MONTH(EDATE(TODAY(),{-back})),{names})"


def next_month_label_formula(prefix: str) -> str:
    """Text such as 'Gasto estimado Noviembre', following today's date."""
    return f'="{prefix} "&{month_name_formula(-1)[1:]}'


def year_formula(back: int) -> str:
    return f"=YEAR(EDATE(TODAY(),-{back}))"


def has_data_formula(row: int, summary_tab: str) -> str:
    s = _summary(summary_tab)
    return f"=IF(COUNTIFS({s}!$A$1:$A$1000,B{row},{s}!$B$1:$B$1000,A{row})>0,1,0)"


def month_total_formula(row: int, summary_tab: str) -> str:
    s = _summary(summary_tab)
    return (
        f"=SUMIFS(INDEX({s}!{GRID},0,{TOTAL_COL_CELL}),"
        f"{s}!$A$1:$A$1000,B{row},{s}!$B$1:$B$1000,A{row})"
    )


def total_column_formula(summary_tab: str) -> str:
    return f'=MATCH("{TOTAL_HEADER}",{_summary(summary_tab)}!$1:$1,0)'


def estimate_formula() -> str:
    first, last = MONTH_ROWS[0], MONTH_ROWS[-1]
    return (
        f'=IF(SUM(D{first}:D{last})=0,"Sin datos",'
        f"ROUND(SUMPRODUCT(C{first}:C{last},D{first}:D{last})/SUM(D{first}:D{last}),2))"
    )


def _category_index(row: int) -> str:
    return f"(ROW()-ROW($A${CATEGORY_HEADER_ROW})+{FIRST_CATEGORY_COLUMN - 1})"


def category_name_formula(row: int, summary_tab: str) -> str:
    s = _summary(summary_tab)
    idx = _category_index(row)
    return f'=IF({idx}<{TOTAL_COL_CELL},INDEX({s}!$A$1:$Z$1,1,{idx}),"")'


def category_estimate_formula(row: int, summary_tab: str) -> str:
    s = _summary(summary_tab)
    idx = _category_index(row)
    first, last = MONTH_ROWS[0], MONTH_ROWS[-1]
    terms = "+".join(
        f"SUMIFS(INDEX({s}!{GRID},0,{idx}),{s}!$A$1:$A$1000,$B${r},{s}!$B$1:$B$1000,$A${r})*$D${r}"
        for r in MONTH_ROWS
    )
    return (
        f'=IF(A{row}="","",IF(SUM($D${first}:$D${last})=0,"Sin datos",'
        f"ROUND(({terms})/SUM($D${first}:$D${last}),2)))"
    )


def _format_requests(sheet_id: int) -> list[dict]:
    bold = {"userEnteredFormat": {"textFormat": {"bold": True}}}
    money = {"userEnteredFormat": {"numberFormat": {"type": "NUMBER", "pattern": "#,##0.00"}}}

    def cells(row_start, row_end, col_start, col_end, cell, fields):
        return {
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": row_start,
                    "endRowIndex": row_end,
                    "startColumnIndex": col_start,
                    "endColumnIndex": col_end,
                },
                "cell": cell,
                "fields": fields,
            }
        }

    return [
        cells(0, 1, 0, 1, bold, "userEnteredFormat.textFormat"),                  # title
        cells(3, 4, 0, 4, bold, "userEnteredFormat.textFormat"),                  # month headers
        cells(ESTIMATE_ROW - 1, ESTIMATE_ROW, 0, 3, bold, "userEnteredFormat.textFormat"),
        cells(CATEGORY_HEADER_ROW - 1, CATEGORY_HEADER_ROW, 0, 3, bold, "userEnteredFormat.textFormat"),
        cells(4, ESTIMATE_ROW, 2, 3, money, "userEnteredFormat.numberFormat"),
        cells(CATEGORY_FIRST_ROW - 1, CATEGORY_FIRST_ROW - 1 + MAX_CATEGORIES, 2, 3, money,
              "userEnteredFormat.numberFormat"),
        {
            "updateDimensionProperties": {
                "range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": 0, "endIndex": 1},
                "properties": {"pixelSize": 260},
                "fields": "pixelSize",
            }
        },
    ]


def create_estimate(spreadsheet, summary_tab: str = USER2_SUMMARY_SHEET) -> None:
    try:
        spreadsheet.worksheet(summary_tab)
    except gspread.exceptions.WorksheetNotFound:
        raise SystemExit(
            f"Tab '{summary_tab}' not found. Save a receipt from user 2 first so the bot creates it."
        )

    try:
        sheet = spreadsheet.worksheet(ESTIMATE_TAB)
    except gspread.exceptions.WorksheetNotFound:
        sheet = spreadsheet.add_worksheet(title=ESTIMATE_TAB, rows=40, cols=10)
        logger.info(f"Created '{ESTIMATE_TAB}' sheet")

    sheet.update(
        [[f"Promedio de los últimos {MONTHS_BACK} meses completos de '{summary_tab}'"]], "A2"
    )
    sheet.update([["Mes", "Año", "Total ($)", "Con datos"]], "A4")
    sheet.update([["Categoría", "", "Estimado ($)"]], f"A{CATEGORY_HEADER_ROW}")
    sheet.update([["Col. Total"]], "H1")

    # The API parses formulas with the Sheet's locale, so adapt the separators to it
    locale = spreadsheet.locale
    cells = {
        (1, 7): total_column_formula(summary_tab),  # H2
        (0, 0): next_month_label_formula("Estimado de gastos de"),
        (ESTIMATE_ROW - 1, 0): next_month_label_formula("Gasto estimado"),
    }
    for back, row in enumerate(MONTH_ROWS, start=1):
        r = row - 1
        cells[(r, 0)] = month_name_formula(back)
        cells[(r, 1)] = year_formula(back)
        cells[(r, 2)] = month_total_formula(row, summary_tab)
        cells[(r, 3)] = has_data_formula(row, summary_tab)
    cells[(ESTIMATE_ROW - 1, 2)] = estimate_formula()
    for i in range(MAX_CATEGORIES):
        row = CATEGORY_FIRST_ROW + i
        cells[(row - 1, 0)] = category_name_formula(row, summary_tab)
        cells[(row - 1, 2)] = category_estimate_formula(row, summary_tab)

    requests = [
        formula_request(sheet.id, r, c, localize_formula(f, locale))
        for (r, c), f in cells.items()
    ]
    requests.extend(_format_requests(sheet.id))
    spreadsheet.batch_update({"requests": requests})
    logger.info(f"'{ESTIMATE_TAB}' ready")


if __name__ == "__main__":
    create_estimate(_get_spreadsheet())

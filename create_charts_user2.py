"""
Run this script locally once to create the monthly products chart for user 2.

    python create_charts_user2.py

Reads .env for credentials. Creates the 'Charts_2' tab with a month dropdown (B1),
a table of total price and quantity per product for that month (A3), a bar chart and the
total of the current calendar month (G1:H1, from the summary tab, ignoring the dropdown).
Safe to run again: it never creates a second chart or resets the selected month.
"""

import logging
from datetime import datetime

import gspread

from config import USER2_PRODUCTOS_SHEET, USER2_SUMMARY_SHEET
from services.sheets_service import MONTHS_ES, _get_spreadsheet

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

CHARTS_TAB = "Charts_2"
MONTH_CELL = "B1"
MONTHS_LIST_CELL = "E2"      # helper list of months found in the products tab
MONTHS_LIST_LAST_ROW = 100
TABLE_FIRST_ROW = 3          # header row of the table (1-indexed)
MAX_PRODUCTS = 40
CHART_ANCHOR_COLUMN = 6      # column G (0-indexed)
CURRENT_TOTAL_LABEL_CELL = (0, 6)   # G1: "Total Octubre"
CURRENT_TOTAL_VALUE_CELL = (0, 7)   # H1: total of the current calendar month
TOTAL_HEADER = "Total ($)"


def _current_month_name() -> str:
    names = ",".join(f'"{MONTHS_ES[m]}"' for m in range(1, 13))
    return f"CHOOSE(MONTH(TODAY()),{names})"


def current_total_label_formula() -> str:
    return f'="Total "&{_current_month_name()}'


def current_total_formula(summary_tab: str) -> str:
    """Total of the current calendar month from the summary tab, ignoring the dropdown."""
    s = f"'{summary_tab}'"
    return (
        f'=IFERROR(SUMIFS(INDEX({s}!$A$1:$Z$1000,0,MATCH("{TOTAL_HEADER}",{s}!$1:$1,0)),'
        f"{s}!$A$1:$A$1000,YEAR(TODAY()),{s}!$B$1:$B$1000,{_current_month_name()}),0)"
    )


def months_formula(productos_tab: str) -> str:
    """Distinct 'yyyy-mm' months present in column B (Fecha), newest first."""
    p = f"'{productos_tab}'"
    return (
        f'=IFERROR(SORT(UNIQUE(ARRAYFORMULA(TEXT(FILTER({p}!B2:B,{p}!B2:B<>""),"yyyy-mm"))),1,FALSE),"")'
    )


def table_formula(productos_tab: str) -> str:
    """Total price and quantity per product for the month selected in B1."""
    p = f"'{productos_tab}'"
    selected_month = f'IF(ISNUMBER($B$1),TEXT($B$1,"yyyy-mm"),$B$1)'
    return (
        f'=QUERY(ARRAYFORMULA({{{p}!E2:E,{p}!F2:F,{p}!G2:G,TEXT({p}!B2:B,"yyyy-mm")}}),'
        f'"select Col1, sum(Col2), sum(Col3) where Col4 = \'"&{selected_month}&"\' '
        f'group by Col1 order by sum(Col2) desc limit {MAX_PRODUCTS} '
        f"label Col1 'Producto', sum(Col2) 'Total', sum(Col3) 'Cantidad'\",0)"
    )


def _column_range(sheet_id: int, column: int) -> dict:
    return {
        "sheetId": sheet_id,
        "startRowIndex": TABLE_FIRST_ROW - 1,
        "endRowIndex": TABLE_FIRST_ROW + MAX_PRODUCTS,
        "startColumnIndex": column,
        "endColumnIndex": column + 1,
    }


def chart_request(sheet_id: int) -> dict:
    return {
        "addChart": {
            "chart": {
                "spec": {
                    "title": "Total por producto del mes",
                    "basicChart": {
                        "chartType": "BAR",
                        "legendPosition": "NO_LEGEND",
                        "headerCount": 1,
                        "axis": [
                            {"position": "BOTTOM_AXIS", "title": "Total"},
                            {"position": "LEFT_AXIS", "title": "Producto"},
                        ],
                        "domains": [
                            {"domain": {"sourceRange": {"sources": [_column_range(sheet_id, 0)]}}}
                        ],
                        "series": [
                            {
                                "series": {"sourceRange": {"sources": [_column_range(sheet_id, 1)]}},
                                "targetAxis": "BOTTOM_AXIS",
                            }
                        ],
                    },
                },
                "position": {
                    "overlayPosition": {
                        "anchorCell": {
                            "sheetId": sheet_id,
                            "rowIndex": TABLE_FIRST_ROW - 1,
                            "columnIndex": CHART_ANCHOR_COLUMN,
                        },
                        "widthPixels": 700,
                        "heightPixels": 520,
                    }
                },
            }
        }
    }


def month_validation_request(sheet_id: int) -> dict:
    return {
        "setDataValidation": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": 0,
                "endRowIndex": 1,
                "startColumnIndex": 1,
                "endColumnIndex": 2,
            },
            "rule": {
                "condition": {
                    "type": "ONE_OF_RANGE",
                    "values": [
                        {"userEnteredValue": f"='{CHARTS_TAB}'!$E$2:$E${MONTHS_LIST_LAST_ROW}"}
                    ],
                },
                "showCustomUi": True,
                "strict": False,
            },
        }
    }


COMMA_LOCALES = ("en", "ja", "ko", "zh", "he", "th", "hi", "es_MX", "es_US", "es_419")


def localize_formula(formula: str, locale: str) -> str:
    """Convert US-style separators to the Sheet's locale (e.g. es_AR uses ';' and '\\')."""
    if (locale or "en_US").startswith(COMMA_LOCALES):
        return formula
    out = []
    in_string = False
    stack = []  # open '(' and '{'; a comma directly inside '{' separates array columns
    for char in formula:
        if char == '"':
            in_string = not in_string
        elif not in_string:
            if char in "({":
                stack.append(char)
            elif char in ")}" and stack:
                stack.pop()
            elif char == ",":
                char = "\\" if stack and stack[-1] == "{" else ";"
        out.append(char)
    return "".join(out)


def formula_request(sheet_id: int, row: int, column: int, formula: str) -> dict:
    return {
        "updateCells": {
            "start": {"sheetId": sheet_id, "rowIndex": row, "columnIndex": column},
            "rows": [{"values": [{"userEnteredValue": {"formulaValue": formula}}]}],
            "fields": "userEnteredValue",
        }
    }


def _has_chart(spreadsheet, sheet_id: int) -> bool:
    metadata = spreadsheet.fetch_sheet_metadata(
        {"fields": "sheets(properties(sheetId),charts(chartId))"}
    )
    for sheet in metadata.get("sheets", []):
        if sheet.get("properties", {}).get("sheetId") == sheet_id:
            return bool(sheet.get("charts"))
    return False


def _warn_if_dates_are_text(productos_sheet) -> None:
    values = productos_sheet.col_values(2, value_render_option="UNFORMATTED_VALUE")[1:]
    text_dates = [v for v in values if isinstance(v, str) and v.strip()]
    if text_dates:
        logger.warning(
            f"{len(text_dates)} value(s) in column B (Fecha) of '{productos_sheet.title}' are text, "
            f"not dates (e.g. {text_dates[0]!r}). Those rows won't appear in the monthly chart."
        )


def _current_total_requests(spreadsheet, sheet_id: int, summary_tab: str, locale: str) -> list[dict]:
    try:
        spreadsheet.worksheet(summary_tab)
    except gspread.exceptions.WorksheetNotFound:
        logger.warning(f"Tab '{summary_tab}' not found, skipping the current month total")
        return []
    label_row, label_col = CURRENT_TOTAL_LABEL_CELL
    value_row, value_col = CURRENT_TOTAL_VALUE_CELL

    def style(row, col, cell, fields):
        return {
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": row,
                    "endRowIndex": row + 1,
                    "startColumnIndex": col,
                    "endColumnIndex": col + 1,
                },
                "cell": cell,
                "fields": fields,
            }
        }

    return [
        formula_request(
            sheet_id, label_row, label_col, localize_formula(current_total_label_formula(), locale)
        ),
        formula_request(
            sheet_id, value_row, value_col,
            localize_formula(current_total_formula(summary_tab), locale),
        ),
        style(label_row, label_col, {"userEnteredFormat": {"textFormat": {"bold": True}}},
              "userEnteredFormat.textFormat"),
        style(value_row, value_col,
              {"userEnteredFormat": {"textFormat": {"bold": True},
                                     "numberFormat": {"type": "NUMBER", "pattern": "#,##0.00"}}},
              "userEnteredFormat.textFormat,userEnteredFormat.numberFormat"),
    ]


def create_charts(
    spreadsheet,
    productos_tab: str = USER2_PRODUCTOS_SHEET,
    summary_tab: str = USER2_SUMMARY_SHEET,
) -> None:
    try:
        productos_sheet = spreadsheet.worksheet(productos_tab)
    except gspread.exceptions.WorksheetNotFound:
        raise SystemExit(
            f"Tab '{productos_tab}' not found. Save a receipt from user 2 first so the bot creates it."
        )
    _warn_if_dates_are_text(productos_sheet)

    try:
        charts_sheet = spreadsheet.worksheet(CHARTS_TAB)
    except gspread.exceptions.WorksheetNotFound:
        charts_sheet = spreadsheet.add_worksheet(title=CHARTS_TAB, rows=100, cols=20)
        logger.info(f"Created '{CHARTS_TAB}' sheet")

    charts_sheet.update([["Mes"]], "A1")
    if not charts_sheet.acell(MONTH_CELL).value:
        # Raw so "2026-10" stays text instead of being parsed as a date
        charts_sheet.update([[datetime.now().strftime("%Y-%m")]], MONTH_CELL, raw=True)
    charts_sheet.update([["Meses disponibles"]], "E1")

    # The API parses formulas with the Sheet's locale, so adapt the separators to it
    locale = spreadsheet.locale
    requests = [
        month_validation_request(charts_sheet.id),
        formula_request(
            charts_sheet.id, 1, 4, localize_formula(months_formula(productos_tab), locale)
        ),
        formula_request(
            charts_sheet.id,
            TABLE_FIRST_ROW - 1,
            0,
            localize_formula(table_formula(productos_tab), locale),
        ),
    ]
    requests.extend(_current_total_requests(spreadsheet, charts_sheet.id, summary_tab, locale))
    if _has_chart(spreadsheet, charts_sheet.id):
        logger.info("Chart already exists, not creating another one")
    else:
        requests.append(chart_request(charts_sheet.id))
    spreadsheet.batch_update({"requests": requests})
    logger.info(f"'{CHARTS_TAB}' ready: pick a month in {MONTH_CELL}")


if __name__ == "__main__":
    create_charts(_get_spreadsheet())

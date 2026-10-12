"""
One-off fix: dates saved with day and month swapped in user 2's tabs.

    python fix_swapped_dates.py            # dry run, prints what would change
    python fix_swapped_dates.py --apply    # writes the fix (saves a backup first)

Google Sheets stored receipt dates like "03/10/2026" as 10 March instead of 3 October.
The cell still DISPLAYS the original text, so the true date is read from the displayed
text as dd/mm/yyyy and written back as a real date with a dd/mm/yyyy display format.
Text dates (e.g. "14/09/2026") and dates that are already correct are left alone.
"""

import argparse
import json
import logging
import re
from datetime import date, datetime, timedelta

from config import USER2_PRODUCTOS_SHEET, USER2_SUMMARY_SHEET, USER2_TICKETS_SHEET
from services.sheets_service import _get_spreadsheet, refresh_summary

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

EPOCH = date(1899, 12, 30)
DATE_FORMAT = {"type": "DATE", "pattern": "dd/mm/yyyy"}
DATETIME_FORMAT = {"type": "DATE_TIME", "pattern": "dd/mm/yyyy hh:mm:ss"}

# tab -> {0-indexed column: number format}
TARGETS = {
    USER2_TICKETS_SHEET: {0: DATE_FORMAT, 5: DATETIME_FORMAT},    # Date, Logged At
    USER2_PRODUCTOS_SHEET: {0: DATETIME_FORMAT, 1: DATE_FORMAT},  # Logged At, Fecha
}

SHOWN_PATTERN = re.compile(r"^\s*(\d{1,2})/(\d{1,2})/(\d{4})(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?\s*$")


def corrected_serial(raw, shown):
    """New serial for a swapped date, or None if the cell needs no change."""
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    match = SHOWN_PATTERN.match(str(shown))
    if not match:
        return None
    first, second, year = (int(g) for g in match.groups())
    stored = EPOCH + timedelta(days=int(raw))
    # Only cells that display as month/day of the stored date were misparsed
    if (stored.month, stored.day, stored.year) != (first, second, year) or first == second:
        return None
    try:
        true_date = date(year, second, first)  # displayed text is dd/mm/yyyy
    except ValueError:
        return None
    return (true_date - EPOCH).days + (raw - int(raw))


def find_fixes(ws, columns):
    raw_rows = ws.get_all_values(value_render_option="UNFORMATTED_VALUE")
    shown_rows = ws.get_all_values()
    fixes = []
    for row_index in range(1, len(raw_rows)):
        for col in columns:
            if col >= len(raw_rows[row_index]):
                continue
            raw, shown = raw_rows[row_index][col], shown_rows[row_index][col]
            new = corrected_serial(raw, shown)
            if new is not None:
                cell = f"{chr(ord('A') + col)}{row_index + 1}"
                fixes.append({"cell": cell, "old": raw, "new": new, "shown": shown})
    return fixes


def apply_fixes(spreadsheet, ws, columns, fixes):
    ws.batch_update(
        [{"range": f["cell"], "values": [[f["new"]]]} for f in fixes], raw=True
    )
    requests = [
        {
            "repeatCell": {
                "range": {
                    "sheetId": ws.id,
                    "startRowIndex": 1,
                    "endRowIndex": ws.row_count,
                    "startColumnIndex": col,
                    "endColumnIndex": col + 1,
                },
                "cell": {"userEnteredFormat": {"numberFormat": fmt}},
                "fields": "userEnteredFormat.numberFormat",
            }
        }
        for col, fmt in columns.items()
    ]
    spreadsheet.batch_update({"requests": requests})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="write the fix (default: dry run)")
    args = parser.parse_args()

    spreadsheet = _get_spreadsheet()
    plan = {}
    for tab, columns in TARGETS.items():
        ws = spreadsheet.worksheet(tab)
        fixes = find_fixes(ws, columns)
        plan[tab] = (ws, columns, fixes)
        logger.info(f"{tab}: {len(fixes)} cell(s) to fix")
        for f in fixes[:6]:
            old = EPOCH + timedelta(days=int(f["old"]))
            new = EPOCH + timedelta(days=int(f["new"]))
            logger.info(f"  {f['cell']}: shown {f['shown']!r}  stored {old} -> {new}")

    if not args.apply:
        logger.info("Dry run only. Re-run with --apply to write changes.")
        return

    backup = f"dates_backup_{datetime.now():%Y%m%d_%H%M%S}.json"
    with open(backup, "w") as f:
        json.dump({tab: fixes for tab, (_, _, fixes) in plan.items()}, f, indent=1)
    logger.info(f"Backup of old values saved to {backup}")

    for tab, (ws, columns, fixes) in plan.items():
        if fixes:
            apply_fixes(spreadsheet, ws, columns, fixes)
            logger.info(f"{tab}: fixed {len(fixes)} cell(s)")

    refresh_summary(
        tickets_tab=USER2_TICKETS_SHEET, summary_tab=USER2_SUMMARY_SHEET, with_budget=False
    )
    logger.info(f"'{USER2_SUMMARY_SHEET}' recalculated")


if __name__ == "__main__":
    main()

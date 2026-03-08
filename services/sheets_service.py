import json
import logging
from collections import defaultdict
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials
from config import GOOGLE_SHEET_ID, GOOGLE_SERVICE_ACCOUNT_JSON

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

MONTHS_ES = {
    1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril",
    5: "Mayo", 6: "Junio", 7: "Julio", 8: "Agosto",
    9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre",
}


def _get_spreadsheet():
    raw = GOOGLE_SERVICE_ACCOUNT_JSON
    try:
        info = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        with open(raw) as f:
            info = json.load(f)

    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    gc = gspread.authorize(creds)
    spreadsheet = gc.open_by_key(GOOGLE_SHEET_ID)

    # Rename the first sheet if it still has a default name
    first_sheet = spreadsheet.sheet1
    if first_sheet.title in ("Sheet1", "Hoja 1", "Hoja1"):
        first_sheet.update_title("Tickets")
        logger.info("Renamed first sheet to 'Tickets'")

    return spreadsheet


def _get_or_create_summary_sheet(spreadsheet):
    try:
        return spreadsheet.worksheet("Resumen")
    except gspread.exceptions.WorksheetNotFound:
        sheet = spreadsheet.add_worksheet(title="Resumen", rows=100, cols=5)
        return sheet


def _update_summary(spreadsheet):
    data_sheet = spreadsheet.sheet1
    rows = data_sheet.get_all_values()

    # monthly[key] = {"total": float, "count": int, "categories": {cat: float}}
    monthly: dict[tuple, dict] = {}
    all_categories: list[str] = []

    for row in rows[1:]:  # skip header
        if not row or not row[0]:
            continue
        date_str = row[0].strip()       # Column A: Date
        total_str = row[2]              # Column C: Total
        category = row[3].strip() if len(row) > 3 else ""  # Column D: Category

        # Fall back to Logged At (Column F) if receipt date is missing
        if not date_str and len(row) > 5 and row[5]:
            date_str = row[5].split(" ")[0]

        try:
            date = datetime.strptime(date_str, "%d/%m/%Y")
        except ValueError:
            continue

        try:
            total = float(str(total_str).replace(",", ".").replace("$", "").strip())
        except ValueError:
            total = 0.0

        store = row[1].strip() if len(row) > 1 else ""  # Column B: Store

        key = (date.year, date.month)
        if key not in monthly:
            monthly[key] = {"total": 0.0, "count": 0, "categories": {}, "stores": []}

        monthly[key]["total"] += total
        monthly[key]["count"] += 1

        if store and store not in monthly[key]["stores"]:
            monthly[key]["stores"].append(store)

        if category:
            monthly[key]["categories"][category] = (
                monthly[key]["categories"].get(category, 0.0) + total
            )
            if category not in all_categories:
                all_categories.append(category)

    all_categories.sort()
    headers = ["Año", "Mes", "Nro. Tickets"] + all_categories + ["Total ($)"]
    summary_rows = [headers]

    for (year, month) in sorted(monthly.keys()):
        entry = monthly[(year, month)]
        cat_values = [round(entry["categories"].get(cat, 0.0), 2) for cat in all_categories]
        summary_rows.append([
            year,
            MONTHS_ES[month],
            entry["count"],
            *cat_values,
            round(entry["total"], 2),
        ])

    summary_sheet = _get_or_create_summary_sheet(spreadsheet)
    summary_sheet.clear()
    summary_sheet.update(summary_rows, "A1")
    logger.info(f"Summary sheet updated with {len(summary_rows) - 1} month(s)")

    # Return structured data: last 4 data rows with store info for WhatsApp message
    last_keys = sorted(monthly.keys())[-4:]
    last_months = [
        {
            "month": MONTHS_ES[k[1]],
            "year": k[0],
            "count": monthly[k]["count"],
            "total": round(monthly[k]["total"], 2),
            "stores": monthly[k]["stores"],
        }
        for k in last_keys
    ]
    return last_months


def append_row(data: dict) -> None:
    logger.info(f"Connecting to Google Sheet: {GOOGLE_SHEET_ID}")
    spreadsheet = _get_spreadsheet()
    sheet = spreadsheet.sheet1

    logged_at = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    row = [
        data.get("date") or "",
        data.get("store") or "",
        data.get("total") or "",
        data.get("category") or "",
        data.get("items") or "",
        logged_at,
    ]
    logger.info(f"Appending row: {row}")
    sheet.append_row(row, value_input_option="USER_ENTERED")
    logger.info("Row appended successfully")

    return _update_summary(spreadsheet)

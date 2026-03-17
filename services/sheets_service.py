import json
import logging
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
        sheet = spreadsheet.add_worksheet(title="Resumen", rows=100, cols=20)
        return sheet


def _get_or_create_productos_sheet(spreadsheet):
    try:
        return spreadsheet.worksheet("Productos")
    except gspread.exceptions.WorksheetNotFound:
        sheet = spreadsheet.add_worksheet(title="Productos", rows=1000, cols=6)
        sheet.append_row(["Logged At", "Fecha", "Comercio", "Categoría", "Producto", "Precio"])
        logger.info("Created 'Productos' sheet")
        return sheet


def get_budget_eur() -> float:
    """Read monthly budget in EUR from cell B1 of the 'Config' sheet."""
    spreadsheet = _get_spreadsheet()
    try:
        config_sheet = spreadsheet.worksheet("Config")
        value = config_sheet.acell("B1").value
        return float(str(value).replace(",", ".").strip())
    except gspread.exceptions.WorksheetNotFound:
        logger.warning("'Config' sheet not found, defaulting budget to 0")
        return 0.0
    except (ValueError, TypeError):
        logger.warning("Could not parse budget from Config!B1, defaulting to 0")
        return 0.0


def append_productos(logged_at: str, date: str, store: str, category: str, items: list[dict]):
    """Append one row per item to the 'Productos' sheet."""
    if not items:
        return
    spreadsheet = _get_spreadsheet()
    sheet = _get_or_create_productos_sheet(spreadsheet)
    rows = [
        [logged_at, date, store, category, item.get("name") or "", item.get("price") or ""]
        for item in items
    ]
    sheet.append_rows(rows, value_input_option="USER_ENTERED")
    logger.info(f"Appended {len(rows)} producto row(s)")


def _update_summary(spreadsheet, budget_eur: float = 0.0, eur_to_ars: float = 0.0):
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

        date = None
        for fmt in ("%d/%m/%Y", "%m/%d/%Y", "%Y-%m-%d", "%d-%m-%Y", "%Y/%m/%d"):
            try:
                date = datetime.strptime(date_str, fmt)
                break
            except ValueError:
                continue
        if date is None:
            logger.warning(f"Could not parse date '{date_str}', skipping row")
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
    budget_ars = round(budget_eur * eur_to_ars, 2) if eur_to_ars else 0.0
    headers = (
        ["Año", "Mes", "Nro. Tickets"]
        + all_categories
        + ["Total ($)", "Presupuesto (EUR)", "Tipo de cambio", "Presupuesto (ARS)", "% Gastado", "Estado"]
    )
    summary_rows = [headers]

    for (year, month) in sorted(monthly.keys()):
        entry = monthly[(year, month)]
        cat_values = [round(entry["categories"].get(cat, 0.0), 2) for cat in all_categories]
        total_month = round(entry["total"], 2)
        pct = round(total_month / budget_ars * 100) if budget_ars else 0
        estado = "✓ Dentro" if pct <= 100 else "⚠ Excedido"
        summary_rows.append([
            year,
            MONTHS_ES[month],
            entry["count"],
            *cat_values,
            total_month,
            budget_eur,
            round(eur_to_ars, 2) if eur_to_ars else "",
            budget_ars,
            f"{pct}%",
            estado,
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
            "categories": monthly[k]["categories"],
        }
        for k in last_keys
    ]
    return last_months


def append_row(data: dict, budget_eur: float = 0.0, eur_to_ars: float = 0.0) -> list:
    logger.info(f"Connecting to Google Sheet: {GOOGLE_SHEET_ID}")
    spreadsheet = _get_spreadsheet()
    sheet = spreadsheet.sheet1

    logged_at = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    items = data.get("items") or []
    # Store a readable summary of items in Tickets sheet (column E)
    if isinstance(items, list):
        items_summary = ", ".join(it.get("name") or "" for it in items if it.get("name"))
    else:
        items_summary = str(items)

    row = [
        data.get("date") or "",
        data.get("store") or "",
        data.get("total") or "",
        data.get("category") or "",
        items_summary,
        logged_at,
    ]
    logger.info(f"Appending row: {row}")
    sheet.append_row(row, value_input_option="USER_ENTERED")
    logger.info("Row appended successfully")

    # Append individual items to Productos sheet
    if isinstance(items, list) and items:
        _get_or_create_productos_sheet(spreadsheet)  # ensure sheet + header exist
        productos_sheet = spreadsheet.worksheet("Productos")
        rows = [
            [
                logged_at,
                data.get("date") or "",
                data.get("store") or "",
                data.get("category") or "",
                item.get("name") or "",
                item.get("price") if item.get("price") is not None else "",
            ]
            for item in items
        ]
        productos_sheet.append_rows(rows, value_input_option="USER_ENTERED")
        logger.info(f"Appended {len(rows)} producto row(s)")

    return _update_summary(spreadsheet, budget_eur=budget_eur, eur_to_ars=eur_to_ars)


def get_previous_month_summary(year: int, month: int) -> dict | None:
    """Return the Resumen row for a given year/month, or None if not found."""
    spreadsheet = _get_spreadsheet()
    summary_sheet = _get_or_create_summary_sheet(spreadsheet)
    rows = summary_sheet.get_all_values()
    if not rows:
        return None
    headers = rows[0]
    month_name = MONTHS_ES.get(month, "")
    for row in rows[1:]:
        if len(row) >= 2 and str(row[0]) == str(year) and row[1] == month_name:
            return dict(zip(headers, row))
    return None

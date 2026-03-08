import logging
import traceback
from fastapi import FastAPI, Form, Response
from services.groq_service import parse_receipt
from services.sheets_service import append_row
from services.twilio_service import send_message, send_typing_indicator

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

app = FastAPI()

# In-memory state: phone -> receipt dict
pending: dict[str, dict] = {}

FIELDS_MAP = {
    "total": "total",
    "comercio": "store",
    "store": "store",
    "fecha": "date",
    "date": "date",
    "categoria": "category",
    "category": "category",
    "items": "items",
}


def fmt_ars(value) -> str:
    """Format a number as Argentine peso: $ 1.234,56"""
    try:
        amount = float(str(value).replace(",", ".").replace("$", "").strip())
        # Argentine format: dot for thousands, comma for decimals
        formatted = f"{amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        return f"$ {formatted}"
    except (ValueError, TypeError):
        return str(value)


def build_summary(data: dict) -> str:
    total = data.get("total")
    total_display = fmt_ars(total) if total else "?"
    return (
        "Esto es lo que encontré:\n"
        f"  Comercio: {data.get('store') or '?'}\n"
        f"  Fecha: {data.get('date') or '?'}\n"
        f"  Total: {total_display}\n"
        f"  Categoría: {data.get('category') or '?'}\n"
        f"  Items: {data.get('items') or '?'}\n\n"
        "Respondé *SI* para guardar, *NO* para cancelar, o corregí un dato:\n"
        "  corregir total 52.10\n"
        "  corregir comercio Lidl"
    )


@app.post("/webhook")
async def webhook(
    From: str = Form(...),
    Body: str = Form(""),
    NumMedia: int = Form(0),
    MediaUrl0: str = Form(None),
    MessageSid: str = Form(None),
):
    sender = From
    text = Body.strip()

    if MessageSid:
        send_typing_indicator(MessageSid)

    if sender in pending:
        # --- Pending confirmation ---
        upper = text.upper()

        if upper in ("SI", "YES", "SÍ"):
            try:
                months = append_row(pending[sender])
                lines = ["Listo, guardado en la planilla!\n", "*Resumen:*"]
                for m in months:
                    stores = ", ".join(m["stores"]) or "?"
                    ticket_label = "ticket" if m["count"] == 1 else "tickets"
                    lines.append(
                        f"{m['month']} {m['year']}  |  Tienda: {stores}  |  Total: {fmt_ars(m['total'])}  |  {m['count']} {ticket_label}"
                    )
                reply = "\n".join(lines)
            except Exception as e:
                logging.error(f"sheets append_row failed: {traceback.format_exc()}")
                reply = "Hubo un error al guardar. Intentá de nuevo."
            del pending[sender]

        elif upper in ("NO"):
            del pending[sender]
            reply = "Okey, cancelado. Mandá otra foto cuando quieras."

        elif text.lower().startswith("corregir "):
            parts = text.split(" ", 2)
            if len(parts) < 3:
                reply = "No entendí. Usá el formato: corregir <campo> <valor> (ej: corregir total 52.10)."
            else:
                field_key = parts[1].lower()
                value = parts[2].strip()
                field = FIELDS_MAP.get(field_key)
                if field:
                    pending[sender][field] = value
                    reply = build_summary(pending[sender])
                else:
                    reply = (
                        "No entendí ese campo. Campos válidos: total, comercio, fecha, categoria, items.\n"
                        "Ej: corregir total 52.10"
                    )
        else:
            reply = "Respondé SI, NO, o corregí un dato (ej: corregir total 52.10)."

    else:
        # --- Idle state ---
        if NumMedia and NumMedia > 0 and MediaUrl0:
            send_message(to=sender, body="Recibí el ticket, estoy analizándolo...")
            data = parse_receipt(MediaUrl0)
            if data is None:
                reply = "No pude leer el ticket. ¿Podés mandar otra foto con mejor luz?"
            else:
                pending[sender] = data
                reply = build_summary(data)
        else:
            reply = "Mandame una foto del ticket para registrarlo."

    send_message(to=sender, body=reply)
    return Response(content="", media_type="text/plain")

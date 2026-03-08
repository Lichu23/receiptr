import asyncio
import logging
import traceback
from fastapi import FastAPI, Form, Response
from services.groq_service import parse_receipt
from services.sheets_service import append_row
from services.twilio_service import send_message, send_typing_indicator

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

app = FastAPI()

# phone -> receipt dict awaiting SI/NO confirmation
pending: dict[str, dict] = {}

# phone -> [url, ...] when 2 images arrived and we asked if same or different receipt
awaiting_split: dict[str, list[str]] = {}

# phone -> [url] next receipt to process after current pending is resolved
queued_images: dict[str, list[str]] = {}

# phone -> {"urls": [...], "task": asyncio.Task} — 4s buffer for multi-image sends
image_buffer: dict[str, dict] = {}

BUFFER_WAIT = 4  # seconds

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

MANUAL_ENTRY_HINT = (
    "Si querés cargarlo igual, mandame los datos así:\n"
    "  *agregar <monto> <categoría> <comercio> <fecha> <items>*\n\n"
    "Ejemplo:\n"
    "  agregar 1500 Farmacia Farmacity 07/03/2026 ibuprofeno, vitamina C"
)


def fmt_ars(value) -> str:
    try:
        amount = float(str(value).replace(",", ".").replace("$", "").strip())
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


def process_single_image(sender: str, url: str) -> str:
    data = parse_receipt([url])
    if data is None:
        return "No pude leer el ticket.\n\n" + MANUAL_ENTRY_HINT
    pending[sender] = data
    return build_summary(data)


async def flush_image_buffer(sender: str):
    """After BUFFER_WAIT seconds, decide what to do with buffered images."""
    await asyncio.sleep(BUFFER_WAIT)
    entry = image_buffer.pop(sender, None)
    if not entry:
        return
    urls = entry["urls"]
    logging.info(f"Flushing {len(urls)} buffered image(s) for {sender}")

    if len(urls) == 1:
        # Single image — process directly
        reply = process_single_image(sender, urls[0])
    else:
        # Multiple images — ask the user before processing
        awaiting_split[sender] = urls
        reply = (
            f"Recibí {len(urls)} fotos. ¿Son del *mismo ticket* o de *tickets distintos*?\n\n"
            "  Respondé *MISMO* o *DISTINTOS*"
        )

    send_message(to=sender, body=reply)


@app.post("/webhook")
async def webhook(
    From: str = Form(...),
    Body: str = Form(""),
    NumMedia: int = Form(0),
    MediaUrl0: str = Form(None),
    MediaUrl1: str = Form(None),
    MessageSid: str = Form(None),
):
    sender = From
    text = Body.strip()
    upper = text.upper()

    if MessageSid:
        send_typing_indicator(MessageSid)

    # --- Incoming image(s) ---
    if NumMedia and NumMedia > 0 and MediaUrl0:
        if sender in pending or sender in awaiting_split:
            send_message(
                to=sender,
                body=(
                    "Todavía tenés un ticket pendiente.\n"
                    "Confirmalo o cancelalo primero, y después mandá el nuevo ticket."
                ),
            )
            return Response(content="", media_type="text/plain")

        urls = [u for u in [MediaUrl0, MediaUrl1] if u]

        if sender in image_buffer:
            image_buffer[sender]["task"].cancel()
            image_buffer[sender]["urls"].extend(urls)
            logging.info(f"Added to buffer for {sender}, total: {len(image_buffer[sender]['urls'])}")
        else:
            image_buffer[sender] = {"urls": urls}
            send_message(to=sender, body="Recibí el ticket, estoy analizándolo...")

        task = asyncio.create_task(flush_image_buffer(sender))
        image_buffer[sender]["task"] = task
        return Response(content="", media_type="text/plain")

    # --- Awaiting split answer (MISMO / DISTINTOS) ---
    if sender in awaiting_split:
        urls = awaiting_split.pop(sender)

        if upper in ("MISMO", "MISMOS", "UNO", "1", "JUNTOS", "SI", "SÍ"):
            send_message(to=sender, body="Entendido, analizo las dos fotos juntas...")
            data = parse_receipt(urls)
            if data is None:
                reply = "No pude leer el ticket.\n\n" + MANUAL_ENTRY_HINT
            else:
                pending[sender] = data
                reply = build_summary(data)

        elif upper in ("DISTINTOS", "DOS", "2", "SEPARADOS", "NO"):
            # Process first image now, queue the second
            queued_images[sender] = urls[1:]
            send_message(to=sender, body="Perfecto, analizo el primero...")
            reply = process_single_image(sender, urls[0])

        else:
            awaiting_split[sender] = urls  # put it back
            reply = "No entendí. Respondé *MISMO* si es un solo ticket, o *DISTINTOS* si son dos tickets diferentes."

        send_message(to=sender, body=reply)
        return Response(content="", media_type="text/plain")

    # --- Pending confirmation ---
    if sender in pending:
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
            except Exception:
                logging.error(f"sheets append_row failed: {traceback.format_exc()}")
                reply = "Hubo un error al guardar. Intentá de nuevo."
            del pending[sender]

        elif upper == "NO":
            del pending[sender]
            reply = "Okey, cancelado."

        elif text.lower().startswith("corregir "):
            parts = text.split(" ", 2)
            if len(parts) < 3:
                reply = "No entendí. Usá: corregir <campo> <valor> (ej: corregir total 52.10)."
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

        send_message(to=sender, body=reply)

        # After resolving pending, auto-process the next queued image (if any)
        if sender not in pending and sender in queued_images:
            remaining = queued_images.pop(sender)
            if remaining:
                next_url = remaining.pop(0)
                if remaining:
                    queued_images[sender] = remaining  # re-queue the rest
                send_message(to=sender, body="Ahora analizo el siguiente ticket...")
                next_reply = process_single_image(sender, next_url)
                send_message(to=sender, body=next_reply)

        return Response(content="", media_type="text/plain")

    # --- Idle state ---
    if text.lower().startswith("agregar "):
        parts = text.split(" ", 5)
        if len(parts) < 6:
            reply = (
                "Faltan datos. El formato es:\n"
                "  *agregar <monto> <categoría> <comercio> <fecha> <items>*\n\n"
                "Ejemplo:\n"
                "  agregar 1500 Farmacia Farmacity 07/03/2026 ibuprofeno, vitamina C"
            )
        else:
            data = {
                "total": parts[1],
                "category": parts[2],
                "store": parts[3],
                "date": parts[4],
                "items": parts[5],
            }
            pending[sender] = data
            reply = build_summary(data)
    else:
        reply = (
            "Mandame una foto del ticket para registrarlo.\n\n"
            "O si no tenés foto, escribí:\n"
            "  *agregar <monto> <categoría> <comercio> <fecha> <items>*"
        )

    send_message(to=sender, body=reply)
    return Response(content="", media_type="text/plain")

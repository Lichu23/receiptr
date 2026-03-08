import base64
import json
import logging
import httpx
from groq import Groq
from config import GROQ_API_KEY, TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN

logger = logging.getLogger(__name__)
client = Groq(api_key=GROQ_API_KEY)

PROMPT = """Analizá esta imagen de un ticket de compra y extraé la siguiente información en formato JSON.
Devolvé SOLO el JSON, sin texto adicional, con estas claves exactas:
{
  "store": "nombre del comercio",
  "date": "fecha de la compra en formato DD/MM/YYYY",
  "total": "monto total como número con dos decimales (ej: 47.30)",
  "category": "categoría del gasto (ej: Supermercado, Farmacia, Restaurante, Combustible, Otro)",
  "items": [{"name": "nombre del producto", "price": 123.45}, ...]
}
El campo "items" debe ser una lista de objetos con "name" (string) y "price" (número con dos decimales).
Si un producto no tiene precio visible, usá null para "price".
Si no podés determinar algún campo raíz, usá null."""


def parse_receipt(image_urls: list[str]) -> dict | None:
    try:
        content = []
        for url in image_urls:
            logger.info(f"Downloading image from: {url}")
            response = httpx.get(url, timeout=15, auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN), follow_redirects=True)
            logger.info(f"Image download status: {response.status_code}, size: {len(response.content)} bytes")
            response.raise_for_status()
            image_b64 = base64.standard_b64encode(response.content).decode("utf-8")
            content_type = response.headers.get("content-type", "image/jpeg").split(";")[0]
            logger.info(f"Image content-type: {content_type}")
            content.append({"type": "image_url", "image_url": {"url": f"data:{content_type};base64,{image_b64}"}})
        content.append({"type": "text", "text": PROMPT})

        logger.info(f"Sending {len(image_urls)} image(s) to Groq...")
        completion = client.chat.completions.create(
            model="meta-llama/llama-4-scout-17b-16e-instruct",
            messages=[{"role": "user", "content": content}],
            max_tokens=512,
        )

        raw = completion.choices[0].message.content.strip()
        logger.info(f"Groq raw response: {raw}")

        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        data = json.loads(raw)
        logger.info(f"Parsed data: {data}")

        # Normalise items: always return a list of {name, price} dicts
        raw_items = data.get("items")
        if isinstance(raw_items, list):
            items = [
                {"name": str(it.get("name") or ""), "price": it.get("price")}
                for it in raw_items
                if isinstance(it, dict)
            ]
        else:
            # Fallback: Groq returned a string — wrap as single item with no price
            items = [{"name": str(raw_items), "price": None}] if raw_items else []

        return {
            "store": data.get("store"),
            "date": data.get("date"),
            "total": data.get("total"),
            "category": data.get("category"),
            "items": items,
        }
    except Exception as e:
        logger.error(f"parse_receipt failed: {type(e).__name__}: {e}")
        return None

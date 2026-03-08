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
  "items": "lista resumida de productos separados por coma"
}
Si no podés determinar algún campo, usá null."""


def parse_receipt(image_url: str) -> dict | None:
    try:
        logger.info(f"Downloading image from: {image_url}")
        response = httpx.get(image_url, timeout=15, auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN), follow_redirects=True)
        logger.info(f"Image download status: {response.status_code}, size: {len(response.content)} bytes")
        response.raise_for_status()
        image_b64 = base64.standard_b64encode(response.content).decode("utf-8")
        content_type = response.headers.get("content-type", "image/jpeg").split(";")[0]
        logger.info(f"Image content-type: {content_type}")

        logger.info("Sending image to Groq...")
        completion = client.chat.completions.create(
            model="meta-llama/llama-4-scout-17b-16e-instruct",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{content_type};base64,{image_b64}"
                            },
                        },
                        {"type": "text", "text": PROMPT},
                    ],
                }
            ],
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
        return {
            "store": data.get("store"),
            "date": data.get("date"),
            "total": data.get("total"),
            "category": data.get("category"),
            "items": data.get("items"),
        }
    except Exception as e:
        logger.error(f"parse_receipt failed: {type(e).__name__}: {e}")
        return None

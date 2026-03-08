import logging
import time
import httpx

logger = logging.getLogger(__name__)

_cache: dict = {"rate": None, "ts": 0}
_CACHE_TTL = 3 * 60 * 60  # 3 hours


async def get_eur_to_ars() -> float:
    """Fetch EUR→ARS blue (venta) rate from dolarapi.com, cached 3h."""
    now = time.monotonic()
    if _cache["rate"] is not None and (now - _cache["ts"]) < _CACHE_TTL:
        logger.info(f"EUR/ARS rate from cache: {_cache['rate']}")
        return _cache["rate"]

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get("https://dolarapi.com/v1/cotizaciones/eur")
        resp.raise_for_status()
        data = resp.json()

    rate = float(data["venta"])
    _cache["rate"] = rate
    _cache["ts"] = now
    logger.info(f"EUR/ARS rate fetched: {rate}")
    return rate

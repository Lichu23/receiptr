"""
Run this script locally to rebuild the Resumen sheet from the Tickets sheet.

    python update_summary.py

Reads .env for credentials. No arguments needed.
"""

import asyncio
import logging
from services.sheets_service import refresh_summary
from services.exchange_service import get_eur_to_ars
from services.sheets_service import get_budget_eur

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


async def main():
    budget_eur = get_budget_eur()
    logging.info(f"Budget: {budget_eur} EUR")

    try:
        eur_to_ars = await get_eur_to_ars()
        logging.info(f"EUR/ARS rate: {eur_to_ars}")
    except Exception as e:
        logging.warning(f"Could not fetch EUR/ARS rate ({e}), using 0")
        eur_to_ars = 0.0

    months = refresh_summary(
        budget_eur=budget_eur,
        eur_to_ars=eur_to_ars,
        tickets_tab="Tickets",
        summary_tab="Resumen",
        with_budget=True,
    )

    print("\nResumen actualizado:")
    for m in months:
        ticket_label = "ticket" if m["count"] == 1 else "tickets"
        print(f"  {m['month']} {m['year']}  |  Total: {m['total']}  |  {m['count']} {ticket_label}")


if __name__ == "__main__":
    asyncio.run(main())

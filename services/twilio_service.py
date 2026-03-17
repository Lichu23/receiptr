import logging
import httpx
from twilio.rest import Client
from config import TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_NUMBER

logger = logging.getLogger(__name__)


def send_message(to: str, body: str) -> None:
    logger.info(f"Sending message to={to} from={TWILIO_WHATSAPP_NUMBER}")
    logger.info(f"Message body: {body}")
    client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    msg = client.messages.create(
        from_=TWILIO_WHATSAPP_NUMBER,
        to=to,
        body=body,
    )
    logger.info(f"Twilio message created: sid={msg.sid} status={msg.status} error_code={msg.error_code} error_message={msg.error_message}")


def send_typing_indicator(message_sid: str) -> None:
    """Send a typing indicator + mark message as read (blue ticks). Public Beta."""
    try:
        response = httpx.post(
            "https://messaging.twilio.com/v2/Indicators/Typing.json",
            auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN),
            data={"messageId": message_sid, "channel": "whatsapp"},
            timeout=5,
        )
        logger.info(f"Typing indicator response: {response.status_code} {response.text}")
    except Exception as e:
        logger.warning(f"Typing indicator failed (non-critical): {e}")

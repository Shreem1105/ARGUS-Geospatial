from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class EmailProviderError(Exception):
    def __init__(self, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.retryable = retryable


@dataclass(slots=True)
class EmailMessage:
    to_email: str
    subject: str
    text: str
    html: str


@dataclass(slots=True)
class EmailDeliveryResult:
    status: str
    provider_message_id: str | None = None
    error: str | None = None


class EmailProvider:
    name = "none"

    def send(self, message: EmailMessage) -> EmailDeliveryResult:
        raise NotImplementedError


class DisabledEmailProvider(EmailProvider):
    name = "none"

    def send(self, message: EmailMessage) -> EmailDeliveryResult:
        _ = message
        return EmailDeliveryResult(status="disabled", error="email provider not configured")


class ConsoleEmailProvider(EmailProvider):
    name = "console"

    def send(self, message: EmailMessage) -> EmailDeliveryResult:
        logger.info(
            "Console email delivery to=%s subject=%s",
            message.to_email,
            message.subject,
        )
        return EmailDeliveryResult(status="delivered", provider_message_id="console")


class ResendEmailProvider(EmailProvider):
    name = "resend"

    def __init__(self, *, api_key: str, base_url: str, from_email: str) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._from_email = from_email

    def send(self, message: EmailMessage) -> EmailDeliveryResult:
        payload = {
            "from": self._from_email,
            "to": [message.to_email],
            "subject": message.subject,
            "text": message.text,
            "html": message.html,
        }

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        try:
            response = httpx.post(
                f"{self._base_url}/emails",
                json=payload,
                headers=headers,
                timeout=10.0,
            )
        except httpx.TimeoutException as exc:
            raise EmailProviderError("Email provider timeout", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise EmailProviderError("Email provider request failed", retryable=True) from exc

        if response.status_code >= 500:
            raise EmailProviderError("Email provider unavailable", retryable=True)
        if response.status_code >= 400:
            raise EmailProviderError("Email provider rejected request", retryable=False)

        body = response.json() if response.content else {}
        message_id = body.get("id") if isinstance(body, dict) else None
        if message_id is not None and not isinstance(message_id, str):
            message_id = str(message_id)

        return EmailDeliveryResult(status="delivered", provider_message_id=message_id)


def get_email_provider() -> EmailProvider:
    settings = get_settings()
    provider_name = settings.email_provider.strip().lower()

    if provider_name == "console":
        return ConsoleEmailProvider()

    if provider_name == "resend" and settings.email_api_key:
        return ResendEmailProvider(
            api_key=settings.email_api_key,
            base_url=settings.email_resend_api_url,
            from_email=settings.email_from_address,
        )

    return DisabledEmailProvider()

"""Exotel Outbound Voice Calling Client for RevivePay.

Handles direct authentication and API interaction with Exotel's Voice Platform:
POST https://<subdomain>/v1/Accounts/<account_sid>/Calls/connect.json

Security Invariants:
- Never logs API key, API password, Authorization headers, or full sensitive phone numbers.
- Handles timeouts, HTTP errors, and network failures fail-closed.
- Normalizes provider-specific payloads into typed internal results.
"""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from app.core.config import Settings, get_settings
from app.core.logging import get_logger

logger = get_logger("exotel_client")


@dataclass(frozen=True)
class ExotelCallResult:
    """Normalized response from Exotel voice call initiation."""

    success: bool
    call_id: str | None
    status: str
    message: str
    error: str | None = None
    raw_status_code: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "call_id": self.call_id,
            "status": self.status,
            "message": self.message,
            "error": self.error,
        }


class ExotelClient:
    """Isolated client for Exotel outbound call execution."""

    def __init__(self, settings: Settings | None = None) -> None:
        if settings is not None:
            self.settings = settings
            self.api_key = settings.exotel_api_key
            self.api_password = settings.exotel_api_password
            self.account_sid = settings.exotel_account_sid
            self.subdomain = (settings.exotel_subdomain or "api.exotel.com").strip().replace("https://", "").replace("http://", "").rstrip("/")
            self.caller_id = settings.exotel_caller_id
            self.flow_id = settings.exotel_flow_id
        else:
            self.settings = get_settings()
            import os
            from dotenv import load_dotenv

            load_dotenv()

            self.api_key = self.settings.exotel_api_key or os.getenv("EXOTEL_API_KEY")
            self.api_password = self.settings.exotel_api_password or os.getenv("EXOTEL_API_PASSWORD")
            self.account_sid = self.settings.exotel_account_sid or os.getenv("EXOTEL_ACCOUNT_SID")
            self.subdomain = (
                self.settings.exotel_subdomain
                or os.getenv("EXOTEL_SUBDOMAIN")
                or "api.exotel.com"
            ).strip().replace("https://", "").replace("http://", "").rstrip("/")
            self.caller_id = self.settings.exotel_caller_id or os.getenv("EXOTEL_CALLER_ID")
            self.flow_id = self.settings.exotel_flow_id or os.getenv("EXOTEL_FLOW_ID")

    @property
    def is_configured(self) -> bool:
        """True if all necessary credentials and identifiers are present."""
        return bool(self.api_key and self.api_password and self.account_sid and self.caller_id)

    def _mask_phone(self, phone: str) -> str:
        """Mask middle digits of customer phone for safe logging."""
        if len(phone) > 6:
            return f"{phone[:3]}****{phone[-3:]}"
        return "***"

    def initiate_outbound_call(
        self,
        to_phone: str,
        case_id: str,
        callback_url: str | None = None,
        custom_greeting: str | None = None,
    ) -> ExotelCallResult:
        """Initiate an outbound voice call to the customer via Exotel Connect API."""
        if not self.api_key or not self.api_password:
            return ExotelCallResult(
                success=False,
                call_id=None,
                status="CONFIG_ERROR",
                message="Exotel API credentials missing in .env (EXOTEL_API_KEY / EXOTEL_API_PASSWORD)",
                error="CREDENTIALS_MISSING",
            )

        if not self.account_sid or not self.caller_id:
            return ExotelCallResult(
                success=False,
                call_id=None,
                status="CONFIG_ERROR",
                message="Exotel Account SID or Caller ID missing in .env (EXOTEL_ACCOUNT_SID / EXOTEL_CALLER_ID)",
                error="CONFIG_INCOMPLETE",
            )

        endpoint = (
            f"https://{self.subdomain}/v1/Accounts/{self.account_sid}/Calls/connect.json"
        )

        clean_to = to_phone.strip()
        if not clean_to.startswith("+") and not clean_to.startswith("0") and len(clean_to) == 10:
            clean_to = f"0{clean_to}"

        # Standard Exotel payload
        # From: Customer's number to ring
        # CallerId: Exotel virtual number
        # Url: Flow URL to play IVR/prompt once answered
        flow_url = (
            f"http://my.exotel.com/{self.account_sid}/exoml/start_voice/{self.flow_id}"
            if self.flow_id
            else None
        )

        payload_dict: dict[str, str] = {
            "From": clean_to,
            "CallerId": self.caller_id,
            "CallType": "trans",
            "CustomField": case_id,
        }

        if flow_url:
            payload_dict["Url"] = flow_url
        else:
            # When flow_id is not yet created in Exotel, connect to CallerId directly
            payload_dict["To"] = self.caller_id

        if callback_url:
            payload_dict["StatusCallback"] = callback_url
            payload_dict["StatusCallbackEvents[0]"] = "terminal"

        encoded_data = urllib.parse.urlencode(payload_dict).encode("utf-8")

        # HTTP Basic Auth: <api_key>:<api_password>
        auth_bytes = f"{self.api_key}:{self.api_password}".encode("ascii")
        auth_header = f"Basic {base64.b64encode(auth_bytes).decode('ascii')}"

        req = urllib.request.Request(
            endpoint,
            data=encoded_data,
            headers={
                "Authorization": auth_header,
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": "RevivePay-Voice-Agent/1.0",
            },
            method="POST",
        )

        logger.info(
            "Initiating Exotel voice recovery call | case_id=%s | recipient=%s | endpoint=%s",
            case_id,
            self._mask_phone(clean_to),
            endpoint,
        )

        try:
            with urllib.request.urlopen(req, timeout=12) as response:
                status_code = response.status
                raw_body = response.read().decode("utf-8")
                data = json.loads(raw_body)

                call_obj = data.get("Call", {})
                call_sid = call_obj.get("Sid")
                call_status = (call_obj.get("Status") or "queued").upper()

                logger.info(
                    "Exotel call placed successfully | case_id=%s | call_sid=%s | status=%s",
                    case_id,
                    call_sid,
                    call_status,
                )

                return ExotelCallResult(
                    success=True,
                    call_id=call_sid,
                    status=call_status,
                    message=f"Exotel outbound voice recovery call initiated ({call_status})",
                    raw_status_code=status_code,
                )

        except urllib.error.HTTPError as err:
            err_body = err.read().decode("utf-8")
            logger.error(
                "Exotel API HTTPError | code=%s | body=%s", err.code, err_body
            )
            parsed_msg = f"Exotel error (HTTP {err.code})"
            try:
                err_data = json.loads(err_body)
                if "RestException" in err_data:
                    parsed_msg = err_data["RestException"].get("Message", parsed_msg)
            except Exception:
                pass

            return ExotelCallResult(
                success=False,
                call_id=None,
                status="PROVIDER_ERROR",
                message=parsed_msg,
                error=err_body,
                raw_status_code=err.code,
            )

        except urllib.error.URLError as err:
            logger.error("Exotel connection failure: %s", err.reason)
            return ExotelCallResult(
                success=False,
                call_id=None,
                status="NETWORK_ERROR",
                message=f"Network error connecting to Exotel: {err.reason}",
                error=str(err.reason),
            )

        except Exception as ex:
            logger.error("Unexpected error placing Exotel call: %s", ex)
            return ExotelCallResult(
                success=False,
                call_id=None,
                status="INTERNAL_ERROR",
                message=f"Unexpected error: {str(ex)}",
                error=str(ex),
            )

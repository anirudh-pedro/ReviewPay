"""Live Transactional Email Service for Payment Recovery.

Supports:
- Resend API (HTTP POST to https://api.resend.com/emails)
- SendGrid API (HTTP POST to https://api.sendgrid.com/v3/mail/send)
- Standard SMTP (Python built-in smtplib)
- Graceful mailto fallback for client-side review.
"""

from __future__ import annotations

import json
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any
import urllib.request
import urllib.error

from app.core.config import Settings, get_settings
from app.core.logging import get_logger

logger = get_logger("email_service")


class EmailDispatchResult:
    def __init__(
        self,
        success: bool,
        provider: str,
        message: str,
        recipient: str,
        message_id: str | None = None,
        error: str | None = None,
    ) -> None:
        self.success = success
        self.provider = provider
        self.message = message
        self.recipient = recipient
        self.message_id = message_id
        self.error = error

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "provider": self.provider,
            "message": self.message,
            "recipient": self.recipient,
            "message_id": self.message_id,
            "error": self.error,
        }


class EmailRecoveryService:
    """Dispatches real transactional recovery emails to interrupted customers."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        import os
        from dotenv import load_dotenv
        load_dotenv()

        if not getattr(self.settings, "resend_api_key", None):
            self.settings.resend_api_key = os.getenv("RESEND_API_KEY")
        if not getattr(self.settings, "sendgrid_api_key", None):
            self.settings.sendgrid_api_key = os.getenv("SENDGRID_API_KEY")
        if not getattr(self.settings, "smtp_password", None):
            self.settings.smtp_password = os.getenv("SMTP_PASSWORD")

    def render_recovery_html(
        self,
        customer_name: str,
        amount_formatted: str,
        failure_reason_text: str,
        recovery_url: str,
        order_id: str,
    ) -> str:
        """Render a modern, responsive HTML recovery email."""
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Complete Your Interrupted Order</title>
</head>
<body style="margin: 0; padding: 0; background-color: #f8fafc; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color: #0f172a;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #f8fafc; padding: 40px 16px;">
    <tr>
      <td align="center">
        <table width="100%" max-width="580px" cellpadding="0" cellspacing="0" style="max-width: 580px; background-color: #ffffff; border: 1px solid #e2e8f0; border-radius: 16px; overflow: hidden; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);">
          <!-- Header Banner -->
          <tr>
            <td style="background-color: #4f46e5; padding: 32px 32px 24px 32px; text-align: center;">
              <span style="display: inline-block; background-color: rgba(255, 255, 255, 0.2); color: #ffffff; font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; padding: 4px 12px; border-radius: 9999px; margin-bottom: 12px;">
                RevivePay Autonomous Recovery
              </span>
              <h1 style="color: #ffffff; margin: 0; font-size: 24px; font-weight: 800; letter-spacing: -0.02em;">
                Acme Checkout Session Preserved
              </h1>
            </td>
          </tr>

          <!-- Body Content -->
          <tr>
            <td style="padding: 32px;">
              <p style="margin: 0 0 16px 0; font-size: 15px; line-height: 24px; color: #334155;">
                Hi <strong>{customer_name}</strong>,
              </p>
              <p style="margin: 0 0 20px 0; font-size: 15px; line-height: 24px; color: #334155;">
                Your recent payment of <strong>{amount_formatted}</strong> was interrupted due to a temporary <strong>{failure_reason_text}</strong>. No funds were debited from your account.
              </p>
              
              <!-- Transaction Box -->
              <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #f1f5f9; border-radius: 12px; padding: 16px; margin-bottom: 24px;">
                <tr>
                  <td style="font-size: 13px; color: #64748b; padding: 4px 0;">Order Reference:</td>
                  <td align="right" style="font-size: 13px; font-family: monospace; font-weight: 700; color: #1e293b; padding: 4px 0;">{order_id}</td>
                </tr>
                <tr>
                  <td style="font-size: 13px; color: #64748b; padding: 4px 0;">Amount at Risk:</td>
                  <td align="right" style="font-size: 13px; font-weight: 700; color: #047857; padding: 4px 0;">{amount_formatted}</td>
                </tr>
                <tr>
                  <td style="font-size: 13px; color: #64748b; padding: 4px 0;">Checkout Session Status:</td>
                  <td align="right" style="font-size: 13px; font-weight: 700; color: #4f46e5; padding: 4px 0;">Active &amp; Reserved</td>
                </tr>
              </table>

              <p style="margin: 0 0 24px 0; font-size: 14px; line-height: 22px; color: #475569;">
                RevivePay has securely saved your shopping cart and opened an instant recovery channel. You can retry with 1-click UPI, a backup card, or alternative bank without re-entering your shipping details:
              </p>

              <!-- CTA Button -->
              <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom: 28px;">
                <tr>
                  <td align="center">
                    <a href="{recovery_url}" target="_blank" style="display: inline-block; background-color: #059669; color: #ffffff; font-size: 15px; font-weight: 700; text-decoration: none; padding: 14px 32px; border-radius: 10px; box-shadow: 0 4px 6px -1px rgba(5, 150, 105, 0.3);">
                      Complete My Payment Now &rarr;
                    </a>
                  </td>
                </tr>
              </table>

              <p style="margin: 0; font-size: 12px; line-height: 18px; color: #94a3b8; text-align: center;">
                If the button above does not work, copy and paste this secure link into your browser:<br>
                <a href="{recovery_url}" style="color: #4f46e5; word-break: break-all;">{recovery_url}</a>
              </p>
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="background-color: #f8fafc; border-top: 1px solid #e2e8f0; padding: 20px 32px; text-align: center;">
              <p style="margin: 0; font-size: 12px; color: #64748b;">
                Secured by <strong>RevivePay Autonomous Recovery Engine</strong> &bull; Bank-grade 256-bit Encryption
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""

    def send_recovery_email(
        self,
        recipient_email: str,
        customer_name: str,
        amount_formatted: str,
        failure_reason_text: str,
        recovery_url: str,
        order_id: str,
    ) -> EmailDispatchResult:
        """Dispatches real email using Resend, SendGrid, or SMTP."""
        subject = f"Finish your payment of {amount_formatted} ({order_id})"
        html_body = self.render_recovery_html(
            customer_name=customer_name,
            amount_formatted=amount_formatted,
            failure_reason_text=failure_reason_text,
            recovery_url=recovery_url,
            order_id=order_id,
        )
        plain_body = (
            f"Hi {customer_name},\n\n"
            f"Your payment of {amount_formatted} failed due to {failure_reason_text}.\n"
            f"Please complete your payment using this secure link:\n{recovery_url}\n\n"
            f"Order ID: {order_id}\n"
            f"— RevivePay Autonomous Recovery"
        )

        # 1. Try Resend API
        if self.settings.resend_api_key:
            return self._send_via_resend(recipient_email, subject, html_body, plain_body)

        # 2. Try SendGrid API
        if self.settings.sendgrid_api_key:
            return self._send_via_sendgrid(recipient_email, subject, html_body, plain_body)

        # 3. Try Standard SMTP
        if self.settings.smtp_host and self.settings.smtp_username and self.settings.smtp_password:
            return self._send_via_smtp(recipient_email, subject, html_body, plain_body)

        # If no credentials configured yet
        return EmailDispatchResult(
            success=False,
            provider="none",
            message="No live email provider configured in .env (add RESEND_API_KEY, SENDGRID_API_KEY, or SMTP credentials).",
            recipient=recipient_email,
            error="CREDENTIALS_MISSING",
        )

    def _send_via_resend(
        self, recipient: str, subject: str, html: str, text: str
    ) -> EmailDispatchResult:
        try:
            url = "https://api.resend.com/emails"
            payload = {
                "from": self.settings.email_from,
                "to": [recipient],
                "subject": subject,
                "html": html,
                "text": text,
            }
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {self.settings.resend_api_key}",
                    "Content-Type": "application/json",
                    "User-Agent": "RevivePay-Agent/1.0",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return EmailDispatchResult(
                    success=True,
                    provider="resend",
                    message=f"Live email dispatched successfully to {recipient} via Resend",
                    recipient=recipient,
                    message_id=data.get("id"),
                )
        except urllib.error.HTTPError as err:
            err_msg = err.read().decode("utf-8")
            logger.error("Resend API error: %s", err_msg)
            return EmailDispatchResult(
                success=False,
                provider="resend",
                message=f"Resend error: {err_msg}",
                recipient=recipient,
                error=err_msg,
            )
        except Exception as ex:
            logger.error("Failed to send email via Resend: %s", ex)
            return EmailDispatchResult(
                success=False,
                provider="resend",
                message=f"Connection failure: {str(ex)}",
                recipient=recipient,
                error=str(ex),
            )

    def _send_via_sendgrid(
        self, recipient: str, subject: str, html: str, text: str
    ) -> EmailDispatchResult:
        try:
            url = "https://api.sendgrid.com/v3/mail/send"
            from_email = self.settings.email_from
            if "<" in from_email:
                # Parse "Name <email@domain.com>"
                name, raw_email = from_email.split("<")
                from_obj = {"name": name.strip(), "email": raw_email.replace(">", "").strip()}
            else:
                from_obj = {"email": from_email.strip()}

            payload = {
                "personalizations": [{"to": [{"email": recipient}]}],
                "from": from_obj,
                "subject": subject,
                "content": [
                    {"type": "text/plain", "value": text},
                    {"type": "text/html", "value": html},
                ],
            }
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {self.settings.sendgrid_api_key}",
                    "Content-Type": "application/json",
                    "User-Agent": "RevivePay-Agent/1.0",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                msg_id = resp.headers.get("X-Message-Id")
                return EmailDispatchResult(
                    success=True,
                    provider="sendgrid",
                    message=f"Live email dispatched successfully to {recipient} via SendGrid",
                    recipient=recipient,
                    message_id=msg_id,
                )
        except urllib.error.HTTPError as err:
            err_msg = err.read().decode("utf-8")
            logger.error("SendGrid API error: %s", err_msg)
            return EmailDispatchResult(
                success=False,
                provider="sendgrid",
                message=f"SendGrid error: {err_msg}",
                recipient=recipient,
                error=err_msg,
            )
        except Exception as ex:
            logger.error("Failed to send email via SendGrid: %s", ex)
            return EmailDispatchResult(
                success=False,
                provider="sendgrid",
                message=f"Connection failure: {str(ex)}",
                recipient=recipient,
                error=str(ex),
            )

    def _send_via_smtp(
        self, recipient: str, subject: str, html: str, text: str
    ) -> EmailDispatchResult:
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = self.settings.email_from
            msg["To"] = recipient

            part1 = MIMEText(text, "plain", "utf-8")
            part2 = MIMEText(html, "html", "utf-8")
            msg.attach(part1)
            msg.attach(part2)

            port = self.settings.smtp_port or 587
            host = self.settings.smtp_host or "smtp.gmail.com"

            if port == 465:
                server = smtplib.SMTP_SSL(host, port, timeout=10)
            else:
                server = smtplib.SMTP(host, port, timeout=10)
                server.starttls()

            server.login(self.settings.smtp_username, self.settings.smtp_password)
            server.sendmail(self.settings.email_from, [recipient], msg.as_string())
            server.quit()

            return EmailDispatchResult(
                success=True,
                provider="smtp",
                message=f"Live email dispatched successfully to {recipient} via SMTP",
                recipient=recipient,
            )
        except Exception as ex:
            logger.error("SMTP dispatch failed: %s", ex)
            return EmailDispatchResult(
                success=False,
                provider="smtp",
                message=f"SMTP error: {str(ex)}",
                recipient=recipient,
                error=str(ex),
            )

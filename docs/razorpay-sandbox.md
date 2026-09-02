# Razorpay Sandbox gateway

RevivePay's Razorpay integration is an **opt-in Sandbox checkout path**, separate from the deterministic payment simulator and scenarios A–D. It uses the backend to create an order, verifies Checkout's HMAC on the server, retrieves the provider order/payment state before changing local data, and verifies signed webhooks over their raw request bytes.

## Local configuration

Keep these values in the ignored `.env` file or a deployment secret manager; never commit them:

```dotenv
RAZORPAY_ENABLED=true
RAZORPAY_KEY_ID=rzp_test_...
RAZORPAY_KEY_SECRET=...
RAZORPAY_WEBHOOK_SECRET=...
```

`RAZORPAY_WEBHOOK_SECRET` is a separate secret configured for the webhook in the Razorpay dashboard. Register the endpoint as:

```text
https://your-public-host/api/gateway/razorpay/webhooks
```

Use a test-mode key ID only. The application refuses to enable Checkout unless its key ID and key secret are configured; the webhook endpoint separately requires its own webhook secret.

## Working flow

1. Open **Live Gateway Demo** and create an INR-minor-unit Sandbox order.
2. The server returns only the Razorpay public key ID, order ID, amount, and a local non-synthetic payment ID.
3. Checkout returns its callback fields to the browser; the browser posts them to `/api/gateway/razorpay/verify`.
4. The server validates the Checkout HMAC and retrieves both the provider order and payment before persisting a safe provider summary.
5. Razorpay webhooks are independently HMAC-verified from raw bytes, recorded in a digest-only inbound-event ledger, and deduplicated.
6. Verified failed or abandoned payments create/reuse ordinary recovery cases through `RiskDetector`; they then use the unchanged policy-gated recovery workflow.

Only provider/order/payment IDs, status, normalized failure reason, and non-sensitive error code are persisted in the attempt summary. Raw webhook bodies, callback data, customer contacts, and instrument information are not retained.

## Deliberate boundary

The current `RevenueRecoveryWorkflow` is synchronous and keeps the simulator executor as its default. Browser Checkout is asynchronous, so it is **not** represented as a recovery action and it does not write a `RecoveryOutcome`. A future live recovery executor needs an explicit awaiting-external-settlement workflow state before it can safely drive Checkout-based recovery.

## Validation

```powershell
.\.venv\Scripts\python.exe -m pytest -q --tb=line
npm run typecheck
npm run build
.\.venv\Scripts\python.exe -m alembic upgrade head
```

The test suite uses injected fake Razorpay responses and signed webhook fixtures; it makes no live provider calls.

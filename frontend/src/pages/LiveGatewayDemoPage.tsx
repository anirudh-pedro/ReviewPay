import { useState } from 'react';
import { Link } from 'react-router-dom';
import { CreditCard, ExternalLink, ShieldCheck } from 'lucide-react';
import { createRazorpayOrder, verifyRazorpayCheckout } from '@/api';
import type { RazorpayVerificationResponse } from '@/types/api';
import { ApiError } from '@/api/client';
import { Accordion, Button, Card, CardHeader, ErrorState, StatusBadge } from '@/components/ui';
import { formatMoney, humanize } from '@/utils/format';

interface RazorpayCheckoutResponse {
  razorpay_payment_id: string;
  razorpay_order_id: string;
  razorpay_signature: string;
}

interface RazorpayCheckoutInstance {
  open: () => void;
}

interface RazorpayConstructor {
  new (options: {
    key: string;
    amount: number;
    currency: string;
    name: string;
    description: string;
    order_id: string;
    handler: (response: RazorpayCheckoutResponse) => void;
    modal: { ondismiss: () => void };
    theme: { color: string };
  }): RazorpayCheckoutInstance;
}

declare global {
  interface Window {
    Razorpay?: RazorpayConstructor;
  }
}

let checkoutScript: Promise<void> | null = null;

function loadRazorpayCheckout(): Promise<void> {
  if (window.Razorpay) return Promise.resolve();
  if (checkoutScript) return checkoutScript;

  checkoutScript = new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = 'https://checkout.razorpay.com/v1/checkout.js';
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error('Razorpay Checkout could not be loaded.'));
    document.head.appendChild(script);
  });
  return checkoutScript;
}

function idempotencyKey(): string {
  return globalThis.crypto?.randomUUID?.() ?? `gateway-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export function LiveGatewayDemoPage() {
  const [amount, setAmount] = useState('10000');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('Create a Sandbox order to begin.');
  const [error, setError] = useState<Error | null>(null);
  const [verified, setVerified] = useState<RazorpayVerificationResponse | null>(null);

  async function verify(response: RazorpayCheckoutResponse) {
    setBusy(true);
    setError(null);
    setMessage('Checkout callback received. Verifying signature & provider state on server...');
    try {
      const result = await verifyRazorpayCheckout(response);
      setVerified(result);
      setMessage(
        result.payment.status === 'SUCCEEDED'
          ? 'Server verification confirmed Razorpay Sandbox captured state.'
          : `Server verification recorded provider status ${result.verified_provider_status}.`,
      );
    } catch (cause) {
      setError(cause instanceof Error ? cause : new Error('Server-side verification failed.'));
      setMessage('The browser callback was not treated as payment success.');
    } finally {
      setBusy(false);
    }
  }

  async function openCheckout() {
    const minorUnits = Number(amount);
    if (!Number.isInteger(minorUnits) || minorUnits <= 0) {
      setError(new Error('Enter a positive whole number of paise (INR minor units).'));
      return;
    }

    setBusy(true);
    setError(null);
    setVerified(null);
    setMessage('Creating an idempotent Razorpay Sandbox order on server...');
    try {
      const order = await createRazorpayOrder({ amount: minorUnits, currency: 'INR' }, idempotencyKey());
      setMessage('Loading Razorpay Checkout. No secret is present in this browser.');
      await loadRazorpayCheckout();
      if (!window.Razorpay) throw new Error('Razorpay Checkout loaded without API.');

      const checkout = new window.Razorpay({
        key: order.key_id,
        amount: order.money.amount,
        currency: order.money.currency,
        name: 'RevivePay',
        description: 'REAL RAZORPAY SANDBOX — isolated gateway demo',
        order_id: order.order_id,
        handler: (response) => { void verify(response); },
        modal: {
          ondismiss: () => {
            setBusy(false);
            setMessage('Checkout was dismissed. No browser result was persisted.');
          },
        },
        theme: { color: '#38bdf8' },
      });
      setBusy(false);
      setMessage('Razorpay Sandbox Checkout is open.');
      checkout.open();
    } catch (cause) {
      setBusy(false);
      setError(cause instanceof Error ? cause : new Error('Unable to start Razorpay Sandbox Checkout.'));
    }
  }

  return (
    <div className="space-y-6">
      {/* Banner */}
      <Card className="p-6 border-amber-500/30 bg-amber-500/10">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <div className="flex items-center gap-2">
              <StatusBadge tone="warning">REAL RAZORPAY SANDBOX</StatusBadge>
              <StatusBadge tone="neutral">HMAC VERIFIED GATEWAY</StatusBadge>
            </div>
            <h1 className="mt-2 text-2xl font-bold text-slate-50">Razorpay Sandbox Gateway</h1>
            <p className="mt-1 text-sm text-slate-300">
              Create live test orders via Razorpay Checkout. Server creates orders and verifies HMAC signatures.
            </p>
          </div>
          <a
            className="inline-flex items-center gap-1 text-xs font-semibold text-amber-300 hover:text-amber-200"
            href="https://razorpay.com/docs/payments/"
            rel="noreferrer"
            target="_blank"
          >
            Razorpay Docs <ExternalLink aria-hidden="true" className="size-3.5" />
          </a>
        </div>
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        {/* Start Checkout */}
        <Card className="p-6">
          <CardHeader className="px-0 pt-0 mb-4">
            <div>
              <h2 className="text-base font-semibold text-slate-100">Start Sandbox Order</h2>
              <p className="text-xs text-slate-400">Order created server-side in INR paise minor units</p>
            </div>
            <CreditCard className="size-5 text-amber-400" />
          </CardHeader>

          <div className="space-y-4">
            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1">Amount (paise)</label>
              <input
                className="h-10 w-full rounded-lg border border-white/10 bg-slate-900 px-3 font-mono text-sm text-slate-100 outline-none focus:border-amber-400"
                min="1"
                type="number"
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
              />
              <p className="mt-1 text-xs text-slate-400">
                Preview: {Number.isFinite(Number(amount)) ? formatMoney(Number(amount), true) : '0'} INR
              </p>
            </div>

            <Button className="w-full" loading={busy} onClick={() => void openCheckout()}>
              <CreditCard aria-hidden="true" className="size-4" /> Open Razorpay Sandbox Checkout
            </Button>
          </div>
        </Card>

        {/* Verification Boundary */}
        <Card className="p-6 border-sky-500/20 bg-sky-500/5">
          <CardHeader className="px-0 pt-0 mb-4">
            <div>
              <h2 className="text-base font-semibold text-slate-100">Server Verification Boundary</h2>
              <p className="text-xs text-slate-400">Server re-reads provider payment state after HMAC verification</p>
            </div>
            <ShieldCheck className="size-5 text-sky-400" />
          </CardHeader>

          <div className="space-y-4">
            <div className="rounded-lg border border-white/10 bg-black/40 p-3 text-xs text-slate-300">
              {message}
            </div>

            {verified ? (
              <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 p-4">
                <p className="font-semibold text-emerald-300">
                  Verified Status: {humanize(verified.verified_provider_status)}
                </p>
                <p className="mt-1 text-xs text-slate-300">
                  Local payment {verified.payment.payment_id} is {humanize(verified.payment.status)} with {verified.payment.attempt_count} attempt(s).
                </p>
                {verified.recovery_case_id ? (
                  <Link
                    className="mt-3 inline-block text-xs font-semibold text-sky-300 hover:text-sky-200"
                    to={`/cases/${verified.recovery_case_id}`}
                  >
                    Open Recovery Case →
                  </Link>
                ) : null}
              </div>
            ) : null}

            {error ? <ErrorState compact error={error instanceof ApiError ? error : error.message} /> : null}
          </div>
        </Card>
      </div>

      <Accordion title="View Gateway Architecture Details">
        <p className="text-xs text-slate-400 leading-relaxed">
          All recovery execution remains deterministic and simulator-backed. A verified gateway failure enters the same Risk Detector and case queue. Configure a distinct Razorpay webhook secret before enabling the gateway in production.
        </p>
      </Accordion>
    </div>
  );
}

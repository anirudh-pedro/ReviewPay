import { useState } from 'react';
import { Link } from 'react-router-dom';
import { AlertTriangle, CheckCircle2, CreditCard, ExternalLink, ShieldCheck } from 'lucide-react';
import { createRazorpayOrder, verifyRazorpayCheckout } from '@/api';
import type { RazorpayVerificationResponse } from '@/types/api';
import { ApiError } from '@/api/client';
import { Button, Card, CardHeader, ErrorState, StatusBadge } from '@/components/ui';
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
    setMessage('Checkout callback received. Verifying the signature and authoritative provider state on the server…');
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
      setMessage('The browser callback was not treated as payment success. Check the server verification error.');
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
    setMessage('Creating an idempotent Razorpay Sandbox order on the server…');
    try {
      const order = await createRazorpayOrder({ amount: minorUnits, currency: 'INR' }, idempotencyKey());
      setMessage('Loading Razorpay Checkout. No secret is present in this browser.');
      await loadRazorpayCheckout();
      if (!window.Razorpay) throw new Error('Razorpay Checkout loaded without its expected API.');

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
            setMessage('Checkout was dismissed. No browser result was persisted; a signed provider webhook remains authoritative.');
          },
        },
        theme: { color: '#38bdf8' },
      });
      setBusy(false);
      setMessage('Razorpay Sandbox Checkout is open. The browser callback will still be verified by the server.');
      checkout.open();
    } catch (cause) {
      setBusy(false);
      setError(cause instanceof Error ? cause : new Error('Unable to start Razorpay Sandbox Checkout.'));
    }
  }

  return (
    <div className="space-y-6">
      <Card className="overflow-hidden border-amber-300/30 bg-amber-300/[0.045] p-5 sm:p-6">
        <div className="flex flex-col gap-5 xl:flex-row xl:items-end xl:justify-between">
          <div className="max-w-3xl">
            <div className="flex flex-wrap items-center gap-2"><StatusBadge tone="warning">REAL RAZORPAY SANDBOX</StatusBadge><StatusBadge tone="neutral">Separate from simulator</StatusBadge></div>
            <div className="mt-4 flex items-start gap-3"><span className="grid size-10 shrink-0 place-items-center rounded-xl border border-amber-300/25 bg-amber-300/10 text-amber-200"><CreditCard aria-hidden="true" className="size-5" /></span><div><h1 className="text-xl font-semibold tracking-tight text-slate-50 sm:text-2xl">Live Gateway Demo</h1><p className="mt-2 text-sm leading-6 text-slate-300">This page opens Razorpay’s test Checkout with a server-created Sandbox order. It does not modify deterministic scenarios A–D, Autopilot, Strategy Lab, the virtual clock, or the simulator executor.</p></div></div>
          </div>
          <a className="inline-flex items-center gap-1.5 text-xs font-semibold text-amber-200 hover:text-amber-100" href="https://razorpay.com/docs/payments/" rel="noreferrer" target="_blank">Razorpay Sandbox docs <ExternalLink aria-hidden="true" className="size-3.5" /></a>
        </div>
      </Card>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,0.95fr)_minmax(0,1.05fr)]">
        <Card>
          <CardHeader><div><p className="text-sm font-semibold text-slate-100">Start Sandbox Checkout</p><p className="mt-1 text-xs leading-5 text-slate-500">Amount is sent exactly as INR minor units (paise). The public key and provider order ID come from the server; no secret reaches this page.</p></div><ShieldCheck aria-hidden="true" className="size-5 text-accent" /></CardHeader>
          <div className="p-5 pt-4"><label className="block"><span className="text-[0.64rem] font-semibold uppercase tracking-[0.12em] text-slate-500">Amount (paise)</span><input className="mt-2 h-11 w-full rounded-lg border border-white/[0.08] bg-ink-900 px-3 font-mono text-sm text-slate-100 outline-none focus:border-accent focus:ring-2 focus:ring-accent/20" inputMode="numeric" min="1" type="number" value={amount} onChange={(event) => setAmount(event.target.value)} /></label><p className="mt-2 text-xs text-slate-500">Preview: {Number.isFinite(Number(amount)) ? formatMoney(Number(amount), true) : '—'} INR</p><Button className="mt-5 w-full" loading={busy} onClick={() => void openCheckout()}><CreditCard aria-hidden="true" className="size-4" />Open Razorpay Sandbox Checkout</Button></div>
        </Card>

        <Card className="border-accent/20 bg-accent/[0.025]">
          <CardHeader><div><p className="text-sm font-semibold text-slate-100">Server-verification boundary</p><p className="mt-1 text-xs leading-5 text-slate-500">A browser callback is provisional. RevivePay verifies its HMAC, retrieves the provider payment and order state, persists only an allowlisted summary, and opens/reuses recovery cases only for verified at-risk outcomes.</p></div><CheckCircle2 aria-hidden="true" className="size-5 text-accent" /></CardHeader>
          <div className="p-5 pt-4"><p aria-live="polite" className="rounded-lg border border-white/[0.06] bg-ink-900/60 p-3 text-sm leading-6 text-slate-300">{message}</p>{verified ? <div className="mt-4 rounded-lg border border-recovered/25 bg-recovered/[0.06] p-4"><p className="font-semibold text-green-200">Verified provider status: {humanize(verified.verified_provider_status)}</p><p className="mt-2 text-xs leading-5 text-slate-400">Local payment {verified.payment.payment_id} is {humanize(verified.payment.status)} with {verified.payment.attempt_count} persisted attempt(s).</p>{verified.recovery_case_id ? <Link className="mt-3 inline-flex text-xs font-semibold text-sky-300 hover:text-sky-200" to={`/cases/${verified.recovery_case_id}`}>Open the normal policy-gated recovery case →</Link> : null}</div> : null}{error ? <div className="mt-4"><ErrorState compact error={error instanceof ApiError ? error : error.message} title="Sandbox checkout did not complete" /></div> : null}</div>
        </Card>
      </div>

      <Card className="border-white/[0.06] p-5"><div className="flex items-start gap-3"><AlertTriangle aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-amber-300" /><div><p className="text-sm font-semibold text-slate-100">What remains simulated</p><p className="mt-1 text-xs leading-5 text-slate-400">All recovery execution remains deterministic and simulator-backed. A verified gateway failure enters the same Risk Detector and case queue, but this page does not turn asynchronous Checkout into a synchronous recovery action or claim a RecoveryOutcome. Configure a distinct Razorpay webhook secret before enabling the gateway, then register <code className="font-mono text-sky-300">/api/gateway/razorpay/webhooks</code> in Razorpay.</p></div></div></Card>
    </div>
  );
}

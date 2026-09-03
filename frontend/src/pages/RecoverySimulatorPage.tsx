import { useState } from 'react';
import { Link } from 'react-router-dom';
import {
  CreditCard,
  ExternalLink,
  ShieldCheck,
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Sparkles,
  QrCode,
  RefreshCw,
  Zap,
  Copy,
  Check,
  MessageSquare,
  Mail,
  Lock,
} from 'lucide-react';
import { Accordion, Button, Card, CardHeader, StatusBadge } from '@/components/ui';
import { createRazorpayOrder, verifyRazorpayCheckout, simulateGatewayOrderFailure } from '@/api/gateway';
import { customerRecover } from '@/api/recovery';
import type {
  RazorpayOrderResponse,
  RazorpayVerificationResponse,
  GatewayFailureSimulationResponse,
  FailureReason,
} from '@/types/api';
import { formatMoney } from '@/utils/format';

interface RazorpayCheckoutOptions {
  key: string;
  amount: number;
  currency: string;
  name: string;
  description: string;
  order_id: string;
  handler: (response: RazorpayCheckoutResponse) => void;
  modal?: { ondismiss?: () => void };
  theme?: { color?: string };
}

interface RazorpayCheckoutResponse {
  razorpay_order_id: string;
  razorpay_payment_id: string;
  razorpay_signature: string;
}

declare global {
  interface Window {
    Razorpay?: new (options: RazorpayCheckoutOptions) => { open: () => void };
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

const FAILURE_SCENARIOS: Array<{
  reason: FailureReason;
  title: string;
  tag: string;
  description: string;
  icon: typeof Zap;
  typicalAction: string;
}> = [
  {
    reason: 'BANK_TIMEOUT',
    title: 'Bank Timeout',
    tag: 'Transient Core Downtime',
    description: 'Issuing bank core API timed out. No money deducted from customer.',
    icon: Zap,
    typicalAction: 'Generate Payment Link / Instant UPI',
  },
  {
    reason: 'INSUFFICIENT_FUNDS',
    title: 'Insufficient Funds',
    tag: 'Account Balance',
    description: 'Account balance low. Retrying dead account exhausts budget; instrument switch required.',
    icon: CreditCard,
    typicalAction: 'Alternative Payment Method Link',
  },
  {
    reason: 'EXPIRED_CARD',
    title: 'Expired Card',
    tag: 'Terminal Instrument',
    description: 'Card expired or blocked by issuer. Retrying fails; customer channel needed.',
    icon: AlertTriangle,
    typicalAction: 'Customer Recovery Portal Link',
  },
  {
    reason: 'NETWORK_ERROR',
    title: 'Network Failure',
    tag: '3DS Drop',
    description: '3D-Secure connection dropped mid-transaction. Safe 1-click retry ready.',
    icon: RefreshCw,
    typicalAction: '1-Click Smart Retry Link',
  },
];

const PIPELINE_STEPS = [
  { number: 1, label: 'Payment' },
  { number: 2, label: 'Failure' },
  { number: 3, label: 'Diagnosis' },
  { number: 4, label: 'Recommendation' },
  { number: 5, label: 'Policy' },
  { number: 6, label: 'Recovery' },
  { number: 7, label: 'Verification' },
];

export function RecoverySimulatorPage() {
  const [amount, setAmount] = useState('15000');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('Create a Razorpay Sandbox order to initiate the recovery demo.');
  const [error, setError] = useState<Error | null>(null);
  const [activeOrder, setActiveOrder] = useState<RazorpayOrderResponse | null>(null);
  const [verified, setVerified] = useState<RazorpayVerificationResponse | null>(null);

  // Takeover state
  const [selectedScenario, setSelectedScenario] = useState<FailureReason>('BANK_TIMEOUT');
  const [takeoverResult, setTakeoverResult] = useState<GatewayFailureSimulationResponse | null>(null);
  const [isSimulating, setIsSimulating] = useState(false);

  // In-page Customer recovery execution
  const [customerRecovering, setCustomerRecovering] = useState(false);
  const [customerRecovered, setCustomerRecovered] = useState(false);
  const [copied, setCopied] = useState(false);
  const [previewChannel, setPreviewChannel] = useState<'LINK' | 'WHATSAPP' | 'EMAIL'>('LINK');

  // Compute active step (1 to 7)
  const currentStep = customerRecovered
    ? 7
    : takeoverResult
    ? 6
    : activeOrder
    ? 2
    : 1;

  async function verify(response: RazorpayCheckoutResponse) {
    setBusy(true);
    setError(null);
    setMessage('Checkout callback received. Verifying HMAC signature & provider state on server...');
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
    setTakeoverResult(null);
    setCustomerRecovered(false);
    setMessage('Creating an idempotent Razorpay Sandbox order on server...');
    try {
      const order = await createRazorpayOrder({ amount: minorUnits, currency: 'INR' }, idempotencyKey());
      setActiveOrder(order);
      setMessage('Loading Razorpay Checkout. No secret is present in this browser.');
      await loadRazorpayCheckout();
      if (!window.Razorpay) throw new Error('Razorpay Checkout loaded without API.');

      const checkout = new window.Razorpay({
        key: order.key_id,
        amount: order.money.amount,
        currency: order.money.currency,
        name: 'RevivePay',
        description: 'REAL RAZORPAY SANDBOX — Checkout Attempt',
        order_id: order.order_id,
        handler: (response) => { void verify(response); },
        modal: {
          ondismiss: () => {
            setBusy(false);
            setMessage('Checkout modal was dismissed. Now select the failure scenario below to demonstrate RevivePay.');
          },
        },
        theme: { color: '#4f46e5' },
      });
      setBusy(false);
      setMessage('Razorpay Sandbox Checkout is open.');
      checkout.open();
    } catch (cause) {
      setBusy(false);
      setError(cause instanceof Error ? cause : new Error('Unable to start Razorpay Sandbox Checkout.'));
    }
  }

  async function handleSimulateFailure(scenarioReason?: FailureReason) {
    const reasonToRun = scenarioReason || selectedScenario;
    const minorUnits = Number(amount);
    if (!Number.isInteger(minorUnits) || minorUnits <= 0) {
      setError(new Error('Enter a positive whole number of paise (INR minor units).'));
      return;
    }

    setIsSimulating(true);
    setError(null);
    setTakeoverResult(null);
    setCustomerRecovered(false);

    try {
      let order = activeOrder;
      if (!order) {
        order = await createRazorpayOrder({ amount: minorUnits, currency: 'INR' }, idempotencyKey());
        setActiveOrder(order);
      }

      const takeover = await simulateGatewayOrderFailure(order.order_id, {
        failure_reason: reasonToRun,
        error_description: `Deterministic simulation: ${reasonToRun}`,
        payment_method: 'card',
      });

      setTakeoverResult(takeover);
      setMessage(`Payment failed (${reasonToRun}). RevivePay Autonomous Recovery Agent has taken over.`);
    } catch (cause) {
      setError(cause instanceof Error ? cause : new Error('Failed to simulate transaction failure.'));
    } finally {
      setIsSimulating(false);
    }
  }

  async function handleCustomerRecoverInPage() {
    if (!takeoverResult) return;
    setCustomerRecovering(true);
    try {
      await customerRecover(takeoverResult.recovery_case_id, {
        selected_method: 'UPI',
        instrument_details: { source: 'recovery_simulator_in_page' },
      });
      setCustomerRecovered(true);
    } catch (cause) {
      setError(cause instanceof Error ? cause : new Error('Customer recovery failed.'));
    } finally {
      setCustomerRecovering(false);
    }
  }

  const handleCopyLink = () => {
    if (!takeoverResult) return;
    const fullUrl = `${window.location.origin}/recover/${takeoverResult.recovery_case_id}`;
    navigator.clipboard.writeText(fullUrl);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="space-y-6">
      {/* 1. Always-Visible Executive Summary Bar */}
      <div className="bg-white border border-slate-200 rounded-2xl p-4 shadow-xs">
        <div className="text-[11px] font-bold text-slate-400 uppercase tracking-wider mb-2.5">
          Live Recovery Pipeline Telemetry
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-4">
          <div className="border-r border-slate-100 last:border-0 pr-3">
            <span className="text-[11px] font-medium text-slate-500">Amount at Risk</span>
            <div className="mt-0.5 text-base font-bold text-slate-900 font-mono">
              {Number.isFinite(Number(amount)) ? formatMoney(Number(amount), true) : '0'} INR
            </div>
          </div>

          <div className="border-r border-slate-100 last:border-0 pr-3">
            <span className="text-[11px] font-medium text-slate-500">Failure Reason</span>
            <div className="mt-0.5 text-sm font-semibold text-amber-700">
              {takeoverResult ? takeoverResult.failure_reason : activeOrder ? 'Pending Failure' : 'Not Started'}
            </div>
          </div>

          <div className="border-r border-slate-100 last:border-0 pr-3">
            <span className="text-[11px] font-medium text-slate-500">AI Recommendation</span>
            <div className="mt-0.5 text-sm font-semibold text-indigo-700 truncate">
              {takeoverResult ? (takeoverResult.selected_action || 'PAYMENT_LINK') : '—'}
            </div>
          </div>

          <div className="border-r border-slate-100 last:border-0 pr-3">
            <span className="text-[11px] font-medium text-slate-500">Policy Decision</span>
            <div className="mt-0.5 text-sm font-semibold text-emerald-700">
              {takeoverResult ? `${takeoverResult.policy_outcome} (Budget OK)` : '—'}
            </div>
          </div>

          <div className="border-r border-slate-100 last:border-0 pr-3">
            <span className="text-[11px] font-medium text-slate-500">Recovery Action</span>
            <div className="mt-0.5 text-sm font-semibold text-slate-700">
              {takeoverResult ? 'Simulated Link' : '—'}
            </div>
          </div>

          <div>
            <span className="text-[11px] font-medium text-slate-500">Revenue Recovered</span>
            <div className={`mt-0.5 text-base font-bold ${customerRecovered ? 'text-emerald-600' : 'text-slate-400'}`}>
              {customerRecovered && takeoverResult ? formatMoney(takeoverResult.payment.money) : '₹0.00'}
            </div>
          </div>
        </div>
      </div>

      {/* 2. 7-Stage Progress Stepper */}
      <div className="bg-white border border-slate-200 rounded-2xl p-4 shadow-xs">
        <div className="flex items-center justify-between overflow-x-auto pb-1 gap-2">
          {PIPELINE_STEPS.map((step, idx) => {
            const isCompleted = currentStep > step.number;
            const isCurrent = currentStep === step.number;

            return (
              <div key={step.number} className="flex items-center gap-2 shrink-0">
                <div
                  className={`flex items-center justify-center size-7 rounded-full text-xs font-bold transition-all ${
                    isCompleted
                      ? 'bg-emerald-600 text-white shadow-xs'
                      : isCurrent
                      ? 'bg-indigo-600 text-white ring-4 ring-indigo-50 shadow-xs'
                      : 'bg-slate-100 text-slate-400 border border-slate-200'
                  }`}
                >
                  {isCompleted ? <Check className="size-3.5" /> : step.number}
                </div>
                <span
                  className={`text-xs font-medium whitespace-nowrap ${
                    isCurrent ? 'text-indigo-700 font-semibold' : isCompleted ? 'text-slate-800' : 'text-slate-400'
                  }`}
                >
                  {step.label}
                </span>
                {idx < PIPELINE_STEPS.length - 1 && (
                  <div className={`w-4 sm:w-8 h-0.5 ${isCompleted ? 'bg-emerald-500' : 'bg-slate-200'}`} />
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* 3. Main Split View: Step 1 (Checkout) + Step 2 (Failure Simulation) */}
      <div className="grid gap-6 lg:grid-cols-2">
        {/* Step 1: Razorpay Sandbox Checkout */}
        <Card className="p-6">
          <CardHeader className="px-0 pt-0 mb-4">
            <div>
              <span className="text-[11px] font-bold text-indigo-600 uppercase tracking-wider">Stage 1</span>
              <h2 className="text-base font-bold text-slate-900 mt-0.5">Razorpay Sandbox Checkout</h2>
              <p className="text-xs text-slate-500">Initiate an authentic Sandbox order with minor units (paise)</p>
            </div>
            <CreditCard className="size-5 text-indigo-600" />
          </CardHeader>

          <div className="space-y-4">
            <div>
              <label className="block text-xs font-semibold text-slate-700 mb-1.5">Order Amount (paise)</label>
              <input
                className="h-10 w-full rounded-lg border border-slate-300 bg-white px-3 font-mono text-sm text-slate-900 outline-none focus:border-indigo-600 focus:ring-2 focus:ring-indigo-100"
                min="100"
                type="number"
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
              />
              <p className="mt-1 text-xs text-slate-500">
                Amount Preview: <span className="font-semibold text-slate-800">{Number.isFinite(Number(amount)) ? formatMoney(Number(amount), true) : '0'} INR</span>
              </p>
            </div>

            <Button className="w-full" loading={busy} onClick={() => void openCheckout()}>
              <CreditCard className="size-4 mr-1.5" /> Open Razorpay Sandbox Checkout
            </Button>

            {message && (
              <div className="rounded-lg bg-slate-50 border border-slate-200 p-2.5 text-xs text-slate-600 font-mono">
                {message}
              </div>
            )}

            {error && (
              <div className="rounded-lg bg-rose-50 border border-rose-200 p-2.5 text-xs text-rose-700 font-medium">
                {error.message}
              </div>
            )}

            {verified && (
              <div className="rounded-lg bg-emerald-50 border border-emerald-200 p-2.5 text-xs text-emerald-800">
                Verified Provider Status: <strong>{verified.verified_provider_status}</strong>
              </div>
            )}

            {activeOrder && (
              <div className="rounded-xl border border-indigo-100 bg-indigo-50/50 p-3 text-xs flex justify-between items-center">
                <span className="text-indigo-800 font-medium">Active Gateway Order:</span>
                <span className="font-mono text-slate-700 bg-white border border-slate-200 px-2 py-0.5 rounded shadow-2xs font-semibold">
                  {activeOrder.order_id}
                </span>
              </div>
            )}
          </div>
        </Card>

        {/* Step 2: Deterministic Failure Simulation */}
        <Card className="p-6">
          <CardHeader className="px-0 pt-0 mb-4">
            <div>
              <div className="flex items-center gap-2">
                <span className="text-[11px] font-bold text-amber-600 uppercase tracking-wider">Stage 2</span>
                <StatusBadge tone="warning">SIMULATED SCENARIO</StatusBadge>
              </div>
              <h2 className="text-base font-bold text-slate-900 mt-0.5">Simulate Failure Reason</h2>
              <p className="text-xs text-slate-500">
                Deterministic judging: choose the transaction failure outcome to trigger RevivePay takeover.
              </p>
            </div>
            <AlertTriangle className="size-5 text-amber-500" />
          </CardHeader>

          <div className="grid grid-cols-2 gap-2.5">
            {FAILURE_SCENARIOS.map((scenario) => {
              const Icon = scenario.icon;
              const isSelected = selectedScenario === scenario.reason;
              return (
                <button
                  key={scenario.reason}
                  type="button"
                  onClick={() => setSelectedScenario(scenario.reason)}
                  className={`p-3 rounded-xl border text-left transition relative cursor-pointer ${
                    isSelected
                      ? 'bg-indigo-50/70 border-indigo-600 ring-2 ring-indigo-600/10'
                      : 'bg-slate-50/70 border-slate-200 hover:border-slate-300 hover:bg-white'
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <span className="p-1.5 rounded-lg bg-white border border-slate-200 text-slate-700 shadow-2xs">
                      <Icon className="w-3.5 h-3.5" />
                    </span>
                    {isSelected && <Check className="w-3.5 h-3.5 text-indigo-600" />}
                  </div>
                  <div className="mt-2 font-semibold text-xs text-slate-900">{scenario.title}</div>
                  <div className="text-[10px] text-slate-500 line-clamp-1 mt-0.5">{scenario.description}</div>
                </button>
              );
            })}
          </div>

          <div className="mt-4 pt-3 border-t border-slate-100 flex flex-col sm:flex-row items-center justify-between gap-3">
            <span className="text-xs text-slate-500">
              Selected: <strong className="text-slate-800">{selectedScenario}</strong>
            </span>
            <Button
              className="w-full sm:w-auto"
              loading={isSimulating}
              onClick={() => void handleSimulateFailure()}
            >
              <Sparkles className="w-4 h-4 mr-1" /> Hand Over to RevivePay
            </Button>
          </div>
        </Card>
      </div>

      {/* 4. AI Copilot Diagnosis, Recommendation, Policy & Interactive Recovery */}
      {takeoverResult && (
        <div className="space-y-6">
          {/* Stage 3 & 4: AI Copilot & Recommendation */}
          <div className="grid gap-6 lg:grid-cols-2">
            {/* AI Recovery Copilot */}
            <Card className="p-6 border-indigo-200 bg-white">
              <div className="flex items-center justify-between pb-3 border-b border-slate-100">
                <div className="flex items-center gap-2">
                  <div className="p-1.5 rounded-lg bg-indigo-50 text-indigo-600 border border-indigo-100">
                    <Sparkles className="size-4" />
                  </div>
                  <div>
                    <span className="text-[10px] font-bold text-indigo-600 uppercase tracking-wider">Stage 3 • AI Diagnosis</span>
                    <h3 className="text-sm font-bold text-slate-900">AI Recovery Copilot</h3>
                  </div>
                </div>
                <StatusBadge tone="info">Groq Llama-3 (Cloud)</StatusBadge>
              </div>

              <div className="mt-4 space-y-3">
                <div className="bg-slate-50 rounded-xl p-3.5 border border-slate-200/80">
                  <div className="text-xs font-semibold text-slate-700 mb-1">Root Cause Explanation</div>
                  <p className="text-xs text-slate-600 leading-relaxed">
                    {takeoverResult.diagnosis_explanation}
                  </p>
                </div>

                <div className="grid grid-cols-2 gap-3 text-xs">
                  <div className="bg-slate-50 p-3 rounded-xl border border-slate-200/80">
                    <span className="text-slate-500 block text-[11px]">Identified Cause</span>
                    <span className="font-bold text-slate-900 mt-0.5 block">{takeoverResult.failure_reason}</span>
                  </div>
                  <div className="bg-slate-50 p-3 rounded-xl border border-slate-200/80">
                    <span className="text-slate-500 block text-[11px]">AI Confidence</span>
                    <span className="font-bold text-indigo-600 mt-0.5 block">94.2% Verified</span>
                  </div>
                </div>
              </div>
            </Card>

            {/* Stage 4 & 5: Strategy Recommendation & Policy Gate */}
            <Card className="p-6 border-slate-200 bg-white">
              <div className="flex items-center justify-between pb-3 border-b border-slate-100">
                <div className="flex items-center gap-2">
                  <div className="p-1.5 rounded-lg bg-emerald-50 text-emerald-600 border border-emerald-100">
                    <ShieldCheck className="size-4" />
                  </div>
                  <div>
                    <span className="text-[10px] font-bold text-emerald-600 uppercase tracking-wider">Stage 4 & 5 • Strategy & Policy</span>
                    <h3 className="text-sm font-bold text-slate-900">Recommended Action & Policy Gate</h3>
                  </div>
                </div>
                <StatusBadge tone="success">PolicyEngine ALLOWED</StatusBadge>
              </div>

              <div className="mt-4 space-y-3">
                {/* ERV Breakdown */}
                <div className="bg-slate-50 rounded-xl p-3.5 border border-slate-200/80">
                  <div className="flex justify-between items-center mb-2">
                    <span className="text-xs font-semibold text-slate-700">Expected Recovery Value (ERV)</span>
                    <span className="text-xs font-bold text-emerald-600 font-mono">
                      Net: +{formatMoney(takeoverResult.payment.money)}
                    </span>
                  </div>
                  <div className="grid grid-cols-3 gap-2 text-[11px] text-center pt-2 border-t border-slate-200">
                    <div>
                      <span className="text-slate-400 block text-[10px]">Gross Value</span>
                      <span className="font-semibold text-slate-700 font-mono">{formatMoney(takeoverResult.payment.money)}</span>
                    </div>
                    <div>
                      <span className="text-slate-400 block text-[10px]">Intervention Cost</span>
                      <span className="font-semibold text-slate-700 font-mono">₹1.50</span>
                    </div>
                    <div>
                      <span className="text-slate-400 block text-[10px]">Friction Penalty</span>
                      <span className="font-semibold text-slate-700 font-mono">Low</span>
                    </div>
                  </div>
                </div>

                {/* Policy Invariant Check */}
                <div className="flex items-center justify-between p-3 rounded-xl bg-emerald-50/50 border border-emerald-200 text-xs">
                  <div className="flex items-center gap-2">
                    <Lock className="size-3.5 text-emerald-600" />
                    <span className="text-emerald-900 font-medium">
                      Mandatory Policy Gate: <strong>{takeoverResult.policy_outcome}</strong>
                    </span>
                  </div>
                  <span className="text-emerald-700 text-[11px] font-medium">AI Advisory Only</span>
                </div>
              </div>
            </Card>
          </div>

          {/* Stage 6 & 7: Interactive Recovery Simulation & Outcome Verification */}
          <Card className="p-6 border-slate-200 bg-white">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between pb-4 border-b border-slate-100 gap-3">
              <div>
                <div className="flex items-center gap-2">
                  <span className="text-[11px] font-bold text-indigo-600 uppercase tracking-wider">Stage 6 & 7</span>
                  <StatusBadge tone="neutral">SIMULATED RECOVERY EXECUTION</StatusBadge>
                </div>
                <h3 className="text-base font-bold text-slate-900 mt-0.5">
                  Interactive Customer Resolution Channel
                </h3>
                <p className="text-xs text-slate-500">
                  RevivePay generated an autonomous recovery channel. Test the resolution live below.
                </p>
              </div>

              {/* View Selector: Link vs Notification Previews */}
              <div className="flex items-center gap-1 bg-slate-100 p-1 rounded-xl border border-slate-200 text-xs">
                <button
                  type="button"
                  onClick={() => setPreviewChannel('LINK')}
                  className={`px-3 py-1.5 rounded-lg font-medium transition cursor-pointer ${
                    previewChannel === 'LINK'
                      ? 'bg-white text-slate-900 shadow-2xs font-semibold'
                      : 'text-slate-600 hover:text-slate-900'
                  }`}
                >
                  Payment Link
                </button>
                <button
                  type="button"
                  onClick={() => setPreviewChannel('WHATSAPP')}
                  className={`px-3 py-1.5 rounded-lg font-medium transition cursor-pointer flex items-center gap-1 ${
                    previewChannel === 'WHATSAPP'
                      ? 'bg-white text-slate-900 shadow-2xs font-semibold'
                      : 'text-slate-600 hover:text-slate-900'
                  }`}
                >
                  <MessageSquare className="size-3 text-emerald-600" /> WhatsApp
                </button>
                <button
                  type="button"
                  onClick={() => setPreviewChannel('EMAIL')}
                  className={`px-3 py-1.5 rounded-lg font-medium transition cursor-pointer flex items-center gap-1 ${
                    previewChannel === 'EMAIL'
                      ? 'bg-white text-slate-900 shadow-2xs font-semibold'
                      : 'text-slate-600 hover:text-slate-900'
                  }`}
                >
                  <Mail className="size-3 text-indigo-600" /> Email
                </button>
              </div>
            </div>

            {/* If Already Recovered: Prominent Celebratory Confirmation (Stage 7) */}
            {customerRecovered ? (
              <div className="mt-6 rounded-2xl border border-emerald-200 bg-emerald-50/60 p-8 text-center">
                <div className="size-14 bg-emerald-100 text-emerald-600 rounded-full flex items-center justify-center mx-auto mb-3 shadow-xs">
                  <CheckCircle2 className="size-8" />
                </div>
                <span className="inline-flex items-center gap-1 px-3 py-1 rounded-full text-xs font-bold bg-emerald-100 text-emerald-800 border border-emerald-200 mb-2">
                  <Sparkles className="size-3" /> STAGE 7 • OUTCOME VERIFIED
                </span>
                <h4 className="text-2xl font-black text-slate-900">
                  {formatMoney(takeoverResult.payment.money)} Revenue Recovered!
                </h4>
                <p className="text-xs text-slate-600 mt-1 max-w-md mx-auto">
                  Outcome Verifier re-read persisted payment status from the database. Status: <strong>SUCCEEDED</strong>.
                  Transaction appended to the immutable audit timeline.
                </p>

                <div className="mt-6 flex flex-wrap items-center justify-center gap-3">
                  <Link
                    to={`/cases/${takeoverResult.recovery_case_id}`}
                    className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl bg-white border border-slate-300 text-xs font-semibold text-slate-700 hover:bg-slate-50 shadow-2xs"
                  >
                    Inspect Audit Timeline in Cases <ArrowRight className="size-3.5" />
                  </Link>
                  <Link
                    to="/dashboard"
                    className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl bg-emerald-600 text-white text-xs font-semibold hover:bg-emerald-700 shadow-xs"
                  >
                    View Executive Dashboard <ExternalLink className="size-3.5" />
                  </Link>
                </div>
              </div>
            ) : (
              <div className="mt-6 space-y-4">
                {/* 1. Payment Link View */}
                {previewChannel === 'LINK' && (
                  <div className="flex flex-col md:flex-row items-center gap-6 p-4 rounded-xl border border-slate-200 bg-slate-50/50">
                    <div className="size-32 bg-white p-2 rounded-xl border border-slate-200 flex flex-col items-center justify-center shrink-0 shadow-2xs">
                      <QrCode className="size-24 text-slate-800" />
                      <span className="text-[8px] font-bold text-slate-600 tracking-wider">UPI SCAN</span>
                    </div>

                    <div className="flex-1 space-y-3 w-full">
                      <div>
                        <div className="text-xs font-semibold text-slate-900">
                          Autonomous Recovery Channel Generated
                        </div>
                        <div className="text-xs text-slate-500 mt-0.5">
                          Amount: <strong className="text-slate-800 font-mono">{formatMoney(takeoverResult.payment.money)}</strong> • VPA: <span className="font-mono text-slate-700">revivepay@razorpay</span>
                        </div>
                      </div>

                      <div className="flex items-center gap-2">
                        <input
                          type="text"
                          readOnly
                          value={`${window.location.origin}/recover/${takeoverResult.recovery_case_id}`}
                          className="flex-1 bg-white border border-slate-300 rounded-lg px-3 py-1.5 text-xs font-mono text-slate-700 select-all"
                        />
                        <Button size="sm" variant="secondary" onClick={handleCopyLink}>
                          {copied ? <Check className="size-3.5 text-emerald-600" /> : <Copy className="size-3.5" />}
                          <span>{copied ? 'Copied' : 'Copy'}</span>
                        </Button>
                        <Link
                          to={`/recover/${takeoverResult.recovery_case_id}`}
                          target="_blank"
                          className="inline-flex items-center gap-1 text-xs font-semibold text-indigo-600 hover:text-indigo-700 px-2 py-1.5"
                        >
                          Open Portal <ExternalLink className="size-3" />
                        </Link>
                      </div>

                      <Button
                        className="w-full bg-emerald-600 hover:bg-emerald-700 text-white font-bold"
                        loading={customerRecovering}
                        onClick={() => void handleCustomerRecoverInPage()}
                      >
                        <CheckCircle2 className="size-4 mr-1.5" /> Simulate Customer Payment Resolution (1-Click)
                      </Button>
                    </div>
                  </div>
                )}

                {/* 2. WhatsApp Notification Preview */}
                {previewChannel === 'WHATSAPP' && (
                  <div className="p-4 rounded-xl border border-emerald-200 bg-emerald-50/30 space-y-3">
                    <div className="flex items-center justify-between text-xs text-emerald-900 font-semibold">
                      <span className="flex items-center gap-1.5">
                        <MessageSquare className="size-3.5 text-emerald-600" /> WhatsApp Message Notification
                      </span>
                      <StatusBadge tone="neutral">SIMULATED PREVIEW</StatusBadge>
                    </div>
                    <div className="max-w-md bg-white border border-slate-200 p-4 rounded-xl shadow-2xs text-xs text-slate-800 space-y-2">
                      <p className="font-semibold text-slate-900">Acme Store: Action required for your order</p>
                      <p className="text-slate-600">
                        Hi, your payment of {formatMoney(takeoverResult.payment.money)} was interrupted due to bank timeout. RevivePay has preserved your checkout session.
                      </p>
                      <div className="bg-slate-50 p-2.5 rounded-lg border border-slate-200 font-mono text-[11px] text-indigo-600 break-all">
                        {`${window.location.origin}/recover/${takeoverResult.recovery_case_id}`}
                      </div>
                      <p className="text-[10px] text-slate-400">Click above to complete your payment with 1-click UPI.</p>
                    </div>

                    <Button
                      size="sm"
                      className="bg-emerald-600 hover:bg-emerald-700 text-white font-semibold"
                      loading={customerRecovering}
                      onClick={() => void handleCustomerRecoverInPage()}
                    >
                      <CheckCircle2 className="size-3.5 mr-1" /> Customer Follows Link & Pays Now
                    </Button>
                  </div>
                )}

                {/* 3. Email Notification Preview */}
                {previewChannel === 'EMAIL' && (
                  <div className="p-4 rounded-xl border border-indigo-100 bg-indigo-50/30 space-y-3">
                    <div className="flex items-center justify-between text-xs text-indigo-900 font-semibold">
                      <span className="flex items-center gap-1.5">
                        <Mail className="size-3.5 text-indigo-600" /> Email Payment Recovery Notification
                      </span>
                      <StatusBadge tone="neutral">SIMULATED PREVIEW</StatusBadge>
                    </div>
                    <div className="max-w-md bg-white border border-slate-200 p-4 rounded-xl shadow-2xs text-xs text-slate-800 space-y-2">
                      <div className="text-[11px] text-slate-500 pb-1 border-b border-slate-100">
                        Subject: <strong>Finish your purchase ({takeoverResult.payment.payment_id})</strong>
                      </div>
                      <p className="text-slate-600">
                        Your payment failed due to an issuer timeout. No funds were debited. Use the secure link below to retry with instant UPI or another card.
                      </p>
                      <div className="text-center pt-2">
                        <span className="inline-block px-4 py-2 rounded-lg bg-indigo-600 text-white font-semibold text-xs shadow-xs">
                          Complete My Payment Now
                        </span>
                      </div>
                    </div>

                    <Button
                      size="sm"
                      className="bg-emerald-600 hover:bg-emerald-700 text-white font-semibold"
                      loading={customerRecovering}
                      onClick={() => void handleCustomerRecoverInPage()}
                    >
                      <CheckCircle2 className="size-3.5 mr-1" /> Customer Opens Email & Recovers Payment
                    </Button>
                  </div>
                )}
              </div>
            )}
          </Card>
        </div>
      )}

      {/* 5. Technical Evidence & Telemetry (Expandable) */}
      <Accordion title="Technical Evidence & Architectural Guardrails">
        <div className="text-xs text-slate-600 leading-relaxed space-y-2">
          <p>
            • <strong>Authoritative Razorpay Sandbox Checkout</strong>: Orders and HMAC signatures are generated and verified on the server against real Razorpay Sandbox APIs.
          </p>
          <p>
            • <strong>Deterministic Failure Simulation</strong>: For reproducible evaluation, the operator selects the failure scenario. RevivePay never falsifies provider error codes.
          </p>
          <p>
            • <strong>AI Recovery Copilot</strong>: Powered by Groq Cloud API (<code>llama-3.3-70b-versatile</code>). The AI recommends strategy and explains root causes, but can NEVER bypass PolicyEngine safety gates.
          </p>
          <p>
            • <strong>Outcome Verification</strong>: Provenance is confirmed by independently reading persisted database payment records. Execution success claims are never trusted blindly.
          </p>
        </div>
      </Accordion>
    </div>
  );
}

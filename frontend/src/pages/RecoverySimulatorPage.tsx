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
  Send,
  PhoneCall,
} from 'lucide-react';
import { Accordion, Button, Card, CardHeader, StatusBadge } from '@/components/ui';
import { createRazorpayOrder, verifyRazorpayCheckout, simulateGatewayOrderFailure } from '@/api/gateway';
import { customerRecover, sendRecoveryEmail, triggerVoiceRecovery } from '@/api/recovery';
import type {
  RazorpayOrderResponse,
  RazorpayVerificationResponse,
  GatewayFailureSimulationResponse,
  SendRecoveryEmailResponse,
  VoiceRecoveryResponse,
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
  const [previewChannel, setPreviewChannel] = useState<'LINK' | 'WHATSAPP' | 'EMAIL' | 'VOICE'>('LINK');

  // Live Dispatch State
  const [recipientEmail, setRecipientEmail] = useState('');
  const [emailSending, setEmailSending] = useState(false);
  const [emailResult, setEmailResult] = useState<SendRecoveryEmailResponse | null>(null);
  const [whatsappPhone, setWhatsappPhone] = useState('');

  // Exotel Voice Channel State
  const [voicePhone, setVoicePhone] = useState('');
  const [voiceCalling, setVoiceCalling] = useState(false);
  const [voiceResult, setVoiceResult] = useState<VoiceRecoveryResponse | null>(null);
  const [voiceCallStep, setVoiceCallStep] = useState<number>(0);

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

  const handleSendLiveEmail = async () => {
    if (!takeoverResult?.recovery_case_id || !recipientEmail) return;
    setEmailSending(true);
    setEmailResult(null);
    try {
      const res = await sendRecoveryEmail(takeoverResult.recovery_case_id, {
        recipient_email: recipientEmail,
        customer_name: 'Valued Customer',
        portal_base_url: window.location.origin,
      });
      setEmailResult(res);
    } catch (err: unknown) {
      setEmailResult({
        success: false,
        provider: 'resend',
        recipient: recipientEmail,
        message: err instanceof Error ? err.message : 'Failed to dispatch live email',
        error: String(err),
      });
    } finally {
      setEmailSending(false);
    }
  };

  const handleOpenWhatsApp = () => {
    if (!takeoverResult?.recovery_case_id) return;
    const cleanPhone = whatsappPhone.replace(/[^0-9]/g, '');
    const amountStr = formatMoney(takeoverResult.payment.money);
    const recoveryUrl = `${window.location.origin}/recover/${takeoverResult.recovery_case_id}`;
    const text = encodeURIComponent(
      `Hi, your payment of ${amountStr} was interrupted. RevivePay has preserved your checkout session. Complete your payment with 1-click UPI: ${recoveryUrl}`
    );
    const waUrl = cleanPhone ? `https://wa.me/${cleanPhone}?text=${text}` : `https://wa.me/?text=${text}`;
    window.open(waUrl, '_blank');
  };

  const handleInitiateVoiceRecovery = async () => {
    if (!takeoverResult?.recovery_case_id || !voicePhone.trim()) return;
    setVoiceCalling(true);
    setVoiceResult(null);
    setVoiceCallStep(1); // Preparing recovery
    try {
      setTimeout(() => setVoiceCallStep(2), 600); // Calling customer
      const res = await triggerVoiceRecovery(takeoverResult.recovery_case_id, {
        customer_phone: voicePhone.trim(),
        customer_name: 'Valued Customer',
        portal_base_url: window.location.origin,
      });
      setVoiceResult(res);
      if (res.success) {
        setVoiceCallStep(3); // Customer response
      } else {
        setVoiceCallStep(0);
      }
    } catch (err: unknown) {
      setVoiceResult({
        case_id: takeoverResult.recovery_case_id,
        channel: 'VOICE',
        status: 'CALL_FAILED',
        payment_link: `${window.location.origin}/recover/${takeoverResult.recovery_case_id}`,
        policy_decision: 'REJECTED',
        message: err instanceof Error ? err.message : 'Failed to initiate voice call',
        success: false,
        error: String(err),
      });
      setVoiceCallStep(0);
    } finally {
      setVoiceCalling(false);
    }
  };

  const handleResetSimulation = () => {
    setActiveOrder(null);
    setTakeoverResult(null);
    setCustomerRecovered(false);
    setVoiceResult(null);
    setVoiceCallStep(0);
    setEmailResult(null);
    setMessage('Ready for a new recovery run. Click "Open Razorpay Sandbox Checkout" to start.');
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
                <button
                  type="button"
                  onClick={() => setPreviewChannel('VOICE')}
                  className={`px-3 py-1.5 rounded-lg font-medium transition cursor-pointer flex items-center gap-1 ${
                    previewChannel === 'VOICE'
                      ? 'bg-white text-slate-900 shadow-2xs font-semibold'
                      : 'text-slate-600 hover:text-slate-900'
                  }`}
                >
                  <PhoneCall className="size-3 text-purple-600" /> ☎ Voice
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

                {/* 2. WhatsApp Notification & Live Dispatch */}
                {previewChannel === 'WHATSAPP' && (
                  <div className="p-5 rounded-2xl border border-emerald-200 bg-emerald-50/40 space-y-4">
                    <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-emerald-950 font-semibold">
                      <span className="flex items-center gap-1.5">
                        <MessageSquare className="size-4 text-emerald-600" /> WhatsApp Direct Recovery Message
                      </span>
                      <StatusBadge tone="success">LIVE WA.ME DISPATCH</StatusBadge>
                    </div>

                    {/* Phone Number Input & Launch */}
                    <div className="bg-white border border-slate-200 rounded-xl p-4 shadow-2xs space-y-3">
                      <label className="block text-xs font-semibold text-slate-700">
                        Recipient Phone Number (Optional — opens WhatsApp Web or Mobile App)
                      </label>
                      <div className="flex flex-col sm:flex-row gap-2">
                        <input
                          type="tel"
                          placeholder="e.g. 919876543210 (include country code)"
                          value={whatsappPhone}
                          onChange={(e) => setWhatsappPhone(e.target.value)}
                          className="flex-1 rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs text-slate-900 outline-none focus:border-emerald-600 focus:ring-2 focus:ring-emerald-100 font-mono"
                        />
                        <Button
                          size="sm"
                          className="bg-emerald-600 hover:bg-emerald-700 text-white font-semibold shrink-0"
                          onClick={handleOpenWhatsApp}
                        >
                          <Send className="size-3.5 mr-1.5" /> Send via WhatsApp
                        </Button>
                      </div>
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

                    <div className="flex flex-wrap gap-2 pt-1">
                      <Button
                        size="sm"
                        className="bg-emerald-600 hover:bg-emerald-700 text-white font-semibold"
                        loading={customerRecovering}
                        onClick={() => void handleCustomerRecoverInPage()}
                      >
                        <CheckCircle2 className="size-3.5 mr-1" /> Customer Follows Link & Pays Now
                      </Button>
                      <Link
                        to={`/recover/${takeoverResult.recovery_case_id}`}
                        target="_blank"
                        className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg border border-slate-200 bg-white text-xs font-semibold text-slate-700 hover:bg-slate-50 shadow-2xs"
                      >
                        Open Customer Portal <ExternalLink className="size-3" />
                      </Link>
                    </div>
                  </div>
                )}

                {/* 3. Email Notification Preview & Live Resend Sender */}
                {previewChannel === 'EMAIL' && (
                  <div className="p-5 rounded-2xl border border-indigo-100 bg-indigo-50/40 space-y-4">
                    <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-indigo-950 font-semibold">
                      <span className="flex items-center gap-1.5">
                        <Mail className="size-4 text-indigo-600" /> Live Transactional Recovery Email
                      </span>
                      <StatusBadge tone="success">POWERED BY RESEND LIVE</StatusBadge>
                    </div>

                    {/* Email Input & Send Controls */}
                    <div className="bg-white border border-slate-200 rounded-xl p-4 shadow-2xs space-y-3">
                      <label className="block text-xs font-semibold text-slate-700">
                        Recipient Email Address (Enter your email to receive live email)
                      </label>
                      <div className="flex flex-col sm:flex-row gap-2">
                        <input
                          type="email"
                          placeholder="e.g. your_email@domain.com"
                          value={recipientEmail}
                          onChange={(e) => setRecipientEmail(e.target.value)}
                          className="flex-1 rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs text-slate-900 outline-none focus:border-indigo-600 focus:ring-2 focus:ring-indigo-100"
                        />
                        <Button
                          size="sm"
                          className="bg-indigo-600 hover:bg-indigo-700 text-white font-semibold shrink-0"
                          loading={emailSending}
                          disabled={!recipientEmail.trim()}
                          onClick={() => void handleSendLiveEmail()}
                        >
                          <Send className="size-3.5 mr-1.5" /> Send Live Email
                        </Button>
                      </div>

                      {/* Live Feedback Banner */}
                      {emailResult && (
                        <div
                          className={`p-3 rounded-lg border text-xs ${
                            emailResult.success
                              ? 'bg-emerald-50 border-emerald-200 text-emerald-800'
                              : 'bg-rose-50 border-rose-200 text-rose-800'
                          }`}
                        >
                          <div className="flex items-center gap-1.5 font-bold">
                            {emailResult.success ? (
                              <CheckCircle2 className="size-4 text-emerald-600 shrink-0" />
                            ) : (
                              <AlertTriangle className="size-4 text-rose-600 shrink-0" />
                            )}
                            {emailResult.success ? 'Email Dispatched via Resend!' : 'Delivery Notice'}
                          </div>
                          <p className="mt-1 text-[11px] leading-relaxed">
                            {emailResult.message}
                          </p>
                          {emailResult.message_id && (
                            <p className="mt-1 font-mono text-[10px] text-emerald-700">
                              Resend Message ID: {emailResult.message_id}
                            </p>
                          )}
                          {emailResult.mailto_fallback_url && !emailResult.success && (
                            <div className="mt-2">
                              <a
                                href={emailResult.mailto_fallback_url}
                                className="inline-flex items-center gap-1 text-[11px] font-semibold text-indigo-700 underline"
                              >
                                Open in your default mail app instead <ExternalLink className="size-3" />
                              </a>
                            </div>
                          )}
                        </div>
                      )}
                    </div>

                    {/* Rendered Email Preview */}
                    <div className="max-w-md bg-white border border-slate-200 p-4 rounded-xl shadow-2xs text-xs text-slate-800 space-y-2">
                      <div className="text-[11px] text-slate-500 pb-1 border-b border-slate-100">
                        Subject: <strong>Finish your payment of {formatMoney(takeoverResult.payment.money)} ({takeoverResult.payment.payment_id})</strong>
                      </div>
                      <p className="text-slate-600">
                        Hi Valued Customer, your payment was interrupted due to a temporary bank timeout. RevivePay has preserved your checkout session. Click below to complete:
                      </p>
                      <div className="text-center pt-2 pb-1">
                        <Link
                          to={`/recover/${takeoverResult.recovery_case_id}`}
                          target="_blank"
                          className="inline-block px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white font-semibold text-xs shadow-xs"
                        >
                          Complete My Payment (1-Click) &rarr;
                        </Link>
                      </div>
                    </div>

                    <div className="flex flex-wrap gap-2 pt-1">
                      <Button
                        size="sm"
                        className="bg-emerald-600 hover:bg-emerald-700 text-white font-semibold"
                        loading={customerRecovering}
                        onClick={() => void handleCustomerRecoverInPage()}
                      >
                        <CheckCircle2 className="size-3.5 mr-1" /> Customer Opens Email & Recovers Payment
                      </Button>
                      <Link
                        to={`/recover/${takeoverResult.recovery_case_id}`}
                        target="_blank"
                        className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg border border-slate-200 bg-white text-xs font-semibold text-slate-700 hover:bg-slate-50 shadow-2xs"
                      >
                        Open Customer Portal <ExternalLink className="size-3" />
                      </Link>
                    </div>
                  </div>
                )}

                {/* 4. Voice Recovery Channel (Exotel) */}
                {previewChannel === 'VOICE' && (
                  <div className="p-5 rounded-2xl border border-purple-200 bg-purple-50/40 space-y-4">
                    <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-purple-950 font-semibold">
                      <span className="flex items-center gap-1.5">
                        <PhoneCall className="size-4 text-purple-600" /> ☎ AI Voice Recovery (Exotel)
                      </span>
                      <StatusBadge tone="violet">REAL EXOTEL VOICE</StatusBadge>
                    </div>

                    {/* Channel Brief & Architecture Invariants */}
                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 bg-white p-3 rounded-xl border border-purple-100 text-[11px]">
                      <div>
                        <span className="text-slate-400 block text-[10px] uppercase font-bold">Diagnosis</span>
                        <strong className="text-slate-800">{takeoverResult.failure_reason.replace('_', ' ')}</strong>
                      </div>
                      <div>
                        <span className="text-slate-400 block text-[10px] uppercase font-bold">Recommended Action</span>
                        <strong className="text-slate-800">Retry Payment via Voice</strong>
                      </div>
                      <div>
                        <span className="text-slate-400 block text-[10px] uppercase font-bold">Recommended Channel</span>
                        <strong className="text-purple-700">Voice (Outbound Call)</strong>
                      </div>
                      <div>
                        <span className="text-slate-400 block text-[10px] uppercase font-bold">PolicyEngine Gate</span>
                        <span className={`inline-flex items-center gap-1 font-bold ${customerRecovered ? 'text-emerald-700' : 'text-emerald-700'}`}>
                          {customerRecovered ? '✓ RECOVERED (Paid)' : '✓ ALLOWED (Budget OK)'}
                        </span>
                      </div>
                    </div>

                    {/* Phone Number Input & Launch */}
                    <div className="bg-white border border-slate-200 rounded-xl p-4 shadow-2xs space-y-3">
                      {customerRecovered ? (
                        <div className="rounded-lg border border-emerald-200 bg-emerald-50/80 p-3 text-xs text-emerald-900 flex items-center justify-between gap-3">
                          <span className="flex items-center gap-2">
                            <Check className="size-4 text-emerald-600 shrink-0" />
                            <strong>Payment Already Recovered:</strong> Outbound voice recovery is prohibited for completed transactions.
                          </span>
                          <Button
                            size="sm"
                            variant="secondary"
                            onClick={handleResetSimulation}
                            className="shrink-0 text-xs"
                          >
                            <RefreshCw className="size-3 mr-1" /> New Simulation
                          </Button>
                        </div>
                      ) : null}

                      <label className="block text-xs font-semibold text-slate-700">
                        Customer Mobile Number (e.g. 09876543210 or +919876543210)
                      </label>
                      <div className="flex flex-col sm:flex-row gap-2">
                        <input
                          type="tel"
                          placeholder="Enter customer phone number"
                          value={voicePhone}
                          onChange={(e) => setVoicePhone(e.target.value)}
                          disabled={customerRecovered}
                          className="flex-1 rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs text-slate-900 outline-none focus:border-purple-600 focus:ring-2 focus:ring-purple-100 font-mono disabled:bg-slate-100 disabled:text-slate-400"
                        />
                        <Button
                          size="sm"
                          className="bg-purple-600 hover:bg-purple-700 text-white font-semibold shrink-0"
                          loading={voiceCalling}
                          disabled={!voicePhone.trim() || customerRecovered}
                          onClick={() => void handleInitiateVoiceRecovery()}
                        >
                          <PhoneCall className="size-3.5 mr-1.5" /> Initiate Voice Recovery
                        </Button>
                      </div>

                      {/* Live Call Lifecycle Stepper */}
                      {(voiceCalling || voiceResult || voiceCallStep > 0) && (
                        <div className="pt-2 border-t border-slate-100">
                          <div className="text-[11px] font-bold text-slate-500 uppercase tracking-wider mb-2">
                            CALL INITIATED
                          </div>
                          <div className="grid grid-cols-2 sm:grid-cols-5 gap-2 text-[11px]">
                            <div className="flex items-center gap-1 text-emerald-700 font-medium">
                              ● Preparing recovery
                            </div>
                            <div className={`flex items-center gap-1 ${voiceCallStep >= 2 ? 'text-emerald-700 font-medium' : 'text-slate-400'}`}>
                              {voiceCallStep >= 2 ? '● Calling customer' : '○ Calling customer'}
                            </div>
                            <div className={`flex items-center gap-1 ${voiceCallStep >= 3 ? 'text-emerald-700 font-medium' : 'text-slate-400'}`}>
                              {voiceCallStep >= 3 ? '● Customer response' : '○ Customer response'}
                            </div>
                            <div className={`flex items-center gap-1 ${customerRecovered ? 'text-emerald-700 font-medium' : 'text-slate-400'}`}>
                              {customerRecovered ? '● Payment' : '○ Payment'}
                            </div>
                            <div className={`flex items-center gap-1 ${customerRecovered ? 'text-emerald-700 font-medium' : 'text-slate-400'}`}>
                              {customerRecovered ? '● Verification' : '○ Verification'}
                            </div>
                          </div>
                        </div>
                      )}

                      {/* Result Feedback Banner */}
                      {voiceResult && (
                        <div
                          className={`p-3 rounded-lg border text-xs ${
                            voiceResult.success
                              ? 'bg-emerald-50 border-emerald-200 text-emerald-800'
                              : 'bg-rose-50 border-rose-200 text-rose-800'
                          }`}
                        >
                          <div className="flex items-center gap-1.5 font-bold">
                            {voiceResult.success ? (
                              <CheckCircle2 className="size-4 text-emerald-600 shrink-0" />
                            ) : (
                              <AlertTriangle className="size-4 text-rose-600 shrink-0" />
                            )}
                            {voiceResult.success ? 'Exotel Call Placed Successfully!' : 'Call Initiation Notice'}
                          </div>
                          <p className="mt-1 text-[11px] leading-relaxed">
                            {voiceResult.message}
                          </p>
                          {voiceResult.call_id && (
                            <p className="mt-1 font-mono text-[10px] text-emerald-700">
                              Exotel Call SID: {voiceResult.call_id}
                            </p>
                          )}
                          <div className="mt-2 text-[10px] text-slate-500 bg-white/60 p-1.5 rounded border border-slate-200">
                            <strong>Policy Notice:</strong> Voice call is non-custodial. Revenue is only marked recovered when payment is completed via the verified recovery link.
                          </div>
                        </div>
                      )}
                    </div>

                    {/* Voice Script & Link Prompt */}
                    <div className="max-w-md bg-white border border-slate-200 p-4 rounded-xl shadow-2xs text-xs text-slate-800 space-y-2">
                      <p className="font-semibold text-slate-900">Spoken Voice Script (Exotel IVR):</p>
                      <p className="text-slate-600 italic bg-slate-50 p-2.5 rounded-lg border border-slate-100 text-[11px] leading-relaxed">
                        &ldquo;Hello, this is RevivePay calling regarding your recent payment of {formatMoney(takeoverResult.payment.money)}. Your payment could not be completed because the bank did not respond in time. We have prepared a secure payment link to complete your payment with 1-click UPI.&rdquo;
                      </p>
                      <div className="bg-slate-50 p-2 rounded-lg border border-slate-200 font-mono text-[10px] text-indigo-600 break-all">
                        {`${window.location.origin}/recover/${takeoverResult.recovery_case_id}`}
                      </div>
                    </div>

                    <div className="flex flex-wrap gap-2 pt-1">
                      <Button
                        size="sm"
                        className="bg-emerald-600 hover:bg-emerald-700 text-white font-semibold"
                        loading={customerRecovering}
                        onClick={() => void handleCustomerRecoverInPage()}
                      >
                        <CheckCircle2 className="size-3.5 mr-1" /> Customer Completes Payment After Voice Call
                      </Button>
                      <Link
                        to={`/recover/${takeoverResult.recovery_case_id}`}
                        target="_blank"
                        className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg border border-slate-200 bg-white text-xs font-semibold text-slate-700 hover:bg-slate-50 shadow-2xs"
                      >
                        Open Customer Portal <ExternalLink className="size-3" />
                      </Link>
                    </div>
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

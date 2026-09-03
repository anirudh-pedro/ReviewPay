import { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import {
  CheckCircle2,
  AlertTriangle,
  QrCode,
  CreditCard,
  Smartphone,
  ShieldCheck,
  Building2,
  ArrowRight,
  ExternalLink,
  Copy,
  Check,
  Clock,
  Sparkles,
  Lock,
} from 'lucide-react';
import { getCustomerRecoveryView, customerRecover } from '@/api/recovery';
import type { CustomerRecoveryViewResponse, CustomerRecoveryExecutionResponse } from '@/types/api';
import { formatMoney } from '@/utils/format';

export function CustomerRecoveryPage() {
  const { caseId } = useParams<{ caseId: string }>();
  const [data, setData] = useState<CustomerRecoveryViewResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedMethod, setSelectedMethod] = useState<'UPI' | 'CARD' | 'NETBANKING'>('UPI');
  const [isProcessing, setIsProcessing] = useState(false);
  const [recoveryResult, setRecoveryResult] = useState<CustomerRecoveryExecutionResponse | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!caseId) {
      setError('No recovery case identifier provided.');
      setLoading(false);
      return;
    }

    let isMounted = true;
    getCustomerRecoveryView(caseId)
      .then((res) => {
        if (isMounted) {
          setData(res);
          if (res.action_type === 'ALTERNATIVE_PAYMENT') {
            setSelectedMethod('UPI');
          }
          setLoading(false);
        }
      })
      .catch((err) => {
        if (isMounted) {
          setError(err instanceof Error ? err.message : 'Unable to load payment recovery details.');
          setLoading(false);
        }
      });

    return () => {
      isMounted = false;
    };
  }, [caseId]);

  const handleCopyUpi = () => {
    if (!data) return;
    navigator.clipboard.writeText('revivepay@razorpay');
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleCompletePayment = async () => {
    if (!caseId || !data) return;
    setIsProcessing(true);
    setError(null);

    try {
      const result = await customerRecover(caseId, {
        selected_method: selectedMethod,
        instrument_details: {
          vpa: selectedMethod === 'UPI' ? 'customer@upi' : undefined,
          channel: 'revivepay_customer_portal',
        },
      });
      setRecoveryResult(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Payment recovery failed. Please try again.');
    } finally {
      setIsProcessing(false);
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-50 flex flex-col items-center justify-center p-6 text-slate-800">
        <div className="w-10 h-10 border-3 border-indigo-200 border-t-indigo-600 rounded-full animate-spin mb-3" />
        <h2 className="text-base font-semibold tracking-tight text-slate-900">Securing Your Checkout Session...</h2>
        <p className="text-xs text-slate-500 mt-0.5">Retrieving payment recovery options from RevivePay</p>
      </div>
    );
  }

  if (error && !data) {
    return (
      <div className="min-h-screen bg-slate-50 flex flex-col items-center justify-center p-6 text-slate-800">
        <div className="max-w-md w-full bg-white border border-slate-200 rounded-2xl p-8 text-center shadow-sm">
          <div className="w-12 h-12 bg-rose-50 text-rose-600 rounded-2xl flex items-center justify-center mx-auto mb-4 border border-rose-100">
            <AlertTriangle className="w-6 h-6" />
          </div>
          <h2 className="text-lg font-bold tracking-tight text-slate-900">Recovery Link Expired or Invalid</h2>
          <p className="text-xs text-slate-500 mt-2">{error}</p>
          <Link
            to="/simulator"
            className="mt-6 inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-slate-100 text-slate-700 text-xs font-semibold hover:bg-slate-200 transition"
          >
            Go to Simulator
          </Link>
        </div>
      </div>
    );
  }

  if (recoveryResult || data?.status === 'RECOVERED') {
    return (
      <div className="min-h-screen bg-slate-50 flex flex-col items-center justify-center p-4 sm:p-6 text-slate-900">
        <div className="max-w-md w-full bg-white border border-slate-200 rounded-3xl p-6 sm:p-8 text-center shadow-md relative overflow-hidden">
          <div className="absolute inset-x-0 top-0 h-1.5 bg-emerald-500" />
          
          <div className="w-14 h-14 bg-emerald-50 text-emerald-600 rounded-2xl flex items-center justify-center mx-auto mb-4 border border-emerald-100">
            <CheckCircle2 className="w-8 h-8" />
          </div>

          <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200 mb-3">
            <Sparkles className="w-3.5 h-3.5" /> REVENUE RECOVERED
          </span>

          <h1 className="text-2xl font-bold tracking-tight text-slate-900">Payment Recovered Successfully!</h1>
          <p className="text-xs text-slate-600 mt-2">
            Your transaction was processed and verified. Your order with <span className="text-slate-900 font-semibold">{data?.merchant_name || 'Demo Store'}</span> is confirmed.
          </p>

          <div className="mt-6 bg-slate-50 border border-slate-200/80 rounded-2xl p-4 text-left space-y-2.5">
            <div className="flex justify-between items-center text-sm">
              <span className="text-slate-500">Amount Paid</span>
              <span className="text-base font-bold text-emerald-600 font-mono">{data?.amount ? formatMoney(data.amount) : '₹125.00'}</span>
            </div>
            <div className="flex justify-between items-center text-xs">
              <span className="text-slate-500">Receipt ID</span>
              <span className="font-mono text-slate-700 bg-white border border-slate-200 px-2 py-0.5 rounded text-[11px]">{recoveryResult?.receipt_id || 'rcpt_revive_captured'}</span>
            </div>
            <div className="flex justify-between items-center text-xs">
              <span className="text-slate-500">Payment ID</span>
              <span className="font-mono text-slate-700">{data?.payment_id}</span>
            </div>
            <div className="flex justify-between items-center text-xs">
              <span className="text-slate-500">Verified By</span>
              <span className="text-slate-700 flex items-center gap-1 font-medium">
                <ShieldCheck className="w-3.5 h-3.5 text-emerald-600" /> RevivePay Safe Engine
              </span>
            </div>
          </div>

          <div className="mt-8 flex flex-col sm:flex-row gap-3">
            <Link
              to="/simulator"
              className="flex-1 py-2.5 px-4 rounded-xl bg-emerald-600 hover:bg-emerald-700 text-white font-semibold text-xs transition text-center shadow-xs"
            >
              Return to Recovery Simulator
            </Link>
            <Link
              to={`/cases/${caseId}`}
              className="flex-1 py-2.5 px-4 rounded-xl bg-slate-100 hover:bg-slate-200 text-slate-700 font-medium text-xs transition text-center flex items-center justify-center gap-1"
            >
              Inspect Case Audit <ExternalLink className="w-3.5 h-3.5" />
            </Link>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900 flex flex-col items-center justify-start p-4 sm:p-8">
      {/* Top Brand Bar */}
      <header className="w-full max-w-xl flex items-center justify-between py-4 border-b border-slate-200 mb-6">
        <div className="flex items-center gap-2.5">
          <div className="size-8 rounded-lg bg-indigo-600 flex items-center justify-center font-bold text-white text-xs shadow-xs">
            RP
          </div>
          <div>
            <div className="text-[10px] text-slate-500 font-medium uppercase tracking-wider">Merchant Checkout</div>
            <div className="text-xs font-bold text-slate-900">{data?.merchant_name}</div>
          </div>
        </div>
        <div className="flex items-center gap-1.5 text-[11px] text-emerald-700 bg-emerald-50 border border-emerald-200 px-2.5 py-1 rounded-full font-medium">
          <Lock className="w-3 h-3 text-emerald-600" />
          <span>256-bit Encrypted Recovery</span>
        </div>
      </header>

      {/* Main Recovery Card */}
      <main className="w-full max-w-xl bg-white border border-slate-200 rounded-3xl p-6 sm:p-8 shadow-sm relative">
        <div className="absolute inset-x-0 top-0 h-1.5 bg-indigo-600 rounded-t-3xl" />

        {/* Amount Header */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between pb-5 border-b border-slate-100 gap-4">
          <div>
            <span className="text-[11px] uppercase tracking-wider text-indigo-600 font-bold flex items-center gap-1">
              <Sparkles className="w-3.5 h-3.5" /> Autonomous Recovery Channel
            </span>
            <h1 className="text-xl font-bold tracking-tight text-slate-900 mt-1">Complete Your Payment</h1>
            <p className="text-xs text-slate-500 mt-0.5">Payment ID: <span className="font-mono text-slate-700 font-medium">{data?.payment_id}</span></p>
          </div>
          <div className="text-left sm:text-right bg-slate-50 border border-slate-200 p-3 rounded-2xl">
            <div className="text-[10px] text-slate-500 uppercase font-semibold">Total Payable</div>
            <div className="text-xl font-black text-slate-900 tracking-tight font-mono">
              {data ? formatMoney(data.amount) : '₹0.00'}
            </div>
          </div>
        </div>

        {/* Why it failed: Customer-Friendly Explainer */}
        <div className="my-5 bg-amber-50/70 border border-amber-200/80 rounded-2xl p-4 flex items-start gap-3">
          <div className="size-8 rounded-xl bg-amber-100 text-amber-700 flex items-center justify-center shrink-0 mt-0.5">
            <AlertTriangle className="w-4 h-4" />
          </div>
          <div>
            <h2 className="text-xs font-bold text-amber-900">{data?.failure_title}</h2>
            <p className="text-xs text-amber-800 mt-0.5 leading-relaxed">
              {data?.failure_explanation}
            </p>
          </div>
        </div>

        {/* Interactive Payment Method Selector */}
        <div className="space-y-4">
          <div className="text-xs font-semibold uppercase tracking-wider text-slate-600">
            Choose Payment Recovery Method
          </div>

          <div className="grid grid-cols-3 gap-2 sm:gap-3">
            <button
              type="button"
              onClick={() => setSelectedMethod('UPI')}
              className={`p-3 rounded-2xl border text-center transition flex flex-col items-center justify-center gap-1 cursor-pointer ${
                selectedMethod === 'UPI'
                  ? 'bg-indigo-50 border-indigo-600 text-indigo-950 ring-2 ring-indigo-600/10'
                  : 'bg-white border-slate-200 text-slate-600 hover:border-slate-300'
              }`}
            >
              <Smartphone className="w-4 h-4 text-indigo-600" />
              <span className="text-xs font-semibold">Instant UPI</span>
              <span className="text-[10px] text-emerald-600 font-medium">99.8% Success</span>
            </button>

            <button
              type="button"
              onClick={() => setSelectedMethod('CARD')}
              className={`p-3 rounded-2xl border text-center transition flex flex-col items-center justify-center gap-1 cursor-pointer ${
                selectedMethod === 'CARD'
                  ? 'bg-indigo-50 border-indigo-600 text-indigo-950 ring-2 ring-indigo-600/10'
                  : 'bg-white border-slate-200 text-slate-600 hover:border-slate-300'
              }`}
            >
              <CreditCard className="w-4 h-4 text-indigo-600" />
              <span className="text-xs font-semibold">New Card</span>
              <span className="text-[10px] text-slate-400">Visa / MC</span>
            </button>

            <button
              type="button"
              onClick={() => setSelectedMethod('NETBANKING')}
              className={`p-3 rounded-2xl border text-center transition flex flex-col items-center justify-center gap-1 cursor-pointer ${
                selectedMethod === 'NETBANKING'
                  ? 'bg-indigo-50 border-indigo-600 text-indigo-950 ring-2 ring-indigo-600/10'
                  : 'bg-white border-slate-200 text-slate-600 hover:border-slate-300'
              }`}
            >
              <Building2 className="w-4 h-4 text-indigo-600" />
              <span className="text-xs font-semibold">Netbanking</span>
              <span className="text-[10px] text-slate-400">All Banks</span>
            </button>
          </div>

          {/* Active Method Render Panel */}
          <div className="bg-slate-50 border border-slate-200 rounded-2xl p-5 mt-3">
            {selectedMethod === 'UPI' && (
              <div className="flex flex-col sm:flex-row items-center gap-5">
                <div className="size-32 bg-white p-2 rounded-2xl border border-slate-200 flex flex-col items-center justify-center shrink-0 shadow-2xs">
                  <QrCode className="size-24 text-slate-900" />
                  <span className="text-[8px] font-bold text-slate-600 tracking-wider">SCAN TO PAY</span>
                </div>

                <div className="flex-1 space-y-2.5 text-center sm:text-left">
                  <div className="text-xs font-semibold text-slate-800">Scan with any UPI application</div>
                  <div className="flex flex-wrap gap-1.5 justify-center sm:justify-start">
                    <span className="px-2 py-0.5 bg-white text-slate-700 text-xs font-medium rounded-md border border-slate-200 shadow-2xs">Google Pay</span>
                    <span className="px-2 py-0.5 bg-white text-slate-700 text-xs font-medium rounded-md border border-slate-200 shadow-2xs">PhonePe</span>
                    <span className="px-2 py-0.5 bg-white text-slate-700 text-xs font-medium rounded-md border border-slate-200 shadow-2xs">Paytm</span>
                  </div>
                  <div className="flex items-center gap-2 bg-white border border-slate-200 rounded-xl px-3 py-1.5 text-xs">
                    <span className="text-slate-400">VPA:</span>
                    <span className="font-mono text-slate-800 font-semibold flex-1 truncate">revivepay@razorpay</span>
                    <button
                      type="button"
                      onClick={handleCopyUpi}
                      className="text-indigo-600 hover:text-indigo-700 transition flex items-center gap-1 font-medium cursor-pointer"
                    >
                      {copied ? <Check className="w-3.5 h-3.5 text-emerald-600" /> : <Copy className="w-3.5 h-3.5" />}
                      <span className="text-[11px]">{copied ? 'Copied' : 'Copy'}</span>
                    </button>
                  </div>
                </div>
              </div>
            )}

            {selectedMethod === 'CARD' && (
              <div className="space-y-3 text-xs">
                <div>
                  <label className="block font-medium text-slate-600 mb-1">Card Number</label>
                  <input
                    type="text"
                    readOnly
                    value="4111 •••• •••• 1111 (Demo Card)"
                    className="w-full bg-white border border-slate-300 rounded-xl px-3 py-2 text-slate-800 font-mono text-xs"
                  />
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block font-medium text-slate-600 mb-1">Expiry</label>
                    <input
                      type="text"
                      readOnly
                      value="12 / 28"
                      className="w-full bg-white border border-slate-300 rounded-xl px-3 py-2 text-slate-800 font-mono text-xs"
                    />
                  </div>
                  <div>
                    <label className="block font-medium text-slate-600 mb-1">CVV</label>
                    <input
                      type="password"
                      readOnly
                      value="•••"
                      className="w-full bg-white border border-slate-300 rounded-xl px-3 py-2 text-slate-800 font-mono text-xs"
                    />
                  </div>
                </div>
              </div>
            )}

            {selectedMethod === 'NETBANKING' && (
              <div className="space-y-2 text-xs">
                <label className="block font-medium text-slate-600">Select Bank</label>
                <div className="grid grid-cols-2 gap-2">
                  <button type="button" className="p-2.5 rounded-xl border border-slate-200 bg-white text-xs font-medium text-slate-800 hover:border-indigo-600 transition text-left cursor-pointer">
                    HDFC Bank
                  </button>
                  <button type="button" className="p-2.5 rounded-xl border border-slate-200 bg-white text-xs font-medium text-slate-800 hover:border-indigo-600 transition text-left cursor-pointer">
                    ICICI Bank
                  </button>
                  <button type="button" className="p-2.5 rounded-xl border border-slate-200 bg-white text-xs font-medium text-slate-800 hover:border-indigo-600 transition text-left cursor-pointer">
                    State Bank of India
                  </button>
                  <button type="button" className="p-2.5 rounded-xl border border-slate-200 bg-white text-xs font-medium text-slate-800 hover:border-indigo-600 transition text-left cursor-pointer">
                    Axis Bank
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Submit CTA */}
        <div className="mt-6 space-y-3">
          <button
            type="button"
            disabled={isProcessing}
            onClick={handleCompletePayment}
            className="w-full py-3.5 px-5 rounded-xl bg-indigo-600 hover:bg-indigo-700 text-white font-bold text-sm shadow-xs transition flex items-center justify-center gap-2 disabled:opacity-50 cursor-pointer"
          >
            {isProcessing ? (
              <>
                <div className="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin" />
                <span>Authorizing Recovery...</span>
              </>
            ) : (
              <>
                <span>Complete Payment & Recover Now</span>
                <ArrowRight className="w-4 h-4" />
              </>
            )}
          </button>

          <div className="flex items-center justify-center gap-2 text-xs text-slate-500">
            <Clock className="w-3.5 h-3.5 text-slate-400" />
            <span>Session saved by RevivePay • Protected against duplicate charges</span>
          </div>
        </div>
      </main>

      <footer className="mt-6 text-center text-xs text-slate-500 space-y-1">
        <div>Case Reference: <span className="font-mono text-slate-700">{caseId}</span></div>
        <div>
          <Link to={`/cases/${caseId}`} className="text-indigo-600 hover:underline">
            View Live Case in Command Center ↗
          </Link>
        </div>
      </footer>
    </div>
  );
}

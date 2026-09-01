import { useEffect, useState } from 'react';
import { AlertTriangle, DatabaseZap, RotateCcw, X } from 'lucide-react';
import { resetDemo } from '@/api';
import { useDemoData } from '@/contexts/DemoDataContext';
import { useAsyncAction } from '@/hooks/useApi';
import { useToast } from '@/components/Toast';
import { Button, ErrorState, StatusBadge } from '@/components/ui';
import { formatDateTime, humanize } from '@/utils/format';

export function DemoResetModal({ onClose }: { onClose: () => void }) {
  const reset = useAsyncAction(resetDemo);
  const { invalidateDemoData } = useDemoData();
  const { notify } = useToast();
  const [completed, setCompleted] = useState<Awaited<ReturnType<typeof resetDemo>> | null>(null);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape' && !reset.loading) onClose();
    }

    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [onClose, reset.loading]);

  async function handleReset() {
    try {
      const result = await reset.run({ background_customers: 12 });
      setCompleted(result);
      invalidateDemoData();
      notify({ tone: 'success', message: 'Synthetic demo data and the virtual clock were reset.' });
    } catch {
      // useAsyncAction retains the structured API error for the view below.
    }
  }

  return (
    <div className="fixed inset-0 z-[60] grid place-items-center px-4 py-6" role="presentation">
      <button
        aria-label="Close demo reset dialog"
        className="absolute inset-0 bg-black/70 backdrop-blur-sm"
        disabled={reset.loading}
        type="button"
        onClick={onClose}
      />
      <section
        aria-describedby="demo-reset-description"
        aria-labelledby="demo-reset-title"
        aria-modal="true"
        className="relative z-10 w-full max-w-xl overflow-hidden rounded-2xl border border-white/[0.1] bg-ink-850 shadow-2xl shadow-black/60"
        role="dialog"
      >
        <header className="flex items-start justify-between gap-4 border-b border-white/[0.06] px-5 py-5 sm:px-6">
          <div className="flex min-w-0 gap-3">
            <div className="grid size-10 shrink-0 place-items-center rounded-xl border border-atrisk/30 bg-atrisk/10 text-atrisk">
              <DatabaseZap aria-hidden="true" className="size-5" />
            </div>
            <div>
              <h2 id="demo-reset-title" className="text-base font-semibold text-slate-50">Reset deterministic demo data?</h2>
              <p id="demo-reset-description" className="mt-1.5 text-sm leading-6 text-slate-400">
                This recreates the local synthetic dataset and resets the virtual clock. It removes current demo audit/history data, but never contacts a payment provider or handles real money.
              </p>
            </div>
          </div>
          <button
            aria-label="Close demo reset dialog"
            className="rounded-lg p-1.5 text-slate-500 transition-colors hover:bg-white/[0.06] hover:text-slate-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
            disabled={reset.loading}
            type="button"
            onClick={onClose}
          >
            <X aria-hidden="true" className="size-4" />
          </button>
        </header>

        <div className="space-y-4 px-5 py-5 sm:px-6">
          {completed ? (
            <div className="rounded-xl border border-recovered/25 bg-recovered/[0.06] p-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div><p className="text-sm font-semibold text-green-200">Demo data is ready</p><p className="mt-1 text-xs leading-5 text-slate-400">{completed.message}</p></div>
                <StatusBadge tone="success">{completed.cases} cases</StatusBadge>
              </div>
              <dl className="mt-4 grid gap-2 sm:grid-cols-3">
                <div className="rounded-lg border border-white/[0.06] bg-ink-900/40 p-3"><dt className="text-[0.62rem] uppercase tracking-[0.1em] text-slate-500">Customers</dt><dd className="mt-1 font-mono text-sm text-slate-200">{completed.customers}</dd></div>
                <div className="rounded-lg border border-white/[0.06] bg-ink-900/40 p-3"><dt className="text-[0.62rem] uppercase tracking-[0.1em] text-slate-500">Payments</dt><dd className="mt-1 font-mono text-sm text-slate-200">{completed.payments}</dd></div>
                <div className="rounded-lg border border-white/[0.06] bg-ink-900/40 p-3"><dt className="text-[0.62rem] uppercase tracking-[0.1em] text-slate-500">Virtual clock</dt><dd className="mt-1 text-xs text-slate-200">{formatDateTime(completed.virtual_clock_time)}</dd></div>
              </dl>
              <div className="mt-4 flex flex-wrap gap-2">
                {completed.scenarios.map((scenario) => <StatusBadge key={scenario.key} tone="info">{scenario.key} · {humanize(scenario.current_state)}</StatusBadge>)}
              </div>
            </div>
          ) : (
            <div className="rounded-xl border border-atrisk/20 bg-atrisk/[0.04] p-4">
              <div className="flex gap-2.5"><AlertTriangle aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-atrisk" /><p className="text-sm leading-6 text-amber-100">Use this before a judge demo to restore the four deterministic scenarios. The endpoint is deliberately restricted by the backend to local/demo environments.</p></div>
            </div>
          )}
          {reset.error ? <ErrorState compact error={reset.error} title="Demo reset could not complete" /> : null}
        </div>

        <footer className="flex flex-col-reverse gap-2 border-t border-white/[0.06] bg-ink-900/40 px-5 py-4 sm:flex-row sm:justify-end sm:px-6">
          <Button variant="ghost" onClick={onClose}>{completed ? 'Close' : 'Cancel'}</Button>
          {!completed ? <Button loading={reset.loading} variant="danger" onClick={handleReset}><RotateCcw aria-hidden="true" className="size-4" />Reset synthetic demo</Button> : null}
        </footer>
      </section>
    </div>
  );
}

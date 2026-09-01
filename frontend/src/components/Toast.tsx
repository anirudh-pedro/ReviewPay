import { CheckCircle2, Info, TriangleAlert, X } from 'lucide-react';
import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { cx } from './ui';

type ToastTone = 'success' | 'info' | 'error';

interface ToastItem {
  id: string;
  message: string;
  tone: ToastTone;
}

export interface ToastInput {
  message: string;
  tone?: ToastTone;
}

interface ToastContextValue {
  notify: (toast: ToastInput) => string;
  dismiss: (id: string) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

const toastPresentation: Record<ToastTone, { icon: typeof Info; className: string }> = {
  success: { icon: CheckCircle2, className: 'border-recovered/30 text-green-200' },
  info: { icon: Info, className: 'border-accent/30 text-sky-200' },
  error: { icon: TriangleAlert, className: 'border-blocked/30 text-red-200' },
};

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const sequenceRef = useRef(0);
  const timersRef = useRef<number[]>([]);

  const dismiss = useCallback((id: string) => {
    setToasts((current) => current.filter((toast) => toast.id !== id));
  }, []);

  const notify = useCallback(
    ({ message, tone = 'info' }: ToastInput): string => {
      const id = `toast-${Date.now()}-${sequenceRef.current++}`;
      setToasts((current) => [...current, { id, message, tone }]);
      const timer = window.setTimeout(() => dismiss(id), 5000);
      timersRef.current.push(timer);
      return id;
    },
    [dismiss],
  );

  useEffect(() => {
    return () => timersRef.current.forEach((timer) => window.clearTimeout(timer));
  }, []);

  return (
    <ToastContext.Provider value={{ notify, dismiss }}>
      {children}
      <div aria-atomic="true" aria-live="polite" className="fixed inset-x-4 bottom-4 z-50 flex flex-col items-end gap-2 sm:left-auto sm:w-96">
        {toasts.map((toast) => {
          const presentation = toastPresentation[toast.tone];
          const Icon = presentation.icon;
          return (
            <div
              key={toast.id}
              className={cx(
                'flex w-full items-start gap-3 rounded-xl border bg-ink-800 p-3 shadow-xl shadow-black/30',
                presentation.className,
              )}
              role="status"
            >
              <Icon aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
              <p className="flex-1 text-sm leading-5">{toast.message}</p>
              <button
                aria-label="Dismiss notification"
                className="rounded p-0.5 text-slate-400 transition-colors hover:bg-white/10 hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
                onClick={() => dismiss(toast.id)}
                type="button"
              >
                <X aria-hidden="true" className="size-4" />
              </button>
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextValue {
  const context = useContext(ToastContext);
  if (!context) throw new Error('useToast must be used inside ToastProvider.');
  return context;
}

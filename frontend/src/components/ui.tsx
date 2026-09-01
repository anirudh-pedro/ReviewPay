import { AlertTriangle, ArrowRight, LoaderCircle, RefreshCw } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import type { ButtonHTMLAttributes, HTMLAttributes, ReactNode } from 'react';
import type { ApiError } from '@/api/client';

export function cx(...values: Array<string | false | null | undefined>): string {
  return values.filter(Boolean).join(' ');
}

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger';
export type ButtonSize = 'sm' | 'md' | 'lg';

const buttonVariants: Record<ButtonVariant, string> = {
  primary:
    'border border-accent bg-accent text-ink-950 shadow-[0_6px_18px_-8px_rgba(56,189,248,0.9)] hover:bg-sky-300 focus-visible:ring-accent',
  secondary:
    'border border-ink-600 bg-ink-800 text-slate-100 hover:border-slate-500 hover:bg-ink-750 focus-visible:ring-slate-400',
  ghost:
    'border border-transparent bg-transparent text-slate-300 hover:bg-ink-800 hover:text-white focus-visible:ring-slate-400',
  danger:
    'border border-blocked/70 bg-blocked/10 text-red-100 hover:bg-blocked/20 focus-visible:ring-blocked',
};

const buttonSizes: Record<ButtonSize, string> = {
  sm: 'h-8 gap-1.5 px-3 text-xs',
  md: 'h-10 gap-2 px-4 text-sm',
  lg: 'h-11 gap-2 px-4 text-sm',
};

export function buttonClassName(
  variant: ButtonVariant = 'primary',
  size: ButtonSize = 'md',
  className?: string,
): string {
  return cx(
    'inline-flex items-center justify-center rounded-lg font-semibold transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-offset-ink-950 disabled:cursor-not-allowed disabled:opacity-50',
    buttonVariants[variant],
    buttonSizes[size],
    className,
  );
}

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
  children: ReactNode;
}

export function Button({
  children,
  className,
  variant = 'primary',
  size = 'md',
  loading = false,
  disabled,
  type,
  ...props
}: ButtonProps) {
  return (
    <button
      className={buttonClassName(variant, size, className)}
      disabled={disabled || loading}
      type={type ?? 'button'}
      {...props}
    >
      {loading ? <LoaderCircle aria-hidden="true" className="size-4 animate-spin" /> : null}
      {children}
    </button>
  );
}

export interface CardProps extends HTMLAttributes<HTMLDivElement> {
  children: ReactNode;
}

export function Card({ children, className, ...props }: CardProps) {
  return (
    <section className={cx('rounded-xl border border-white/[0.055] bg-ink-850 shadow-card', className)} {...props}>
      {children}
    </section>
  );
}

export function CardHeader({ children, className, ...props }: CardProps) {
  return (
    <header className={cx('flex items-start justify-between gap-4 px-5 pt-5', className)} {...props}>
      {children}
    </header>
  );
}

export function Skeleton({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      aria-hidden="true"
      className={cx(
        'relative overflow-hidden rounded-md bg-ink-750/80 before:absolute before:inset-0 before:-translate-x-full before:bg-gradient-to-r before:from-transparent before:via-white/[0.06] before:to-transparent before:animate-shimmer',
        className,
      )}
      {...props}
    />
  );
}

export type StatusTone = 'success' | 'warning' | 'danger' | 'violet' | 'info' | 'neutral';

const statusStyles: Record<StatusTone, string> = {
  success: 'border-recovered/30 bg-recovered/10 text-green-300',
  warning: 'border-atrisk/30 bg-atrisk/10 text-amber-300',
  danger: 'border-blocked/30 bg-blocked/10 text-red-300',
  violet: 'border-escalated/30 bg-escalated/10 text-violet-300',
  info: 'border-accent/30 bg-accent/10 text-sky-300',
  neutral: 'border-white/10 bg-white/[0.045] text-slate-300',
};

export function StatusBadge({
  children,
  className,
  tone = 'neutral',
}: {
  children: ReactNode;
  className?: string;
  tone?: StatusTone;
}) {
  return (
    <span
      className={cx(
        'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[0.68rem] font-semibold uppercase tracking-[0.1em]',
        statusStyles[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
  compact = false,
}: {
  icon: LucideIcon;
  title: string;
  description: string;
  action?: ReactNode;
  compact?: boolean;
}) {
  return (
    <div
      className={cx(
        'flex flex-col items-center justify-center text-center',
        compact ? 'min-h-48 px-5 py-8' : 'min-h-80 px-6 py-12',
      )}
    >
      <div className="mb-4 grid size-11 place-items-center rounded-xl border border-white/[0.07] bg-ink-800 text-slate-400">
        <Icon aria-hidden="true" className="size-5" />
      </div>
      <h2 className="text-base font-semibold text-slate-100">{title}</h2>
      <p className="mt-2 max-w-md text-sm leading-6 text-slate-400">{description}</p>
      {action ? <div className="mt-5">{action}</div> : null}
    </div>
  );
}

function readableError(error: ApiError | Error | string): string {
  if (typeof error === 'string') return error;
  if ('isNetworkError' in error && error.isNetworkError) {
    return 'The Command Center could not reach the API. Check that the backend is running, then try again.';
  }
  if ('isMalformedResponse' in error && error.isMalformedResponse) {
    return 'The API response was incomplete or unexpected. No dashboard values are being shown as a result.';
  }
  return error.message || 'The request could not be completed.';
}

export function ErrorState({
  error,
  title = 'Unable to load this view',
  onRetry,
  compact = false,
}: {
  error: ApiError | Error | string;
  title?: string;
  onRetry?: () => void;
  compact?: boolean;
}) {
  return (
    <div
      className={cx(
        'flex flex-col items-center justify-center text-center',
        compact ? 'min-h-48 px-5 py-8' : 'min-h-80 px-6 py-12',
      )}
      role="alert"
    >
      <div className="mb-4 grid size-11 place-items-center rounded-xl border border-blocked/25 bg-blocked/10 text-red-300">
        <AlertTriangle aria-hidden="true" className="size-5" />
      </div>
      <h2 className="text-base font-semibold text-slate-100">{title}</h2>
      <p className="mt-2 max-w-lg text-sm leading-6 text-slate-400">{readableError(error)}</p>
      {onRetry ? (
        <Button className="mt-5" size="sm" variant="secondary" onClick={onRetry}>
          <RefreshCw aria-hidden="true" className="size-3.5" />
          Retry request
        </Button>
      ) : null}
    </div>
  );
}

export function InlineLinkArrow() {
  return <ArrowRight aria-hidden="true" className="size-3.5 transition-transform group-hover:translate-x-0.5" />;
}

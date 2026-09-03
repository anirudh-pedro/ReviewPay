import { AlertTriangle, ChevronDown, LoaderCircle, RefreshCw } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { useState } from 'react';
import type { ButtonHTMLAttributes, HTMLAttributes, ReactNode } from 'react';
import type { ApiError } from '@/api/client';

export function cx(...values: Array<string | false | null | undefined>): string {
  return values.filter(Boolean).join(' ');
}

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger';
export type ButtonSize = 'sm' | 'md' | 'lg';

const buttonVariants: Record<ButtonVariant, string> = {
  primary:
    'border border-indigo-600 bg-indigo-600 text-white shadow-xs hover:bg-indigo-700 hover:border-indigo-700 focus-visible:ring-indigo-500',
  secondary:
    'border border-slate-300 bg-white text-slate-700 shadow-xs hover:bg-slate-50 hover:text-slate-900 focus-visible:ring-slate-400',
  ghost:
    'border border-transparent bg-transparent text-slate-600 hover:bg-slate-100 hover:text-slate-900 focus-visible:ring-slate-400',
  danger:
    'border border-rose-300 bg-rose-50 text-rose-700 hover:bg-rose-100 focus-visible:ring-rose-400',
};

const buttonSizes: Record<ButtonSize, string> = {
  sm: 'h-8 gap-1.5 px-3 text-xs',
  md: 'h-9.5 gap-2 px-4 text-sm',
  lg: 'h-11 gap-2.5 px-5 text-sm font-semibold',
};

export function buttonClassName(
  variant: ButtonVariant = 'primary',
  size: ButtonSize = 'md',
  className?: string,
): string {
  return cx(
    'inline-flex items-center justify-center rounded-lg font-medium transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-offset-white disabled:cursor-not-allowed disabled:opacity-50 cursor-pointer',
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
    <section className={cx('rounded-xl border border-slate-200 bg-white shadow-xs', className)} {...props}>
      {children}
    </section>
  );
}

export function CardHeader({ children, className, ...props }: CardProps) {
  return (
    <header className={cx('flex items-start justify-between gap-4 px-5 pt-5 pb-2', className)} {...props}>
      {children}
    </header>
  );
}

export function Skeleton({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      aria-hidden="true"
      className={cx('animate-pulse rounded-md bg-slate-100', className)}
      {...props}
    />
  );
}

export interface MetricCardProps {
  title: string;
  value: string;
  subtext?: string;
  icon?: LucideIcon;
  tone?: 'default' | 'success' | 'amber' | 'rose' | 'indigo';
}

const metricToneMap: Record<NonNullable<MetricCardProps['tone']>, { iconBg: string; iconColor: string }> = {
  default: { iconBg: 'bg-slate-100', iconColor: 'text-slate-600' },
  success: { iconBg: 'bg-emerald-50', iconColor: 'text-emerald-600' },
  amber: { iconBg: 'bg-amber-50', iconColor: 'text-amber-600' },
  rose: { iconBg: 'bg-rose-50', iconColor: 'text-rose-600' },
  indigo: { iconBg: 'bg-indigo-50', iconColor: 'text-indigo-600' },
};

export function MetricCard({ title, value, subtext, icon: Icon, tone = 'default' }: MetricCardProps) {
  const { iconBg, iconColor } = metricToneMap[tone];
  return (
    <Card className="p-5">
      <div className="flex items-center justify-between gap-4">
        <div>
          <span className="text-xs font-medium text-slate-500 uppercase tracking-wider">{title}</span>
          <div className="metric-value mt-1 text-2xl font-bold tracking-tight text-slate-900">{value}</div>
          {subtext ? <div className="mt-1 text-xs text-slate-500">{subtext}</div> : null}
        </div>
        {Icon ? (
          <div className={cx('grid size-11 shrink-0 place-items-center rounded-xl', iconBg)}>
            <Icon aria-hidden="true" className={cx('size-5', iconColor)} />
          </div>
        ) : null}
      </div>
    </Card>
  );
}

export type StatusTone = 'success' | 'warning' | 'danger' | 'info' | 'violet' | 'neutral';

const badgeToneClasses: Record<StatusTone, string> = {
  success: 'border-emerald-200 bg-emerald-50 text-emerald-700',
  warning: 'border-amber-200 bg-amber-50 text-amber-800',
  danger: 'border-rose-200 bg-rose-50 text-rose-700',
  info: 'border-sky-200 bg-sky-50 text-sky-700',
  violet: 'border-purple-200 bg-purple-50 text-purple-700',
  neutral: 'border-slate-200 bg-slate-100 text-slate-700',
};

export function StatusBadge({
  children,
  tone = 'neutral',
  className,
}: {
  children: ReactNode;
  tone?: StatusTone;
  className?: string;
}) {
  return (
    <span
      className={cx(
        'inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs font-semibold tracking-wide',
        badgeToneClasses[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

export function Accordion({
  title,
  children,
  defaultOpen = false,
  className,
}: {
  title: ReactNode;
  children: ReactNode;
  defaultOpen?: boolean;
  className?: string;
}) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div className={cx('rounded-xl border border-slate-200 bg-white overflow-hidden shadow-xs', className)}>
      <button
        aria-expanded={open}
        className="flex w-full items-center justify-between p-4 text-left font-medium text-slate-800 hover:bg-slate-50 transition cursor-pointer text-sm"
        type="button"
        onClick={() => setOpen((prev) => !prev)}
      >
        <span>{title}</span>
        <ChevronDown
          aria-hidden="true"
          className={cx('size-4 text-slate-500 transition-transform duration-200', open && 'rotate-180')}
        />
      </button>
      {open ? <div className="border-t border-slate-100 p-4 bg-slate-50/50">{children}</div> : null}
    </div>
  );
}

export function ErrorState({
  error,
  title,
  onRetry,
  compact = false,
}: {
  error: Error | ApiError | string;
  title?: string;
  onRetry?: () => void;
  compact?: boolean;
}) {
  const message = typeof error === 'string' ? error : error.message;

  if (compact) {
    return (
      <div className="flex items-center justify-between rounded-lg border border-rose-200 bg-rose-50/80 p-3 text-xs text-rose-700">
        <div className="flex items-center gap-2">
          <AlertTriangle aria-hidden="true" className="size-4 shrink-0 text-rose-600" />
          <span className="font-medium">{title ? `${title}: ` : ''}{message}</span>
        </div>
        {onRetry ? (
          <button
            className="inline-flex items-center gap-1 font-semibold text-rose-700 hover:underline cursor-pointer"
            type="button"
            onClick={onRetry}
          >
            <RefreshCw aria-hidden="true" className="size-3" /> Retry
          </button>
        ) : null}
      </div>
    );
  }

  return (
    <Card className="border-rose-200 bg-rose-50/40 p-6 text-center">
      <div className="mx-auto grid size-12 place-items-center rounded-full bg-rose-100 text-rose-600">
        <AlertTriangle aria-hidden="true" className="size-6" />
      </div>
      <h3 className="mt-3 text-base font-semibold text-slate-900">{title ?? 'An Error Occurred'}</h3>
      <p className="mt-1 text-sm text-slate-600 max-w-md mx-auto">{message}</p>
      {onRetry ? (
        <div className="mt-5">
          <Button size="sm" variant="secondary" onClick={onRetry}>
            <RefreshCw aria-hidden="true" className="size-3.5" /> Try Again
          </Button>
        </div>
      ) : null}
    </Card>
  );
}

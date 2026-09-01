/**
 * Display-only formatting. No arithmetic on money happens here beyond dividing
 * minor units by 100 for presentation — every ERV, probability, and rate is a value
 * the backend already computed.
 */

import type { Money } from '@/types/api';

const inrFormatter = new Intl.NumberFormat('en-IN', {
  style: 'currency',
  currency: 'INR',
  maximumFractionDigits: 0,
});

const inrFormatterPrecise = new Intl.NumberFormat('en-IN', {
  style: 'currency',
  currency: 'INR',
  maximumFractionDigits: 2,
});

/** Format minor units as a currency string, e.g. 1_000_000 -> "₹10,000". */
export function formatMoney(money: Money | number, precise = false): string {
  const amount = typeof money === 'number' ? money : money.amount;
  const rupees = amount / 100;
  return precise ? inrFormatterPrecise.format(rupees) : inrFormatter.format(rupees);
}

/** Compact form for dense tables and chart axes, e.g. ₹1.09L, ₹90.0K. */
export function formatMoneyCompact(money: Money | number): string {
  const amount = typeof money === 'number' ? money : money.amount;
  const rupees = amount / 100;
  const abs = Math.abs(rupees);

  if (abs >= 1_00_00_000) return `₹${(rupees / 1_00_00_000).toFixed(2)}Cr`;
  if (abs >= 1_00_000) return `₹${(rupees / 1_00_000).toFixed(2)}L`;
  if (abs >= 1_000) return `₹${(rupees / 1_000).toFixed(1)}K`;
  return `₹${rupees.toFixed(0)}`;
}

/** A 0..1 fraction as a percentage string, e.g. 0.2635 -> "26.35%". */
export function formatPercent(fraction: number, decimals = 2): string {
  return `${(fraction * 100).toFixed(decimals)}%`;
}

/** A signed percentage point delta, e.g. 25.07 -> "+25.07pp". */
export function formatPercentPoints(points: number, decimals = 2): string {
  const sign = points > 0 ? '+' : '';
  return `${sign}${points.toFixed(decimals)}pp`;
}

/** A signed relative-change percentage, e.g. 1957.92 -> "+1,957.92%". */
export function formatSignedPercent(pct: number, decimals = 1): string {
  const sign = pct > 0 ? '+' : pct < 0 ? '' : '';
  return `${sign}${pct.toLocaleString('en-IN', { maximumFractionDigits: decimals })}%`;
}

/** Title-case an ENUM_STYLE identifier for display: "BANK_TIMEOUT" -> "Bank Timeout". */
export function humanize(value: string): string {
  return value
    .toLowerCase()
    .split('_')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ');
}

/** Format an ISO timestamp as a compact local time, e.g. "13:15:00". */
export function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString('en-IN', { hour12: false });
}

/** Format an ISO timestamp as date + time. */
export function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString('en-IN', {
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  });
}

/** Relative time for an audit feed, e.g. "3m ago". Falls back to a time for old events. */
export function formatRelativeToNow(iso: string, nowIso: string): string {
  const diffMs = new Date(nowIso).getTime() - new Date(iso).getTime();
  const diffMin = Math.round(diffMs / 60_000);

  if (diffMin < 1) return 'just now';
  if (diffMin === 1) return '1m ago';
  if (diffMin < 60) return `${diffMin}m ago`;

  const diffHr = Math.round(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;

  return formatDateTime(iso);
}

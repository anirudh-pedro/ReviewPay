import { useMemo, useState } from 'react';
import { ChevronDown, ChevronUp, ClipboardList, FileText } from 'lucide-react';
import type { AuditEvent } from '@/types/api';
import { Card, CardHeader, EmptyState, StatusBadge, buttonClassName, cx } from '@/components/ui';
import { formatDateTime, humanize } from '@/utils/format';
import { auditEventTone } from '@/utils/recoveryPresentation';

const INITIAL_EVENT_COUNT = 5;

function metadataValue(value: unknown): string {
  if (typeof value === 'string') return value;
  if (value === null) return 'null';
  if (value === undefined) return 'undefined';

  try {
    return JSON.stringify(value) ?? String(value);
  } catch {
    return String(value);
  }
}

function AuditEventRow({ event, isLast }: { event: AuditEvent; isLast: boolean }) {
  const metadataEntries = Object.entries(event.metadata);
  const tone = auditEventTone(event.event_type);

  return (
    <li className="relative flex gap-3 pb-6 last:pb-0">
      {!isLast ? <span aria-hidden="true" className="absolute left-[0.84rem] top-7 h-[calc(100%-1rem)] w-px bg-white/[0.07]" /> : null}
      <span
        aria-hidden="true"
        className={cx(
          'relative z-10 mt-1 grid size-7 shrink-0 place-items-center rounded-full border bg-ink-850',
          tone === 'success' && 'border-recovered/35 text-recovered',
          tone === 'danger' && 'border-blocked/35 text-blocked',
          tone === 'violet' && 'border-escalated/35 text-escalated',
          tone === 'warning' && 'border-atrisk/35 text-atrisk',
          (tone === 'info' || tone === 'neutral') && 'border-white/[0.12] text-slate-400',
        )}
      >
        <span className="size-1.5 rounded-full bg-current" />
      </span>
      <div className="min-w-0 flex-1 pb-0.5">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <StatusBadge tone={tone}>{humanize(event.event_type)}</StatusBadge>
              <span className="font-mono text-[0.65rem] text-slate-600">#{String(event.sequence).padStart(2, '0')}</span>
            </div>
            <p className="mt-2 text-sm leading-6 text-slate-200">{event.message}</p>
          </div>
          <time className="shrink-0 font-mono text-[0.67rem] tabular-nums text-slate-500" dateTime={event.timestamp}>
            {formatDateTime(event.timestamp)}
          </time>
        </div>
        <p className="mt-1.5 text-[0.68rem] font-semibold uppercase tracking-[0.1em] text-slate-600">
          {humanize(event.stage)}
        </p>
        {metadataEntries.length > 0 ? (
          <details className="group mt-3 rounded-lg border border-white/[0.055] bg-ink-900/45 px-3 py-2.5">
            <summary className="flex cursor-pointer list-none items-center justify-between gap-3 text-xs font-medium text-slate-400 marker:hidden">
              Event evidence ({metadataEntries.length})
              <ChevronDown aria-hidden="true" className="size-3.5 text-slate-500 transition-transform group-open:rotate-180" />
            </summary>
            <dl className="mt-3 divide-y divide-white/[0.05] border-t border-white/[0.05]">
              {metadataEntries.map(([key, value]) => (
                <div key={key} className="grid gap-1 py-2.5 sm:grid-cols-[minmax(8rem,0.35fr)_1fr] sm:gap-3">
                  <dt className="font-mono text-[0.67rem] text-slate-500">{key}</dt>
                  <dd className="break-words font-mono text-[0.67rem] leading-5 text-slate-300">{metadataValue(value)}</dd>
                </div>
              ))}
            </dl>
          </details>
        ) : null}
      </div>
    </li>
  );
}

export function AuditTimeline({ events }: { events: AuditEvent[] }) {
  const [expanded, setExpanded] = useState(false);
  const orderedEvents = useMemo(
    () => [...events].sort((left, right) => left.sequence - right.sequence),
    [events],
  );
  const visibleEvents = expanded ? orderedEvents : orderedEvents.slice(0, INITIAL_EVENT_COUNT);
  const remainingCount = orderedEvents.length - visibleEvents.length;

  return (
    <Card className="overflow-hidden">
      <CardHeader className="items-center">
        <div>
          <div className="flex items-center gap-2">
            <ClipboardList aria-hidden="true" className="size-4 text-accent" />
            <p className="text-sm font-semibold text-slate-100">Audit timeline</p>
          </div>
          <p className="mt-1 text-xs leading-5 text-slate-500">
            Sequence-ordered evidence from the recovery workflow. Expand an event to inspect its recorded metadata.
          </p>
        </div>
        <StatusBadge tone="info">{orderedEvents.length} events</StatusBadge>
      </CardHeader>

      {orderedEvents.length === 0 ? (
        <EmptyState
          compact
          description="The backend has not recorded audit events for this case yet. Once a workflow cycle runs, its evidence will appear here."
          icon={FileText}
          title="No audit evidence yet"
        />
      ) : (
        <div className="px-5 pb-5 pt-6">
          <ol aria-label="Chronological audit events">
            {visibleEvents.map((event, index) => (
              <AuditEventRow key={event.event_id} event={event} isLast={index === visibleEvents.length - 1} />
            ))}
          </ol>
          {remainingCount > 0 ? (
            <button className={buttonClassName('secondary', 'sm', 'mt-5 w-full')} type="button" onClick={() => setExpanded(true)}>
              Show {remainingCount} earlier audit event{remainingCount === 1 ? '' : 's'}
              <ChevronDown aria-hidden="true" className="size-3.5" />
            </button>
          ) : expanded && orderedEvents.length > INITIAL_EVENT_COUNT ? (
            <button className={buttonClassName('ghost', 'sm', 'mt-5 w-full')} type="button" onClick={() => setExpanded(false)}>
              Collapse to recent events
              <ChevronUp aria-hidden="true" className="size-3.5" />
            </button>
          ) : null}
        </div>
      )}
    </Card>
  );
}

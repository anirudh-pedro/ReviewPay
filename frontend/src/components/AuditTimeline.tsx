import { useMemo, useState } from 'react';
import { ChevronDown, ChevronUp, FileText } from 'lucide-react';
import type { AuditEvent } from '@/types/api';
import { StatusBadge, buttonClassName, cx } from '@/components/ui';
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
      {!isLast ? <span aria-hidden="true" className="absolute left-[0.84rem] top-7 h-[calc(100%-1rem)] w-px bg-slate-200" /> : null}
      <span
        aria-hidden="true"
        className={cx(
          'relative z-10 mt-1 grid size-7 shrink-0 place-items-center rounded-full border bg-white shadow-2xs',
          tone === 'success' && 'border-emerald-300 text-emerald-600',
          tone === 'danger' && 'border-rose-300 text-rose-600',
          tone === 'violet' && 'border-purple-300 text-purple-600',
          tone === 'warning' && 'border-amber-300 text-amber-600',
          (tone === 'info' || tone === 'neutral') && 'border-slate-300 text-slate-500',
        )}
      >
        <span className="size-1.5 rounded-full bg-current" />
      </span>
      <div className="min-w-0 flex-1 pb-0.5">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <StatusBadge tone={tone}>{humanize(event.event_type)}</StatusBadge>
              <span className="font-mono text-[0.65rem] text-slate-500">#{String(event.sequence).padStart(2, '0')}</span>
            </div>
            <p className="mt-1.5 text-xs font-medium leading-relaxed text-slate-800">{event.message}</p>
          </div>
          <time className="shrink-0 font-mono text-[0.67rem] tabular-nums text-slate-400" dateTime={event.timestamp}>
            {formatDateTime(event.timestamp)}
          </time>
        </div>
        <p className="mt-1 text-[0.68rem] font-semibold uppercase tracking-[0.08em] text-slate-400">
          Stage: {humanize(event.stage)}
        </p>
        {metadataEntries.length > 0 ? (
          <details className="group mt-2 rounded-lg border border-slate-200 bg-slate-50 p-2.5">
            <summary className="flex cursor-pointer list-none items-center justify-between gap-3 text-xs font-medium text-slate-600 marker:hidden">
              <span className="inline-flex items-center gap-1.5">
                <FileText aria-hidden="true" className="size-3.5 text-slate-400" />
                Metadata ({metadataEntries.length})
              </span>
              <ChevronDown
                aria-hidden="true"
                className="size-3.5 text-slate-400 transition-transform group-open:rotate-180"
              />
            </summary>
            <dl className="mt-2 space-y-1 border-t border-slate-200 pt-2">
              {metadataEntries.map(([key, val]) => (
                <div key={key} className="flex justify-between gap-3 text-[0.7rem]">
                  <dt className="font-mono text-slate-500">{key}</dt>
                  <dd className="font-mono text-slate-700 break-all text-right">{metadataValue(val)}</dd>
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

  const displayedEvents = useMemo(() => {
    if (expanded || events.length <= INITIAL_EVENT_COUNT) return events;
    return events.slice(0, INITIAL_EVENT_COUNT);
  }, [events, expanded]);

  if (events.length === 0) {
    return (
      <div className="text-center py-6 text-xs text-slate-400">
        No audit events recorded yet.
      </div>
    );
  }

  return (
    <div>
      <ol className="relative space-y-1">
        {displayedEvents.map((event, idx) => (
          <AuditEventRow
            key={event.event_id || idx}
            event={event}
            isLast={idx === displayedEvents.length - 1}
          />
        ))}
      </ol>

      {events.length > INITIAL_EVENT_COUNT ? (
        <div className="mt-4 pt-3 border-t border-slate-100 text-center">
          <button
            type="button"
            className={buttonClassName('ghost', 'sm', 'text-xs text-indigo-600 hover:text-indigo-800')}
            onClick={() => setExpanded(!expanded)}
          >
            {expanded ? (
              <>
                <ChevronUp className="size-3.5 mr-1" /> Show fewer events
              </>
            ) : (
              <>
                <ChevronDown className="size-3.5 mr-1" /> Show all {events.length} events
              </>
            )}
          </button>
        </div>
      ) : null}
    </div>
  );
}

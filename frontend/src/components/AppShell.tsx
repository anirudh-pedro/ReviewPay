import {
  Activity,
  Beaker,
  Bot,
  ChevronRight,
  Clock3,
  CreditCard,
  LayoutDashboard,
  Menu,
  RotateCcw,
  ServerCog,
  X,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { useState } from 'react';
import { NavLink, Outlet, useLocation } from 'react-router-dom';
import { getClock, getHealth } from '@/api';
import { useDemoData } from '@/contexts/DemoDataContext';
import { useApi } from '@/hooks/useApi';
import { DemoResetModal } from './DemoResetModal';
import { formatDateTime } from '@/utils/format';
import { Button, StatusBadge, buttonClassName, cx } from './ui';

interface NavigationItem {
  label: string;
  detail: string;
  to: string;
  icon: LucideIcon;
}

const navigation: NavigationItem[] = [
  {
    label: 'Command Center',
    detail: 'Executive dashboard',
    to: '/command-center',
    icon: LayoutDashboard,
  },
  { label: 'Cases', detail: 'Recovery queue', to: '/cases', icon: Activity },
  { label: 'Autopilot', detail: 'Batch operations', to: '/autopilot', icon: Bot },
  { label: 'Strategy Lab', detail: 'What-if analysis', to: '/strategy-lab', icon: Beaker },
  { label: 'Live Gateway Demo', detail: 'Razorpay Sandbox', to: '/live-gateway-demo', icon: CreditCard },
];

const pageDetails: Record<string, { title: string; description: string }> = {
  '/command-center': {
    title: 'Command Center',
    description: 'Synthetic revenue recovery at a glance.',
  },
  '/cases': { title: 'Cases', description: 'Recovery case operations.' },
  '/autopilot': { title: 'Autopilot', description: 'Batch recovery operations.' },
  '/strategy-lab': { title: 'Strategy Lab', description: 'Compare server-evaluated strategies.' },
  '/live-gateway-demo': { title: 'Live Gateway Demo', description: 'Isolated Razorpay Sandbox Checkout.' },
};

function BrandMark() {
  return (
    <div className="grid size-9 place-items-center rounded-xl border border-accent/30 bg-accent/10 shadow-[0_0_22px_-8px_rgba(56,189,248,0.7)]">
      <svg aria-hidden="true" className="size-5 text-accent" fill="none" viewBox="0 0 24 24">
        <path d="M5 12.5 9.2 16.7 19 6.8" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.3" />
        <path d="M5 7.5h5.25" stroke="currentColor" strokeLinecap="round" strokeWidth="2" />
      </svg>
    </div>
  );
}

function NavigationList({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <nav aria-label="Primary navigation" className="space-y-1 px-3">
      {navigation.map((item) => {
        const Icon = item.icon;
        return (
          <NavLink
            key={item.to}
            className={({ isActive }) =>
              cx(
                'group flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent',
                isActive
                  ? 'bg-accent/10 text-sky-200 shadow-[inset_2px_0_0_0_#38bdf8]'
                  : 'text-slate-400 hover:bg-white/[0.035] hover:text-slate-100',
              )
            }
            onClick={onNavigate}
            to={item.to}
          >
            <Icon aria-hidden="true" className="size-[18px] shrink-0" />
            <span className="min-w-0 flex-1">
              <span className="block font-medium">{item.label}</span>
              <span className="mt-0.5 block truncate text-[0.68rem] text-slate-500 group-[.active]:text-sky-300/70">
                {item.detail}
              </span>
            </span>
            <ChevronRight aria-hidden="true" className="size-3.5 opacity-0 transition-opacity group-hover:opacity-70" />
          </NavLink>
        );
      })}
    </nav>
  );
}

function Sidebar({ mobile = false, onNavigate }: { mobile?: boolean; onNavigate?: () => void }) {
  return (
    <div className={cx('flex h-full flex-col bg-ink-900', mobile ? 'w-[min(19rem,calc(100vw-3rem))]' : 'w-60')}>
      <div className="flex h-[73px] items-center gap-3 border-b border-white/[0.06] px-5">
        <BrandMark />
        <div>
          <p className="text-sm font-bold tracking-tight text-slate-100">RevivePay</p>
          <p className="mt-0.5 text-[0.66rem] font-medium uppercase tracking-[0.16em] text-slate-500">Command Center</p>
        </div>
      </div>
      <div className="flex-1 py-5">
        <p className="mb-2 px-6 text-[0.65rem] font-semibold uppercase tracking-[0.16em] text-slate-500">Workspace</p>
        <NavigationList onNavigate={onNavigate} />
      </div>
      <div className="m-3 rounded-xl border border-white/[0.06] bg-white/[0.025] p-3">
        <div className="flex items-center gap-2 text-xs font-semibold text-slate-300">
          <ServerCog aria-hidden="true" className="size-3.5 text-accent" />
          Simulation environment
        </div>
        <p className="mt-1.5 text-xs leading-5 text-slate-500">All recovery figures are synthetic. No real money moves.</p>
      </div>
    </div>
  );
}

function ServiceStatus() {
  const { dataVersion } = useDemoData();
  const health = useApi(getHealth, [dataVersion]);
  const clock = useApi(getClock, [dataVersion]);
  const isHealthy = health.data?.status.toLowerCase() === 'ok';

  return (
    <div className="flex min-w-0 items-center gap-2 sm:gap-3">
      <div className="hidden min-w-0 items-center gap-2 rounded-lg border border-white/[0.06] bg-ink-850 px-2.5 py-1.5 sm:flex">
        <Clock3 aria-hidden="true" className="size-3.5 shrink-0 text-slate-400" />
        <div className="min-w-0">
          <p className="text-[0.62rem] font-semibold uppercase tracking-[0.12em] text-slate-500">Virtual clock</p>
          <time
            className="block truncate font-mono text-[0.68rem] tabular-nums text-slate-300"
            dateTime={clock.data?.virtual_clock_time}
          >
            {clock.data ? formatDateTime(clock.data.virtual_clock_time) : clock.error ? 'Clock unavailable' : 'Syncing clock…'}
          </time>
        </div>
      </div>
      <StatusBadge tone={health.loading ? 'neutral' : isHealthy ? 'success' : 'danger'}>
        <span
          aria-hidden="true"
          className={cx(
            'size-1.5 rounded-full',
            health.loading ? 'bg-slate-500' : isHealthy ? 'bg-recovered shadow-[0_0_8px_#22c55e]' : 'bg-blocked',
          )}
        />
        <span className="hidden sm:inline">{health.loading ? 'Checking API' : isHealthy ? 'API online' : 'API offline'}</span>
        <span className="sm:hidden">{isHealthy ? 'Live' : health.loading ? 'Sync' : 'Offline'}</span>
      </StatusBadge>
    </div>
  );
}

export function AppShell() {
  const location = useLocation();
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [demoResetOpen, setDemoResetOpen] = useState(false);
  const currentPage = location.pathname.startsWith('/cases/')
    ? {
        title: 'Case Intelligence',
        description: 'Decision, policy, execution, and audit evidence.',
      }
    : pageDetails[location.pathname] ?? pageDetails['/command-center'];

  return (
    <div className="min-h-screen bg-ink-950 text-slate-100">
      {demoResetOpen ? <DemoResetModal onClose={() => setDemoResetOpen(false)} /> : null}
      <aside className="fixed inset-y-0 left-0 z-30 hidden border-r border-white/[0.06] lg:block">
        <Sidebar />
      </aside>

      {mobileNavOpen ? (
        <div className="fixed inset-0 z-50 lg:hidden" role="dialog" aria-label="Navigation menu" aria-modal="true">
          <button
            aria-label="Close navigation menu"
            className="absolute inset-0 bg-black/65 backdrop-blur-[2px]"
            onClick={() => setMobileNavOpen(false)}
            type="button"
          />
          <div className="relative h-full shadow-2xl shadow-black/50">
            <Button
              aria-label="Close navigation menu"
              className="absolute right-3 top-4 z-10"
              size="sm"
              variant="ghost"
              onClick={() => setMobileNavOpen(false)}
            >
              <X aria-hidden="true" className="size-4" />
            </Button>
            <Sidebar mobile onNavigate={() => setMobileNavOpen(false)} />
          </div>
        </div>
      ) : null}

      <div className="min-h-screen lg:pl-60">
        <header className="sticky top-0 z-20 border-b border-white/[0.06] bg-ink-950/85 backdrop-blur-xl">
          <div className="flex min-h-[73px] items-center justify-between gap-3 px-4 sm:px-6 lg:px-8">
            <div className="flex min-w-0 items-center gap-2.5">
              <Button
                aria-expanded={mobileNavOpen}
                aria-label="Open navigation menu"
                className="lg:hidden"
                size="sm"
                variant="ghost"
                onClick={() => setMobileNavOpen(true)}
              >
                <Menu aria-hidden="true" className="size-4" />
              </Button>
              <div className="min-w-0">
                <p className="truncate text-base font-semibold tracking-tight text-slate-100">{currentPage.title}</p>
                <p className="hidden truncate text-xs text-slate-500 sm:block">{currentPage.description}</p>
              </div>
            </div>
            <div className="flex shrink-0 items-center gap-2 sm:gap-3">
              <ServiceStatus />
              <button
                className={buttonClassName('secondary', 'sm', 'hidden md:inline-flex')}
                title="Reset the local deterministic demo dataset and virtual clock."
                type="button"
                onClick={() => setDemoResetOpen(true)}
              >
                <RotateCcw aria-hidden="true" className="size-3.5" />
                Demo reset
              </button>
            </div>
          </div>
        </header>
        <main className="mx-auto w-full max-w-[1600px] px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

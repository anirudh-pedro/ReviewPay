import {
  Activity,
  Award,
  Beaker,
  Bot,
  ChevronRight,
  Clock3,
  CreditCard,
  LayoutDashboard,
  Menu,
  RotateCcw,
  X,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { useState } from 'react';
import { NavLink, Outlet, useLocation } from 'react-router-dom';
import { getClock, getHealth } from '@/api';
import { useApi } from '@/hooks/useApi';
import { DemoResetModal } from './DemoResetModal';
import { formatDateTime } from '@/utils/format';
import { Button, StatusBadge, cx } from './ui';

interface NavigationItem {
  label: string;
  detail: string;
  to: string;
  icon: LucideIcon;
}

const navigation: NavigationItem[] = [
  {
    label: 'Dashboard',
    detail: 'Executive KPIs',
    to: '/command-center',
    icon: LayoutDashboard,
  },
  { label: 'Recovery Cases', detail: 'Queue & detail', to: '/cases', icon: Activity },
  { label: 'Judge Demo', detail: '8-stage proof flow', to: '/judge-demo', icon: Award },
  { label: 'Autopilot', detail: 'Batch automation', to: '/autopilot', icon: Bot },
  { label: 'Strategy Lab', detail: 'What-if simulation', to: '/strategy-lab', icon: Beaker },
  { label: 'Razorpay Sandbox', detail: 'Gateway test', to: '/live-gateway-demo', icon: CreditCard },
];

const pageDetails: Record<string, { title: string; description: string }> = {
  '/command-center': {
    title: 'Executive Dashboard',
    description: 'Real-time synthetic revenue recovery performance & KPIs.',
  },
  '/cases': { title: 'Recovery Cases', description: 'Interactive case operations and evidence inspection.' },
  '/judge-demo': { title: 'Judge Demo Flow', description: 'Buildathon 8-stage proof verification pipeline.' },
  '/autopilot': { title: 'Autopilot', description: 'Automated batch recovery operations.' },
  '/strategy-lab': { title: 'Strategy Lab', description: 'Simulate & compare recovery strategies.' },
  '/live-gateway-demo': { title: 'Razorpay Sandbox', description: 'Isolated Razorpay Sandbox Checkout integration.' },
};

function BrandMark() {
  return (
    <div className="grid size-9 place-items-center rounded-xl border border-sky-400/30 bg-sky-500/10 shadow-[0_0_22px_-8px_rgba(56,189,248,0.7)]">
      <svg aria-hidden="true" className="size-5 text-sky-400" fill="none" viewBox="0 0 24 24">
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
                'group flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400',
                isActive
                  ? 'bg-sky-500/15 font-semibold text-sky-300 border border-sky-400/20'
                  : 'text-slate-400 hover:bg-slate-800/60 hover:text-slate-200',
              )
            }
            to={item.to}
            onClick={onNavigate}
          >
            <Icon aria-hidden="true" className="size-4 shrink-0 transition-transform group-hover:scale-105" />
            <div className="flex-1 truncate">
              <div className="leading-tight">{item.label}</div>
              <div className="text-[0.68rem] font-normal text-slate-500">{item.detail}</div>
            </div>
            <ChevronRight aria-hidden="true" className="size-3.5 opacity-0 transition-opacity group-hover:opacity-100" />
          </NavLink>
        );
      })}
    </nav>
  );
}

export function AppShell() {
  const location = useLocation();
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [resetModalOpen, setResetModalOpen] = useState(false);

  const healthQuery = useApi(getHealth, []);
  const clockQuery = useApi(getClock, []);

  const page = pageDetails[location.pathname] ?? {
    title: 'RevivePay Command Center',
    description: 'AI Revenue Recovery Platform',
  };

  return (
    <div className="flex min-h-screen bg-slate-950 text-slate-100">
      {/* Desktop Sidebar */}
      <aside className="hidden w-64 shrink-0 flex-col border-r border-white/[0.06] bg-slate-900/60 backdrop-blur-xl lg:flex">
        <div className="flex h-16 items-center gap-3 px-5 border-b border-white/[0.06]">
          <BrandMark />
          <div>
            <span className="font-bold tracking-tight text-slate-50">RevivePay</span>
            <span className="ml-2 font-mono text-[0.625rem] text-sky-400 uppercase tracking-widest">v0.4.0</span>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto py-4">
          <NavigationList />
        </div>

        <div className="border-t border-white/[0.06] p-4">
          <Button
            className="w-full justify-start text-slate-300 hover:text-white"
            size="sm"
            variant="ghost"
            onClick={() => setResetModalOpen(true)}
          >
            <RotateCcw aria-hidden="true" className="size-3.5" />
            Reseed Demo Scenarios
          </Button>
        </div>
      </aside>

      {/* Main Content Area */}
      <div className="flex flex-1 flex-col overflow-hidden">
        {/* Top App Bar */}
        <header className="flex h-16 items-center justify-between border-b border-white/[0.06] bg-slate-900/40 px-4 sm:px-6 backdrop-blur-md">
          <div className="flex items-center gap-3">
            <button
              aria-label="Open mobile navigation"
              className="grid size-9 place-items-center rounded-lg border border-white/[0.08] bg-slate-800/60 text-slate-300 lg:hidden"
              type="button"
              onClick={() => setMobileMenuOpen(true)}
            >
              <Menu aria-hidden="true" className="size-5" />
            </button>
            <div>
              <h1 className="text-base font-semibold tracking-tight text-slate-100 sm:text-lg">
                {page.title}
              </h1>
            </div>
          </div>

          <div className="flex items-center gap-3">
            {clockQuery.data?.virtual_clock_time ? (
              <div className="hidden items-center gap-1.5 font-mono text-xs text-slate-400 sm:flex">
                <Clock3 aria-hidden="true" className="size-3.5 text-sky-400" />
                <span>Sim: {formatDateTime(clockQuery.data.virtual_clock_time)}</span>
              </div>
            ) : null}

            <StatusBadge tone="info">
              {healthQuery.data?.environment_profile ?? 'DEMO'} MODE
            </StatusBadge>
          </div>
        </header>

        {/* Mobile Navigation Drawer */}
        {mobileMenuOpen ? (
          <div className="fixed inset-0 z-50 flex bg-black/80 lg:hidden">
            <div className="w-72 border-r border-white/[0.08] bg-slate-900 p-4">
              <div className="flex items-center justify-between pb-4">
                <div className="flex items-center gap-3">
                  <BrandMark />
                  <span className="font-bold text-slate-100">RevivePay</span>
                </div>
                <button
                  aria-label="Close menu"
                  className="rounded-lg p-2 text-slate-400 hover:text-white"
                  type="button"
                  onClick={() => setMobileMenuOpen(false)}
                >
                  <X aria-hidden="true" className="size-5" />
                </button>
              </div>
              <NavigationList onNavigate={() => setMobileMenuOpen(false)} />
            </div>
          </div>
        ) : null}

        {/* Page Body */}
        <main className="flex-1 overflow-y-auto p-4 sm:p-6 lg:p-8">
          <div className="mx-auto max-w-7xl">
            <Outlet />
          </div>
        </main>
      </div>

      {resetModalOpen ? <DemoResetModal onClose={() => setResetModalOpen(false)} /> : null}
    </div>
  );
}

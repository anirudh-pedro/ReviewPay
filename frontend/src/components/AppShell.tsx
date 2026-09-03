import {
  Activity,
  ChevronRight,
  Clock3,
  LayoutDashboard,
  Menu,
  X,
  Zap,
  ShieldCheck,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { useState } from 'react';
import { NavLink, Outlet, useLocation } from 'react-router-dom';
import { getClock, getHealth } from '@/api';
import { useApi } from '@/hooks/useApi';
import { formatDateTime } from '@/utils/format';
import { StatusBadge, cx } from './ui';

interface NavigationItem {
  label: string;
  detail: string;
  to: string;
  icon: LucideIcon;
}

const navigation: NavigationItem[] = [
  {
    label: 'Recovery Simulator',
    detail: 'Razorpay Sandbox ➔ RevivePay',
    to: '/simulator',
    icon: Zap,
  },
  {
    label: 'Recovery Cases & Audit',
    detail: 'Case queue & decisions',
    to: '/cases',
    icon: Activity,
  },
  {
    label: 'Executive Dashboard',
    detail: 'Revenue performance & KPIs',
    to: '/dashboard',
    icon: LayoutDashboard,
  },
];

const pageDetails: Record<string, { title: string; description: string }> = {
  '/simulator': {
    title: 'Recovery Simulator',
    description: 'Razorpay Sandbox Checkout ➔ Failure Scenario ➔ RevivePay Autonomous Recovery.',
  },
  '/': {
    title: 'Recovery Simulator',
    description: 'Razorpay Sandbox Checkout ➔ Failure Scenario ➔ RevivePay Autonomous Recovery.',
  },
  '/cases': {
    title: 'Recovery Cases & Audit',
    description: 'Interactive case queue, explainable decisions, and immutable audit events.',
  },
  '/dashboard': {
    title: 'Executive Dashboard',
    description: 'Executive revenue recovery metrics, performance trends, and safety guard statistics.',
  },
};

function BrandMark() {
  return (
    <div className="grid size-9 place-items-center rounded-xl bg-indigo-600 shadow-sm text-white">
      <svg aria-hidden="true" className="size-5" fill="none" viewBox="0 0 24 24">
        <path d="M5 12.5 9.2 16.7 19 6.8" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.5" />
        <path d="M5 7.5h5.25" stroke="currentColor" strokeLinecap="round" strokeWidth="2.2" />
      </svg>
    </div>
  );
}

function NavigationList({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <nav aria-label="Primary navigation" className="space-y-1.5 px-3">
      {navigation.map((item) => {
        const Icon = item.icon;
        return (
          <NavLink
            key={item.to}
            className={({ isActive }) =>
              cx(
                'group flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500',
                isActive
                  ? 'bg-indigo-50 font-semibold text-indigo-700 border border-indigo-100 shadow-xs'
                  : 'text-slate-600 hover:bg-slate-100/70 hover:text-slate-900',
              )
            }
            to={item.to}
            onClick={onNavigate}
          >
            <Icon aria-hidden="true" className="size-4.5 shrink-0 transition-transform group-hover:scale-105" />
            <div className="flex-1 truncate">
              <div className="leading-tight font-medium">{item.label}</div>
              <div className="text-[0.7rem] text-slate-500">{item.detail}</div>
            </div>
            <ChevronRight aria-hidden="true" className="size-3.5 opacity-0 transition-opacity group-hover:opacity-100 text-slate-400" />
          </NavLink>
        );
      })}
    </nav>
  );
}

export function AppShell() {
  const location = useLocation();
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  const healthQuery = useApi(getHealth, []);
  const clockQuery = useApi(getClock, []);

  const page = pageDetails[location.pathname] ?? {
    title: 'RevivePay Recovery Platform',
    description: 'Autonomous Revenue Recovery System',
  };

  return (
    <div className="flex min-h-screen bg-slate-50 text-slate-900">
      {/* Desktop Sidebar */}
      <aside className="hidden w-64 shrink-0 flex-col border-r border-slate-200 bg-white lg:flex">
        <div className="flex h-16 items-center gap-3 px-5 border-b border-slate-100">
          <BrandMark />
          <div>
            <span className="font-bold tracking-tight text-slate-900 text-base">RevivePay</span>
            <span className="ml-2 font-mono text-[0.625rem] text-indigo-600 font-semibold bg-indigo-50 px-1.5 py-0.5 rounded border border-indigo-100">PROD</span>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto py-5">
          <div className="px-5 mb-2 text-[10px] font-bold text-slate-400 uppercase tracking-wider">
            Navigation
          </div>
          <NavigationList />
        </div>

        {/* Live gateway connection indicator */}
        <div className="border-t border-slate-100 p-4">
          <div className="rounded-xl border border-slate-200/80 bg-slate-50/70 p-3 text-xs">
            <div className="flex items-center gap-1.5 font-semibold text-slate-800">
              <span className="size-2 rounded-full bg-emerald-500 animate-pulse" />
              Razorpay Sandbox Live
            </div>
            <p className="mt-1 text-[11px] text-slate-500">Autonomous recovery pipeline enabled</p>
          </div>
        </div>
      </aside>

      {/* Main Content Area */}
      <div className="flex flex-1 flex-col overflow-hidden">
        {/* Top App Bar */}
        <header className="flex h-16 items-center justify-between border-b border-slate-200 bg-white px-4 sm:px-6">
          <div className="flex items-center gap-3">
            <button
              aria-label="Open mobile navigation"
              className="grid size-9 place-items-center rounded-lg border border-slate-200 bg-slate-50 text-slate-700 lg:hidden"
              type="button"
              onClick={() => setMobileMenuOpen(true)}
            >
              <Menu aria-hidden="true" className="size-5" />
            </button>
            <div>
              <h1 className="text-base font-semibold tracking-tight text-slate-900 sm:text-lg">
                {page.title}
              </h1>
              <p className="hidden text-xs text-slate-500 sm:block">{page.description}</p>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <StatusBadge tone="neutral" className="hidden sm:inline-flex bg-slate-50 border-slate-200 text-slate-600">
              <ShieldCheck className="size-3 text-indigo-600" />
              PolicyEngine Gated
            </StatusBadge>

            {healthQuery.data ? (
              <StatusBadge tone={healthQuery.data.status === 'HEALTHY' ? 'success' : 'warning'}>
                API {healthQuery.data.status}
              </StatusBadge>
            ) : null}

            {clockQuery.data ? (
              <div className="hidden items-center gap-1.5 rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs text-slate-600 md:flex">
                <Clock3 aria-hidden="true" className="size-3.5 text-slate-500" />
                <span className="font-mono text-[11px] font-medium">{formatDateTime(clockQuery.data.virtual_clock_time)}</span>
              </div>
            ) : null}
          </div>
        </header>

        {/* Mobile Navigation Drawer */}
        {mobileMenuOpen && (
          <div className="fixed inset-0 z-50 flex lg:hidden">
            <div
              className="fixed inset-0 bg-slate-900/30 backdrop-blur-xs"
              onClick={() => setMobileMenuOpen(false)}
            />
            <div className="relative flex w-full max-w-xs flex-1 flex-col bg-white border-r border-slate-200 p-5 shadow-xl">
              <div className="flex items-center justify-between pb-4 border-b border-slate-100">
                <div className="flex items-center gap-2.5">
                  <BrandMark />
                  <span className="font-bold text-slate-900">RevivePay</span>
                </div>
                <button
                  aria-label="Close menu"
                  className="rounded-lg p-1 text-slate-500 hover:bg-slate-100"
                  type="button"
                  onClick={() => setMobileMenuOpen(false)}
                >
                  <X className="size-5" />
                </button>
              </div>

              <div className="mt-5 flex-1">
                <NavigationList onNavigate={() => setMobileMenuOpen(false)} />
              </div>
            </div>
          </div>
        )}

        {/* View Outlet Container */}
        <main className="flex-1 overflow-y-auto p-4 sm:p-6 lg:p-8">
          <div className="mx-auto max-w-7xl">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}

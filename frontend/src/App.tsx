import { lazy, Suspense } from 'react';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { AppShell } from '@/components/AppShell';

const ExecutiveDashboard = lazy(() => import('@/pages/ExecutiveDashboard').then((module) => ({ default: module.ExecutiveDashboard })));
const CasesPage = lazy(() => import('@/pages/CasesPage').then((module) => ({ default: module.CasesPage })));
const CaseDetailPage = lazy(() => import('@/pages/CaseDetailPage').then((module) => ({ default: module.CaseDetailPage })));
const AutopilotPage = lazy(() => import('@/pages/AutopilotPage').then((module) => ({ default: module.AutopilotPage })));
const StrategyLabPage = lazy(() => import('@/pages/StrategyLabPage').then((module) => ({ default: module.StrategyLabPage })));
const LiveGatewayDemoPage = lazy(() => import('@/pages/LiveGatewayDemoPage').then((module) => ({ default: module.LiveGatewayDemoPage })));

function RouteLoading() {
  return <main className="grid min-h-48 place-items-center p-6" aria-live="polite">Loading Command Center view…</main>;
}

export default function App() {
  return (
    <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <Suspense fallback={<RouteLoading />}>
        <Routes>
          <Route element={<AppShell />}>
            <Route index element={<Navigate replace to="/command-center" />} />
            <Route path="command-center" element={<ExecutiveDashboard />} />
            <Route path="cases" element={<CasesPage />} />
            <Route path="cases/:caseId" element={<CaseDetailPage />} />
            <Route path="autopilot" element={<AutopilotPage />} />
            <Route path="strategy-lab" element={<StrategyLabPage />} />
            <Route path="live-gateway-demo" element={<LiveGatewayDemoPage />} />
            <Route path="*" element={<Navigate replace to="/command-center" />} />
          </Route>
        </Routes>
      </Suspense>
    </BrowserRouter>
  );
}

import { lazy, Suspense } from 'react';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { AppShell } from '@/components/AppShell';

const RecoverySimulatorPage = lazy(() =>
  import('@/pages/RecoverySimulatorPage').then((module) => ({ default: module.RecoverySimulatorPage })),
);
const CasesPage = lazy(() => import('@/pages/CasesPage').then((module) => ({ default: module.CasesPage })));
const CaseDetailPage = lazy(() =>
  import('@/pages/CaseDetailPage').then((module) => ({ default: module.CaseDetailPage })),
);
const ExecutiveDashboard = lazy(() =>
  import('@/pages/ExecutiveDashboard').then((module) => ({ default: module.ExecutiveDashboard })),
);
const CustomerRecoveryPage = lazy(() =>
  import('@/pages/CustomerRecoveryPage').then((module) => ({ default: module.CustomerRecoveryPage })),
);

function RouteLoading() {
  return (
    <main className="grid min-h-48 place-items-center p-6 text-slate-400 text-sm" aria-live="polite">
      Loading RevivePay Recovery view…
    </main>
  );
}

export default function App() {
  return (
    <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <Suspense fallback={<RouteLoading />}>
        <Routes>
          {/* Customer Recovery Checkout Portal (Standalone) */}
          <Route path="recover/:caseId" element={<CustomerRecoveryPage />} />

          {/* Operator Recovery Command Center Shell */}
          <Route element={<AppShell />}>
            <Route index element={<RecoverySimulatorPage />} />
            <Route path="simulator" element={<RecoverySimulatorPage />} />
            <Route path="cases" element={<CasesPage />} />
            <Route path="cases/:caseId" element={<CaseDetailPage />} />
            <Route path="dashboard" element={<ExecutiveDashboard />} />
            <Route path="command-center" element={<ExecutiveDashboard />} />
            <Route path="*" element={<Navigate replace to="/simulator" />} />
          </Route>
        </Routes>
      </Suspense>
    </BrowserRouter>
  );
}

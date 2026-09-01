import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { AppShell } from '@/components/AppShell';
import { AutopilotPage } from '@/pages/AutopilotPage';
import { ExecutiveDashboard } from '@/pages/ExecutiveDashboard';
import { CasesPage } from '@/pages/CasesPage';
import { CaseDetailPage } from '@/pages/CaseDetailPage';
import { StrategyLabPage } from '@/pages/StrategyLabPage';

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<AppShell />}>
          <Route index element={<Navigate replace to="/command-center" />} />
          <Route path="command-center" element={<ExecutiveDashboard />} />
          <Route path="cases" element={<CasesPage />} />
          <Route path="cases/:caseId" element={<CaseDetailPage />} />
          <Route path="autopilot" element={<AutopilotPage />} />
          <Route path="strategy-lab" element={<StrategyLabPage />} />
          <Route path="*" element={<Navigate replace to="/command-center" />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}

import { createContext, useCallback, useContext, useMemo, useState } from 'react';
import type { ReactNode } from 'react';

interface DemoDataContextValue {
  /** Changes after any backend mutation so persistent/read views refetch. */
  dataVersion: number;
  /** Changes only after destructive reseeding, so pages can discard stale demo results. */
  demoResetVersion: number;
  /** Marks the synthetic dataset as replaced and clears demo-specific view state. */
  invalidateDemoData: () => void;
  /** Marks regular recovery mutations (manual run or Autopilot) as fresh live data. */
  refreshLiveData: () => void;
}

const DemoDataContext = createContext<DemoDataContextValue | null>(null);

export function DemoDataProvider({ children }: { children: ReactNode }) {
  const [dataVersion, setDataVersion] = useState(0);
  const [demoResetVersion, setDemoResetVersion] = useState(0);
  const refreshLiveData = useCallback(() => setDataVersion((version) => version + 1), []);
  const invalidateDemoData = useCallback(() => {
    setDataVersion((version) => version + 1);
    setDemoResetVersion((version) => version + 1);
  }, []);
  const value = useMemo(
    () => ({ dataVersion, demoResetVersion, invalidateDemoData, refreshLiveData }),
    [dataVersion, demoResetVersion, invalidateDemoData, refreshLiveData],
  );

  return <DemoDataContext.Provider value={value}>{children}</DemoDataContext.Provider>;
}

export function useDemoData(): DemoDataContextValue {
  const context = useContext(DemoDataContext);
  if (!context) throw new Error('useDemoData must be used inside DemoDataProvider.');
  return context;
}

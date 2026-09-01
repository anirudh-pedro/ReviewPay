import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import { AppErrorBoundary } from './components/ErrorBoundary';
import { ToastProvider } from './components/Toast';
import { DemoDataProvider } from './contexts/DemoDataContext';
import './styles/index.css';

const rootElement = document.getElementById('root');

if (!rootElement) {
  throw new Error('RevivePay could not find the application root.');
}

createRoot(rootElement).render(
  <StrictMode>
    <AppErrorBoundary>
      <ToastProvider>
        <DemoDataProvider>
          <App />
        </DemoDataProvider>
      </ToastProvider>
    </AppErrorBoundary>
  </StrictMode>,
);

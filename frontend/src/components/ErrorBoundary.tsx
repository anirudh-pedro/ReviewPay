import { Component } from 'react';
import type { ErrorInfo, ReactNode } from 'react';
import { ErrorState } from './ui';

interface ErrorBoundaryProps {
  children: ReactNode;
}

interface ErrorBoundaryState {
  error: Error | null;
}

/** A last-resort operator-safe fallback for unexpected render failures. */
export class AppErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  override state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  override componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
    console.error('RevivePay Command Center render error', error, errorInfo);
  }

  private reset = () => {
    this.setState({ error: null });
  };

  override render(): ReactNode {
    if (this.state.error) {
      return (
        <main className="grid min-h-screen place-items-center bg-ink-950 px-5">
          <ErrorState
            error={this.state.error}
            title="The Command Center could not render"
            onRetry={this.reset}
          />
        </main>
      );
    }

    return this.props.children;
  }
}

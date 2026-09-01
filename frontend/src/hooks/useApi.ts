/**
 * Shared async state for the small set of RevivePay read and action endpoints.
 *
 * Read requests are aborted on dependency changes and unmount. Mutating actions
 * do not silently retry; callers decide when an operator intentionally runs one.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import type { DependencyList } from 'react';
import { isAbortError, toApiError } from '@/api/client';
import type { ApiError } from '@/api/client';

export interface AsyncState<T> {
  data: T | null;
  loading: boolean;
  error: ApiError | null;
  refetch: () => void;
}

export interface AsyncActionState<Args extends unknown[], T> {
  data: T | null;
  loading: boolean;
  error: ApiError | null;
  run: (...args: Args) => Promise<T>;
  reset: () => void;
}

export function useApi<T>(
  fetcher: (signal: AbortSignal) => Promise<T>,
  deps: DependencyList = [],
): AsyncState<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const [nonce, setNonce] = useState(0);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);

    // Starting from a resolved promise also normalizes a synchronously thrown
    // fetcher into the same API error state as an asynchronously rejected one.
    void Promise.resolve()
      .then(() => fetcherRef.current(controller.signal))
      .then((result) => {
        if (!controller.signal.aborted) {
          setData(result);
          setLoading(false);
        }
      })
      .catch((cause: unknown) => {
        if (controller.signal.aborted || isAbortError(cause)) return;
        setError(toApiError(cause));
        setLoading(false);
      });

    return () => controller.abort();
    // The caller owns semantic dependencies. fetcherRef avoids requiring
    // memoization just to keep an inline endpoint function stable.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nonce, ...deps]);

  const refetch = useCallback(() => setNonce((value) => value + 1), []);

  return { data, loading, error, refetch };
}

/**
 * Shared state for intentional POST-triggered operator actions.
 *
 * A newer action (or reset) supersedes older pending actions, preventing an
 * obsolete response from replacing the operator's most recent state.
 */
export function useAsyncAction<Args extends unknown[], T>(
  action: (...args: Args) => Promise<T>,
): AsyncActionState<Args, T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const actionRef = useRef(action);
  const mountedRef = useRef(true);
  const requestIdRef = useRef(0);
  actionRef.current = action;

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const run = useCallback(async (...args: Args): Promise<T> => {
    const requestId = requestIdRef.current + 1;
    requestIdRef.current = requestId;

    if (mountedRef.current) {
      setLoading(true);
      setError(null);
    }

    try {
      const result = await actionRef.current(...args);
      if (mountedRef.current && requestId === requestIdRef.current) setData(result);
      return result;
    } catch (cause) {
      const apiError = toApiError(cause);
      if (mountedRef.current && requestId === requestIdRef.current) setError(apiError);
      throw apiError;
    } finally {
      if (mountedRef.current && requestId === requestIdRef.current) setLoading(false);
    }
  }, []);

  const reset = useCallback(() => {
    requestIdRef.current += 1;
    if (!mountedRef.current) return;

    setData(null);
    setError(null);
    setLoading(false);
  }, []);

  return { data, loading, error, run, reset };
}

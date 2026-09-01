/**
 * The single HTTP boundary to the RevivePay backend.
 *
 * Components never call fetch directly. Requests made through this module receive
 * one consistent error shape for network, HTTP, JSON, and response-shape failures.
 */

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/+$/, '');

/**
 * FastAPI's configurable mount path. Keep this separate from the API host so a
 * static deployment can point at another origin without baking `/api` into it.
 */
function normalizeApiPrefix(value: string | undefined): string {
  const path = (value ?? '/api').trim().replace(/^\/+|\/+$/g, '');
  return `/${path || 'api'}`;
}

export const API_PREFIX = normalizeApiPrefix(import.meta.env.VITE_API_PREFIX);

export type ApiResponseValidator<T> = (value: unknown) => value is T;

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(message: string, status: number, code: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
  }

  /** True only when the browser could not reach the API at all. */
  get isNetworkError(): boolean {
    return this.code === 'NETWORK_ERROR';
  }

  get isMalformedResponse(): boolean {
    return this.code === 'MALFORMED_RESPONSE';
  }
}

export function isAbortError(cause: unknown): boolean {
  return cause instanceof Error && cause.name === 'AbortError';
}

export function toApiError(
  cause: unknown,
  fallbackMessage = 'An unexpected error occurred while communicating with RevivePay.',
): ApiError {
  if (cause instanceof ApiError) return cause;

  return new ApiError(
    cause instanceof Error && cause.message ? cause.message : fallbackMessage,
    0,
    'UNEXPECTED_ERROR',
  );
}

interface RequestOptions<T> {
  method?: 'GET' | 'POST';
  body?: unknown;
  signal?: AbortSignal;
  validate?: ApiResponseValidator<T>;
}

interface ErrorEnvelope {
  error?: {
    code?: unknown;
    message?: unknown;
  };
}

function isErrorEnvelope(value: unknown): value is ErrorEnvelope {
  return typeof value === 'object' && value !== null;
}

function parseJson(rawText: string, path: string, status: number): unknown {
  try {
    return JSON.parse(rawText);
  } catch {
    throw new ApiError(
      `The server returned malformed JSON for ${path}.`,
      status,
      'MALFORMED_RESPONSE',
    );
  }
}

async function request<T>(path: string, options: RequestOptions<T> = {}): Promise<T> {
  const url = `${API_BASE_URL}${path}`;
  const hasBody = options.body !== undefined;

  let response: Response;
  try {
    response = await fetch(url, {
      method: options.method ?? 'GET',
      headers: hasBody
        ? { Accept: 'application/json', 'Content-Type': 'application/json' }
        : { Accept: 'application/json' },
      body: hasBody ? JSON.stringify(options.body) : undefined,
      signal: options.signal,
    });
  } catch (cause) {
    if (isAbortError(cause)) throw cause;

    throw new ApiError(
      `Could not reach the RevivePay API at ${url}. Is the backend running?`,
      0,
      'NETWORK_ERROR',
    );
  }

  let rawText: string;
  try {
    rawText = await response.text();
  } catch {
    throw new ApiError(
      `The response from ${path} could not be read.`,
      response.status,
      'MALFORMED_RESPONSE',
    );
  }

  let payload: unknown = null;
  if (rawText.trim()) {
    try {
      payload = parseJson(rawText, path, response.status);
    } catch (cause) {
      if (!response.ok && cause instanceof ApiError) {
        throw new ApiError(
          `Request to ${path} failed with status ${response.status}.`,
          response.status,
          'UNKNOWN_ERROR',
        );
      }
      throw cause;
    }
  }

  if (!response.ok) {
    const envelope = isErrorEnvelope(payload) ? payload.error : undefined;
    throw new ApiError(
      typeof envelope?.message === 'string'
        ? envelope.message
        : `Request to ${path} failed with status ${response.status}.`,
      response.status,
      typeof envelope?.code === 'string' ? envelope.code : 'UNKNOWN_ERROR',
    );
  }

  if (options.validate && !options.validate(payload)) {
    throw new ApiError(
      `The server returned an unexpected response shape for ${path}.`,
      response.status,
      'MALFORMED_RESPONSE',
    );
  }

  return payload as T;
}

export function apiGet<T>(
  path: string,
  signal?: AbortSignal,
  validate?: ApiResponseValidator<T>,
): Promise<T> {
  return request<T>(path, { method: 'GET', signal, validate });
}

export function apiPost<T>(
  path: string,
  body: unknown = {},
  signal?: AbortSignal,
  validate?: ApiResponseValidator<T>,
): Promise<T> {
  return request<T>(path, { method: 'POST', body, signal, validate });
}

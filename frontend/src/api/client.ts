// Axios client configured for the Clover backend.
//
// A response interceptor unwraps the standard success envelope
// ({ success, data, message }) so callers receive `data` directly, and
// converts the error envelope ({ error, code, message, details }) into a
// typed ApiError that is thrown.

import axios, {
  AxiosError,
  type AxiosInstance,
  type AxiosResponse,
  type InternalAxiosRequestConfig,
} from 'axios'
import type { ErrorResponse, SuccessResponse } from '../types'
import { isErrorResponse } from '../types'
import { API_BASE } from '../lib/constants'

/** A typed error thrown for any failed API call. */
export class ApiError extends Error {
  readonly code: string
  readonly status: number | null
  readonly details: Record<string, unknown> | null

  constructor(
    message: string,
    code = 'UNKNOWN_ERROR',
    status: number | null = null,
    details: Record<string, unknown> | null = null,
  ) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.status = status
    this.details = details
  }
}

/** Type guard for objects shaped like the backend error envelope. */
function looksLikeErrorEnvelope(value: unknown): value is ErrorResponse {
  return (
    typeof value === 'object' &&
    value !== null &&
    (value as { error?: unknown }).error === true
  )
}

export const apiClient: AxiosInstance = axios.create({
  baseURL: API_BASE,
  headers: {
    'Content-Type': 'application/json',
    Accept: 'application/json',
  },
  // The backend may return 4xx with an error envelope we want to parse,
  // so we don't reject purely on status here — the interceptor decides.
})

apiClient.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => config,
  (error) => Promise.reject(error),
)

apiClient.interceptors.response.use(
  // Success path: HTTP 2xx.
  (response: AxiosResponse) => {
    const body = response.data

    // Some endpoints (or 204s) may not use the envelope — pass through.
    if (looksLikeErrorEnvelope(body)) {
      throw new ApiError(
        body.message,
        body.code,
        response.status,
        body.details ?? null,
      )
    }

    if (
      typeof body === 'object' &&
      body !== null &&
      (body as { success?: unknown }).success === true
    ) {
      // Unwrap the success envelope: replace `data` with the inner payload.
      response.data = (body as SuccessResponse<unknown>).data
    }

    return response
  },
  // Failure path: network error or non-2xx HTTP status.
  (error: AxiosError) => {
    const response = error.response
    const body = response?.data

    if (looksLikeErrorEnvelope(body)) {
      return Promise.reject(
        new ApiError(
          body.message,
          body.code,
          response?.status ?? null,
          body.details ?? null,
        ),
      )
    }

    if (isErrorResponse((body ?? {}) as never)) {
      const env = body as ErrorResponse
      return Promise.reject(
        new ApiError(env.message, env.code, response?.status ?? null, env.details ?? null),
      )
    }

    // Fallback for unstructured failures (timeouts, 500s without envelope).
    return Promise.reject(
      new ApiError(
        error.message || 'Request failed',
        error.code ?? 'NETWORK_ERROR',
        response?.status ?? null,
        null,
      ),
    )
  },
)

/**
 * Helper that performs a GET and returns the unwrapped, typed payload.
 * The interceptor has already stripped the success envelope.
 */
export async function get<T>(url: string, params?: Record<string, unknown>): Promise<T> {
  const res = await apiClient.get<T>(url, { params })
  return res.data
}

/** Helper for POST returning the unwrapped, typed payload. */
export async function post<T>(url: string, payload?: unknown): Promise<T> {
  const res = await apiClient.post<T>(url, payload)
  return res.data
}

/** Helper for PATCH returning the unwrapped, typed payload. */
export async function patch<T>(url: string, payload?: unknown): Promise<T> {
  const res = await apiClient.patch<T>(url, payload)
  return res.data
}

export default apiClient

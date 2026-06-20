// Mirrors backend/schemas/api_responses.py.
//
// All API responses use one of two consistent envelopes:
//   success: { "success": true, "data": {...}, "message": "..." }
//   error:   { "error": true, "code": "VALIDATION_ERROR", "message": "...",
//              "details": {...} }

/** Envelope for a successful API response. */
export interface SuccessResponse<T> {
  success: true
  data: T | null
  message: string | null
}

/** Envelope for a failed API response. */
export interface ErrorResponse {
  error: true
  code: string
  message: string
  details?: Record<string, unknown> | null
}

/** Discriminated union covering either response shape. */
export type ApiResponse<T> = SuccessResponse<T> | ErrorResponse

/** Type guard: narrow an ApiResponse to its error variant. */
export function isErrorResponse<T>(
  response: ApiResponse<T>,
): response is ErrorResponse {
  return (response as ErrorResponse).error === true
}

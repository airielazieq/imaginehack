// Display formatters for dates, currency, percentages, and numbers.

const USD = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  maximumFractionDigits: 0,
})

const USD_CENTS = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

/**
 * Format a number as USD. Whole dollars by default; pass `cents` to show
 * two decimal places (e.g. for cost-per-hour).
 */
export function formatCurrency(value: number, cents = false): string {
  if (!Number.isFinite(value)) return '—'
  return cents ? USD_CENTS.format(value) : USD.format(value)
}

/**
 * Format a ratio or already-scaled percentage value.
 * By default the input is treated as already a percentage (e.g. 42 → "42%").
 * Pass `fromRatio` to convert a 0-1 ratio (e.g. 0.42 → "42%").
 */
export function formatPercent(
  value: number,
  { fromRatio = false, decimals = 0 }: { fromRatio?: boolean; decimals?: number } = {},
): string {
  if (!Number.isFinite(value)) return '—'
  const pct = fromRatio ? value * 100 : value
  return `${pct.toFixed(decimals)}%`
}

/** Format a number with thousands separators and optional decimals. */
export function formatNumber(value: number, decimals = 0): string {
  if (!Number.isFinite(value)) return '—'
  return value.toLocaleString('en-US', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })
}

const parseDate = (input: string | number | Date): Date | null => {
  const d = input instanceof Date ? input : new Date(input)
  return Number.isNaN(d.getTime()) ? null : d
}

/** Format an ISO timestamp as a readable date (e.g. "Jun 20, 2026"). */
export function formatDate(input: string | number | Date): string {
  const d = parseDate(input)
  if (!d) return '—'
  return d.toLocaleDateString('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  })
}

/** Format an ISO timestamp as date + time (e.g. "Jun 20, 2026, 10:31 AM"). */
export function formatDateTime(input: string | number | Date): string {
  const d = parseDate(input)
  if (!d) return '—'
  return d.toLocaleString('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}

/** Format an ISO timestamp as a short time (e.g. "10:31 AM"). */
export function formatTime(input: string | number | Date): string {
  const d = parseDate(input)
  if (!d) return '—'
  return d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })
}

/**
 * Relative "time ago" string from a timestamp (e.g. "3m ago", "2h ago").
 * Useful for approval queue "time since request" displays.
 */
export function formatRelativeTime(
  input: string | number | Date,
  now: Date = new Date(),
): string {
  const d = parseDate(input)
  if (!d) return '—'
  const deltaSec = Math.round((now.getTime() - d.getTime()) / 1000)
  const abs = Math.abs(deltaSec)
  const suffix = deltaSec >= 0 ? 'ago' : 'from now'

  if (abs < 60) return `${abs}s ${suffix}`
  if (abs < 3600) return `${Math.floor(abs / 60)}m ${suffix}`
  if (abs < 86_400) return `${Math.floor(abs / 3600)}h ${suffix}`
  return `${Math.floor(abs / 86_400)}d ${suffix}`
}

/**
 * Format a duration in seconds as a compact countdown "MM:SS" (or "H:MM:SS").
 * Negative values clamp to zero. Useful for escalation timers.
 */
export function formatCountdown(totalSeconds: number): string {
  const s = Math.max(0, Math.floor(totalSeconds))
  const hours = Math.floor(s / 3600)
  const minutes = Math.floor((s % 3600) / 60)
  const seconds = s % 60
  const pad = (n: number) => n.toString().padStart(2, '0')
  return hours > 0
    ? `${hours}:${pad(minutes)}:${pad(seconds)}`
    : `${pad(minutes)}:${pad(seconds)}`
}

/** Format a duration in milliseconds (e.g. "850ms", "1.2s"). */
export function formatDuration(ms: number): string {
  if (!Number.isFinite(ms)) return '—'
  return ms < 1000 ? `${Math.round(ms)}ms` : `${(ms / 1000).toFixed(1)}s`
}

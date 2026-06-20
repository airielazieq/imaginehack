// Color + scale helpers shared across the app.

// Priority score (0 healthy → 100 critical): green → amber → red.
export function priorityColor(score) {
  const s = Math.min(Math.max(score, 0), 100)
  const hue = 140 - (s / 100) * 140 // 140 green → 0 red
  const light = s > 55 ? 42 : 40
  return `hsl(${hue}, 62%, ${light}%)`
}

// Health/dimension score (0 bad → 100 good): red → amber → green. null = not monitored.
export function healthColor(score) {
  if (score === null || score === undefined) return '#d4d4c8' // sand-300
  const s = Math.min(Math.max(score, 0), 100)
  const hue = (s / 100) * 140
  return `hsl(${hue}, 55%, 42%)`
}

export const SEVERITY = {
  Critical: { color: '#dc2626', bg: 'bg-red-50', text: 'text-red-700', ring: 'ring-red-200' },
  High: { color: '#ea580c', bg: 'bg-orange-50', text: 'text-orange-700', ring: 'ring-orange-200' },
  Medium: { color: '#ca8a04', bg: 'bg-amber-50', text: 'text-amber-700', ring: 'ring-amber-200' },
  Low: { color: '#16a34a', bg: 'bg-clover-50', text: 'text-clover-700', ring: 'ring-clover-200' },
}

export function severityFromPriority(p) {
  if (p >= 81) return 'Critical'
  if (p >= 61) return 'High'
  if (p >= 31) return 'Medium'
  return 'Low'
}

export const usd = (n) => '$' + n.toLocaleString('en-US')

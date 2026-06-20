interface PlaceholderProps {
  /** Human-readable page name shown as the heading. */
  title: string
  /** Optional secondary line, e.g. a route param or short description. */
  subtitle?: string
}

// TODO: Temporary scaffold page. Replaced by real implementations in tasks 10-13, 15.
// Renders the route name so routing/navigation can be exercised end-to-end now.
export default function Placeholder({ title, subtitle }: PlaceholderProps) {
  return (
    <div className="card p-8">
      <p className="eyebrow">Clover · Coming soon</p>
      <h1 className="mt-2 text-2xl font-semibold text-white">{title}</h1>
      {subtitle && <p className="mt-1 text-sm text-navy-300">{subtitle}</p>}
      <p className="mt-4 max-w-prose text-sm text-navy-200">
        This page is a placeholder. The full experience is implemented in a later task.
      </p>
    </div>
  )
}

// Clover logo mark — four rounded leaves + stem. Inherits color via `currentColor`.
interface CloverMarkProps {
  className?: string
  title?: string
}

export default function CloverMark({ className = 'h-7 w-7', title = 'Clover' }: CloverMarkProps) {
  return (
    <svg viewBox="0 0 48 48" className={className} role="img" aria-label={title}>
      <g fill="currentColor">
        {/* top */}
        <path d="M24 23c-2.2-3.4-1-8.2 2.6-9.4 3-1 6 1.2 6 4.4 0 3.8-4.4 6-8.6 5z" />
        {/* right */}
        <path d="M25 24c3.4-2.2 8.2-1 9.4 2.6 1 3-1.2 6-4.4 6-3.8 0-6-4.4-5-8.6z" />
        {/* bottom */}
        <path d="M24 25c2.2 3.4 1 8.2-2.6 9.4-3 1-6-1.2-6-4.4 0-3.8 4.4-6 8.6-5z" />
        {/* left */}
        <path d="M23 24c-3.4 2.2-8.2 1-9.4-2.6-1-3 1.2-6 4.4-6 3.8 0 6 4.4 5 8.6z" />
      </g>
      <path
        d="M24 26c1 4 1.5 9 5 13"
        stroke="currentColor"
        strokeWidth="2.4"
        strokeLinecap="round"
        fill="none"
        opacity="0.65"
      />
    </svg>
  )
}

import { useEffect, type ReactNode } from 'react'
import { X } from 'lucide-react'

interface ModalProps {
  /** Controls visibility. When false the modal is not rendered. */
  open: boolean
  /** Title shown in the header. */
  title: ReactNode
  /** Body content. */
  children: ReactNode
  /** Footer content (typically action buttons). */
  footer?: ReactNode
  /** Invoked when the user dismisses (overlay click, close button, or Esc). */
  onClose: () => void
}

/**
 * Lightweight modal dialog used for approve/deny confirmation flows
 * (task 12.1). Closes on overlay click, the close button, or the Escape key.
 */
export default function Modal({ open, title, children, footer, onClose }: ModalProps) {
  // Close on Escape while open.
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
    >
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/60 backdrop-blur-sm"
        onClick={onClose}
        aria-hidden
      />

      {/* Panel */}
      <div className="card relative z-10 w-full max-w-lg p-6 shadow-lift">
        <div className="flex items-start justify-between gap-4">
          <h2 className="text-lg font-semibold text-navy-50">{title}</h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1 text-navy-300 transition-colors hover:bg-navy-900 hover:text-navy-50"
            aria-label="Close"
          >
            <X className="h-5 w-5" aria-hidden />
          </button>
        </div>

        <div className="mt-4 text-sm text-navy-200">{children}</div>

        {footer && (
          <div className="mt-6 flex justify-end gap-3">{footer}</div>
        )}
      </div>
    </div>
  )
}

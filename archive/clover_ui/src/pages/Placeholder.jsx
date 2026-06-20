import { Link } from 'react-router-dom'
import { Construction } from 'lucide-react'
import { PageHeader } from '../components/ui.jsx'

export default function Placeholder({ title, blurb }) {
  return (
    <>
      <PageHeader title={title} />
      <div className="card p-10 text-center">
        <div className="mx-auto h-12 w-12 grid place-items-center rounded-xl bg-clover-50 text-clover-500 mb-4">
          <Construction size={22} />
        </div>
        <p className="text-stone-600 max-w-md mx-auto">{blurb}</p>
        <p className="text-xs text-stone-400 mt-3">
          Specified in <span className="font-mono">specs/11_UI_UX_SPECIFICATION.md</span> — not yet built in this pass.
        </p>
        <Link to="/" className="inline-block mt-5 px-4 py-2 rounded-lg bg-clover-600 hover:bg-clover-700 text-white text-sm font-medium transition">
          Back to dashboard
        </Link>
      </div>
    </>
  )
}

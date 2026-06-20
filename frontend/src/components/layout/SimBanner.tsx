// Persistent simulation-mode banner. Sits at the very top of the app shell so it
// is always visible — Clover never touches live cloud resources (Requirement 19).
export default function SimBanner() {
  return (
    <div
      role="status"
      className="bg-navy-950 text-healthy-300 text-center text-xs py-1.5 font-medium tracking-wide border-b border-navy-700"
    >
      Simulation Mode — data is simulated, no live cloud connections
    </div>
  )
}

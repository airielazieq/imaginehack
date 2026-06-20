# Clover — Cloud Operations Console (UI)

Brand-forward React UI for **Clover** (HILTI Track 2): a secure & energy-aware cloud
operations console. This is a fresh build that lives alongside the original
`../UI_prototype/` (left untouched) and follows `../specs/`.

All data is **simulated** — there are no live cloud connections.

## Stack
- React 18 + Vite
- React Router
- Tailwind CSS (custom Clover green design system)
- Recharts (charts)
- lucide-react (icons — no emoji)

## Run
```bash
npm install
npm run dev      # http://localhost:5173
npm run build    # production build to dist/
npm run preview  # serve the built app
```

## What's built in this pass
- **Dashboard** — summary stats, composite heatmap (continuous gradient) with a
  Composite/Matrix toggle, and a "needs attention" chart.
- **Workloads** — filterable fleet table.
- **Workload detail** — AI downtime prediction (risk timeline), key metrics,
  priority score, 90-day uptime, and a GreenOps tab (energy degradation +
  optimization impact forecast + inefficiency findings).
- **Placeholders** for Issues, Recommendations, Self-Healing, Reports, Audit Logs,
  Mock Controller (spec'd, not yet built).

## Design system
See `tailwind.config.js` for the Clover palette and `src/lib/scale.js` for the
priority/health color scales.

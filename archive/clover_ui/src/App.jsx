import { Routes, Route } from 'react-router-dom'
import Layout from './components/Layout.jsx'
import Dashboard from './pages/Dashboard.jsx'
import Workloads from './pages/Workloads.jsx'
import WorkloadDetail from './pages/WorkloadDetail.jsx'
import Placeholder from './pages/Placeholder.jsx'

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Dashboard />} />
        <Route path="workloads" element={<Workloads />} />
        <Route path="workloads/:id" element={<WorkloadDetail />} />
        <Route path="issues" element={<Placeholder title="Issues" blurb="Cross-workload issue list with severity, category and environment filters, each linking to an issue detail with ML anomaly result, SHAP factors and next best action." />} />
        <Route path="recommendations" element={<Placeholder title="Recommendations" blurb="Consolidated AI recommendations across the fleet, grouped by execution mode (auto / approval / escalation)." />} />
        <Route path="self-healing" element={<Placeholder title="Self-Healing" blurb="Approval queue and execution history for guardrailed self-healing — major (approval) vs minor (auto-resolved), with rollback notes and post-incident reports." />} />
        <Route path="reports" element={<Placeholder title="Reports" blurb="Post-incident reports: what happened, the AI decision process, MCP tools executed, before/after and audit trail." />} />
        <Route path="audit" element={<Placeholder title="Audit Logs" blurb="Immutable event log: timestamp, actor, workload, issue, status transitions and details." />} />
        <Route path="mock" element={<Placeholder title="Mock Controller" blurb="Drive the live demo: trigger idle dev server, public storage exposure, critical vulnerability, carbon-heavy batch, cost spike and more." />} />
        <Route path="*" element={<Placeholder title="Not found" blurb="That page doesn't exist yet." />} />
      </Route>
    </Routes>
  )
}

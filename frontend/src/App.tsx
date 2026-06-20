import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import Layout from './components/layout/Layout'
import Dashboard from './pages/Dashboard'
import Workloads from './pages/Workloads'
import WorkloadDetail from './pages/WorkloadDetail'
import Issues from './pages/Issues'
import IssueDetail from './pages/IssueDetail'
import Approvals from './pages/Approvals'
import Reports from './pages/Reports'
import AuditLogs from './pages/AuditLogs'
import MockController from './pages/MockController'

// Application routing. Most pages are placeholders for now (tasks 10-13, 15
// replace them); this wires the navigation shell so the full route map works.
export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<Dashboard />} />
          <Route path="/workloads" element={<Workloads />} />
          <Route path="/workloads/:id" element={<WorkloadDetail />} />
          <Route path="/issues" element={<Issues />} />
          <Route path="/issues/:id" element={<IssueDetail />} />
          <Route path="/approvals" element={<Approvals />} />
          <Route path="/reports" element={<Reports />} />
          <Route path="/audit" element={<AuditLogs />} />
          <Route path="/mock" element={<MockController />} />
          {/* Unknown paths fall back to the dashboard. */}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}

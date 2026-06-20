# Implementation Plan: Clover Cloud Intelligence Platform

## Overview

Phased implementation prioritizing an end-to-end demo (P0) as quickly as possible. The build order is: backend spine → mock data → detection pipeline → NBA + forecast → self-healing → UI pages → polish. Each task is atomic and independently verifiable. Python 3.11+ / FastAPI for backend, React 18 + TypeScript + Vite for frontend.

## Tasks

- [x] 1. Backend Spine and Core Infrastructure
  - [x] 1.1 Create FastAPI application skeleton with project structure
    - Create `backend/main.py` with FastAPI app, CORS middleware, lifespan handler
    - Create `backend/core/config.py` for JSON policy/config loading
    - Create `backend/core/database.py` with SQLite connection, migrations, table schemas for workloads, telemetry, issues, recommendations, remediations, audit_logs, alerts
    - Create `backend/core/event_bus.py` with asyncio pub/sub (EventType enum, Event dataclass, subscribe/publish)
    - Set up `requirements.txt` or `pyproject.toml` with dependencies (fastapi, uvicorn, pydantic, scikit-learn, xgboost, shap, joblib)
    - _Requirements: 1.1, 1.3, 21.1_

  - [x] 1.2 Create Pydantic schemas for all data models
    - Create `backend/schemas/workload.py` (Workload model)
    - Create `backend/schemas/telemetry.py` (TelemetrySnapshot with field validators)
    - Create `backend/schemas/issue.py` (Issue, MLResult, XAIExplanation, XAIFactor, EstimatedImpact)
    - Create `backend/schemas/recommendation.py` (Recommendation, RuleTriggered, OptimizationImpactForecast, ForecastComponent)
    - Create `backend/schemas/remediation.py` (RemediationResult, MCPToolExecution, SafetyDecision, AuditCompliance)
    - Create `backend/schemas/scoring.py` (PriorityScore, DimensionScore, DimensionScores)
    - Create `backend/schemas/alert.py` (Alert)
    - Create `backend/schemas/audit.py` (AuditLog)
    - Create `backend/schemas/prediction.py` (DowntimePrediction)
    - Create `backend/schemas/api_responses.py` (success/error envelope wrappers)
    - _Requirements: 1.1, 1.2, 21.3_

  - [x] 1.4 Create JSON rule/policy files
    - Create `backend/rules/detection_rules.json` with 7 rule definitions (DET-SEC-001 through DET-COST-002)
    - Create `backend/rules/recommendation_rules.json` with 7 recommendation rules (RULE-SEC-001 through RULE-COST-001)
    - Create `backend/rules/safety_rules.json` with auto-fix conditions, approval conditions, escalation conditions, blocklist
    - Create `backend/rules/scoring_weights.json` with 6 factor weights summing to 1.0
    - _Requirements: 5.1, 7.1, 12.2_

  - [x] 1.5 Create telemetry ingestion API endpoint
    - Create `backend/api/telemetry.py` with POST `/api/telemetry/ingest` and POST `/api/telemetry/bulk-ingest`
    - Validate TelemetrySnapshot via Pydantic, persist to SQLite, emit `TELEMETRY_INGESTED` event
    - Return 422 with structured error envelope on validation failure
    - _Requirements: 1.1, 1.2, 1.3, 1.4_

  - [x] 1.6 Create workloads API endpoints
    - Create `backend/api/workloads.py` with GET `/api/workloads`, GET `/api/workloads/{id}`, GET `/api/workloads/{id}/telemetry`
    - Create `backend/services/workload_service.py` for workload CRUD
    - Create `backend/services/telemetry_service.py` for telemetry persistence + query
    - _Requirements: 21.1_

- [x] 2. Mock Data Generator and Controller
  - [x] 2.1 Create mock workload definitions and healthy baseline data
    - Create `backend/mock_data/sample_workloads.json` with 8+ workload definitions (field-app, iot-dashboard, bim-processor, doc-storage, report-generator, ci-pipeline, costly-vm, site-db, plus extras for ~20 total)
    - Create `backend/mock_data/healthy_baseline.json` with healthy telemetry per workload
    - Create `backend/mock_data/scenario_payloads.json` with 7 scenario telemetry injections
    - _Requirements: 19.1, 19.4_

  - [x] 2.2 Implement mock data service
    - Create `backend/services/mock_data_service.py` with scenario trigger logic, stream control, reset functionality
    - Inject telemetry payloads on scenario trigger, seed workloads from sample data on startup
    - Support continuous streaming mode (emit telemetry every 3-10s with random variation)
    - _Requirements: 19.2, 19.3, 19.4_

  - [x] 2.3 Create Mock Controller API endpoints
    - Create `backend/api/mock_controller.py` with GET `/api/mock/scenarios`, POST `/api/mock/trigger/{scenarioId}`, POST `/api/mock/reset`, POST `/api/mock/stream/start`, POST `/api/mock/stream/stop`, GET `/api/mock/status`
    - Wire triggers to mock_data_service → telemetry ingestion → event bus pipeline
    - _Requirements: 19.1, 19.2, 19.3, 19.4_

  - [x] 2.4 Generate ML training data
    - Create `backend/mock_data/training_data.csv` generation script
    - Generate 50-200 historical rows per workload for XGBoost training
    - Target values: `current_24h × 30 × random(0.85, 1.20)` for cost, energy, carbon
    - _Requirements: 6.1_

- [x] 3. Module 1: Detection & Insight Engine
  - [x] 3.1 Implement rule-based detection and classification
    - Create `backend/modules/detection_insight/rule_classifier.py` — load `detection_rules.json`, evaluate each rule against TelemetrySnapshot, classify into issue_type + category
    - Create `backend/modules/detection_insight/severity_assigner.py` — assign severity (low/medium/high/critical) and confidence score based on rule conditions + environment + criticality
    - _Requirements: 3.1, 3.2_

  - [x] 3.2 Implement Isolation Forest anomaly detection
    - Create `backend/modules/detection_insight/isolation_forest.py` — train IsolationForest on workload historical data (17 features, contamination=0.1), produce anomaly_score + is_anomaly
    - Create `backend/ml/train_isolation_forest.py` — training script that saves model to `backend/ml/models/`
    - Implement fallback: if model unavailable, return default MLResult with model_name="fallback_rules_only"
    - _Requirements: 2.1, 2.3_

  - [x] 3.3 Implement SHAP explainer
    - Create `backend/modules/detection_insight/shap_explainer.py` — use `shap.TreeExplainer` on Isolation Forest, return top 3-5 XAIFactors sorted by absolute SHAP value
    - Include plain-language impact strings from lookup table
    - Fallback: rule-based feature contribution with method="rule-based feature contribution fallback"
    - _Requirements: 2.2, 4.2_

  - [x] 3.4 Implement LLM/template explanation generator
    - Create `backend/modules/detection_insight/llm_explainer.py` — generate 2-3 sentence plain-language explanation
    - Implement template fallback: `"This workload was flagged for {issue_type} because {top_evidence}. It may affect {impact_area}."`
    - LLM used only for wording, never classification
    - _Requirements: 4.1, 4.3, 4.4_

  - [x] 3.5 Implement detection orchestrator with issue consolidation
    - Create `backend/modules/detection_insight/detector.py` — orchestrate: preprocessing → IF → SHAP → rule classifier → severity → LLM explanation → emit Issue event
    - Implement 5-minute window consolidation (same workload → single Issue with max severity)
    - Create `backend/api/detection.py` with POST `/api/detection/run`, POST `/api/detection/run/{workloadId}`, GET `/api/issues`, GET `/api/issues/{id}`, PATCH `/api/issues/{id}/status`
    - Subscribe to `TELEMETRY_INGESTED` events on the event bus
    - _Requirements: 2.1, 2.4, 3.3, 18.1, 18.2_

- [x] 4. Module 2: Next Best Action + Forecasting
  - [x] 4.1 Implement rule-based recommendation engine
    - Create `backend/modules/next_best_action/nba_engine.py` — load `recommendation_rules.json`, match Issue to rule, produce Recommendation with action_category, recommendation_type, rule_triggered
    - Create `backend/modules/next_best_action/risk_assessor.py` — assign risk_level based on environment + reversibility + sensitivity + criticality
    - Select execution_mode from risk→mode mapping (low+reversible+non-prod → auto_fix, medium/high → approval, critical → escalation)
    - _Requirements: 5.1, 5.2, 5.3, 5.4_

  - [x] 4.2 Implement XGBoost 30-day forecaster
    - Create `backend/modules/next_best_action/xgboost_forecast.py` — train 3 XGBoost Regressors (cost_30d, energy_kwh_30d, carbon_kgco2e_30d) from training data
    - Create `backend/ml/train_xgboost.py` — training script saving models to `backend/ml/models/`
    - Implement formula fallback: `current_24h × 30` with model_name="deterministic_forecast_fallback"
    - _Requirements: 6.1, 6.3_

  - [x] 4.3 Implement optimization impact calculator
    - Create `backend/modules/next_best_action/optimization_impact.py` — apply optimization factors per recommendation type to compute forecast_without_action, forecast_after_action, projected_savings
    - Enforce arithmetic consistency: without - after = savings for each dimension
    - Ensure all savings values are non-negative
    - _Requirements: 6.2, 6.4_

  - [x] 4.4 Wire NBA pipeline and create API endpoints
    - Subscribe NBA engine to `ISSUE_DETECTED` events on event bus
    - Create `backend/api/recommendations.py` with POST `/api/recommendations/generate/{issueId}`, GET `/api/recommendations/{id}`, POST `/api/forecast/{workloadId}`
    - Emit `RECOMMENDATION_GENERATED` event after producing recommendation
    - _Requirements: 5.1, 21.1_

- [x] 5. Module 3: Guardrailed Self-Healing
  - [x] 5.1 Implement safety router
    - Create `backend/modules/self_healing/safety_router.py` — load `safety_rules.json`, evaluate all 7 auto-fix conditions; route to auto_fix / user_approval_required / human_escalation_required
    - Critical risk → always human_escalation regardless of other conditions
    - Deterministic: identical inputs → identical routing decision
    - _Requirements: 7.1, 7.2, 7.3, 7.4_

  - [x] 5.2 Implement MCP connectors (simulated)
    - Create `backend/connectors/mcp_base.py` — base MCPConnector protocol with execute_tool + get_available_tools
    - Create `backend/connectors/cloud_connector.py` — simulated infra ops (restart, scale, stop, resize, etc.)
    - Create `backend/connectors/ticketing_connector.py` — simulated ticket creation
    - Create `backend/connectors/notification_connector.py` — simulated notifications
    - Create `backend/connectors/audit_connector.py` — audit log writer
    - Each tool returns MCPToolExecution with simulated duration, status, input/output
    - _Requirements: 8.1, 10.1, 10.2_

  - [x] 5.3 Implement runbook executor with verification and rollback
    - Create `backend/modules/self_healing/runbook_executor.py` — execute runbook steps via MCP connectors sequentially
    - Create `backend/modules/self_healing/verification.py` — post-fix health check within 30s timeout
    - Create `backend/modules/self_healing/rollback.py` — rollback within 60s on verification failure, then escalate
    - _Requirements: 8.1, 8.2, 8.3_

  - [x] 5.4 Implement approval queue management
    - Create `backend/modules/self_healing/approval_queue.py` — add to queue sorted by severity (Critical→High→Medium→Low), 15-min escalation countdown for high-risk items, auto-escalate on timeout
    - Create `backend/api/approvals.py` with GET `/api/approvals`, POST `/api/approvals/{id}/approve`, POST `/api/approvals/{id}/deny`, POST `/api/approvals/{id}/snooze`
    - _Requirements: 9.1, 9.2, 9.3, 9.4_

  - [x] 5.5 Implement remediation report generator and API
    - Create `backend/modules/self_healing/report_generator.py` — build RemediationResult with execution_timeline, mcp_tools_executed, safety_decision, audit_compliance, user_facing_report
    - Create `backend/api/remediation.py` with POST `/api/remediation/evaluate/{recId}`, POST `/api/remediation/execute/{recId}`, GET `/api/remediation/{id}/report`
    - Emit `REMEDIATION_COMPLETED` event, persist result with links to Issue + Recommendation + Workload
    - _Requirements: 8.4, 11.1, 11.2, 11.3_

- [x] 6. Checkpoint - Backend Pipeline End-to-End
  - Ensure the full pipeline works: ingest telemetry → detect issue → generate recommendation → route through self-healing → produce report
  - Trigger mock scenario and verify end-to-end completion

- [x] 7. Scoring Engine and Downtime Prediction
  - [x] 7.1 Implement priority score computation
    - Create `backend/modules/scoring/priority_scorer.py` — compute 6-factor weighted Priority Score (0-100, 1dp)
    - Load weights from `scoring_weights.json`, validate sum = 1.0
    - Recompute on Issue/Recommendation/Remediation state changes (subscribe to events)
    - Handle missing factors: redistribute weight proportionally, list in unavailable_factors
    - _Requirements: 12.1, 12.2, 12.3_

  - [x] 7.2 Implement dimension scores
    - Create `backend/modules/scoring/dimension_scorer.py` — compute 6 dimension scores (security, energy, carbon, cost, performance, monitoring) each 0-100
    - Map state: ≥75 → green, 50-74 → yellow, <50 → red, insufficient data → gray
    - Create `backend/api/scoring.py` with GET `/api/scoring/issues`
    - _Requirements: 12.4_

  - [x] 7.3 Implement downtime prediction engine
    - Create `backend/modules/downtime_prediction/predictor.py` — compute failure probability (0-100%), estimated TTF, confidence, primary/secondary signals from telemetry trends (linear regression on metric degradation)
    - Create `backend/modules/downtime_prediction/timeline.py` — generate 12-point hourly risk timeline
    - When probability > 70%, trigger preemptive Recommendation via NBA engine
    - Add GET `/api/workloads/{id}/prediction` endpoint
    - _Requirements: 14.1, 14.2, 14.3, 14.4_

- [x] 8. Dashboard API and Summary Endpoints
  - [x] 8.1 Create dashboard API endpoints
    - Create `backend/api/dashboard.py` with GET `/api/dashboard/summary` (stat cards: total workloads, active issues, pending approvals, projected savings), GET `/api/dashboard/heatmap/composite` (Priority Scores per workload), GET `/api/dashboard/heatmap/matrix` (Dimension Scores per workload), GET `/api/dashboard/savings`, GET `/api/dashboard/recent-actions`
    - _Requirements: 16.1, 16.2, 21.1_

  - [x] 8.2 Create uptime history endpoint
    - Add GET `/api/workloads/{id}/uptime` — return 90-day uptime segments
    - Generate synthetic uptime history from mock data
    - _Requirements: 17.3_

- [x] 9. Frontend: New Project Setup and Core UI
  - [x] 9.1 Initialize new TypeScript React frontend project
    - Create `frontend/` directory with Vite + React 18 + TypeScript template
    - Configure Tailwind CSS (dark navy base, teal/green healthy, yellow/orange warning, red/pink critical)
    - Install dependencies: react-router-dom, recharts, lucide-react, axios
    - Create `frontend/src/types/` with all TypeScript interfaces matching backend schemas (workload.ts, issue.ts, recommendation.ts, remediation.ts, scoring.ts, alert.ts, audit.ts, api.ts)
    - _Requirements: 16.1, 21.1_

  - [x] 9.2 Create API client and shared hooks
    - Create `frontend/src/api/client.ts` — axios wrapper with base URL config, error interceptor
    - Create `frontend/src/api/endpoints.ts` — typed API functions for all backend endpoints
    - Create `frontend/src/hooks/useWorkloads.ts`, `frontend/src/hooks/useIssues.ts` — data fetching hooks
    - Create `frontend/src/lib/colorScale.ts` — Priority Score → green-to-red gradient color mapping
    - Create `frontend/src/lib/formatters.ts` — date, currency, percentage formatters
    - Create `frontend/src/lib/constants.ts` — API URLs, thresholds
    - _Requirements: 21.1_

  - [x] 9.3 Create layout components and routing
    - Create `frontend/src/App.tsx` with React Router (routes: /, /workloads, /workloads/:id, /issues, /issues/:id, /approvals, /reports, /audit, /mock)
    - Create `frontend/src/components/layout/Header.tsx` — nav with pending-approvals badge
    - Create `frontend/src/components/layout/Sidebar.tsx` — navigation menu
    - Create `frontend/src/components/layout/SimBanner.tsx` — "Simulation Mode" banner
    - _Requirements: 16.1, 17.1_

- [x] 10. Frontend: Dashboard with Dual Heatmap
  - [x] 10.1 Implement composite heatmap grid
    - Create `frontend/src/components/heatmap/CompositeGrid.tsx` — grid of cells, one per workload, colored green→red based on Priority Score
    - Create `frontend/src/components/heatmap/HeatmapCell.tsx` — individual cell with hover tooltip (name, score, status, top alert, downtime risk)
    - Create `frontend/src/components/heatmap/HeatmapToggle.tsx` — composite ↔ matrix switch
    - Click on cell navigates to `/workloads/:id`
    - _Requirements: 16.1, 16.3, 16.4_

  - [x] 10.2 Implement dimension matrix heatmap
    - Create `frontend/src/components/heatmap/MatrixView.tsx` — rows=workloads, columns=Security/Energy/Carbon/Cost/Performance/Monitoring, cells colored green/yellow/red/gray
    - Click on cell navigates to workload detail relevant tab
    - _Requirements: 16.2_

  - [x] 10.3 Implement Dashboard page with summary cards
    - Create `frontend/src/pages/Dashboard.tsx` — stat summary cards (total workloads, active issues, pending approvals, projected savings) + heatmap toggle + composite/matrix view
    - Create `frontend/src/components/cards/SummaryCards.tsx`
    - _Requirements: 16.1, 16.2_

- [x] 11. Frontend: Issues, Recommendations, and XAI Views
  - [x] 11.1 Implement Issues List page
    - Create `frontend/src/pages/Issues.tsx` — sortable/filterable table with columns: workload name, issue_type, severity, confidence, detected_at
    - Create filter controls for issue_type, severity, issue_category
    - Create `frontend/src/components/ui/DataTable.tsx` — reusable sortable/filterable table
    - Create `frontend/src/components/ui/Badge.tsx` — severity/status badges
    - _Requirements: 18.1, 18.2_

  - [x] 11.2 Implement Issue Detail page with XAI card and forecast
    - Create `frontend/src/pages/IssueDetail.tsx` — XAI explanation card, Optimization Impact Forecast, recommended action CTA, execution status
    - Create `frontend/src/components/cards/XAICard.tsx` — SHAP top factors table (Feature | Value | Impact)
    - Create `frontend/src/components/cards/OptimizationForecast.tsx` — before/after/savings cards + bar chart + savings badge
    - Create `frontend/src/components/charts/ForecastChart.tsx` — Recharts bar chart for cost/energy/carbon comparison
    - Create `frontend/src/components/cards/SavingsBadge.tsx`
    - _Requirements: 18.3, 4.2, 6.2_

- [x] 12. Frontend: Self-Healing Workflow Pages
  - [x] 12.1 Implement Approvals page
    - Create `frontend/src/pages/Approvals.tsx` — global approval queue sorted by severity
    - Create `frontend/src/components/workflow/ApprovalItem.tsx` — workload, action, AI rationale, risk badge, environment, MCP tools, time-since-request, escalation countdown, Approve/Deny/Snooze buttons
    - Create `frontend/src/components/workflow/EscalationTimer.tsx` — countdown display (pulsing for critical)
    - Create `frontend/src/components/workflow/ExecutionPath.tsx` — auto/approval/escalation indicator
    - Create `frontend/src/components/ui/Modal.tsx` — confirmation modal for approve/deny actions
    - _Requirements: 9.1, 9.2, 10.3_

  - [x] 12.2 Implement Reports page
    - Create `frontend/src/pages/Reports.tsx` — remediation reports list with status, workload, path, timestamp
    - Create `frontend/src/components/workflow/RemediationReport.tsx` — full report view (execution timeline, MCP tools, before/after, safety decision, audit compliance, user-facing narrative)
    - _Requirements: 11.1, 11.2_

- [x] 13. Frontend Completion — Core Pages (TOP PRIORITY)
  Replace every placeholder / "not yet built in this pass" stub with fully functional components wired to the existing backend APIs (all backend endpoints from tasks 1–8, plus the audit and MCP-log endpoints, are complete). No page may ship placeholder text.
  - [x] 13.1 Fully build out the Dashboard page
    - Replace any placeholder content in `frontend/src/pages/Dashboard.tsx` with the functional dashboard component
    - Wire stat summary cards, dual heatmap (composite + matrix), savings panel, and recent-actions feed to `/api/dashboard/summary`, `/api/dashboard/heatmap/composite`, `/api/dashboard/heatmap/matrix`, `/api/dashboard/savings`, `/api/dashboard/recent-actions`
    - Ensure heatmap cell click navigates to `/workloads/:id` and matrix cell click opens the relevant Workload Detail tab
    - _Requirements: 16.1, 16.2, 16.3, 16.4_

  - [x] 13.2 Fully build out the Workloads list page
    - Replace any placeholder content in `frontend/src/pages/Workloads.tsx` with a functional, sortable/filterable table wired to `/api/workloads`
    - Columns: name, type, environment, criticality, status, priority score (color-coded); row click navigates to `/workloads/:id`
    - _Requirements: 21.1_

  - [x] 13.3 Fully build out the Issues list page
    - Replace the placeholder ("Cross-workload issue list … not yet built in this pass") in `frontend/src/pages/Issues.tsx` with a functional filterable/sortable table wired to `/api/issues`
    - Columns: workload name, issue_type, severity, confidence, detected_at; filters for issue_type, severity, issue_category, environment; each row links to the Issue Detail page
    - _Requirements: 18.1, 18.2_

  - [x] 13.4 Fully build out the Issue Detail page (XAI + forecast)
    - Replace any placeholder content in `frontend/src/pages/IssueDetail.tsx` with the functional detail view wired to `/api/issues/{id}` and `/api/recommendations/...`
    - Render the ML anomaly result, XAI SHAP factors table (Feature | Value | Impact), Optimization Impact Forecast (before/after/savings + chart + savings badge), recommended next-best-action CTA, and live execution status
    - _Requirements: 18.3, 4.2, 6.2_

- [x] 14. Frontend Completion — Workload Detail Tabs (TOP PRIORITY)
  Build out `frontend/src/pages/WorkloadDetail.tsx` so all six tabs render real, data-wired UI. Replace any "not yet built in this pass" placeholder in each tab with the functional component.
  - [x] 14.1 Build Workload Detail shell and Overview tab
    - Implement the tabbed shell (Overview, Security, GreenOps, AI Recommendations, Self-Healing, MCP Activity)
    - Overview tab: downtime prediction panel (probability gauge, TTF, contributing signals, 12-point risk timeline, preemptive action CTA), 90-day uptime bar, latest telemetry summary; wire to `/api/workloads/{id}`, `/api/workloads/{id}/prediction`, `/api/workloads/{id}/uptime`, `/api/workloads/{id}/telemetry`
    - Create `frontend/src/components/cards/DowntimePrediction.tsx`, `frontend/src/components/charts/RiskTimeline.tsx`, `frontend/src/components/charts/UptimeBar.tsx`
    - _Requirements: 17.1, 17.2, 17.3, 14.1, 14.2_

  - [x] 14.2 Build Security and GreenOps tabs
    - Replace placeholders with functional tabs: Security tab shows the security dimension score + security issues for the workload; GreenOps tab shows energy/carbon/cost dimension scores + related issues and forecasts
    - Wire to `/api/scoring/issues`, `/api/issues`, and the matrix dimension data for the workload
    - _Requirements: 17.1, 12.4_

  - [x] 14.3 Build AI Recommendations and Self-Healing tabs
    - AI Recommendations tab: list recommendations for the workload with rule traceability, risk level, execution mode, and Optimization Impact Forecast, wired to `/api/recommendations/...`
    - Self-Healing tab: show remediation history/status and execution path (auto/approval/escalation), wired to `/api/remediation/...`
    - Replace any placeholder content with these functional components
    - _Requirements: 17.1, 5.1, 11.1, 11.2_

  - [x] 14.4 Build MCP Activity tab
    - Replace placeholder with a functional MCP activity log view wired to `/api/mcp/log` (filtered by workload), showing tool name, status, duration, and input/output summary
    - _Requirements: 17.1, 10.1, 10.2_

- [x] 15. Frontend Completion — Workflow & Operations Pages (TOP PRIORITY)
  - [x] 15.1 Fully build out the Approvals page
    - Replace any placeholder content in `frontend/src/pages/Approvals.tsx` with the functional approval queue wired to `/api/approvals`
    - Each item: workload, action, AI rationale, risk badge, environment, MCP tools, time-since-request, escalation countdown, Approve/Deny/Snooze actions with confirmation modal
    - _Requirements: 9.1, 9.2, 10.3_

  - [x] 15.2 Fully build out the Reports page
    - Replace any placeholder content in `frontend/src/pages/Reports.tsx` with the functional remediation reports list + full report view wired to `/api/remediation/{id}/report`
    - Report view: execution timeline, MCP tools executed, before/after, safety decision, audit compliance, user-facing narrative
    - _Requirements: 11.1, 11.2_

  - [x] 15.3 Fully build out the Mock Controller page
    - Replace any placeholder content in `frontend/src/pages/MockController.tsx` with the functional controller wired to `/api/mock/*`
    - List 7 scenarios with trigger buttons, stream start/stop toggle, reset button, status indicator, scenario descriptions, target workloads, and expected pipeline path
    - _Requirements: 19.1, 19.2, 19.3, 19.4_

  - [x] 15.4 Fully build out the Audit Logs page
    - Create/replace `frontend/src/pages/AuditLogs.tsx` with a functional sortable table wired to the existing `/api/audit-logs` endpoint
    - Columns: timestamp, event_type, actor, workload, status change, details; filters for workload, event type, and date range
    - _Requirements: 15.1_

- [x] 16. Checkpoint - Frontend Fully Built (P0 Demo End-to-End)
  - Verify every page/tab renders real, data-wired UI with no remaining placeholder or "not yet built in this pass" text
  - Verify full demo flow: trigger scenario → issue with XAI → recommendation with forecast → self-healing → report → heatmap update
  - Idle dev server auto-fix: heatmap cell transitions from red/yellow to green
  - Critical vulnerability escalation: ticket created, notification sent, pulsing indicator, audit log
  - Verified on the live stack (backend :8000 + frontend :5174 via Vite proxy):
    - Idle dev-server scenario → idle_or_overprovisioned_workload (medium) → auto_fix → remediation REM-525932EFE089 completed + verification passed (savings realized, recommendation cleared)
    - Critical vulnerability scenario → critical_exposed_vulnerability (critical) → human_escalation → remediation REM-516047F16568 escalated, ticket TICKET-DF4FDD8B created, owner + security teams notified
    - Audit log recorded every state transition (issue_detected → recommendation_generated → remediation_escalated); MCP log captured ticket/notification/audit tool calls
  - Ask the user if questions arise.
  - _Requirements: 22.1, 22.2, 22.3_

- [x] 17. P1: Audit Logging Backend
  - [x] 17.1 Implement audit log service and event subscribers
    - Create `backend/services/audit_service.py` — append audit entries on every state transition (Issue, Recommendation, Remediation)
    - Subscribe to all relevant events on event bus (ISSUE_DETECTED, RECOMMENDATION_GENERATED, REMEDIATION_COMPLETED, SCORE_UPDATED)
    - Include workload_id, issue_id, recommendation_id, remediation_id, actor, previous_status, new_status, timestamp
    - Log rollback events with original action details and rollback outcome
    - Enforce 90-day retention
    - _Requirements: 15.1, 15.2, 15.3, 15.4_

  - [x] 17.2 Finalize audit log API endpoints
    - Ensure `backend/api/audit.py` exposes GET `/api/audit-logs` (filterable by workload_id, event_type, date range) and GET `/api/audit-logs/{id}`
    - _Requirements: 15.1, 21.1_

- [x] 18. P1: Alert System
  - [x] 18.1 Implement alert engine
    - Create `backend/modules/alerts/alert_engine.py` — generate alerts when Priority Score exceeds thresholds (>80 critical, 60-80 high, 30-60 medium, ≤30 low)
    - Subscribe to SCORE_UPDATED events
    - _Requirements: 13.1_

  - [x] 18.2 Implement alert suppression and delivery
    - Create `backend/modules/alerts/suppression.py` — 15-minute window suppression for same workload_id + issue_type, increment counter
    - Create `backend/modules/alerts/delivery.py` — deliver critical within 30s, non-critical within 5min, retry 3× at 10s intervals, mark delivery_failed
    - Implement auto-resolve within 60s when condition clears
    - Create `backend/api/alerts.py` with GET `/api/alerts` (filterable by workload, severity, status)
    - _Requirements: 13.2, 13.3, 13.4_

- [x] 19. P1: WebSocket Real-Time Updates
  - [x] 19.1 Implement WebSocket endpoint and event streaming
    - Create `backend/api/websocket.py` with WS `/ws/events` endpoint
    - Stream events: heatmap_update, alert_new, healing_status, approval_count, prediction_update
    - Subscribe to relevant event bus events and broadcast to connected WebSocket clients
    - Push updates within 2 seconds of state change
    - _Requirements: 20.1, 20.2_

  - [x] 19.2 Implement frontend WebSocket hook and stale indicator
    - Create `frontend/src/api/websocket.ts` — WebSocket manager with connect, disconnect, reconnect with exponential backoff (1s→30s max)
    - Create `frontend/src/hooks/useWebSocket.ts` — connection lifecycle, event dispatch to state
    - Create `frontend/src/hooks/useRealtime.ts` — real-time state updates for heatmap, alerts, approvals
    - Create `frontend/src/components/ui/StaleIndicator.tsx` — "Data Stale" warning on connection loss
    - _Requirements: 20.1, 20.2, 20.3_

- [x] 20. P1: Missing Monitoring Detection + Ticketing/Notification
  - [x] 20.1 Implement missing-monitoring detection and NBA path
    - Add DET-MON-001 rule evaluation in detector (monitoring_enabled == false)
    - Add RULE-MON-001 in NBA engine: enable monitoring / create ticket
    - Route: auto-enable if safe (non-prod), else create ticket via ticketing connector
    - _Requirements: 3.1, 5.1, 19.1_

  - [x] 20.2 Wire ticketing and notification connectors into self-healing
    - Ensure `ticketing_connector.py` creates tickets on escalation with full Issue + Recommendation + Workload context
    - Ensure `notification_connector.py` sends notifications to owner_team and security_team (for security issues)
    - Log all connector invocations in MCP activity log
    - Ensure `backend/api/mcp_log.py` exposes GET `/api/mcp/log`
    - _Requirements: 10.1, 10.2_

- [x] 21. Checkpoint - P1 Complete
  - Verify audit logs record every state transition
  - Verify alerts fire, suppress duplicates, and auto-resolve
  - Verify WebSocket pushes heatmap updates, alert badges, approval counts in real-time
  - Verify missing-monitoring scenario triggers full pipeline
  - Verified via backend test suite: 356 passed (incl. test_audit_service, test_alert_engine, test_alert_delivery, test_websocket, test_missing_monitoring)
  - Ask the user if questions arise.

- [x] 22. P2: Full Priority Score Engine (Stretch)
  - [x] 22.1 Implement full 6-factor weighted priority score with constraints
    - Enhance `priority_scorer.py` with constraint: security_severity and environment_type each ≥ 1.5× average of other four weights
    - Add tiebreaker: earlier detection_timestamp ranks higher
    - Recompute within 5 seconds of any state change
    - _Requirements: 12.1, 12.2, 12.3_

- [x] 23. P2: Full Alert System and Runbook Depth (Stretch)
  - [x] 23.1 Implement full alert delivery SLAs and retry logic
    - Add delivery SLA tracking: critical within 30s, non-critical within 5min
    - Implement 3× retry at 10s intervals → mark delivery_failed
    - Auto-resolve within 60s when Priority Score drops below threshold
    - _Requirements: 13.2, 13.4_

  - [x] 23.2 Implement runbook verification/rollback timeout enforcement
    - Enforce hard timeouts: runbook execution 120s → abort + escalate, verification 30s → rollback, rollback 60s → abort + escalate
    - Log timeout events in audit trail
    - _Requirements: 8.2, 8.3_

- [x] 24. Final Checkpoint - Full Platform Verification
  - Verify all 7 demo scenarios complete end-to-end within 60 seconds
  - Verify heatmap transitions (red→green on auto-fix, pulsing on critical escalation)
  - Verify all API endpoints return correct envelope format
  - Verify graceful degradation: disable ML models → platform still functions with fallbacks
  - Verified via backend test suite: 356 passed in 1229.82s (full backend coverage incl. detection, NBA, self-healing, scoring, prediction, dashboard, ML fallbacks)
  - Ask the user if questions arise.
  - _Requirements: 22.1, 22.2, 22.3_

## Notes

- Testing tasks have been removed from this plan; the focus is purely on coding/implementation.
- Frontend completion (sections 13–16) is the top priority: every page/tab must be fully built and wired to the existing backend APIs with no placeholder or "not yet built in this pass" content.
- All backend APIs consumed by the frontend pages already exist (tasks 1–8, plus the audit and MCP-log endpoints), so the frontend buildout proceeds before the P1/P2 backend stretch items.
- Each task references specific requirements for traceability.
- Checkpoints provide incremental validation at phase boundaries.
- The existing `clover_ui/` prototype can be referenced for design patterns but the new `frontend/` uses TypeScript.
- All ML models have formula/template fallbacks — the system is fully functional without ML.
- Backend is Python 3.11+ / FastAPI; Frontend is React 18 + TypeScript + Vite + Tailwind + Recharts + Lucide.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["13.1", "13.2", "13.3", "13.4", "15.1", "15.2", "15.3", "15.4"] },
    { "id": 1, "tasks": ["14.1"] },
    { "id": 2, "tasks": ["14.2"] },
    { "id": 3, "tasks": ["14.3"] },
    { "id": 4, "tasks": ["14.4"] },
    { "id": 5, "tasks": ["17.1", "18.1", "19.1", "20.1"] },
    { "id": 6, "tasks": ["17.2", "18.2", "19.2", "20.2"] },
    { "id": 7, "tasks": ["22.1", "23.1", "23.2"] }
  ]
}
```

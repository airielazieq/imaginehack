# Requirements Document

## Introduction

Clover is a secure, energy-aware cloud intelligence platform built for the ImagineHack 2026 hackathon (HILTI Track 2: Secure & Energy-Aware Cloud Platforms for Construction Tech). The platform continuously monitors construction-tech cloud workloads, detects anomalies and inefficiencies using ML and rules, explains findings with explainable AI, recommends the next best action with projected cost/energy/carbon forecasts, and safely remediates through a guardrailed self-healing workflow with full audit trail. The system operates on synthetic cloud telemetry from a live mock data generator.

## Glossary

- **Clover_Platform**: The complete cloud intelligence platform comprising Detection, Next Best Action, and Self-Healing modules
- **Detection_Engine**: Module 1 subsystem that ingests telemetry, runs Isolation Forest anomaly detection, applies rule-based classification, generates SHAP explanations, and produces Issue objects
- **NBA_Engine**: Module 2 Next Best Action subsystem that applies deterministic rules to select recommendations, assigns risk levels, determines execution mode, and generates XGBoost-based forecasts
- **Self_Healing_Engine**: Module 3 subsystem that enforces safety rules, routes remediations through auto-fix/approval/escalation paths, executes runbooks via simulated MCP connectors, and generates reports
- **Scoring_Engine**: Cross-cutting subsystem that computes a weighted Priority Score (0-100) from 6 factors and dimension-level scores for each workload
- **Alert_System**: Cross-cutting subsystem that generates, delivers, suppresses, and resolves alerts based on scoring thresholds
- **Downtime_Predictor**: Cross-cutting subsystem that estimates failure probability, time-to-failure, and risk timeline for each workload
- **Mock_Data_Generator**: Subsystem that produces synthetic cloud telemetry for 8+ construction-tech workloads and supports scenario triggers, continuous streaming, and reset
- **Workload**: The canonical entity representing a construction-tech cloud resource (VM, container, database, storage, serverless function, or pipeline) carrying the full telemetry-to-remediation pipeline
- **Issue**: A detected anomaly or inefficiency classified into one of 7+ issue types with severity, confidence, ML result, XAI explanation, and estimated impact
- **Recommendation**: A next-best-action object containing the suggested fix, risk level, execution mode, forecast, and optimization impact comparison
- **Remediation_Result**: The outcome of executing a recommendation through one of three paths (auto-fix, user-approved, escalated) including verification, rollback status, and audit compliance
- **MCP_Connector**: A simulated Model Context Protocol connector for cloud infrastructure, ticketing, notification, or audit operations
- **Runbook**: A structured sequence of MCP tool invocations with verification (30s timeout) and rollback (60s timeout) steps
- **Priority_Score**: A composite 0-100 score computed from 6 weighted factors (security_severity, energy_waste, cost_waste, workflow_criticality, environment_type, self_healing_safety) that drives the composite heatmap
- **Dimension_Scores**: Per-workload scores across 6 dimensions (security, energy, carbon, cost, performance, monitoring) each mapped to green/yellow/red/gray state for the matrix heatmap
- **Approval_Queue**: A global queue of pending remediations sorted by criticality (Critical→High→Medium→Low) with escalation countdown timers
- **Audit_Log**: An append-only record of every meaningful platform event with 90-day retention

## Requirements

### Requirement 1: Telemetry Ingestion

**User Story:** As a platform operator, I want the system to ingest telemetry snapshots from construction-tech cloud workloads, so that I have continuous visibility into workload health, cost, energy, and security posture.

#### Acceptance Criteria

1. WHEN a TelemetrySnapshot is received via the ingestion API, THE Clover_Platform SHALL validate all numeric fields against defined bounds (cpu/memory/error_rate in [0,100], counts ≥ 0, cost in [0, 999999.99]) and persist the snapshot within 500ms
2. IF a TelemetrySnapshot contains out-of-bounds values, THEN THE Clover_Platform SHALL reject the snapshot with a descriptive validation error and return HTTP 422
3. WHEN a valid TelemetrySnapshot is persisted, THE Clover_Platform SHALL emit an internal event to trigger the Detection_Engine pipeline for the associated Workload
4. THE Clover_Platform SHALL support ingestion of telemetry for 8 or more concurrent Workloads without data loss

### Requirement 2: Anomaly Detection

**User Story:** As a platform operator, I want the system to automatically detect anomalies in workload telemetry using unsupervised ML, so that I am alerted to unusual patterns that rules alone might miss.

#### Acceptance Criteria

1. WHEN a new TelemetrySnapshot triggers the Detection_Engine, THE Detection_Engine SHALL run the Isolation Forest model and produce an anomaly score and binary is_anomaly classification
2. WHEN the Isolation Forest model produces a result, THE Detection_Engine SHALL generate SHAP-style feature contributions identifying the top contributing factors to the anomaly score
3. IF the Isolation Forest model fails or is unavailable, THEN THE Detection_Engine SHALL fall back to rules-only detection and log the model failure event
4. THE Detection_Engine SHALL complete anomaly detection and produce an Issue object within 2 seconds of receiving a TelemetrySnapshot

### Requirement 3: Issue Classification

**User Story:** As a platform operator, I want detected anomalies classified into specific issue types, so that I can quickly understand what category of problem has been found.

#### Acceptance Criteria

1. WHEN an anomaly is detected, THE Detection_Engine SHALL classify the Issue into exactly one of the defined types: public_storage, critical_exposed_vulnerability, idle_or_overprovisioned_workload, carbon_heavy_workload, no_monitoring, high_error_rate, or cost_spike_or_waste
2. THE Detection_Engine SHALL assign a severity level (low, medium, high, or critical) and a confidence score between 0.0 and 1.0 to each classified Issue
3. WHEN multiple issues are detected for the same Workload within a 5-minute window, THE Detection_Engine SHALL consolidate related issues into a single Issue object with the highest severity among them

### Requirement 4: Explainable AI Explanations

**User Story:** As a platform operator, I want human-readable explanations of detected issues, so that I understand why the system flagged a workload and can make informed decisions.

#### Acceptance Criteria

1. WHEN an Issue is classified, THE Detection_Engine SHALL generate an LLM-produced user-facing explanation describing why the issue matters in plain language
2. THE Detection_Engine SHALL include a structured XAI explanation card containing the SHAP method name, top contributing factors (feature name, value, and impact description) with each Issue
3. IF the LLM is unavailable, THEN THE Detection_Engine SHALL use a pre-defined template explanation based on the issue type and detected evidence
4. THE Detection_Engine SHALL use the LLM exclusively for wording and presentation, never for classification or severity decisions

### Requirement 5: Next Best Action Recommendation

**User Story:** As a platform operator, I want deterministic, explainable recommendations for each detected issue, so that I know the safest and most effective fix without guessing.

#### Acceptance Criteria

1. WHEN an Issue is produced by the Detection_Engine, THE NBA_Engine SHALL apply rule-based logic to generate exactly one Recommendation with a specified action category and type
2. THE NBA_Engine SHALL assign a risk level (low, medium, high, or critical) to each Recommendation based on the Workload environment, action reversibility, sensitive data exposure, and workflow criticality
3. THE NBA_Engine SHALL select an execution mode (auto_fix, user_approval_required, or human_escalation_required) for each Recommendation based on the assigned risk level and safety constraints
4. WHEN a Recommendation is generated, THE NBA_Engine SHALL record the triggered rule ID and matched conditions for full audit traceability

### Requirement 6: Cost, Energy, and Carbon Forecasting

**User Story:** As a platform operator, I want 30-day projections of cost, energy, and carbon impact with and without remediation, so that I can see the quantified benefit of acting on a recommendation.

#### Acceptance Criteria

1. WHEN a Recommendation is generated, THE NBA_Engine SHALL produce a 30-day forecast for cost (USD), energy (kWh), and carbon (kgCO2e) using the XGBoost Regressor model
2. THE NBA_Engine SHALL compute an Optimization Impact Forecast containing three components: forecast without action, forecast after action, and projected savings
3. IF the XGBoost model is unavailable, THEN THE NBA_Engine SHALL fall back to a formula-based forecast using current telemetry values extrapolated linearly over 30 days
4. THE NBA_Engine SHALL ensure projected savings values are non-negative and logically consistent (forecast_without_action minus forecast_after_action equals projected_savings for each dimension)

### Requirement 7: Safety Rules and Execution Path Routing

**User Story:** As a platform operator, I want safety rules to govern which remediations execute automatically, which require my approval, and which escalate to a human expert, so that production and sensitive systems are never modified without appropriate oversight.

#### Acceptance Criteria

1. THE Self_Healing_Engine SHALL permit auto-fix execution ONLY when ALL of the following conditions are met: the Workload environment is non-production, the action is reversible, no sensitive data is affected, no database is affected, no network or security policy is modified, workflow criticality is low or medium, and a rollback_note exists
2. WHEN any auto-fix safety condition is not met, THE Self_Healing_Engine SHALL route the Recommendation to user_approval_required or human_escalation_required based on the risk level
3. THE Self_Healing_Engine SHALL make safety routing decisions using deterministic rules only, never using LLM output
4. WHEN a Recommendation has risk level critical, THE Self_Healing_Engine SHALL route it to human_escalation_required regardless of other conditions

### Requirement 8: Auto-Fix Execution

**User Story:** As a platform operator, I want low-risk remediations on non-production workloads to execute automatically, so that routine fixes happen without manual intervention.

#### Acceptance Criteria

1. WHEN a Recommendation is routed to auto_fix, THE Self_Healing_Engine SHALL execute the associated Runbook steps via the appropriate MCP_Connector
2. WHEN an auto-fix Runbook completes, THE Self_Healing_Engine SHALL run a verification check within 30 seconds to confirm the fix was applied successfully
3. IF verification fails after an auto-fix, THEN THE Self_Healing_Engine SHALL trigger a rollback within 60 seconds and escalate the Issue to human_escalation_required
4. WHEN an auto-fix completes (success or rollback), THE Self_Healing_Engine SHALL generate a Remediation_Result with full execution timeline, MCP tools executed, and audit compliance record

### Requirement 9: Approval Queue and User-Approved Fix

**User Story:** As a platform operator, I want a prioritized approval queue for medium-risk remediations, so that I can review and authorize fixes before they execute.

#### Acceptance Criteria

1. WHEN a Recommendation is routed to user_approval_required, THE Self_Healing_Engine SHALL add it to the Approval_Queue sorted by severity (Critical → High → Medium → Low)
2. WHILE a Recommendation with risk level high is pending in the Approval_Queue, THE Self_Healing_Engine SHALL display an escalation countdown timer starting at 15 minutes
3. WHEN the escalation countdown reaches zero without user action, THE Self_Healing_Engine SHALL automatically escalate the Recommendation to human_escalation_required
4. WHEN a user approves a Recommendation, THE Self_Healing_Engine SHALL execute the associated Runbook with the same verification and rollback guarantees as auto-fix

### Requirement 10: Human Escalation

**User Story:** As a platform operator, I want critical or complex issues escalated to human experts with full context, so that dangerous fixes are never applied without expert review.

#### Acceptance Criteria

1. WHEN a Recommendation is routed to human_escalation_required, THE Self_Healing_Engine SHALL create a ticket via the simulated ticketing MCP_Connector with full Issue, Recommendation, and Workload context
2. WHEN a human escalation is triggered, THE Self_Healing_Engine SHALL send a notification via the simulated notification MCP_Connector to the Workload owner team and security team (for security issues)
3. THE Self_Healing_Engine SHALL display a pulsing visual indicator on the Approval_Queue page for any critical-severity escalated item

### Requirement 11: Remediation Reporting

**User Story:** As a platform operator, I want a detailed remediation report generated after every fix attempt, so that I have a complete record of what happened, why, and what changed.

#### Acceptance Criteria

1. WHEN a remediation completes through any execution path, THE Self_Healing_Engine SHALL generate a Remediation_Result containing: execution path taken, actions performed, safety decision rationale, AI decision steps with timestamps, MCP tools executed with inputs/outputs, before/after impact metrics, and audit compliance record
2. THE Self_Healing_Engine SHALL generate a user-facing report narrative summarizing the remediation in plain language
3. THE Self_Healing_Engine SHALL persist each Remediation_Result with a link to the originating Issue, Recommendation, and Workload for traceability

### Requirement 12: Priority Scoring

**User Story:** As a platform operator, I want each workload assigned a composite priority score based on multiple factors, so that I can instantly identify which workloads need attention most.

#### Acceptance Criteria

1. THE Scoring_Engine SHALL compute a Priority_Score (0-100, 1 decimal place) for each Workload using 6 weighted factors: security_severity, energy_waste, cost_waste, workflow_criticality, environment_type, and self_healing_safety
2. THE Scoring_Engine SHALL enforce that configured factor weights sum to exactly 1.0, rejecting invalid weight configurations
3. WHEN any Issue, Recommendation, or Remediation changes state for a Workload, THE Scoring_Engine SHALL recompute the Priority_Score within 5 seconds
4. THE Scoring_Engine SHALL compute Dimension_Scores (security, energy, carbon, cost, performance, monitoring) for each Workload, mapping each dimension to a numeric score (0-100) and a state (green, yellow, red, or gray)

### Requirement 13: Alert System

**User Story:** As a platform operator, I want alerts generated when workloads breach critical thresholds, so that urgent situations are surfaced immediately without waiting for manual review.

#### Acceptance Criteria

1. WHEN a Priority_Score exceeds the critical threshold, THE Alert_System SHALL generate an alert with severity derived from the Priority_Score
2. THE Alert_System SHALL deliver critical alerts within 30 seconds and non-critical alerts within 5 minutes of generation
3. WHILE an alert with the same workload_id and issue_type exists within a 15-minute window, THE Alert_System SHALL suppress duplicate alerts and increment a suppression counter
4. WHEN an alert condition is resolved, THE Alert_System SHALL auto-resolve the corresponding alert within 60 seconds

### Requirement 14: Downtime Prediction

**User Story:** As a platform operator, I want AI-driven predictions of workload failure probability, so that I can take preemptive action before an outage occurs.

#### Acceptance Criteria

1. THE Downtime_Predictor SHALL compute a failure probability (0-100%), estimated time-to-failure, and confidence level (low, medium, or high) for each Workload based on telemetry trends
2. THE Downtime_Predictor SHALL generate a 12-point risk timeline showing predicted risk progression over the next 12 hours
3. WHEN the failure probability exceeds 70%, THE Downtime_Predictor SHALL trigger a preemptive Recommendation via the NBA_Engine
4. THE Downtime_Predictor SHALL identify primary and secondary contributing signals that drive the prediction

### Requirement 15: Audit Logging

**User Story:** As a platform operator, I want every meaningful platform event logged with full context, so that I have a complete audit trail for compliance and troubleshooting.

#### Acceptance Criteria

1. THE Clover_Platform SHALL log an Audit_Log entry for every state transition of an Issue, Recommendation, or Remediation, including actor, previous status, new status, and timestamp
2. THE Clover_Platform SHALL retain Audit_Log entries for 90 days from creation
3. THE Clover_Platform SHALL include workload_id, issue_id, recommendation_id, and remediation_id (where applicable) in each Audit_Log entry for cross-reference traceability
4. WHEN a rollback is triggered, THE Clover_Platform SHALL log the rollback event with the original action details and rollback outcome

### Requirement 16: Dashboard Heatmap Visualization

**User Story:** As a platform operator, I want a dual-heatmap dashboard showing workload health at a glance, so that I can identify problem areas in seconds.

#### Acceptance Criteria

1. THE Clover_Platform SHALL display a composite heatmap grid with one cell per Workload, colored on a continuous green-to-red gradient based on the Priority_Score (0 = green, 100 = red)
2. THE Clover_Platform SHALL provide a toggle to switch between the composite grid view and a dimension matrix view (rows = workloads, columns = Security/Energy/Carbon/Cost/Performance/Monitoring)
3. WHEN a user hovers over a composite heatmap cell, THE Clover_Platform SHALL display a tooltip showing workload name, priority score, status, top alert, and downtime risk
4. WHEN a user clicks a heatmap cell, THE Clover_Platform SHALL navigate to the Workload detail page

### Requirement 17: Workload Detail View

**User Story:** As a platform operator, I want a comprehensive workload detail page with tabs for different concern areas, so that I can drill into specific aspects of a workload's health.

#### Acceptance Criteria

1. THE Clover_Platform SHALL display a Workload detail page with tabs for: Overview, Security, GreenOps, AI Recommendations, Self-Healing, and MCP Activity
2. THE Clover_Platform SHALL include a Downtime Prediction panel on the Overview tab showing failure probability, time-to-failure, contributing signals, and a 12-point risk timeline chart
3. THE Clover_Platform SHALL include a 90-day uptime bar on the Overview tab visualizing historical availability segments

### Requirement 18: Issues List and Detail

**User Story:** As a platform operator, I want a filterable list of all detected issues and a detail page for each, so that I can review the full context of any finding.

#### Acceptance Criteria

1. THE Clover_Platform SHALL display an Issues List page showing all active Issues with columns for workload name, issue type, severity, confidence, and detected timestamp
2. THE Clover_Platform SHALL provide filter controls on the Issues List for issue_type, severity, and issue_category
3. WHEN a user selects an Issue, THE Clover_Platform SHALL display a detail page containing the XAI explanation card, Optimization Impact Forecast (before/after/savings), recommended action, and execution status

### Requirement 19: Mock Data Controller

**User Story:** As a demo presenter, I want a mock data controller page to trigger scenarios, control data streams, and reset state, so that I can reliably demonstrate the platform's capabilities during the hackathon pitch.

#### Acceptance Criteria

1. THE Mock_Data_Generator SHALL provide 7 demo scenarios: idle dev server (auto-fix path), public storage (approval/escalation path), critical vulnerability (human escalation path), carbon-heavy batch workload, missing monitoring, cost spike, and high error rate
2. WHEN a user triggers a scenario via the Mock Data Controller, THE Mock_Data_Generator SHALL inject the corresponding telemetry within 2 seconds and the full detection-to-recommendation pipeline SHALL complete within 10 seconds
3. THE Mock_Data_Generator SHALL support both manual one-shot scenario triggers and continuous streaming mode
4. WHEN a user triggers a reset via the Mock Data Controller, THE Mock_Data_Generator SHALL return all Workloads to a healthy baseline state within 5 seconds

### Requirement 20: Real-Time Updates

**User Story:** As a platform operator, I want the dashboard to reflect changes in real-time without manual refresh, so that I always see the current state of the system.

#### Acceptance Criteria

1. WHEN an Issue, Recommendation, or Remediation state changes, THE Clover_Platform SHALL push the update to connected clients via WebSocket within 2 seconds
2. THE Clover_Platform SHALL push real-time updates for: heatmap cell color changes, new alert badges, self-healing status transitions, and approval queue count changes
3. IF the WebSocket connection is lost, THEN THE Clover_Platform SHALL display a "data stale" indicator in the UI and attempt reconnection with exponential backoff

### Requirement 21: API Layer

**User Story:** As a frontend developer, I want a well-structured REST and WebSocket API, so that the UI can retrieve and display all platform data reliably.

#### Acceptance Criteria

1. THE Clover_Platform SHALL expose a FastAPI REST API with endpoint groups for: telemetry ingestion, workloads, detection/issues, recommendations/forecast, remediation/approvals, scoring/alerts/audit, dashboard summary, and mock controller
2. THE Clover_Platform SHALL expose a WebSocket endpoint that streams real-time events for heatmap updates, alert notifications, healing status changes, and approval queue counts
3. WHEN any REST endpoint encounters an error, THE Clover_Platform SHALL return a structured JSON error response with an error code, human-readable message, and request correlation ID

### Requirement 22: End-to-End Demo Flow

**User Story:** As a demo presenter, I want to trigger a scenario and see the complete pipeline (detection → explanation → recommendation → remediation → report → heatmap update) execute end-to-end in under 60 seconds, so that the pitch demonstrates the full value proposition within the judging timeframe.

#### Acceptance Criteria

1. WHEN a demo scenario is triggered, THE Clover_Platform SHALL complete the full pipeline from telemetry injection through detection, recommendation, remediation, and heatmap update within 60 seconds
2. WHEN the auto-fix demo scenario (idle dev server) completes, THE Clover_Platform SHALL show the workload heatmap cell transition from red/yellow to green
3. WHEN the escalation demo scenario (critical vulnerability) completes, THE Clover_Platform SHALL show a ticket created, notification sent, pulsing indicator on the approval queue, and audit log entry recorded

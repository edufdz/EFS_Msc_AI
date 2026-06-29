// TypeScript types mirroring backend Pydantic models

export interface Session {
  session_id: string
  output_dir: string
  created_at: string
  phases_completed: string[]
}

export interface PhaseStatus {
  session_id: string
  phase: string
  status: 'idle' | 'running' | 'completed' | 'error'
  progress_pct: number
  message: string
  result: Record<string, unknown> | null
  error: string | null
}

// Phase A
export interface PhaseARequest {
  session_id: string
  repo_path: string
  skip_ai: boolean
  language: string | null
  prompt_encoding: string
  context_budget?: number
  use_traces: boolean
}

export interface PhaseAResult {
  framework: string
  framework_confidence: number
  tools_count: number
  prompts_count: number
  risks_count: number
  files_scanned: number
  language: string
  agent_map_path: string
  graph_path: string | null
  tools: Array<{ name: string; description: string; risk_level: string }>
  risks: Array<{ tool: string; risk_type: string; severity: string; description: string }>
}

// Phase B
export interface PhaseBRequest {
  session_id: string
  count: number
  persona_count: number
  scenario_count: number
  variants: number
  seed: number | null
  language: string | null
  include_templates: boolean
  llm_provider?: string
  llm_model?: string
  llm_base_url?: string
}

export interface PhaseBResult {
  test_suite_path: string
  total_tests: number
  persona_count: number
  scenario_count: number
  personas: Array<{ name: string; agent_type: string; source: string }>
  scenarios: Array<{ title: string; difficulty: string; required_tools: string[] }>
  tokens_used?: number
  cost_usd?: number
}

// Phase C
export interface PhaseCRequest {
  session_id: string
  workers: number
  count: number
  ai_personas: boolean
  traces: boolean
  seed: number | null
  language: string | null
  persona_context: string | null
  validate: boolean
  agent_endpoint?: string | null
  llm_provider?: string | null
  llm_model?: string | null
  llm_base_url?: string | null
}

export interface TriageSummary {
  genuine_failures: number
  persona_filtered: number
  chaos_filtered: number
  false_successes: number
}

export interface PhaseCResult {
  total_tests: number
  passed: number
  failed: number
  errors: number
  timeouts: number
  pass_rate: number
  total_duration_sec: number
  total_cost_usd: number
  tool_coverage_pct: number
  tools_not_covered: string[]
  by_difficulty: Record<string, Record<string, number>>
  triage: TriageSummary | null
}

// Phase D
export interface PhaseDRequest {
  session_id: string
  skip_ai: boolean
  use_embeddings: boolean
  max_retries: number
  backoff_base: number
  backoff_max: number
}

export interface FailureExample {
  test_id: string
  test_number: number
  scenario: string
  persona: string
  failure_reason: string
  trace_file: string
  difficulty: string
  coverage_goal: string
  tools_called: string[]
  tools_expected: string[]
  turn_count: number
  duration_sec: number
  chaos_events: Array<Record<string, unknown>>
}

export interface MinimalReproduction {
  steps: Array<{ role: string; content: string }>
  expected_behavior: string
  actual_behavior: string
  key_trigger: string
}

export interface FailureCluster {
  cluster_id: string
  cluster_name: string
  failure_count: number
  failure_examples: FailureExample[]
  root_cause_type: string
  root_cause_description: string
  common_pattern: string
  key_indicators: string[]
  severity: string
  affected_scenarios: string[]
  affected_tools: string[]
  minimal_reproduction: MinimalReproduction | null
  created_at: string
}

export interface FixProposal {
  fix_id: string
  cluster_id: string
  fix_type: string
  description: string
  changes: Record<string, unknown>
  estimated_fix_rate: number
  estimated_effort: string
  risk_level: string
  created_at: string
}

export interface DiagnosisSummary {
  total_failures_analyzed: number
  total_tests: number
  failure_rate: number
  by_root_cause: Record<string, number>
  by_severity: Record<string, number>
  fix_proposals_by_type: Record<string, number>
  clusters_count: number
  fixes_count: number
  bug_discovery_rate?: number
  redundancy_rate?: number
  severity_weighted_score?: number
}

export interface PhaseDResult {
  report_id: string
  run_id: string
  total_failures: number
  clusters_found: number
  clusters: FailureCluster[]
  fix_proposals: FixProposal[]
  priority_ranking: string[]
  summary: DiagnosisSummary
  generated_at: string | null
}

// Certification
export type CertificationTier = 'platinum' | 'gold' | 'silver' | 'not_certified'

export interface CertificationCategoryScore {
  category: string
  score: number
  weight: number
  breakdown: Record<string, number>
  notes: string[]
}

export interface CertificationHardBlocker {
  blocker_type: string
  condition: string
  evidence: string
  tier_blocked: CertificationTier
}

export interface CertificationConfidence {
  total_simulations: number
  confidence_level: number
  margin_of_error: number
  sample_sufficient: boolean
}

export interface CertificationTestingConditions {
  total_simulations: number
  by_difficulty: Record<string, number>
  chaos_tested: boolean
  persona_count: number
  persona_diversity: number
}

export interface CertificationReport {
  certification_id: string
  agent_name: string
  agent_framework: string
  tier: CertificationTier
  overall_score: number
  category_scores: CertificationCategoryScore[]
  hard_blockers: CertificationHardBlocker[]
  strengths: string[]
  improvements: string[]
  testing_conditions: CertificationTestingConditions
  confidence: CertificationConfidence
  radar_chart_data: Record<string, number>
  issued_at: string | null
  expires_at: string | null
}

export interface CertificationRequest {
  session_id: string
}

// Trace types
export interface TraceToolCall {
  tool_name: string
  tool_id: string
  arguments: Record<string, unknown>
  result: unknown
}

export interface TraceTurn {
  turn_number: number
  role: string
  message: string
  tool_calls: TraceToolCall[]
  timestamp: string
  duration_ms: number
}

export interface TraceData {
  test_id: string
  status: string
  turns: TraceTurn[]
  failure_reason: string | null
  duration_sec: number
  total_cost_usd: number
  tools_called: string[]
  tools_expected: string[]
}

// Filesystem browser
export interface FileEntry {
  name: string
  type: 'file' | 'directory'
  path: string
  size: number | null
}

export interface FileBrowseResponse {
  current_path: string
  parent_path: string | null
  entries: FileEntry[]
}

// WebSocket events
export interface WSEvent {
  type: string
  phase?: string
  session_id?: string
  step?: string
  message?: string
  progress_pct?: number
  timestamp?: number
  // Phase C execution events
  test_id?: string
  test_number?: number
  scenario?: string
  persona?: string
  difficulty?: string
  status?: string
  failure_reason?: string
  turn?: number
  role?: string
  tool_name?: string
  tools_called?: string[]
  pass_rate?: number
  cost_usd?: number
  duration_sec?: number
  _totals?: {
    passed: number
    failed: number
    errors: number
    timeouts: number
    completed: number
    total_tests: number
    total_cost_usd: number
    pass_rate: number
    tools_covered: number
    tools_total: number
  }
  result?: Record<string, unknown>
  error?: string
  summary?: Record<string, unknown>
}

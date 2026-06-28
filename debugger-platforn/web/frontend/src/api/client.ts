// REST API client for the FastAPI backend

const BASE = ''  // Vite proxy handles /api -> localhost:8000

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(body.detail || `HTTP ${res.status}`)
  }
  return res.json()
}

// Sessions
export interface SessionSummary {
  session_id: string
  output_dir: string
  created_at: string
  phases_completed: string[]
  phase_status?: Record<string, string>
  phase_results?: Record<string, Record<string, unknown>>
}

export const createSession = () =>
  request<SessionSummary>('/api/sessions', { method: 'POST' })

export const listSessions = () =>
  request<{ sessions: SessionSummary[] }>('/api/sessions')

export const getSession = (id: string) =>
  request<SessionSummary>(`/api/sessions/${id}`)

export const saveSession = (id: string) =>
  request<{ saved: boolean; session_id: string }>(`/api/sessions/${id}/save`, { method: 'POST' })

// Filesystem
export const resolveDirectory = (name: string, files: string[]) =>
  request<{ path: string | null }>('/api/fs/resolve-directory', {
    method: 'POST',
    body: JSON.stringify({ name, files }),
  })

export const browseDirectory = (path: string, showHidden = false) =>
  request<{ current_path: string; parent_path: string | null; entries: Array<{ name: string; type: string; path: string; size: number | null }> }>(
    '/api/fs/browse',
    { method: 'POST', body: JSON.stringify({ path, show_hidden: showHidden }) },
  )

// Phase A
export const runPhaseA = (body: { session_id: string; repo_path: string; skip_ai: boolean; language: string | null; prompt_encoding: string }) =>
  request<{ status: string; session_id: string }>('/api/phase-a/run', { method: 'POST', body: JSON.stringify(body) })

export const getPhaseAStatus = (sessionId: string) =>
  request<{ session_id: string; phase: string; status: string; progress_pct?: number; message?: string; result: Record<string, unknown> | null }>(`/api/phase-a/status/${sessionId}`)

// Phase B
export const runPhaseB = (body: { session_id: string; count: number; persona_count: number; scenario_count: number; variants: number; seed: number | null; language: string | null; include_templates: boolean; llm_provider?: string | null; llm_model?: string | null; llm_base_url?: string | null }) =>
  request<{ status: string; session_id: string }>('/api/phase-b/run', { method: 'POST', body: JSON.stringify(body) })

export const getPhaseBStatus = (sessionId: string) =>
  request<{ session_id: string; phase: string; status: string; progress_pct?: number; message?: string; result: Record<string, unknown> | null }>(`/api/phase-b/status/${sessionId}`)

// Phase C
export const runPhaseC = (body: { session_id: string; workers: number; count: number; ai_personas: boolean; traces: boolean; seed: number | null; language: string | null; persona_context: string | null; validate: boolean; agent_endpoint?: string | null; llm_provider?: string | null; llm_model?: string | null; llm_base_url?: string | null }) =>
  request<{ status: string; session_id: string }>('/api/phase-c/run', { method: 'POST', body: JSON.stringify(body) })

export const getPhaseCStatus = (sessionId: string) =>
  request<{ session_id: string; phase: string; status: string; progress_pct?: number; message?: string; result: Record<string, unknown> | null }>(`/api/phase-c/status/${sessionId}`)

export interface SavedTrace {
  test_id: string
  test_number: number
  scenario: string
  persona: string
  difficulty: string
  status: string
  turns: Array<{ turn: number; role: string; message: string; duration_ms: number }>
  tool_calls: Array<{ tool_name: string; status: string }>
}

export const getPhaseCTraces = (sessionId: string) =>
  request<{ traces: SavedTrace[] }>(`/api/phase-c/traces/${sessionId}`)

// Phase D
export const runPhaseD = (body: { session_id: string; skip_ai: boolean; use_embeddings: boolean; max_retries: number; backoff_base: number; backoff_max: number }) =>
  request<{ status: string; session_id: string }>('/api/phase-d/run', { method: 'POST', body: JSON.stringify(body) })

export const getPhaseDStatus = (sessionId: string) =>
  request<{ session_id: string; phase: string; status: string; progress_pct?: number; message?: string; result: Record<string, unknown> | null }>(`/api/phase-d/status/${sessionId}`)

// Certification
export const runCertification = (body: { session_id: string }) =>
  request<{ status: string; session_id: string }>('/api/certification/run', { method: 'POST', body: JSON.stringify(body) })

export const getCertificationStatus = (sessionId: string) =>
  request<{ session_id: string; phase: string; status: string; progress_pct?: number; message?: string; result: Record<string, unknown> | null }>(`/api/certification/status/${sessionId}`)

// Phase reset
export const resetPhase = (sessionId: string, phase: string) =>
  request<{ reset_phases: string[]; session_id: string }>(`/api/sessions/${sessionId}/reset-phase/${phase}`, { method: 'POST' })

// Trace
export const getTrace = (sessionId: string, traceFilename: string) =>
  request<import('./types').TraceData>(`/api/phase-d/trace/${sessionId}/${traceFilename}`)

// Artifacts
export const getArtifact = (sessionId: string, type: string) =>
  request<unknown>(`/api/artifacts/${sessionId}/${type}`)

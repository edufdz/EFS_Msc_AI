// Zustand store for global app state

import { create } from 'zustand'
import type { PhaseAResult, PhaseBResult, PhaseCResult, PhaseDResult, CertificationReport, TriageSummary, WSEvent } from '../api/types'

export type PhaseStatusValue = 'idle' | 'running' | 'completed' | 'error'

interface ActiveTest {
  test_id: string
  test_number: number
  scenario: string
  persona: string
  difficulty: string
  status: string
  turns: Array<{ turn: number; role: string; message: string; duration_ms: number }>
  tool_calls: Array<{ tool_name: string; status: string }>
}

interface EventLogEntry {
  ts: number
  icon: string
  text: string
  color: string
}

export interface AppState {
  // Session
  sessionId: string | null
  setSessionId: (id: string | null) => void

  // WS connection
  wsConnected: boolean
  setWsConnected: (v: boolean) => void

  // Phase statuses
  phaseA: PhaseStatusValue
  phaseB: PhaseStatusValue
  phaseC: PhaseStatusValue
  phaseD: PhaseStatusValue
  certStatus: PhaseStatusValue
  setPhaseStatus: (phase: 'a' | 'b' | 'c' | 'd' | 'cert', status: PhaseStatusValue) => void

  // Phase progress
  phaseAProgress: { step: string; message: string; pct: number }
  phaseBProgress: { step: string; message: string; pct: number }
  phaseCProgress: { step: string; message: string; pct: number }
  phaseDProgress: { step: string; message: string; pct: number }
  certProgress: { step: string; message: string; pct: number }
  setPhaseProgress: (phase: 'a' | 'b' | 'c' | 'd' | 'cert', step: string, message: string, pct: number) => void

  // Phase results
  phaseAResult: PhaseAResult | null
  phaseBResult: PhaseBResult | null
  phaseCResult: PhaseCResult | null
  phaseDResult: PhaseDResult | null
  certResult: CertificationReport | null
  setPhaseAResult: (r: PhaseAResult | null) => void
  setPhaseBResult: (r: PhaseBResult | null) => void
  setPhaseCResult: (r: PhaseCResult | null) => void
  setPhaseDResult: (r: PhaseDResult | null) => void
  setCertResult: (r: CertificationReport | null) => void

  // Phase C live monitor state
  totalTests: number
  passedTests: number
  failedTests: number
  errorTests: number
  timeoutTests: number
  completedTests: number
  passRate: number
  totalCost: number
  toolsCalled: Set<string>
  allTools: string[]
  activeTests: Map<string, ActiveTest>
  eventLog: EventLogEntry[]
  failures: Array<Record<string, unknown>>
  triageSummary: TriageSummary | null
  setAllTools: (tools: string[]) => void
  handleExecutionEvent: (event: WSEvent) => void
  hydratePhaseCFromResult: (r: PhaseCResult) => void
  hydratePhaseCTraces: (traces: Array<{
    test_id: string; test_number: number; scenario: string; persona: string;
    difficulty: string; status: string;
    turns: Array<{ turn: number; role: string; message: string; duration_ms: number }>;
    tool_calls: Array<{ tool_name: string; status: string }>;
  }>) => void

  // Hydrate full session from server
  hydrateSession: (sessionId: string, phaseStatus: Record<string, string>, phaseResults: Record<string, Record<string, unknown>>) => void

  // Reset
  resetPhase: (phase: 'a' | 'b' | 'c' | 'd' | 'cert') => void
  resetSession: () => void
}

const defaultProgress = { step: '', message: '', pct: 0 }

export const useStore = create<AppState>((set, get) => ({
  sessionId: null,
  setSessionId: (id) => set({ sessionId: id }),

  wsConnected: false,
  setWsConnected: (v) => set({ wsConnected: v }),

  phaseA: 'idle',
  phaseB: 'idle',
  phaseC: 'idle',
  phaseD: 'idle',
  certStatus: 'idle',
  setPhaseStatus: (phase, status) => {
    if (phase === 'a') set({ phaseA: status })
    else if (phase === 'b') set({ phaseB: status })
    else if (phase === 'c') set({ phaseC: status })
    else if (phase === 'd') set({ phaseD: status })
    else if (phase === 'cert') set({ certStatus: status })
  },

  phaseAProgress: { ...defaultProgress },
  phaseBProgress: { ...defaultProgress },
  phaseCProgress: { ...defaultProgress },
  phaseDProgress: { ...defaultProgress },
  certProgress: { ...defaultProgress },
  setPhaseProgress: (phase, step, message, pct) => {
    const key = phase === 'a' ? 'phaseAProgress' : phase === 'b' ? 'phaseBProgress' : phase === 'c' ? 'phaseCProgress' : phase === 'd' ? 'phaseDProgress' : 'certProgress'
    set({ [key]: { step, message, pct } })
  },

  phaseAResult: null,
  phaseBResult: null,
  phaseCResult: null,
  phaseDResult: null,
  certResult: null,
  setPhaseAResult: (r) => set({ phaseAResult: r }),
  setPhaseBResult: (r) => set({ phaseBResult: r }),
  setPhaseCResult: (r) => set({ phaseCResult: r }),
  setPhaseDResult: (r) => set({ phaseDResult: r }),
  setCertResult: (r) => set({ certResult: r }),

  // Phase C live state
  totalTests: 0,
  passedTests: 0,
  failedTests: 0,
  errorTests: 0,
  timeoutTests: 0,
  completedTests: 0,
  passRate: 0,
  totalCost: 0,
  toolsCalled: new Set(),
  allTools: [],
  activeTests: new Map(),
  eventLog: [],
  failures: [],
  triageSummary: null,
  setAllTools: (tools) => set({ allTools: tools }),

  handleExecutionEvent: (event) => {
    const state = get()
    const type = event.type

    if (type === 'run_started') {
      set({
        totalTests: event._totals?.total_tests || 0,
        passedTests: 0,
        failedTests: 0,
        errorTests: 0,
        timeoutTests: 0,
        completedTests: 0,
        passRate: 0,
        totalCost: 0,
        toolsCalled: new Set(),
        activeTests: new Map(),
        eventLog: [],
        failures: [],
        triageSummary: null,
      })
      if (event.tools_called) {
        set({ allTools: event.tools_called as unknown as string[] })
      }
    } else if (type === 'test_started') {
      const tests = new Map(state.activeTests)
      tests.set(event.test_id!, {
        test_id: event.test_id!,
        test_number: event.test_number || 0,
        scenario: event.scenario || '',
        persona: event.persona || '',
        difficulty: event.difficulty || 'medium',
        status: 'running',
        turns: [],
        tool_calls: [],
      })
      set({ activeTests: tests })
    } else if (type === 'turn_completed') {
      const tests = new Map(state.activeTests)
      const test = tests.get(event.test_id!)
      if (test) {
        test.turns.push({
          turn: event.turn || 0,
          role: event.role || '',
          message: event.message || '',
          duration_ms: 0,
        })
        tests.set(event.test_id!, { ...test })
        set({ activeTests: tests })
      }
    } else if (type === 'tool_called') {
      const tc = new Set(state.toolsCalled)
      if (event.tool_name) tc.add(event.tool_name)
      const tests = new Map(state.activeTests)
      const test = tests.get(event.test_id!)
      if (test) {
        test.tool_calls.push({ tool_name: event.tool_name || '', status: event.status || 'success' })
        tests.set(event.test_id!, { ...test })
      }
      set({ toolsCalled: tc, activeTests: tests })
    } else if (type === 'test_completed') {
      if (event._totals) {
        set({
          passedTests: event._totals.passed,
          failedTests: event._totals.failed,
          errorTests: event._totals.errors,
          timeoutTests: event._totals.timeouts,
          completedTests: event._totals.completed,
          totalTests: event._totals.total_tests,
          passRate: event._totals.pass_rate,
          totalCost: event._totals.total_cost_usd,
        })
      }
      const tests = new Map(state.activeTests)
      const test = tests.get(event.test_id!)
      if (test) {
        test.status = event.status || 'completed'
        tests.set(event.test_id!, { ...test })
      }
      if (event.status !== 'passed') {
        set({ failures: [...state.failures, event as unknown as Record<string, unknown>] })
      }
      set({ activeTests: tests })
    } else if (type === 'validation_completed') {
      // Store triage summary from AI validation
      if (event.summary) {
        const s = event.summary as Record<string, number>
        set({
          triageSummary: {
            genuine_failures: s.genuine_failures ?? 0,
            persona_filtered: s.persona_incompetence_filtered ?? 0,
            chaos_filtered: s.chaos_induced_filtered ?? 0,
            false_successes: s.false_successes_caught ?? 0,
          },
        })
      }
    } else if (type === 'run_completed') {
      // Final state update from run_completed enriched data
      if (typeof event.pass_rate === 'number') {
        set({ passRate: event.pass_rate })
      }
    }

    // Add to event log
    const logEntry = makeLogEntry(event)
    if (logEntry) {
      const log = [...state.eventLog, logEntry].slice(-200)
      set({ eventLog: log })
    }
  },

  hydratePhaseCFromResult: (r) => set({
    totalTests: r.total_tests,
    passedTests: r.passed,
    failedTests: r.failed,
    errorTests: r.errors,
    timeoutTests: r.timeouts,
    completedTests: r.total_tests,
    passRate: r.pass_rate,
    totalCost: r.total_cost_usd,
  }),

  hydratePhaseCTraces: (traces) => {
    const tests = new Map<string, ActiveTest>()
    const tc = new Set<string>()
    for (const t of traces) {
      tests.set(t.test_id, {
        test_id: t.test_id,
        test_number: t.test_number,
        scenario: t.scenario,
        persona: t.persona,
        difficulty: t.difficulty,
        status: t.status,
        turns: t.turns,
        tool_calls: t.tool_calls,
      })
      for (const call of t.tool_calls) {
        tc.add(call.tool_name)
      }
    }
    set({ activeTests: tests, toolsCalled: tc })
  },

  hydrateSession: (sessionId, phaseStatus, phaseResults) => {
    const patch: Record<string, unknown> = { sessionId }

    const statusMap = { a: 'phaseA', b: 'phaseB', c: 'phaseC', d: 'phaseD', cert: 'certStatus' } as const
    for (const [key, field] of Object.entries(statusMap)) {
      const status = phaseStatus[key]
      if (status === 'completed' || status === 'error') {
        patch[field] = status
      }
    }

    const resultMap = { a: 'phaseAResult', b: 'phaseBResult', c: 'phaseCResult', d: 'phaseDResult', cert: 'certResult' } as const
    for (const [key, field] of Object.entries(resultMap)) {
      if (phaseResults[key]) {
        patch[field] = phaseResults[key]
      }
    }

    // Hydrate Phase C live metrics if available
    const cResult = phaseResults.c as PhaseCResult | undefined
    if (cResult) {
      patch.totalTests = cResult.total_tests
      patch.passedTests = cResult.passed
      patch.failedTests = cResult.failed
      patch.errorTests = cResult.errors
      patch.timeoutTests = cResult.timeouts
      patch.completedTests = cResult.total_tests
      patch.passRate = cResult.pass_rate
      patch.totalCost = cResult.total_cost_usd
    }

    set(patch)
  },

  resetPhase: (phase) => {
    const PIPELINE: Array<'a' | 'b' | 'c' | 'd' | 'cert'> = ['a', 'b', 'c', 'd', 'cert']
    const idx = PIPELINE.indexOf(phase)
    const toReset = PIPELINE.slice(idx)

    const patch: Record<string, unknown> = {}
    for (const p of toReset) {
      if (p === 'a') { patch.phaseA = 'idle'; patch.phaseAProgress = { ...defaultProgress }; patch.phaseAResult = null }
      if (p === 'b') { patch.phaseB = 'idle'; patch.phaseBProgress = { ...defaultProgress }; patch.phaseBResult = null }
      if (p === 'c') {
        patch.phaseC = 'idle'
        patch.phaseCProgress = { ...defaultProgress }
        patch.phaseCResult = null
        patch.totalTests = 0; patch.passedTests = 0; patch.failedTests = 0
        patch.errorTests = 0; patch.timeoutTests = 0; patch.completedTests = 0
        patch.passRate = 0; patch.totalCost = 0
        patch.toolsCalled = new Set(); patch.activeTests = new Map()
        patch.eventLog = []; patch.failures = []; patch.triageSummary = null
      }
      if (p === 'd') { patch.phaseD = 'idle'; patch.phaseDProgress = { ...defaultProgress }; patch.phaseDResult = null }
      if (p === 'cert') { patch.certStatus = 'idle'; patch.certProgress = { ...defaultProgress }; patch.certResult = null }
    }
    set(patch)
  },

  resetSession: () => set({
    sessionId: null,
    phaseA: 'idle',
    phaseB: 'idle',
    phaseC: 'idle',
    phaseD: 'idle',
    certStatus: 'idle',
    phaseAProgress: { ...defaultProgress },
    phaseBProgress: { ...defaultProgress },
    phaseCProgress: { ...defaultProgress },
    phaseDProgress: { ...defaultProgress },
    certProgress: { ...defaultProgress },
    phaseAResult: null,
    phaseBResult: null,
    phaseCResult: null,
    phaseDResult: null,
    certResult: null,
    totalTests: 0,
    passedTests: 0,
    failedTests: 0,
    errorTests: 0,
    timeoutTests: 0,
    completedTests: 0,
    passRate: 0,
    totalCost: 0,
    toolsCalled: new Set(),
    allTools: [],
    activeTests: new Map(),
    eventLog: [],
    failures: [],
    triageSummary: null,
  }),
}))

function makeLogEntry(event: WSEvent): EventLogEntry | null {
  const ts = Date.now() / 1000
  switch (event.type) {
    case 'run_started':
      return { ts, icon: 'rocket', text: `Run started`, color: 'blue' }
    case 'test_started':
      return { ts, icon: 'rocket', text: `${event.test_id} started: ${(event.scenario || '').slice(0, 40)}`, color: 'blue' }
    case 'turn_completed':
      return { ts, icon: 'chat', text: `${event.test_id} turn ${event.turn} (${event.role})`, color: 'dim' }
    case 'tool_called':
      return { ts, icon: 'tool', text: `${event.test_id}: ${event.tool_name} -> ${event.status}`, color: event.status === 'success' ? 'green' : 'red' }
    case 'test_completed':
      return { ts, icon: event.status === 'passed' ? 'pass' : 'fail', text: `${event.test_id} ${event.status}${event.failure_reason ? ` - ${event.failure_reason.slice(0, 40)}` : ''}`, color: event.status === 'passed' ? 'green' : 'red' }
    case 'run_completed':
      return { ts, icon: 'finish', text: 'Run completed', color: 'green' }
    default:
      return null
  }
}

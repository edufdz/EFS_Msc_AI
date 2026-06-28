// Custom hook for WebSocket connection per session

import { useEffect, useRef } from 'react'
import { WSConnection } from '../api/websocket'
import type { WSEvent } from '../api/types'
import { useStore } from '../store'

export function useWebSocket() {
  const sessionId = useStore((s) => s.sessionId)
  const setWsConnected = useStore((s) => s.setWsConnected)
  const setPhaseStatus = useStore((s) => s.setPhaseStatus)
  const setPhaseProgress = useStore((s) => s.setPhaseProgress)
  const setPhaseAResult = useStore((s) => s.setPhaseAResult)
  const setPhaseBResult = useStore((s) => s.setPhaseBResult)
  const setPhaseCResult = useStore((s) => s.setPhaseCResult)
  const setPhaseDResult = useStore((s) => s.setPhaseDResult)
  const setCertResult = useStore((s) => s.setCertResult)
  const handleExecutionEvent = useStore((s) => s.handleExecutionEvent)
  const connRef = useRef<WSConnection | null>(null)

  useEffect(() => {
    if (!sessionId) return

    const conn = new WSConnection(sessionId)
    connRef.current = conn

    const unsub = conn.subscribe((event: WSEvent) => {
      if (event.type === 'ws_connected') {
        setWsConnected(true)
        return
      }
      if (event.type === 'ws_disconnected') {
        setWsConnected(false)
        return
      }

      // Phase progress events
      if (event.type === 'phase_progress' && event.phase) {
        const phase = event.phase as 'a' | 'b' | 'c' | 'd' | 'cert'
        setPhaseProgress(phase, event.step || '', event.message || '', event.progress_pct || 0)
        return
      }

      // Phase complete events
      if (event.type === 'phase_complete' && event.phase) {
        const phase = event.phase as 'a' | 'b' | 'c' | 'd' | 'cert'
        setPhaseStatus(phase, 'completed')
        if (phase === 'a' && event.result) setPhaseAResult(event.result as never)
        if (phase === 'b' && event.result) setPhaseBResult(event.result as never)
        if (phase === 'c' && event.result) setPhaseCResult(event.result as never)
        if (phase === 'd' && event.result) setPhaseDResult(event.result as never)
        if (phase === 'cert' && event.result) setCertResult(event.result as never)
        return
      }

      // Phase error events
      if (event.type === 'phase_error' && event.phase) {
        setPhaseStatus(event.phase as 'a' | 'b' | 'c' | 'd' | 'cert', 'error')
        return
      }

      // Phase C execution events (from engine.event_queue)
      if (['run_started', 'test_started', 'turn_completed', 'tool_called', 'test_completed', 'run_completed', 'chaos_injected'].includes(event.type)) {
        handleExecutionEvent(event)
        return
      }
    })

    conn.connect()

    return () => {
      unsub()
      conn.disconnect()
      connRef.current = null
    }
  }, [sessionId, setWsConnected, setPhaseStatus, setPhaseProgress, setPhaseAResult, setPhaseBResult, setPhaseCResult, setPhaseDResult, setCertResult, handleExecutionEvent])
}

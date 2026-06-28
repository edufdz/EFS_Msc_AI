import { type ReactNode } from 'react'
import Sidebar from './Sidebar'
import { useWebSocket } from '../../hooks/useWebSocket'
import { useStore } from '../../store'

export default function AppShell({ children }: { children: ReactNode }) {
  useWebSocket()
  const wsConnected = useStore((s) => s.wsConnected)
  const sessionId = useStore((s) => s.sessionId)

  return (
    <div className="flex h-screen bg-bg">
      <Sidebar />
      <div className="flex flex-col flex-1 min-w-0">
        {/* Top bar */}
        <header className="flex items-center justify-between px-6 h-12 bg-bg-surface border-b border-border flex-shrink-0">
          <div className="flex items-center gap-4">
            <span className="font-semibold text-[15px] tracking-tight text-pearl">Plavio</span>
            {sessionId && (
              <span className="font-mono text-xs text-text-muted">{sessionId}</span>
            )}
          </div>
          <div className="flex items-center gap-2 text-xs text-text-muted">
            <div
              className={`w-1.5 h-1.5 rounded-full transition-colors ${wsConnected ? 'bg-pearl animate-pulse-accent' : 'bg-text-muted opacity-40'}`}
            />
            <span>{wsConnected ? 'Connected' : 'Disconnected'}</span>
          </div>
        </header>

        {/* Content area */}
        <main className="flex-1 overflow-y-auto p-6">
          {children}
        </main>
      </div>
    </div>
  )
}

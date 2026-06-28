// WebSocket connection manager with auto-reconnect

import type { WSEvent } from './types'

type EventHandler = (event: WSEvent) => void

export class WSConnection {
  private ws: WebSocket | null = null
  private sessionId: string
  private handlers: Set<EventHandler> = new Set()
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private reconnectDelay = 1000
  private maxReconnectDelay = 30000
  private _connected = false

  constructor(sessionId: string) {
    this.sessionId = sessionId
  }

  get connected() {
    return this._connected
  }

  connect() {
    if (this.ws?.readyState === WebSocket.OPEN) return

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const host = window.location.host
    const url = `${protocol}//${host}/ws/${this.sessionId}`

    this.ws = new WebSocket(url)

    this.ws.onopen = () => {
      this._connected = true
      this.reconnectDelay = 1000
      this.notify({ type: 'ws_connected' })
    }

    this.ws.onmessage = (e) => {
      try {
        const event: WSEvent = JSON.parse(e.data)
        if (event.type === 'ping') {
          this.ws?.send(JSON.stringify({ type: 'pong' }))
          return
        }
        this.notify(event)
      } catch {
        // ignore parse errors
      }
    }

    this.ws.onclose = () => {
      this._connected = false
      this.notify({ type: 'ws_disconnected' })
      this.scheduleReconnect()
    }

    this.ws.onerror = () => {
      this.ws?.close()
    }
  }

  disconnect() {
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer)
    this.ws?.close()
    this.ws = null
    this._connected = false
  }

  subscribe(handler: EventHandler) {
    this.handlers.add(handler)
    return () => this.handlers.delete(handler)
  }

  private notify(event: WSEvent) {
    for (const handler of this.handlers) {
      handler(event)
    }
  }

  private scheduleReconnect() {
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer)
    this.reconnectTimer = setTimeout(() => {
      this.connect()
      this.reconnectDelay = Math.min(this.reconnectDelay * 2, this.maxReconnectDelay)
    }, this.reconnectDelay)
  }
}

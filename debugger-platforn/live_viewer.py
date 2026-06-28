#!/usr/bin/env python3
"""
Live Conversation Viewer — web-based real-time test monitor.

Opens a browser UI at http://localhost:8080 that streams test conversations
as they happen via Server-Sent Events. Zero dependencies beyond Python stdlib.

Automatically detects the newest conversations.log in results/ and switches
to it when a new test run starts (even in a different output directory).

Usage:
    python live_viewer.py                                    # watch results/ for any log
    python live_viewer.py results/ai-test/conversations.log  # specific log file
    python live_viewer.py --port 9090                        # custom port
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path

# ──────────────────────────────────────────────────────────────────────
# Shared state: which log file we're currently watching
# ──────────────────────────────────────────────────────────────────────

class LogState:
    """Tracks which conversations.log we're tailing."""
    results_dir: Path = Path("results")
    log_file: str = ""        # current file path (may change)
    pinned: bool = False      # True = user gave explicit path, don't auto-switch

    @classmethod
    def current(cls) -> Path:
        return Path(cls.log_file)

    @classmethod
    def find_latest(cls) -> Path | None:
        if not cls.results_dir.exists():
            return None
        logs = list(cls.results_dir.glob("**/conversations.log"))
        if not logs:
            return None
        return max(logs, key=lambda p: p.stat().st_mtime)

    @classmethod
    def maybe_switch(cls) -> str | None:
        """Check if a newer log exists. Returns new path if switched, else None."""
        if cls.pinned:
            return None
        latest = cls.find_latest()
        if latest and str(latest) != cls.log_file:
            cls.log_file = str(latest)
            return cls.log_file
        return None


# ──────────────────────────────────────────────────────────────────────
# HTML / CSS / JS — embedded for single-file deployment
# ──────────────────────────────────────────────────────────────────────

HTML_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Live Conversation Viewer</title>
<style>
  :root {
    --bg: #0d1117; --surface: #161b22; --border: #30363d;
    --text: #e6edf3; --muted: #8b949e; --accent: #58a6ff;
    --user-bg: #1f6feb; --agent-bg: #238636; --tool-bg: #9e6a03;
    --font: 'SF Mono', 'Cascadia Code', 'Fira Code', 'Menlo', monospace;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: var(--font); background: var(--bg); color: var(--text); height: 100vh; display: flex; flex-direction: column; }

  /* header */
  header { background: var(--surface); border-bottom: 1px solid var(--border); padding: 12px 20px; display: flex; align-items: center; gap: 16px; flex-shrink: 0; }
  header h1 { font-size: 14px; font-weight: 600; }
  #status { font-size: 12px; color: var(--muted); }
  #status.connected { color: #3fb950; }
  #status.connected::before { content: ''; display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: #3fb950; margin-right: 6px; }
  #status.disconnected { color: #f85149; }
  #status.disconnected::before { content: ''; display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: #f85149; margin-right: 6px; }
  #watching { font-size: 11px; color: var(--muted); margin-left: auto; }

  /* layout */
  .container { display: flex; flex: 1; overflow: hidden; }

  /* sidebar */
  .sidebar { width: 280px; min-width: 280px; background: var(--surface); border-right: 1px solid var(--border); overflow-y: auto; flex-shrink: 0; }
  .sidebar-header { padding: 12px 16px; font-size: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.5px; border-bottom: 1px solid var(--border); }
  .test-item { padding: 10px 16px; cursor: pointer; border-bottom: 1px solid var(--border); transition: background 0.15s; display: flex; align-items: flex-start; gap: 10px; }
  .test-item:hover { background: rgba(88,166,255,0.08); }
  .test-item.active { background: rgba(88,166,255,0.15); border-left: 3px solid var(--accent); padding-left: 13px; }
  .test-dot { width: 10px; height: 10px; border-radius: 50%; margin-top: 4px; flex-shrink: 0; }
  .test-dot.active { background: #3fb950; animation: pulse 1.5s infinite; }
  .test-dot.done { background: var(--muted); }
  @keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.4; } }
  .test-info { flex: 1; min-width: 0; }
  .test-title { font-size: 13px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .test-meta { font-size: 11px; color: var(--muted); margin-top: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

  /* main conversation area */
  .main { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
  .conv-header { padding: 14px 20px; background: var(--surface); border-bottom: 1px solid var(--border); flex-shrink: 0; }
  .conv-header h2 { font-size: 14px; font-weight: 600; }
  .conv-header .meta { font-size: 12px; color: var(--muted); margin-top: 4px; }
  .conv-header .badge { display: inline-block; font-size: 11px; padding: 2px 8px; border-radius: 10px; margin-left: 8px; }
  .badge.ai { background: rgba(56,139,54,0.25); color: #3fb950; }
  .badge.template { background: rgba(158,106,3,0.25); color: #e3b341; }

  .messages { flex: 1; overflow-y: auto; padding: 20px; display: flex; flex-direction: column; gap: 12px; }
  .empty-state { display: flex; align-items: center; justify-content: center; height: 100%; color: var(--muted); font-size: 14px; text-align: center; line-height: 1.8; }

  /* chat bubbles */
  .bubble { max-width: 75%; padding: 10px 14px; border-radius: 12px; font-size: 13px; line-height: 1.5; word-wrap: break-word; white-space: pre-wrap; }
  .bubble.user { align-self: flex-end; background: var(--user-bg); border-bottom-right-radius: 4px; }
  .bubble.agent { align-self: flex-start; background: var(--agent-bg); border-bottom-left-radius: 4px; }
  .bubble .role-label { font-size: 11px; font-weight: 700; margin-bottom: 4px; opacity: 0.8; }
  .bubble .turn-num { font-size: 10px; opacity: 0.5; margin-top: 4px; }

  /* tool calls */
  .tool-tags { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 6px; }
  .tool-tag { display: inline-flex; align-items: center; gap: 4px; background: rgba(158,106,3,0.3); color: #e3b341; font-size: 11px; padding: 2px 8px; border-radius: 6px; }
  .tool-tag::before { content: '\1F527'; font-size: 10px; }
  .tool-detail { font-size: 10px; color: var(--muted); margin-top: 4px; max-height: 80px; overflow-y: auto; white-space: pre-wrap; background: rgba(0,0,0,0.3); padding: 4px 8px; border-radius: 4px; display: none; cursor: pointer; }
  .tool-tag.expandable { cursor: pointer; }
  .tool-tag.expandable:hover { background: rgba(158,106,3,0.5); }

  /* scrollbar */
  ::-webkit-scrollbar { width: 8px; }
  ::-webkit-scrollbar-track { background: transparent; }
  ::-webkit-scrollbar-thumb { background: var(--border); border-radius: 4px; }
  ::-webkit-scrollbar-thumb:hover { background: var(--muted); }
</style>
</head>
<body>

<header>
  <h1>Live Conversation Viewer</h1>
  <span id="status" class="disconnected">Connecting...</span>
  <span id="watching"></span>
</header>

<div class="container">
  <div class="sidebar">
    <div class="sidebar-header">Tests</div>
    <div id="test-list"></div>
  </div>
  <div class="main">
    <div class="conv-header" id="conv-header" style="display:none;">
      <h2 id="conv-title"></h2>
      <div class="meta" id="conv-meta"></div>
    </div>
    <div class="messages" id="messages">
      <div class="empty-state">Waiting for test run...<br>Run execute_tests.py in another terminal</div>
    </div>
  </div>
</div>

<script>
const state = {
  tests: {},          // test_id -> { meta, turns: [] }
  testOrder: [],      // ordered test_ids
  selectedId: null,
  lastActiveId: null,
  currentFile: null,
};

function resetState() {
  state.tests = {};
  state.testOrder = [];
  state.selectedId = null;
  state.lastActiveId = null;
  render();
}

function addEntry(entry) {
  const type = entry.type || (entry.scenario && !entry.role ? 'conversation_start' : 'turn');
  const testId = entry.test_id || 'unknown';

  if (!state.tests[testId]) {
    state.tests[testId] = { meta: {}, turns: [] };
    state.testOrder.push(testId);
  }

  const t = state.tests[testId];

  if (type === 'conversation_start') {
    t.meta = {
      testNumber: entry.test_number,
      scenario: entry.scenario || 'Unknown',
      persona: entry.persona || 'Unknown',
      usesAi: entry.uses_ai_personas || false,
      language: entry.language || 'es',
    };
  } else {
    if (!t.meta.scenario) {
      t.meta.testNumber = entry.test_number;
      t.meta.scenario = entry.scenario || 'Unknown';
      t.meta.persona = entry.persona || 'Unknown';
    }
    t.turns.push(entry);
    t.meta._lastUpdate = Date.now();
  }

  state.lastActiveId = testId;
  if (!state.selectedId) {
    state.selectedId = testId;
  }
}

function renderSidebar() {
  const list = document.getElementById('test-list');
  list.innerHTML = '';

  for (const id of state.testOrder) {
    const t = state.tests[id];
    const m = t.meta;
    const isActive = m._lastUpdate && (Date.now() - m._lastUpdate) < 15000;

    const item = document.createElement('div');
    item.className = 'test-item' + (state.selectedId === id ? ' active' : '');
    item.onclick = () => { state.selectedId = id; render(); };

    const dot = document.createElement('div');
    dot.className = 'test-dot ' + (isActive ? 'active' : 'done');

    const info = document.createElement('div');
    info.className = 'test-info';

    const title = document.createElement('div');
    title.className = 'test-title';
    title.textContent = '#' + (m.testNumber || '?') + ' ' + (m.scenario || id);

    const meta = document.createElement('div');
    meta.className = 'test-meta';
    meta.textContent = (m.persona || '') + ' \u00b7 ' + t.turns.length + ' msgs';

    info.appendChild(title);
    info.appendChild(meta);
    item.appendChild(dot);
    item.appendChild(info);
    list.appendChild(item);
  }
}

function escapeHtml(s) {
  const div = document.createElement('div');
  div.textContent = s;
  return div.innerHTML;
}

function renderConversation() {
  const header = document.getElementById('conv-header');
  const msgs = document.getElementById('messages');

  if (!state.selectedId || !state.tests[state.selectedId]) {
    header.style.display = 'none';
    msgs.innerHTML = '<div class="empty-state">Waiting for test run...<br>Run execute_tests.py in another terminal</div>';
    return;
  }

  const t = state.tests[state.selectedId];
  const m = t.meta;

  header.style.display = '';
  document.getElementById('conv-title').textContent = '#' + (m.testNumber || '?') + ' \u2014 ' + (m.scenario || 'Unknown');

  let metaHtml = escapeHtml(m.persona || '');
  if (m.usesAi) {
    metaHtml += '<span class="badge ai">AI Personas</span>';
  } else if (m.persona) {
    metaHtml += '<span class="badge template">Template</span>';
  }
  document.getElementById('conv-meta').innerHTML = metaHtml;

  const sorted = [...t.turns].sort((a, b) => {
    const ta = a.turn || 0, tb = b.turn || 0;
    if (ta !== tb) return ta - tb;
    const ro = { user: 0, agent: 1, system: 2 };
    return (ro[a.role] || 9) - (ro[b.role] || 9);
  });

  const seen = new Set();
  const unique = [];
  for (const s of sorted) {
    const key = s.turn + ':' + s.role;
    if (!seen.has(key)) { seen.add(key); unique.push(s); }
  }

  const wasAtBottom = msgs.scrollTop + msgs.clientHeight >= msgs.scrollHeight - 40;

  msgs.innerHTML = '';
  for (const entry of unique) {
    const bubble = document.createElement('div');
    bubble.className = 'bubble ' + (entry.role || 'agent');

    const label = document.createElement('div');
    label.className = 'role-label';
    label.textContent = entry.role === 'user' ? '\uD83D\uDC64 User' : '\uD83E\uDD16 Agent';
    bubble.appendChild(label);

    const text = document.createElement('div');
    text.textContent = entry.message || '';
    bubble.appendChild(text);

    const tools = (entry.tool_calls || []).filter(tc => tc.tool_name !== 'debug_conversation_created');
    if (tools.length > 0) {
      const tags = document.createElement('div');
      tags.className = 'tool-tags';
      for (const tc of tools) {
        const tag = document.createElement('span');
        tag.className = 'tool-tag';
        if (tc.arguments || tc.result) tag.className += ' expandable';
        tag.textContent = tc.tool_name || 'unknown';

        if (tc.arguments || tc.result) {
          const detail = document.createElement('div');
          detail.className = 'tool-detail';
          let detailText = '';
          if (tc.arguments) detailText += 'Args: ' + JSON.stringify(tc.arguments, null, 2);
          if (tc.result) detailText += '\nResult: ' + JSON.stringify(tc.result, null, 2);
          detail.textContent = detailText.trim();
          tag.onclick = () => { detail.style.display = detail.style.display === 'block' ? 'none' : 'block'; };
          tags.appendChild(tag);
          tags.appendChild(detail);
        } else {
          tags.appendChild(tag);
        }
      }
      bubble.appendChild(tags);
    }

    const turnNum = document.createElement('div');
    turnNum.className = 'turn-num';
    turnNum.textContent = 'Turn ' + (entry.turn || '?');
    if (entry.duration_ms) turnNum.textContent += ' \u00b7 ' + Math.round(entry.duration_ms) + 'ms';
    bubble.appendChild(turnNum);

    msgs.appendChild(bubble);
  }

  if (wasAtBottom) msgs.scrollTop = msgs.scrollHeight;
}

function render() { renderSidebar(); renderConversation(); }

// ── Connect SSE — the server handles file switching ──
function connectSSE() {
  const es = new EventSource('/events');
  const statusEl = document.getElementById('status');
  const watchEl = document.getElementById('watching');

  es.onopen = () => {
    statusEl.className = 'connected';
    statusEl.textContent = state.testOrder.length > 0
      ? 'Live \u2014 ' + state.testOrder.length + ' test(s)'
      : 'Connected \u2014 waiting for tests...';
  };
  es.onerror = () => { statusEl.className = 'disconnected'; statusEl.textContent = 'Reconnecting...'; };

  es.addEventListener('reset', (ev) => {
    resetState();
    try {
      const data = JSON.parse(ev.data);
      if (data.file) {
        state.currentFile = data.file;
        watchEl.textContent = data.file;
      }
    } catch {}
    statusEl.className = 'connected';
    statusEl.textContent = 'New run detected \u2014 waiting for tests...';
  });

  es.addEventListener('watching', (ev) => {
    try {
      const data = JSON.parse(ev.data);
      if (data.file) {
        state.currentFile = data.file;
        watchEl.textContent = data.file;
      }
    } catch {}
  });

  es.onmessage = (ev) => {
    try {
      const entry = JSON.parse(ev.data);
      const wasEmpty = state.testOrder.length === 0;
      addEntry(entry);
      if (state.lastActiveId && (wasEmpty || !state.selectedId)) {
        state.selectedId = state.lastActiveId;
      }
      render();
      statusEl.textContent = 'Live \u2014 ' + state.testOrder.length + ' test(s)';
    } catch {}
  };
}

// Load history then start SSE
fetch('/history')
  .then(r => r.json())
  .then(data => {
    if (data.file) {
      state.currentFile = data.file;
      document.getElementById('watching').textContent = data.file;
    }
    for (const e of (data.entries || [])) addEntry(e);
    render();
    connectSSE();
  })
  .catch(() => connectSSE());

setInterval(() => renderSidebar(), 5000);
</script>
</body>
</html>"""


# ──────────────────────────────────────────────────────────────────────
# HTTP handler
# ──────────────────────────────────────────────────────────────────────

class ViewerHandler(BaseHTTPRequestHandler):
    """Serves HTML, history JSON, and SSE event stream."""

    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        if self.path == "/":
            self._serve_html()
        elif self.path == "/history":
            self._serve_history()
        elif self.path == "/events":
            self._serve_sse()
        else:
            self.send_error(404)

    def _serve_html(self):
        body = HTML_PAGE.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_history(self):
        log_file = LogState.log_file
        entries = _read_all_entries(log_file)
        payload = {"file": log_file, "entries": entries}
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_sse(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        current_file = LogState.log_file
        log_path = Path(current_file)
        pos = log_path.stat().st_size if log_path.exists() else 0

        # Tell client which file we're watching
        self._sse_send("watching", json.dumps({"file": current_file}))

        try:
            while True:
                # Check if a newer log file appeared (new test run in different dir)
                switched = LogState.maybe_switch()
                if switched:
                    current_file = switched
                    log_path = Path(current_file)
                    pos = 0
                    print(f"  Switched to: {current_file}")
                    self._sse_send("reset", json.dumps({"file": current_file}))
                    # Stream all existing content from new file
                    # (falls through to the size > pos check below)

                if not log_path.exists():
                    time.sleep(0.5)
                    continue

                size = log_path.stat().st_size
                if size < pos:
                    # Same file was truncated — new run reusing same -o dir
                    self._sse_send("reset", json.dumps({"file": current_file}))
                    pos = 0

                if size > pos:
                    with open(log_path, "r", encoding="utf-8") as f:
                        f.seek(pos)
                        for line in f:
                            line = line.strip()
                            if line:
                                try:
                                    json.loads(line)
                                    self.wfile.write(f"data: {line}\n\n".encode("utf-8"))
                                    self.wfile.flush()
                                except json.JSONDecodeError:
                                    pass
                        pos = f.tell()

                time.sleep(0.3)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    def _sse_send(self, event: str, data: str):
        self.wfile.write(f"event: {event}\ndata: {data}\n\n".encode("utf-8"))
        self.wfile.flush()


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────

def _read_all_entries(log_file: str) -> list:
    path = Path(log_file)
    if not path.exists():
        return []
    entries = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return entries


# ──────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Live conversation viewer (web UI)")
    parser.add_argument("log_file", nargs="?", help="Path to conversations.log (omit to auto-detect)")
    parser.add_argument("--port", type=int, default=8080, help="HTTP port (default: 8080)")
    args = parser.parse_args()

    if args.log_file:
        LogState.log_file = str(Path(args.log_file))
        LogState.pinned = True
    else:
        latest = LogState.find_latest()
        if latest:
            LogState.log_file = str(latest)
            print(f"Auto-detected: {latest}")
        else:
            # No log yet — create a placeholder path; SSE will wait for it
            LogState.log_file = str(Path("results/conversations.log"))
            print("No conversations.log found yet — will auto-detect when a test run starts.")

    server = ThreadingHTTPServer(("0.0.0.0", args.port), ViewerHandler)
    if LogState.pinned:
        print(f"Watching:  {LogState.log_file} (pinned)")
    else:
        print(f"Watching:  results/**/ (auto-detect newest)")
    print(f"Open:      http://localhost:{args.port}")
    print(f"Press Ctrl+C to stop.\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        server.server_close()


if __name__ == "__main__":
    main()

# Phase C — Live Monitor Dashboard

Real-time web UI for monitoring Phase C test execution. Shows every simulation as it runs: turns, tool calls, pass/fail state, and metrics, all updating in real time via WebSocket.

## Installation

```bash
pip install websockets
# or
pip install -e ".[ui]"
```

## Usage

### Integrated mode (recommended)

Add `--ui` to your `execute_tests.py` command:

```bash
python execute_tests.py generated/test_suite.json agent_map.json --mock --ui
```

This starts the dashboard server alongside test execution. Open `http://localhost:8080` in your browser.

Options:
- `--ui` — Enable the web dashboard
- `--ui-port 8080` — Change the port (default: 8080)
- `--no-monitor` — Disable the Rich terminal dashboard (auto-disabled when `--ui` is used)

### Standalone mode

Run the server against an existing `conversations.log` file:

```bash
python -m src.monitor_ui.server --log results/conversations.log --port 8080
```

Options:
- `--log` (required) — Path to conversations.log
- `--port` — Server port (default: 8080)
- `--report` — Path to test_run_report.json (enables `/api/report` endpoint)

Then open `http://localhost:8080` in your browser.

## Dashboard Layout

### Left Panel — Run Overview
- Progress bar showing completed / total tests
- Four stat cards: Passed, Failed, Errors, Timeouts
- Large pass rate percentage
- Tool coverage list (checkmark for covered tools)
- Cost, average latency, and speed metrics

### Center Panel — Active Simulations
- Up to 8 cards showing live test conversations
- Each card shows: test ID, scenario, persona, live chat bubbles, tool call pills, and status
- Cards fade and slide out 4 seconds after completion
- Tool pills are color-coded: blue=success, red=error, orange=chaos, purple=in-flight

### Right Panel — Event Feed + Failure Inbox
- **Top**: Scrolling event feed with icons and timestamps. Toggle pause to stop auto-scroll.
- **Bottom**: Failure inbox that builds up as failures arrive. Click a row to expand the full conversation trace with tool call inputs/outputs.

## WebSocket Protocol

The server sends JSON events over WebSocket at `ws://localhost:8080/ws`:

| Event | Description |
|-------|-------------|
| `run_started` | Run begins, includes total_tests and tool list |
| `test_started` | Individual test begins |
| `turn_completed` | A conversation turn (user or agent) completed |
| `tool_called` | Agent called a tool, with status and I/O |
| `chaos_injected` | Chaos event (timeout, malformed response, etc.) |
| `test_completed` | Test finished, with status and metrics |
| `run_completed` | All tests done, final totals |
| `state_snapshot` | Full state sent on client connect/reconnect |

## REST Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /` | Serves the dashboard HTML |
| `GET /api/state` | Returns current state snapshot (JSON) |
| `GET /api/report` | Returns latest test_run_report.json content |

## Architecture

```
execute_tests.py --ui
  └─ MonitorUIServer.start_integrated(engine.event_queue)
       ├─ WebSocket server (port 8080)
       │    ├─ Serves dashboard.html
       │    ├─ Broadcasts events to connected browsers
       │    └─ Sends state snapshot on client connect
       ├─ Event forwarder (engine_queue → internal processing)
       └─ State manager (maintains in-memory snapshot for reconnects)
```

In standalone mode, the event forwarder is replaced by a log file tailer that polls `conversations.log` every 200ms.

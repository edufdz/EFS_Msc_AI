#!/usr/bin/env bash
#
# Start the whole platform with one command.
#
#   ./dev.sh              everything (default)
#   ./dev.sh --no-agent   skip the live agent (no ANTHROPIC_API_KEY needed)
#   ./dev.sh --check      run preflight checks and exit
#
# Brings up five processes and streams their logs into this terminal with a
# per-service prefix. Ctrl+C stops all of them.
#
#   Debugger UI          http://localhost:5173
#   Debugger API         http://localhost:8000
#   Anonymisation UI     http://localhost:5174
#   Anonymisation API    http://localhost:8100
#   Live agent           http://localhost:3098
#
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

DEBUG_API_PORT=8000
DEBUG_UI_PORT=5173
ANON_API_PORT=8100
ANON_UI_PORT=5174
AGENT_PORT=3098

RUN_AGENT=1
CHECK_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --no-agent) RUN_AGENT=0 ;;
    --check)    CHECK_ONLY=1 ;;
    -h|--help)  sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $arg (try --help)"; exit 2 ;;
  esac
done

if [[ -t 1 ]]; then
  B=$'\033[1m'; DIM=$'\033[2m'; R=$'\033[0m'
  RED=$'\033[31m'; GRN=$'\033[32m'; YEL=$'\033[33m'
  BLU=$'\033[34m'; MAG=$'\033[35m'; CYN=$'\033[36m'
else
  B=""; DIM=""; R=""; RED=""; GRN=""; YEL=""; BLU=""; MAG=""; CYN=""
fi

say()  { printf '%s\n' "$*"; }
ok()   { printf '  %s✓%s %s\n' "$GRN" "$R" "$*"; }
bad()  { printf '  %s✗%s %s\n' "$RED" "$R" "$*"; }
warn() { printf '  %s!%s %s\n' "$YEL" "$R" "$*"; }

# ---------------------------------------------------------------- preflight

FATAL=0

need_cmd() {
  if command -v "$1" >/dev/null 2>&1; then ok "$1"; else bad "$1 not found — $2"; FATAL=1; fi
}

need_path() {
  if [[ -e "$2" ]]; then ok "$1"; else bad "$1 missing ($2) — $3"; FATAL=1; fi
}

port_pid() { lsof -ti "tcp:$1" -sTCP:LISTEN 2>/dev/null | head -1; }

check_port() {
  local port=$1 label=$2 pid
  pid="$(port_pid "$port")"
  if [[ -z "$pid" ]]; then
    ok "port $port free ($label)"
  else
    bad "port $port in use by PID $pid ($label) — stop it, or: kill $pid"
    FATAL=1
  fi
}

say ""
say "${B}Preflight${R}"

need_cmd node "install Node 18+"
need_cmd npm  "ships with Node"
[[ $RUN_AGENT -eq 1 ]] && need_cmd bun "install from https://bun.sh (or run with --no-agent)"

need_path "debugger venv"     "debugger-platforn/venv/bin/python"       "python3 -m venv debugger-platforn/venv && debugger-platforn/venv/bin/pip install -r debugger-platforn/requirements.txt"
need_path "anonymiser venv"   "anonymization/backend/venv/bin/python"   "python3 -m venv anonymization/backend/venv && anonymization/backend/venv/bin/pip install -r anonymization/backend/requirements.txt"

# Node deps are installable, so a miss is a warning we can fix, not fatal.
for d in "debugger-platforn/web/frontend" "anonymization/frontend"; do
  if [[ -d "$d/node_modules" ]]; then ok "deps: $d"; else warn "deps missing in $d — will run npm install"; fi
done

if [[ $RUN_AGENT -eq 1 ]]; then
  if [[ -f "tech_repair-live-agent/.env" ]] && grep -q '^ANTHROPIC_API_KEY=.\+' tech_repair-live-agent/.env; then
    ok "agent ANTHROPIC_API_KEY"
  else
    bad "tech_repair-live-agent/.env has no ANTHROPIC_API_KEY — the agent cannot start (or use --no-agent)"
    FATAL=1
  fi
  [[ -d "tech_repair-live-agent/node_modules" ]] || warn "deps missing in tech_repair-live-agent — will run bun install"
fi

check_port $DEBUG_API_PORT "debugger API"
check_port $DEBUG_UI_PORT  "debugger UI"
check_port $ANON_API_PORT  "anonymisation API"
check_port $ANON_UI_PORT   "anonymisation UI"
[[ $RUN_AGENT -eq 1 ]] && check_port $AGENT_PORT "live agent"

if [[ $FATAL -eq 1 ]]; then
  say ""
  say "${RED}Preflight failed.${R} Fix the items marked ✗ above and re-run."
  exit 1
fi

if [[ $CHECK_ONLY -eq 1 ]]; then
  say ""
  say "${GRN}All preflight checks passed.${R}"
  exit 0
fi

# Install any missing node deps before we start streaming logs.
install_deps() {
  local dir=$1 tool=$2
  [[ -d "$dir/node_modules" ]] && return 0
  say "  installing dependencies in $dir ..."
  ( cd "$dir" && $tool install >/dev/null 2>&1 ) \
    || { bad "dependency install failed in $dir"; exit 1; }
}
install_deps "debugger-platforn/web/frontend" npm
install_deps "anonymization/frontend" npm
[[ $RUN_AGENT -eq 1 ]] && install_deps "tech_repair-live-agent" bun

# ------------------------------------------------------------------ process

PIDS=()
LOGDIR="$(mktemp -d)"
SERVICE_PORTS=($DEBUG_API_PORT $DEBUG_UI_PORT $ANON_API_PORT $ANON_UI_PORT $AGENT_PORT)

# Job control: each background job becomes its own process-group leader, so a
# single kill reaches the children vite and uvicorn fork. (setsid is Linux-only.)
set -m

CLEANED=0
cleanup() {
  local code=$?
  # Disarm EXIT too: the `exit` at the end of this function would otherwise
  # re-enter cleanup via the EXIT trap and kill everything a second time.
  trap '' INT TERM EXIT
  [[ $CLEANED -eq 1 ]] && return
  CLEANED=1
  # Leave monitor mode before killing, or bash prints a "[9]- Terminated"
  # line for every job as it dies.
  set +m
  say ""
  say "${B}Shutting down...${R}"
  for pid in "${PIDS[@]:-}"; do
    [[ -n "$pid" ]] || continue
    # Kill the whole process group: vite and uvicorn --reload both fork.
    kill -TERM "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
  done
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    local alive=0
    for pid in "${PIDS[@]:-}"; do
      [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null && alive=1
    done
    [[ $alive -eq 0 ]] && break
    sleep 0.3
  done
  for pid in "${PIDS[@]:-}"; do
    [[ -n "$pid" ]] && { kill -KILL "-$pid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null; } || true
  done
  # Backstop: a forked child that outlived its parent still holds the port.
  for port in "${SERVICE_PORTS[@]}"; do
    for pid in $(lsof -ti "tcp:$port" -sTCP:LISTEN 2>/dev/null); do
      kill -KILL "$pid" 2>/dev/null || true
    done
  done
  rm -rf "$LOGDIR" 2>/dev/null || true
  say "${DIM}All services stopped.${R}"
  exit $code
}
trap cleanup INT TERM EXIT

# start <label> <colour> <workdir> <command...>
start() {
  local label=$1 colour=$2 dir=$3; shift 3
  local pad; pad="$(printf '%-9s' "$label")"
  ( cd "$dir" && exec "$@" >"$LOGDIR/$label.log" 2>&1 ) &
  local pid=$!
  PIDS+=("$pid")
  ( tail -n +1 -f "$LOGDIR/$label.log" 2>/dev/null \
      | sed -u "s/^/${colour}${pad}${R} ${DIM}|${R} /" ) &
  PIDS+=("$!")
}

wait_for() {
  local url=$1 label=$2 tries=${3:-60}
  for ((i = 1; i <= tries; i++)); do
    curl -sf -m 2 "$url" >/dev/null 2>&1 && { ok "$label ready"; return 0; }
    sleep 1
  done
  warn "$label did not answer in ${tries}s — check the log lines above"
  return 1
}

say ""
say "${B}Starting services${R}"

start "api" "$BLU" "debugger-platforn" \
  ./venv/bin/python -m uvicorn web.api.app:app --port $DEBUG_API_PORT --host 127.0.0.1

start "anon-api" "$MAG" "anonymization/backend" \
  ./venv/bin/python -m uvicorn app:app --port $ANON_API_PORT --host 127.0.0.1

if [[ $RUN_AGENT -eq 1 ]]; then
  start "agent" "$YEL" "tech_repair-live-agent" bun server.ts
fi

start "ui" "$CYN" "debugger-platforn/web/frontend" npm run dev -- --port $DEBUG_UI_PORT --strictPort
start "anon-ui" "$GRN" "anonymization/frontend" npm run dev -- --port $ANON_UI_PORT --strictPort

say ""
say "${B}Waiting for readiness${R}"
wait_for "http://localhost:$DEBUG_API_PORT/api/health"      "debugger API"
wait_for "http://localhost:$ANON_API_PORT/api/health"       "anonymisation API"   90
[[ $RUN_AGENT -eq 1 ]] && wait_for "http://localhost:$AGENT_PORT/db" "live agent"
wait_for "http://localhost:$DEBUG_UI_PORT"                  "debugger UI"
wait_for "http://localhost:$ANON_UI_PORT"                   "anonymisation UI"

say ""
say "${B}────────────────────────────────────────────────────────${R}"
say "  ${B}${GRN}Platform is up${R}"
say ""
say "  ${B}Debugger${R}          ${CYN}http://localhost:$DEBUG_UI_PORT${R}"
say "  Anonymisation     ${GRN}http://localhost:$ANON_UI_PORT${R}   ${DIM}(also linked in the sidebar)${R}"
if [[ $RUN_AGENT -eq 1 ]]; then
say "  Live agent        ${YEL}http://localhost:$AGENT_PORT${R}   ${DIM}(Phase C target)${R}"
else
say "  Live agent        ${DIM}not started (--no-agent)${R}"
fi
say ""
say "  ${DIM}Ctrl+C stops everything.${R}"
say "${B}────────────────────────────────────────────────────────${R}"
say ""

if command -v open >/dev/null 2>&1 && [[ "${DEV_OPEN:-1}" == "1" ]]; then
  open "http://localhost:$DEBUG_UI_PORT" 2>/dev/null || true
fi

# Wait on the service processes. If one dies, say which and keep the rest up so
# the failure is visible rather than taking the whole stack down silently.
while true; do
  sleep 2
  for pid in "${PIDS[@]}"; do
    if [[ -n "$pid" ]] && ! kill -0 "$pid" 2>/dev/null; then
      wait "$pid" 2>/dev/null
      code=$?
      [[ $code -ne 0 ]] && warn "a service exited (status $code) — see its log lines above"
      PIDS=("${PIDS[@]/$pid}")
    fi
  done
done

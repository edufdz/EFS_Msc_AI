# TechRepair Live Agent — Simulation Target for Phase C

The **verbatim TechRepair/Pulpoo WhatsApp agent** from `pulpoo-final`, running
against a **fake in-memory database** instead of TechRepair's systems. No
connection of any kind to production — Supabase, GSPN, Meta, mem0, LiveKit
and push notifications are all replaced at the injection boundary. The only
real outbound calls are the agent's own LLM calls (Anthropic lanes +
OpenAI verifier), which is precisely what makes it a *living* agent worth
testing.

Built as the **X3 "real-agent execute mode"** target from
`phase-c-enhancements/CONTEXT.md`: Phase C simulates customer conversations
against this agent through the same `POST /chat` contract the
`APIAgentConnector` speaks, and every conversation exercises the real graph,
the real prompts, the real guardrails.

## Why this exists (dissertation context)

The platform's headline numbers are *static-mode*: Phase C never actually
executed conversations against a faithful agent (only the echo stand-in,
fidelity 0.36). This project provides the faithful agent: **same code, same
prompts, same LangGraph, same guardrails** — only the data layer is fake.
Conversations produced here can be extracted, anonymized-format-matched and
compared against the production taxonomy exactly like real exports.

## Architecture

```
tech_repair-live-agent/
├── server.ts               # POST /chat harness (Phase C contract) + /db + /reset
├── index.ts                # interactive CLI chat
├── bootstrap.ts            # plays pulpoo's "App" role: injects fake Supabase client
├── context-builder.ts      # builds AssembledContext (gateway's job in production)
├── fake-db/
│   ├── fake-supabase.ts    # in-memory Supabase-compatible query builder + RPCs
│   └── seed.ts             # THE fake customer + all tables (see below)
└── server-mirror/          # mirrors pulpoo-final's server/ layout; @/* maps here
    ├── services/agents/whatsapp/   ← the ENTIRE agent, copied VERBATIM
    │   ├── prompts/               ← router/status/support/carry-in prompts, untouched
    │   ├── graph/                 ← LangGraph builder, state, all 12 nodes
    │   ├── events/                ← payment/address/order-received detectors
    │   ├── tools/order-lookup.ts  ← incl. disclosure + warranty gates
    │   └── post-processors/       ← style guide
    ├── shared/ + services/ + db/ + data/  ← 46 support modules copied verbatim
    └── (5 fake shims, clearly headed "FAKE SHIM"):
        shared/semantic-memory.ts            (mem0 → no-op)
        services/surveys/survey-orchestrator.ts (no active survey)
        services/agents/shared/dynamic-config.ts (livekit TTS trimmed)
        services/agents/inbound/greeter-agent.ts (types only)
        services/orchestrator/context-assembler.ts (types only)
```

**How the faking works:** pulpoo-final's core never creates DB connections —
the app injects a Supabase client at bootstrap (`setSupabaseClient`). Our
bootstrap injects `fake-db/fake-supabase.ts` instead: a chainable query
builder over JSON tables that supports the exact query surface the agent
uses (filters, `.or()`, JSON paths, upserts, the three Postgres RPCs).
The agent cannot tell the difference. Every mutation is recorded in a
`mutationLog` for post-conversation inspection.

Six tiny **type-only** patches (marked `// [sim]`) fix pre-existing upstream
tsc errors; zero behavior changes. Prompts are byte-identical to production.

## The fake customer

**Valeria Mendoza García** — phone `5215587654321`, customer `CUST-0084213`,
6 prior interactions, preferred name "Vale", frustration index 2.4.

| Order | Device | Pipeline | Warranty | Status | Exercises |
|---|---|---|---|---|---|
| `4151234567` | Galaxy S24 Ultra 256GB | D2D (home delivery) | Out of warranty (O) | ST030 awaiting parts, quote **$3,480 MXN** | status, pricing, delivery, payment flows, warranty-strip gate |
| `4149876543` | Galaxy Watch6 44mm | Carry-in (store) | In warranty (I) | ST040 → `ready_for_pickup` | **the disclosure gate**: policy forbids status disclosure (customer is at the store door) |

Also seeded: full production `service_status_policy` rows (verbatim from
migrations 0057+0059), an active call-frequency escalation rule, interaction
history, CRM memory with history, feature flags.

## Run it

```bash
cd tech_repair-live-agent
bun install
# .env needs ANTHROPIC_API_KEY (+ OPENAI_API_KEY for the escalation verifier)

bun run api    # HTTP API on :3098 (PORT=... to override)
bun run cli    # interactive terminal chat
bun run typecheck
```

| Endpoint | Description |
|---|---|
| `POST /chat` | `{ "message", "session_id"?, "message_type"? }` → `{ "response", "tool_calls", "intent", "confidence", "escalation", "should_close", "metadata" }` |
| `GET /db` | fake-DB inspection: mutation log, escalated_tasks, notifications, memory |
| `POST /reset` | fresh DB + sessions (between Phase C runs) |
| `GET /health` | liveness |

**Media simulation:** production receives payment receipts as images/PDFs
whose transcription is prefixed `[COMPROBANTE]`. Sending a message containing
`[COMPROBANTE] ...` (or prefixed `[imagen]`/`[documento]`, or with
`"message_type": "image"`) reproduces that path and fires the
payment-receipt detector.

## Wire it to Phase C

`debugger-platforn/agent_endpoints.json` already points the TechRepair agent map
at `http://localhost:3098`. With the API running:

```bash
cd debugger-platforn
# generate (or reuse) a suite from the TechRepair map, then execute WITHOUT --mock:
python execute_tests.py <test_suite.json> tech_repair_whatsapp_map.json --count 10 -o results
```

Phase C's `ConversationSimulator` plays the customer (LLM personas), this
agent plays itself, and the resulting conversations/traces flow into
Phase D diagnosis. After a run, `GET /db` shows what the conversation did to
the "backend" (escalations filed, memory written, policy strips logged in
`agent_thoughts`) — signals the Phase C oracles (X1/X2) can consume.

## Verified behaviors (smoke-tested)

- Greeting personalization from CRM memory ("¡Hola Valeria!"), Lane 1 Haiku.
- `order_lookup` against the fake DB with IQC enrichment (real TechRepair code
  table → Spanish descriptions).
- **Disclosure gate**: carry-in @ ST040 → status/dates/diagnosis stripped
  from the tool result before the LLM sees them; audit row in `agent_thoughts`.
- **Warranty-contradiction gate**: `warranty_type` stripped on Out-of-Warranty
  orders.
- Pricing: SO disambiguation question, then the $3,480 MXN GSPN quote.
- `explicit_human_request` → escalation with handoff message + store phone.
- Payment-receipt detector (`[COMPROBANTE]` image) → acuse reply +
  `escalated_tasks` row `💳 Comprobante de pago enviado (orden 4151234567)`.
- Address-change detector → acuse + `escalated_tasks` row comparing the
  registered address.
- Goodbye → memory extraction persisted (3 facts + CRM + interaction snapshot).

Known non-fatal: the interaction grader's OpenAI structured-output call warns
about zod `.optional()` fields (upstream behavior, fails safe by design).

## What is fake vs real

| Layer | Status |
|---|---|
| Prompts, graph, nodes, routing, guardrails, style guide | **verbatim production code** |
| Lane selection (Haiku/Sonnet one-way upgrade) | verbatim, real LLM calls |
| Supabase (orders, memory, logs, escalations) | fake in-memory DB, seeded |
| GSPN | never called at runtime (data arrives via the DB, as in production) |
| Meta WhatsApp API / push / surveys / mem0 / LiveKit | shimmed out |
| Checkpointer | LangGraph MemorySaver (per-session thread state) |

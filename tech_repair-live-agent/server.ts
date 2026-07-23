/**
 * TechRepair Live Agent — HTTP API for Phase C (Agent Debugger)
 * ==========================================================
 * Exposes POST /chat compatible with the debugger's APIAgentConnector
 * ({ message, session_id } → { response, tool_calls }), running the
 * VERBATIM pulpoo-final WhatsApp agent against the fake database.
 *
 * Endpoints:
 *   POST /chat    { message, session_id? }  → { response, tool_calls, intent, ... }
 *   GET  /health  liveness
 *   GET  /db      fake-DB inspection (mutation log + escalation tables)
 *   POST /reset   fresh DB + sessions (between Phase C runs)
 */

import { bootstrapFakeEnvironment, resetFakeEnvironment } from "./bootstrap";

// Bootstrap MUST run before the agent module loads config.
let fakeClient = bootstrapFakeEnvironment();

import { getWhatsAppAgent, _resetAgent } from "@/services/agents/whatsapp/agent";
import { buildAssembledContext, resolveMessageType, type SessionState } from "./context-builder";

const PORT = Number(process.env.PORT ?? 3098);

const sessions = new Map<string, SessionState>();

function getSession(sessionId: string | null): SessionState {
    const id = sessionId ?? "default";
    let s = sessions.get(id);
    if (!s) {
        s = { sessionId: id, history: [], laneId: undefined, turnCount: 0 };
        sessions.set(id, s);
    }
    return s;
}

async function handleChat(body: { message?: string; session_id?: string; message_type?: string }) {
    const message = typeof body?.message === "string" ? body.message.trim() : "";
    if (!message) {
        return Response.json({ error: "Missing or empty 'message' in body" }, { status: 400 });
    }
    const session = getSession(typeof body?.session_id === "string" ? body.session_id : null);
    session.turnCount += 1;

    const messageType = resolveMessageType(message, typeof body?.message_type === "string" ? body.message_type : undefined);
    const context = await buildAssembledContext(fakeClient, session, message, messageType);
    const agent = getWhatsAppAgent();
    const result = await agent.execute(context, session.sessionId);

    // Persist the turn into the session history (gateway's job in production)
    const nowIso = new Date().toISOString();
    session.history.push({ role: "customer", content: message, timestamp: nowIso });
    session.history.push({ role: "assistant", content: result.response_text, timestamp: nowIso });

    // Lane stickiness (one-way upgrade) — production keeps this in metadata
    const lane = result.metadata?.laneId;
    if (lane === 2) session.laneId = 2;

    // Phase C oracle compatibility: the debugger's ConversationSimulator
    // decides success from tool_call.result.status ("ok"/"error"). Mirror
    // each tool_output into that shape, and surface an escalation as a
    // synthetic escalate_to_human tool call so outcome tier 1 can see it.
    const toolCalls = result.tool_calls.map((tc) => {
        const out = tc.tool_output as Record<string, unknown> | null | undefined;
        const failed = !!out && typeof out === "object" && ((out as any).found === false || (out as any).error);
        return { ...tc, result: { status: failed ? "error" : "ok", data: tc.tool_output } };
    }) as Array<Record<string, unknown>>;
    if (result.escalation?.escalated) {
        toolCalls.push({
            tool_name: "escalate_to_human",
            tool_input: { reason: result.escalation.reason ?? "" },
            tool_output: result.escalation,
            result: { status: "ok", data: result.escalation },
        });
    }

    return Response.json({
        response: result.response_text,
        tool_calls: toolCalls,
        intent: result.intent,
        confidence: result.confidence,
        escalation: result.escalation ?? null,
        should_close: result.should_close,
        metadata: result.metadata,
    });
}

const server = Bun.serve({
    port: PORT,
    idleTimeout: 120,
    async fetch(req) {
        const url = new URL(req.url);

        if (url.pathname === "/health" && req.method === "GET") {
            return Response.json({ status: "ok", service: "tech_repair-live-agent" });
        }

        if (url.pathname === "/chat" && req.method === "POST") {
            try {
                const body = await req.json();
                return await handleChat(body as { message?: string; session_id?: string });
            } catch (err) {
                const detail = err instanceof Error ? err.message : String(err);
                return Response.json({ error: "Agent error", detail }, { status: 500 });
            }
        }

        if (url.pathname === "/db" && req.method === "GET") {
            const db = fakeClient.__db;
            return Response.json({
                mutation_log: db.mutationLog,
                escalated_tasks: db.tables.get("escalated_tasks") ?? [],
                dashboard_notifications: db.tables.get("dashboard_notifications") ?? [],
                interaction_history: db.tables.get("interaction_history") ?? [],
                customer_memory: db.tables.get("customer_memory") ?? [],
                rocket_metrics: db.tables.get("rocket_metrics") ?? [],
            });
        }

        if (url.pathname === "/reset" && req.method === "POST") {
            sessions.clear();
            fakeClient = resetFakeEnvironment();
            _resetAgent();
            return Response.json({ status: "reset" });
        }

        return new Response("Not Found", { status: 404 });
    },
});

console.log(`TechRepair Live Agent (simulation) listening on http://localhost:${server.port}`);
console.log(`  POST /chat   — { message, session_id? } → { response, tool_calls }`);
console.log(`  GET  /db     — inspect fake DB (escalations, mutations)`);
console.log(`  POST /reset  — fresh fake DB + sessions`);
console.log("");
console.log(`Phase C: set agent_map.json api_endpoint to http://localhost:${server.port}`);

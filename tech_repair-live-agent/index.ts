/**
 * TechRepair Live Agent — interactive CLI
 * ====================================
 * Chat with the simulated TechRepair WhatsApp agent from the terminal.
 * Same verbatim agent + fake DB as server.ts, without HTTP.
 */

import { bootstrapFakeEnvironment } from "./bootstrap";

const fakeClient = bootstrapFakeEnvironment();

import { getWhatsAppAgent } from "@/services/agents/whatsapp/agent";
import { buildAssembledContext, type SessionState } from "./context-builder";
import { FAKE_CUSTOMER, SO_D2D, SO_CARRY_IN } from "./fake-db/seed";

const session: SessionState = {
    sessionId: `cli-${Date.now()}`,
    history: [],
    laneId: undefined,
    turnCount: 0,
};

console.log("=".repeat(70));
console.log("TechRepair Live Agent — simulation CLI");
console.log(`Fake customer: ${FAKE_CUSTOMER.name} (${FAKE_CUSTOMER.phone})`);
console.log(`  SO ${SO_D2D}   — Galaxy S24 Ultra, D2D, fuera de garantía, ST030`);
console.log(`  SO ${SO_CARRY_IN}   — Galaxy Watch6, carry-in, en garantía, ST040`);
console.log("Type a WhatsApp message (Ctrl+C to exit).");
console.log("=".repeat(70));

const agent = getWhatsAppAgent();

process.stdout.write("\nYou: ");
for await (const line of console) {
    const message = line.trim();
    if (!message) {
        process.stdout.write("You: ");
        continue;
    }

    session.turnCount += 1;
    const context = await buildAssembledContext(fakeClient, session, message);
    const result = await agent.execute(context, session.sessionId);

    const nowIso = new Date().toISOString();
    session.history.push({ role: "customer", content: message, timestamp: nowIso });
    session.history.push({ role: "assistant", content: result.response_text, timestamp: nowIso });
    if (result.metadata?.laneId === 2) session.laneId = 2;

    for (const tc of result.tool_calls) {
        console.log(`  [tool] ${tc.tool_name}(${JSON.stringify(tc.tool_input)})`);
    }
    console.log(`  [intent] ${result.intent} (${result.confidence})${result.escalation ? "  [ESCALATED]" : ""}`);
    console.log(`\nAgent: ${result.response_text}\n`);
    process.stdout.write("You: ");
}

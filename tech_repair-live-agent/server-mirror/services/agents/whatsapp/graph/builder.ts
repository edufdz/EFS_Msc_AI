/**
 * WhatsApp Agent Graph Builder
 * ============================
 * Builds the LangGraph StateGraph with PostgreSQL checkpointer.
 * Graph: START → router → [status|support|escalation|human_taken_over] → response → END
 */

import { END, START, StateGraph, MemorySaver } from "@langchain/langgraph";
import { PostgresSaver } from "@langchain/langgraph-checkpoint-postgres";
import type { BaseCheckpointSaver } from "@langchain/langgraph";
import { getWhatsAppConfig } from "@/services/agents/whatsapp/config";
import { IntentType } from "@/services/agents/whatsapp/models";
import { WhatsAppState, type WhatsAppStateType } from "./state";
import { routerNode } from "./nodes/router";
import { eventDetectorNode } from "./nodes/event-detector";
import { statusNode } from "./nodes/status";
import { supportNode } from "./nodes/support";
import { contactInfoNode } from "./nodes/contact-info";
import { deliveryLogisticsDispatchNode } from "./nodes/delivery-logistics-dispatch";
import { warrantyAnswerNode } from "./nodes/warranty-answer";
import { pricingAnswerNode } from "./nodes/pricing-answer";
import { memoryExtractionNode } from "./nodes/memory-extraction";
import {
    responseNode,
    escalationNode,
    humanTakenOverNode,
} from "./nodes/response";

// =============================================================================
// Types
// =============================================================================

/**
 * Minimal interface for the compiled LangGraph.
 * Using explicit type to avoid non-portable inferred types from @langchain/core internals.
 */
export interface CompiledWhatsAppGraph {
    invoke(
        input: Partial<WhatsAppStateType> & { messages?: unknown[] },
        config?: { configurable?: { thread_id?: string } },
    ): Promise<WhatsAppStateType>;
}

// =============================================================================
// Routing Logic
// =============================================================================

/**
 * Route from router node to the appropriate handler based on intent.
 *
 * Version-aware: v2 taxonomy introduces new intents that currently share
 * the "support" LLM path. Dedicated nodes for them (contact_info,
 * delivery_logistics, warranty_answer) land in D5/D6/D7 and will be routed
 * here once their addNode calls are added to buildGraph.
 */
function routeByIntent(
    state: WhatsAppStateType,
):
    | "status"
    | "support"
    | "contact_info"
    | "delivery_logistics"
    | "warranty_answer"
    | "pricing_answer"
    | "escalation"
    | "human_taken_over" {
    // Check for human takeover first
    if (state.humanTakenOver) return "human_taken_over";

    // Router fast-path (paste-history) or downstream logic may have set
    // escalatePriority='high' without touching state.escalated. Route to
    // escalation whenever we see any explicit escalation signal.
    const isExplicitEscalation =
        state.escalated ||
        state.escalatePriority === "high" ||
        state.intent === IntentType.ESCALATION ||
        state.intent === IntentType.EXPLICIT_HUMAN_REQUEST ||
        state.intent === IntentType.COMPLAINT_OR_FRUSTRATION;

    if (isExplicitEscalation) return "escalation";

    // Route by intent — v1 and v2 share the buckets below
    switch (state.intent) {
        case IntentType.ORDER_STATUS:
            return "status";

        // PRICING always flows through pricing_answer so replies come from
        // the GSPN quote (via classifyPricingState / planPricingResponse).
        // Never let PRICING reach status.ts — that path reads the
        // repair_pricing estimate table which is inbound-voice-only. // ci-guard:allow repair_pricing
        case IntentType.PRICING:
            return "pricing_answer";

        case IntentType.WARRANTY_QUESTION:
            return "warranty_answer";

        case IntentType.DELIVERY_LOGISTICS:
            return "delivery_logistics";

        case IntentType.CONTACT_INFO_REQUEST:
            return "contact_info";

        case IntentType.GREETING:
        case IntentType.GOODBYE:
        case IntentType.CONFIRMATION:
        case IntentType.REJECTION:
        case IntentType.GENERAL_SUPPORT:         // v1 only
        case IntentType.NEW_SYMPTOM_REPORT:      // stays in support; LLM acknowledges + flags async
        case IntentType.UNKNOWN:
        default:
            // Defensive resume path: an unfamiliar intent (including stale
            // checkpoints from a pre-v2 graph) falls through to support
            // instead of throwing. Do not narrow this default in refactors —
            // it protects in-flight LangGraph conversations at deploy time.
            return "support";
    }
}

/**
 * After the support node, route to memory extraction on goodbye,
 * or directly to response for everything else.
 */
function routeAfterSupport(
    state: WhatsAppStateType,
): "memory_extraction" | "response" {
    return state.intent === IntentType.GOODBYE ? "memory_extraction" : "response";
}

// =============================================================================
// Graph Construction
// =============================================================================

let _checkpointer: BaseCheckpointSaver | null = null;
let _compiledGraph: CompiledWhatsAppGraph | null = null;
let _graphPromise: Promise<CompiledWhatsAppGraph> | null = null;

/**
 * Internal function to build and compile the graph.
 * Used for type inference only.
 */
async function buildGraph(checkpointer: BaseCheckpointSaver) {
    const graph = new StateGraph(WhatsAppState)
        // Add nodes
        .addNode("event_detector", eventDetectorNode)
        .addNode("router", routerNode)
        .addNode("status", statusNode)
        .addNode("support", supportNode)
        .addNode("contact_info", contactInfoNode)
        // [sim] type-only: wrap nodes whose optional test-injection `opts` param
        // clashes with langgraph 1.3 NodeAction typing. Behavior unchanged.
        .addNode("delivery_logistics", (state: WhatsAppStateType) => deliveryLogisticsDispatchNode(state))
        .addNode("warranty_answer", (state: WhatsAppStateType) => warrantyAnswerNode(state))
        .addNode("pricing_answer", (state: WhatsAppStateType) => pricingAnswerNode(state))
        .addNode("memory_extraction", memoryExtractionNode)
        .addNode("escalation", escalationNode)
        .addNode("human_taken_over", humanTakenOverNode)
        .addNode("response", responseNode)

        // Add edges
        .addEdge(START, "event_detector")
        .addEdge("event_detector", "router")
        .addConditionalEdges("router", routeByIntent, [
            "status",
            "support",
            "contact_info",
            "delivery_logistics",
            "warranty_answer",
            "pricing_answer",
            "escalation",
            "human_taken_over",
        ])
        .addEdge("status", "response")
        .addConditionalEdges("support", routeAfterSupport, [
            "memory_extraction",
            "response",
        ])
        .addEdge("contact_info", "response")
        .addEdge("delivery_logistics", "response")
        .addEdge("warranty_answer", "response")
        .addEdge("pricing_answer", "response")
        .addEdge("memory_extraction", "response")
        .addEdge("escalation", "response")
        .addEdge("human_taken_over", "response")
        .addEdge("response", END);

    return graph.compile({ checkpointer });
}

/**
 * Get or create the checkpointer.
 * Uses PostgreSQL (Supabase) when POSTGRES_CONNECTION_STRING is set,
 * falls back to in-memory for development.
 */
async function getCheckpointer(): Promise<BaseCheckpointSaver> {
    if (_checkpointer) return _checkpointer;

    try {
        const config = getWhatsAppConfig();
        if (!config.postgresConnectionString) {
            throw new Error("No POSTGRES_CONNECTION_STRING configured");
        }
        const pgSaver = PostgresSaver.fromConnString(
            config.postgresConnectionString,
        );
        await pgSaver.setup();
        _checkpointer = pgSaver;
        console.info("[WhatsApp Graph] Using PostgreSQL checkpointer (Supabase)");
    } catch (err) {
        console.warn(
            "[WhatsApp Graph] PostgreSQL checkpointer unavailable, using in-memory fallback:",
            err instanceof Error ? err.message : err,
        );
        _checkpointer = new MemorySaver();
    }
    return _checkpointer;
}

/**
 * Build and compile the WhatsApp agent graph.
 *
 * Graph structure:
 *   START → router → [status|support|escalation|human_taken_over] → response → END
 *                         support (goodbye) → memory_extraction → response
 */
export async function getGraph(): Promise<CompiledWhatsAppGraph> {
    if (_compiledGraph) return _compiledGraph;
    if (!_graphPromise) {
        _graphPromise = (async () => {
            const checkpointer = await getCheckpointer();
            _compiledGraph = await buildGraph(checkpointer) as CompiledWhatsAppGraph;
            return _compiledGraph;
        })();
    }
    return _graphPromise;
}

/**
 * Reset the cached graph and checkpointer (for testing).
 */
export function _resetGraph(): void {
    _compiledGraph = null;
    _graphPromise = null;
    _checkpointer = null;
}

/**
 * WhatsApp Agent Graph State
 * ==========================
 * Uses LangGraph Annotation for state definition.
 */

import { Annotation, messagesStateReducer } from "@langchain/langgraph";
import type { BaseMessage } from "@langchain/core/messages";
import type {
    AssembledContext,
    CustomerInfo,
    ServiceOrderInfo,
    SessionInfo,
    ToolCall,
} from "@/services/agents/whatsapp/models";
import { IntentType } from "@/services/agents/whatsapp/models";
import type { LaneConfig } from "@/services/agents/whatsapp/lane-selector";
import type { DetectedEvent } from "@/services/agents/whatsapp/events/types";

// =============================================================================
// LLM Usage Tracking
// =============================================================================

export interface LLMUsage {
    cacheReadTokens: number;
    cacheWriteTokens: number;
    totalInputTokens: number;
    totalOutputTokens: number;
}

// =============================================================================
// State Definition
// =============================================================================

export const WhatsAppState = Annotation.Root({
    // LangChain message history for LLM context
    messages: Annotation<BaseMessage[]>({
        reducer: messagesStateReducer,
        default: () => [],
    }),

    // Gateway-assembled context
    context: Annotation<AssembledContext | null>({
        reducer: (_prev, next) => next,
        default: () => null,
    }),

    // Classification result
    intent: Annotation<string>({
        reducer: (_prev, next) => next,
        default: () => IntentType.UNKNOWN,
    }),
    intentConfidence: Annotation<number>({
        reducer: (_prev, next) => next,
        default: () => 0,
    }),
    taxonomyVersion: Annotation<"v1" | "v2">({
        reducer: (_prev, next) => next,
        default: () => "v2",
    }),
    escalatePriority: Annotation<"high" | "normal" | null>({
        reducer: (_prev, next) => next,
        default: () => null,
    }),
    escalationReasonOverride: Annotation<string | null>({
        reducer: (_prev, next) => next,
        default: () => null,
    }),

    // Agent response
    responseText: Annotation<string>({
        reducer: (_prev, next) => next,
        default: () => "",
    }),

    // Tools used during this turn
    toolCalls: Annotation<ToolCall[]>({
        reducer: (_prev, next) => next,
        default: () => [],
    }),

    // Escalation tracking
    escalated: Annotation<boolean>({
        reducer: (_prev, next) => next,
        default: () => false,
    }),
    escalationReason: Annotation<string>({
        reducer: (_prev, next) => next,
        default: () => "",
    }),
    escalationAttempts: Annotation<number>({
        reducer: (_prev, next) => next,
        default: () => 0,
    }),

    // Human takeover flag
    humanTakenOver: Annotation<boolean>({
        reducer: (_prev, next) => next,
        default: () => false,
    }),

    // Error tracking
    error: Annotation<string | null>({
        reducer: (_prev, next) => next,
        default: () => null,
    }),

    // ROCKET lane config
    laneConfig: Annotation<LaneConfig | null>({
        reducer: (_prev, next) => next,
        default: () => null,
    }),

    // ROCKET LLM usage (accumulated across nodes)
    llmUsage: Annotation<LLMUsage>({
        reducer: (prev, next) => ({
            cacheReadTokens: (prev?.cacheReadTokens ?? 0) + (next?.cacheReadTokens ?? 0),
            cacheWriteTokens: (prev?.cacheWriteTokens ?? 0) + (next?.cacheWriteTokens ?? 0),
            totalInputTokens: (prev?.totalInputTokens ?? 0) + (next?.totalInputTokens ?? 0),
            totalOutputTokens: (prev?.totalOutputTokens ?? 0) + (next?.totalOutputTokens ?? 0),
        }),
        default: () => ({ cacheReadTokens: 0, cacheWriteTokens: 0, totalInputTokens: 0, totalOutputTokens: 0 }),
    }),

    // Business-critical events spotted this turn (payment receipt, address
    // mention, order received). REPLACE per turn — never accumulate across the
    // persisted checkpoint (that's the llmUsage bug we don't want to repeat).
    detectedEvents: Annotation<DetectedEvent[]>({
        reducer: (_prev, next) => next ?? [],
        default: () => [],
    }),
});

export type WhatsAppStateType = typeof WhatsAppState.State;

// =============================================================================
// State Helpers
// =============================================================================

/** Get customer info from assembled context. */
export function getCustomerInfo(
    state: WhatsAppStateType,
): CustomerInfo | null {
    return state.context?.customer ?? null;
}

/**
 * Get active orders from assembled context.
 *
 * Returns a deterministically sorted copy (svc_order_no DESC) so nodes that
 * pick `orders[0]` always resolve to the same SO across calls. TechRepair SO
 * numbers are monotonically increasing, so DESC approximates "newest first"
 * — the right default when a customer with multiple active SOs asks a
 * question without naming one.
 *
 * Load-bearing for warranty_answer and pricing_answer, both of which use
 * `orders[0]` as the single-SO case.
 */
export function getActiveOrders(
    state: WhatsAppStateType,
): ServiceOrderInfo[] {
    const orders = state.context?.active_orders ?? [];
    return [...orders].sort((a, b) =>
        b.svc_order_no.localeCompare(a.svc_order_no),
    );
}

/** Get session info from assembled context. */
export function getSessionInfo(
    state: WhatsAppStateType,
): SessionInfo | null {
    return state.context?.session ?? null;
}

/** Check if escalation threshold is exceeded. */
export function shouldEscalate(
    state: WhatsAppStateType,
    threshold = 3,
): boolean {
    return state.escalationAttempts >= threshold;
}

/** Build conversation history string for prompt injection. */
export function formatConversationHistory(
    state: WhatsAppStateType,
    maxMessages = 10,
): string {
    const history = state.context?.conversation_history ?? [];
    const recent = history.slice(-maxMessages);
    if (recent.length === 0) return "No previous messages.";

    return recent
        .map((m) => `[${m.role}]: ${m.content}`)
        .join("\n");
}

/**
 * Create initial state from an AssembledContext.
 */
export function createInitialState(
    context: AssembledContext,
    laneConfig?: LaneConfig | null,
): Partial<WhatsAppStateType> {
    return {
        context,
        messages: [],
        intent: IntentType.UNKNOWN,
        intentConfidence: 0,
        taxonomyVersion: "v2",
        escalatePriority: null,
        escalationReasonOverride: null,
        responseText: "",
        toolCalls: [],
        escalated: false,
        escalationReason: "",
        escalationAttempts: 0,
        humanTakenOver: false,
        error: null,
        laneConfig: laneConfig ?? null,
        llmUsage: { cacheReadTokens: 0, cacheWriteTokens: 0, totalInputTokens: 0, totalOutputTokens: 0 },
        detectedEvents: [],
    };
}

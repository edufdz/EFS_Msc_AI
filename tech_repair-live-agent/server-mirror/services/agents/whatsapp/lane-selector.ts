/**
 * Lane Selector
 * =============
 * Conversation-level lane assignment with one-way upgrade.
 *
 * Lane 1 (Haiku): default — fast, cheap, handles most conversations.
 * Lane 2 (Sonnet): upgraded — deeper reasoning for complex conversations.
 *
 * Once a conversation upgrades to Lane 2, it stays there. This prevents
 * quality oscillation mid-conversation and ensures complex cases get
 * consistent treatment.
 */

import type { AssembledContext } from "./models";
import { getWhatsAppConfig } from "./config";

// =============================================================================
// Types
// =============================================================================

export type LaneId = 1 | 2;

export interface LaneConfig {
    laneId: LaneId;
    model: string;
    maxResponseTokens: number;
    maxContextTurns: number;
}

// =============================================================================
// Lane 2 Upgrade Triggers
// =============================================================================

/** Keywords in the current message that signal immediate upgrade. */
const COMPLAINT_KEYWORDS = [
    "queja", "inaceptable", "demanda", "reportar",
    "abogado", "profeco", "reembolso", "mal servicio",
];

const LEGAL_PATTERNS = [
    /voy a demandar/i,
    /hablar con mi abogado/i,
    /poner queja/i,
];

/** Warranty dispute: "garantía" + dispute term. */
const WARRANTY_DISPUTE_TERMS = [
    "vencida", "no aplica", "me dijeron que sí", "me dijeron que si",
];

function hasMessageLevelTrigger(text: string): boolean {
    const lower = text.toLowerCase();

    for (const kw of COMPLAINT_KEYWORDS) {
        if (lower.includes(kw)) return true;
    }
    for (const pat of LEGAL_PATTERNS) {
        if (pat.test(lower)) return true;
    }
    if (lower.includes("garantía") || lower.includes("garantia")) {
        for (const term of WARRANTY_DISPUTE_TERMS) {
            if (lower.includes(term)) return true;
        }
    }
    return false;
}

function hasConversationLevelTrigger(context: AssembledContext): boolean {
    // Long conversations need deeper reasoning
    const messageCount = context.conversation_history?.length ?? 0;
    if (messageCount > 10) return true;

    // Previously escalated conversations are complex
    const escalation = (context.metadata?.escalation ?? {}) as Record<string, unknown>;
    if (escalation.escalated === true || escalation.is_human_handling === true) return true;

    return false;
}

// =============================================================================
// Selection Logic
// =============================================================================

/**
 * Select the processing lane for this conversation.
 *
 * Implements one-way upgrade: if the conversation was previously on Lane 2
 * (passed via `currentLane`), it stays on Lane 2. Otherwise, checks upgrade
 * triggers and returns Lane 1 or 2.
 *
 * @param context  - Assembled conversation context
 * @param currentLane - The lane previously assigned to this conversation (from metadata), or undefined for new conversations
 */
export function selectLane(context: AssembledContext, currentLane?: LaneId): LaneConfig {
    // One-way upgrade: never downgrade from Lane 2
    if (currentLane === 2) {
        return getLane2Config();
    }

    // Check message-level triggers (complaint keywords, legal threats)
    const currentMessage = context.current_message?.content ?? "";
    if (hasMessageLevelTrigger(currentMessage)) {
        return getLane2Config();
    }

    // Check conversation-level triggers (long history, prior escalation)
    if (hasConversationLevelTrigger(context)) {
        return getLane2Config();
    }

    // Default: Lane 1
    const config = getWhatsAppConfig();
    return {
        laneId: 1,
        model: config.lane1Model,
        maxResponseTokens: config.lane1MaxTokens,
        maxContextTurns: config.maxContextTurns,
    };
}

/**
 * Get Lane 2 config.
 */
export function getLane2Config(): LaneConfig {
    const config = getWhatsAppConfig();
    return {
        laneId: 2,
        model: config.lane2Model,
        maxResponseTokens: config.lane2MaxTokens,
        maxContextTurns: config.maxContextTurns,
    };
}

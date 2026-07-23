/**
 * Mid-Conversation Escalation Signal Detection
 * ==============================================
 * Shared between WhatsApp and Voice agents.
 *
 * Pattern-matches customer messages for high-confidence escalation signals
 * using curated Mexican Spanish phrases. No LLM — runs in <1ms.
 *
 * Signals are categorized by confidence and urgency:
 * - Escalation triggers (immediate): PROFECO, legal threats → set escalation_risk
 * - Frustration signals (logged): ALL CAPS, frustration phrases → track for trending
 * - Transfer requests (logged): explicit human/supervisor requests
 *
 * Feedback loop: After each conversation, post-extraction checks if
 * sentiment_score <= 2 but no mid-conv signal was detected. Those misses
 * are logged to memory_logs with action='missed_signal' for periodic
 * pattern list expansion.
 */

import { AgentMemory } from "@/shared/memory";
import { getSupabaseClient } from "@/shared/supabase";
import { logAgentThought } from "@/shared/supabase-logger";
import { isMemoryEnhancedPromptsEnabled } from "@/shared/app-config";

// =============================================================================
// Signal Patterns (~30 curated Mexican Spanish phrases)
// =============================================================================

/** Immediate escalation triggers — high confidence, high urgency */
const ESCALATION_PATTERNS: RegExp[] = [
    /\bprofeco\b/i,
    /\bdemanda\b/i,
    /\bqueja\s*formal\b/i,
    /\bdenuncia\b/i,
    /\bvoy\s*a\s*denunciar\b/i,
    /\bacci[oó]n\s*legal\b/i,
    /\babogado\b/i,
    /\bdemand(?:ar[eé]|o)\b/i,
    /\btribunal\b/i,
    /\bprensa\b/i,
    /\bredes\s*sociales.*exponer\b/i,
    /\bBBB\b/,
];

/** Frustration signals — logged for trending, not immediate escalation */
const FRUSTRATION_PATTERNS: RegExp[] = [
    /ya\s*me\s*cans[eé]/i,
    /cu[aá]ntas\s*veces/i,
    /esto\s*es\s*un\s*robo/i,
    /no\s*mam[ea]n/i,
    /llevan\s*semanas/i,
    /a\s*ver\s*si\s*ahora\s*s[ií]/i,
    /p[eé]simo\s*servicio/i,
    /nunca\s*m[aá]s/i,
    /estoy\s*hart[oa]/i,
    /es\s*incre[ií]ble/i,
    /no\s*puede\s*ser/i,
    /que\s*falta\s*de\s*respeto/i,
    /son\s*unos?\s*(?:in[uú]tiles|incompetentes)/i,
    /voy\s*a\s*(?:cancelar|devolver)/i,
    /me\s*(?:tienen|traen)\s*(?:de\s*un\s*lado|vuelta\s*y\s*vuelta)/i,
];

/** Transfer request signals — customer wants a human */
const TRANSFER_PATTERNS: RegExp[] = [
    /hablar\s*con\s*(?:alguien|una?\s*persona)/i,
    /(?:un|una?)\s*humano/i,
    /supervisor/i,
    /gerente/i,
    /encargado/i,
    /quiero\s*hablar\s*con/i,
    /p[aá]same\s*(?:a|con)/i,
    /no\s*quiero\s*(?:hablar\s*con\s*)?(?:un?\s*)?(?:robot|m[aá]quina|bot)/i,
];

// =============================================================================
// Signal Detection Result
// =============================================================================

export interface SignalDetectionResult {
    /** True if any immediate escalation trigger was detected */
    escalationTriggered: boolean;
    /** The matched escalation pattern (for logging) */
    escalationMatch?: string;
    /** True if frustration signals detected */
    frustrationDetected: boolean;
    /** True if transfer request detected */
    transferRequested: boolean;
    /** True if ALL CAPS message (>80% uppercase, >20 chars) */
    allCapsDetected: boolean;
}

// =============================================================================
// Detection Function
// =============================================================================

/**
 * Detect escalation signals in a customer message.
 * Pure function — no side effects, no DB access.
 */
export function detectEscalationSignals(message: string): SignalDetectionResult {
    const result: SignalDetectionResult = {
        escalationTriggered: false,
        frustrationDetected: false,
        transferRequested: false,
        allCapsDetected: false,
    };

    if (!message || message.length === 0) return result;

    // Check ALL CAPS (>80% uppercase, >20 chars to avoid short acronyms)
    if (message.length > 20) {
        const alphaChars = message.replace(/[^a-záéíóúñü]/gi, "");
        if (alphaChars.length > 10) {
            const upperCount = alphaChars.replace(/[^A-ZÁÉÍÓÚÑÜ]/g, "").length;
            if (upperCount / alphaChars.length > 0.8) {
                result.allCapsDetected = true;
                result.frustrationDetected = true;
            }
        }
    }

    // Check escalation patterns (immediate)
    for (const pattern of ESCALATION_PATTERNS) {
        if (pattern.test(message)) {
            result.escalationTriggered = true;
            result.escalationMatch = pattern.source;
            break;
        }
    }

    // Check frustration patterns
    if (!result.frustrationDetected) {
        for (const pattern of FRUSTRATION_PATTERNS) {
            if (pattern.test(message)) {
                result.frustrationDetected = true;
                break;
            }
        }
    }

    // Check transfer patterns
    for (const pattern of TRANSFER_PATTERNS) {
        if (pattern.test(message)) {
            result.transferRequested = true;
            break;
        }
    }

    return result;
}

// =============================================================================
// Side-Effect Handler (DB writes + logging)
// =============================================================================

/**
 * Process detected signals: update DB and log.
 * Fire-and-forget — never blocks the agent response.
 *
 * @param phone Customer phone number
 * @param signals Detection result from detectEscalationSignals
 * @param context Optional context for logging
 */
export async function processSignals(
    phone: string,
    signals: SignalDetectionResult,
    context?: {
        conversationId?: string;
        channel?: "voice" | "whatsapp";
    },
): Promise<void> {
    const enhanced = await isMemoryEnhancedPromptsEnabled();
    if (!enhanced) return;

    if (!signals.escalationTriggered && !signals.frustrationDetected && !signals.transferRequested) {
        return;
    }

    const supabase = getSupabaseClient();

    // Update escalation_risk immediately if triggered
    if (signals.escalationTriggered) {
        try {
            const memory = new AgentMemory(supabase);
            await memory.updateCustomerProfile(phone, { escalationRisk: true });
        } catch (err) {
            console.warn("[signals] Failed to update escalation_risk:", err);
        }
    }

    // Log the detection
    if (supabase) {
        const parts: string[] = [];
        if (signals.escalationTriggered) parts.push(`ESCALATION: matched "${signals.escalationMatch}"`);
        if (signals.frustrationDetected) parts.push("FRUSTRATION detected");
        if (signals.allCapsDetected) parts.push("ALL CAPS detected");
        if (signals.transferRequested) parts.push("TRANSFER requested");

        logAgentThought(supabase, {
            conversationId: context?.conversationId,
            phone,
            stepName: "mid_conversation_signal",
            thoughtContent: `Signal(s) detected: ${parts.join(", ")}`,
        }).catch(() => {/* non-fatal */});
    }
}

// =============================================================================
// Feedback Loop: Log Missed Signals
// =============================================================================

/**
 * Called after post-conversation extraction. If sentiment was very negative
 * (score <= 2) but no mid-conversation signal was detected during the
 * conversation, log the miss for pattern list expansion.
 */
export async function logMissedSignal(
    phone: string,
    sentimentScore: number,
    midConvSignalDetected: boolean,
    lastCustomerMessage?: string,
    conversationId?: string,
): Promise<void> {
    if (sentimentScore > 2 || midConvSignalDetected) return;

    const supabase = getSupabaseClient();
    if (!supabase) return;

    try {
        await supabase.from("memory_logs").insert({
            phone,
            conversation_id: conversationId ?? null,
            query: "missed_signal_feedback",
            found_memories: lastCustomerMessage ? [lastCustomerMessage] : [],
            memory_count: 0,
            status: "empty",
        });
    } catch {
        // non-fatal
    }
}

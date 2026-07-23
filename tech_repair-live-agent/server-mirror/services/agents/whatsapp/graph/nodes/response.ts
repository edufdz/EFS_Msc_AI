/**
 * Response Node
 * =============
 * Final response formatting, escalation handling, and character limits.
 */

import { getWhatsAppDynamicConfig } from "@/services/agents/whatsapp/config";
import {
    type WhatsAppStateType,
    getCustomerInfo,
    getActiveOrders,
    getSessionInfo,
    shouldEscalate,
} from "@/services/agents/whatsapp/graph/state";
import {
    isEscalationReason,
    renderHandoff,
    type EscalationReason,
    type HandoffContext,
    type Register,
} from "@/shared/escalation-reasons";
import { getContactNumbers } from "@/shared/contact-numbers";
import { IntentType } from "@/services/agents/whatsapp/models";

// =============================================================================
// Response Formatting
// =============================================================================

/**
 * Truncate response to WhatsApp character limit.
 *
 * Tries to break at a sentence boundary if possible.
 */
export function truncateResponse(text: string, maxLength: number): string {
    if (text.length <= maxLength) return text;

    // Try to break at last sentence boundary
    const truncated = text.slice(0, maxLength);
    const lastPeriod = truncated.lastIndexOf(".");
    const lastNewline = truncated.lastIndexOf("\n");
    const breakAt = Math.max(lastPeriod, lastNewline);

    if (breakAt > maxLength * 0.5) {
        return truncated.slice(0, breakAt + 1);
    }

    return text.slice(0, maxLength - 3) + "...";
}

/**
 * Build escalation response text — the message the customer sees when
 * the bot escalates without a typed `escalationReasonOverride`.
 *
 * Wording principles (W1 Task 8):
 *   - Mexican Spanish tuteo (never voseo, never usted).
 *   - No "transfer" / "we'll contact you" framing — WhatsApp is async
 *     in the same chat thread; the human just takes over silently via
 *     `humanTakenOverNode`. Promising a transfer or a callback creates
 *     false expectations.
 *   - No timing promises ("enseguida", "en un momento") — escalation
 *     latency depends on staff availability, not the bot.
 *   - When an active order is in scope, ground the message with the
 *     order number to confirm the bot heard the customer correctly and
 *     to disambiguate when the customer has multiple orders.
 *
 * The `reason` parameter is preserved for callers that still pass it
 * (fully unused in the user-facing text — leaking internal slugs to
 * customers was a long-standing bug).
 */
function buildEscalationResponse(
    _reason: string,
    svcOrderNo?: string | null,
): string {
    if (svcOrderNo) {
        return `Permíteme revisar bien tu orden ${svcOrderNo} con el equipo. Te respondemos por aquí en cuanto tengamos los detalles.`;
    }
    return "Permíteme revisar bien esto con el equipo. Te respondemos por aquí en cuanto tengamos los detalles.";
}

/**
 * Map a frustration intent to its typed EscalationReason so it renders the
 * named-handler handoff copy (and, for the human-frustration cluster, the
 * direct store line) instead of the generic bounce. The router classifies
 * these intents but does not set an `escalationReasonOverride`, so without this
 * the most common frustration cases would never reach renderHandoff.
 */
const INTENT_TO_REASON: Partial<Record<string, EscalationReason>> = {
    [IntentType.COMPLAINT_OR_FRUSTRATION]: "complaint_escalation",
    [IntentType.EXPLICIT_HUMAN_REQUEST]: "explicit_human_request",
};

/**
 * Resolve the typed EscalationReason for this escalation, if any: an explicit
 * override slug wins, else the frustration-intent mapping. Returns undefined
 * when neither applies (caller falls back to the legacy generic bounce).
 */
function resolveTypedReason(
    state: WhatsAppStateType,
): EscalationReason | undefined {
    const override = state.escalationReasonOverride;
    if (isEscalationReason(override)) return override;
    return INTENT_TO_REASON[state.intent];
}

/**
 * Derive the handoff context from graph state. Register defaults to
 * `default_formal` until D12's register_lock lands; the customer name is
 * the first token of the stored name (if any) and svcOrderNo is the first
 * active order's number. The store line is attached so the human-frustration
 * handoffs can offer a direct call (renderHandoff ignores it otherwise).
 */
async function buildHandoffContext(
    state: WhatsAppStateType,
): Promise<HandoffContext> {
    const customer = getCustomerInfo(state);
    const orders = getActiveOrders(state);

    const firstName = customer?.name
        ? customer.name.trim().split(/\s+/)[0]
        : undefined;

    const register =
        ((state.context?.metadata?.register as Register | undefined) ??
            "default_formal");

    // The store line lets the human-frustration handoffs offer a direct call
    // to a person (see STORE_PHONE_REASONS). renderHandoff ignores it for the
    // other reasons, so it's safe to always include.
    const { storePhone } = await getContactNumbers();

    return {
        customerFirstName: firstName,
        svcOrderNo: orders[0]?.svc_order_no,
        register,
        storePhone,
    };
}

/**
 * Build wait time notice if the session window is closing.
 */
function buildWaitTimeNotice(minutesRemaining: number): string {
    if (minutesRemaining > 60) return "";
    if (minutesRemaining <= 5) {
        return "\n\n⏰ _Nota: Su ventana de sesión está por cerrarse. Si necesita más ayuda, por favor envíe un nuevo mensaje._";
    }
    return `\n\n⏰ _Sesión activa por ${minutesRemaining} minutos más._`;
}

// =============================================================================
// Response Node
// =============================================================================

export async function responseNode(
    state: WhatsAppStateType,
): Promise<Partial<WhatsAppStateType>> {
    const config = await getWhatsAppDynamicConfig();

    // Check for escalation
    if (state.escalated || shouldEscalate(state, config.escalationThreshold)) {
        const reason =
            state.escalationReason || "El cliente solicitó hablar con un agente.";

        // Preserve handoff text set by escalationNode or an upstream node
        // (paymentPendingEscalation, intake-fee guardrail, etc.). Only fall
        // back to the generic bounce when no text is present.
        const preservedText = state.responseText;
        const fallbackOrder = getActiveOrders(state)?.[0]?.svc_order_no;
        const text =
            preservedText && preservedText.trim().length > 0
                ? preservedText
                : buildEscalationResponse(reason, fallbackOrder);

        return {
            responseText: text,
            escalated: true,
            escalationReason: reason,
        };
    }

    // Format the response
    let text = state.responseText || "Lo siento, no pude generar una respuesta.";

    // Apply character limit (lane-aware: use lane config if available)
    const maxLen = state.laneConfig?.maxResponseTokens ?? config.maxResponseLength;
    text = truncateResponse(text, maxLen);

    // Add wait time notice if applicable
    const session = getSessionInfo(state);
    if (session) {
        text += buildWaitTimeNotice(session.minutes_remaining);
    }

    return {
        responseText: text,
    };
}

/**
 * Escalation node — marks the conversation as escalated.
 *
 * Resolution order for the customer-facing handoff text:
 *   1. If state.responseText is already set (node did its own render via
 *      paymentPendingEscalation / renderHandoff), keep it verbatim.
 *   2. Else if we can resolve a typed EscalationReason — from the override
 *      slug, or by mapping a frustration intent (complaint / explicit-human)
 *      to its reason — emit the D13 renderHandoff copy with state-derived ctx.
 *      For the human-frustration cluster this also appends the direct store
 *      line so the customer reaches a person, not the AI line.
 *   3. Else fall back to the legacy generic bounce (buildEscalationResponse).
 *
 * Persisted `escalation_reason` is the enum slug when we have one (so
 * dashboard queue filters work), else the free-text string.
 */
export async function escalationNode(
    state: WhatsAppStateType,
): Promise<Partial<WhatsAppStateType>> {
    const override = state.escalationReasonOverride;
    // Resolve a typed reason: explicit override wins, else map the frustration
    // intent. Without this mapping, plain complaint / explicit-human intents
    // (which never set an override) would hit the generic bounce and never
    // surface the store line.
    const typedReason = resolveTypedReason(state);
    const persistedReason =
        typedReason ||
        override ||
        state.escalationReason ||
        "El cliente solicitó hablar con un agente.";

    let responseText = state.responseText;
    if (!responseText) {
        if (typedReason) {
            responseText = renderHandoff(
                typedReason,
                await buildHandoffContext(state),
            );
        } else {
            // Legacy path — free-text reason; customer sees generic bounce
            // with a sparse motive, not the raw override slug.
            const customerFacingReason = override
                ? "Solicitud de transferencia."
                : persistedReason;
            const fallbackOrder = getActiveOrders(state)?.[0]?.svc_order_no;
            responseText = buildEscalationResponse(
                customerFacingReason,
                fallbackOrder,
            );
        }
    }

    return {
        escalated: true,
        escalationReason: persistedReason,
        escalationAttempts: state.escalationAttempts + 1,
        responseText,
    };
}

/**
 * Human-taken-over node — marks that a human agent has taken control.
 */
export async function humanTakenOverNode(
    state: WhatsAppStateType,
): Promise<Partial<WhatsAppStateType>> {
    return {
        humanTakenOver: true,
        responseText:
            "Un agente humano ha tomado el control de esta conversación. Gracias por su paciencia.",
    };
}

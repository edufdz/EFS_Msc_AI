/**
 * Delivery Logistics Node (D6)
 * ============================
 * Handles `delivery_logistics` intent ("¿cuándo me llega?" / "¿ya la enviaron?" /
 * "¿cuál es el número de guía?") without escalating. Uses the D4 customer-view
 * projection for safe rendering and the D14 pricing classifier to avoid
 * promising shipping-next when the repair hasn't even been quoted yet.
 *
 * Pricing-state gate (see tech_repair_delivery_pricing_interaction memory):
 *   - in_warranty  → safe to render status-based shipping copy
 *   - quoted       → safe to render status-based shipping copy
 *   - awaiting_diagnosis | intake_fee_only → step back to quote-first framing
 *   - unknown      → ask for order number / fall through to support
 *
 * Re-ask guard (per user direction, revised review item #6):
 *   - first-pass on any status: empathetic status reply + "te aviso automáticamente"
 *   - re-ask during ST030/ST035 (repair not done, no ETA to give): empathetic
 *     variance, NOT escalation — the human queue has 0.66% resolution.
 *   - re-ask during ST040 or later: escalate `shipping_eta_carrier_chase` at
 *     normal priority (real carrier-chase work).
 *   - re-ask during ST050/ST060: confirm delivery date, no escalation unless
 *     the customer disputes (a complaint signal catches that downstream).
 *
 * Register/output: run the final text through the D12 style guide before
 * returning. This node produces the content; post-processing normalizes tone.
 */

import {
    type WhatsAppStateType,
    getActiveOrders,
    getCustomerInfo,
} from "@/services/agents/whatsapp/graph/state";
import { logAgentThought } from "@/shared/supabase-logger";
import { getSupabaseClient } from "@/shared/supabase";
import {
    projectForCustomer,
    type ServiceOrderRowLike,
} from "@/shared/so-customer-view";
import { classifyPricingState } from "@/shared/pricing-semantics";
import { paymentPendingEscalation } from "@/shared/payment-pending";
import { renderHandoff, priorityFor } from "@/shared/escalation-reasons";
import {
    applyStyleGuide,
    type Register,
    type StyleContext,
} from "@/services/agents/whatsapp/post-processors/style-guide";

// =============================================================================
// Re-ask window (used for the second-ask-within-30min escalation guard)
// =============================================================================

const REASK_WINDOW_MS = 30 * 60 * 1000;

function countRecentDeliveryAsks(
    state: WhatsAppStateType,
    nowMs: number,
    windowMs: number = REASK_WINDOW_MS,
): number {
    const history = state.context?.conversation_history ?? [];
    let count = 0;
    for (const msg of history) {
        if (msg.role !== "user") continue;
        const ts = Date.parse(msg.timestamp);
        if (Number.isNaN(ts)) continue;
        if (nowMs - ts > windowMs) continue;
        // Rough keyword heuristic — the router already classified these same
        // keywords as delivery_logistics; we match the same tokens here.
        if (
            /paqueter[ií]a|gu[ií]a|env[ií]o|envi[ae]|rastreo|entrega|cu[aá]ndo\s+llega|mandan|enviar[ao]n/i.test(
                msg.content,
            )
        ) {
            count++;
        }
    }
    return count;
}

// =============================================================================
// Reply copy helpers
// =============================================================================

// Copies are kept tight because the D12 length cap for delivery_logistics
// is max(120, 3*inbound). Short inbound ("cuándo llega?") means a 120-char cap.
const ST_SHIPPING_COPY: Record<string, string> = {
    ST035:
        "Tu equipo ya está listo. La guía de rastreo te llega por aquí en cuanto la emitan.",
    ST040:
        "Tu equipo ya fue enviado. La guía te llega por aquí en cuanto la emitan.",
    ST050: "Tu equipo ya fue entregado. Gracias por tu confianza.",
    ST060:
        "Tu equipo ya fue entregado como cambio físico. Gracias por tu confianza.",
};

const ST_IN_PROGRESS_COPY =
    "Seguimos trabajando en tu equipo. Cuando pase a envío te lo confirmamos por aquí.";

const QUOTE_FIRST_COPY =
    "Tu equipo sigue en diagnóstico. El envío se programa cuando apruebes la cotización del técnico por correo.";

const ASK_ORDER_COPY =
    "Para consultar el estado de tu envío, ¿me compartes tu número de orden?";

const REASK_ST030_VARIANCE =
    "Entiendo la urgencia. Tu equipo sigue en proceso; en cuanto pase a envío te lo confirmamos por aquí.";

const REASK_ST035_VARIANCE =
    "Entiendo la urgencia. Tu equipo ya quedó listo; en cuanto la paquetería emita la guía te llega por aquí.";

// =============================================================================
// Node
// =============================================================================

export interface DeliveryLogisticsOptions {
    /** Injectable now for deterministic tests. */
    nowMs?: number;
    /** Injectable register resolver — callers decide formal/informal. */
    register?: Register;
}

export async function deliveryLogisticsNode(
    state: WhatsAppStateType,
    opts: DeliveryLogisticsOptions = {},
): Promise<Partial<WhatsAppStateType>> {
    const nowMs = opts.nowMs ?? Date.now();
    const register: Register = opts.register ?? "default_formal";

    const orders = getActiveOrders(state);
    const inbound = state.context?.current_message?.content ?? "";

    // No active SO → ask for the order number. This is an answer, not an
    // escalation, so the customer keeps the bot thread.
    if (orders.length === 0) {
        const reply = applyStyleGuide(ASK_ORDER_COPY, {
            isFirstOutbound: isFirstOutbound(state),
            register,
            inboundMessage: inbound,
            intent: "delivery_logistics",
            didConcreteResolution: false,
        });
        logThought(state, "delivery_logistics: no active SO, asking for order number");
        return { responseText: reply };
    }

    // Use the first active order; downstream we can enrich if there are multiple.
    const so = orders[0] as unknown as ServiceOrderRowLike;
    const view = projectForCustomer(so, {
        customerIntent: "delivery_logistics",
    });

    // Payment-pending short-circuit: nothing about shipping we can say if the
    // customer hasn't paid the repair quote yet. Escalate to finance.
    const customer = getCustomerInfo(state);
    const handoffCtx = {
        customerFirstName: customer?.name?.split(/\s+/)[0],
        svcOrderNo: so.svc_order_no,
        register,
    };
    const paymentEsc = paymentPendingEscalation(so, handoffCtx);
    if (paymentEsc) {
        logThought(
            state,
            `delivery_logistics → payment_pending on ${so.svc_order_no}, escalating`,
        );
        return {
            responseText: paymentEsc.replyText,
            escalated: true,
            escalationReasonOverride: paymentEsc.reason,
            escalatePriority: paymentEsc.priority,
        };
    }

    const pricingState = classifyPricingState(so);

    // D14 interaction guard: if the repair hasn't been quoted yet, don't
    // promise shipping-next. Step back to quote-first framing.
    if (
        pricingState.kind === "intake_fee_only" ||
        pricingState.kind === "awaiting_diagnosis"
    ) {
        const reply = applyStyleGuide(
            QUOTE_FIRST_COPY,
            {
                isFirstOutbound: isFirstOutbound(state),
                register,
                inboundMessage: inbound,
                intent: "delivery_logistics",
                didConcreteResolution: true,
            },
        );
        logThought(
            state,
            `delivery_logistics: quote-first framing (pricing=${pricingState.kind}) for ${so.svc_order_no}`,
        );
        return { responseText: reply };
    }

    const status = so.status ?? "";

    // Re-ask guard
    const recentAsks = countRecentDeliveryAsks(state, nowMs);
    const isReask = recentAsks >= 1; // "1" means there's at least one prior ask in window besides the current

    if (isReask) {
        // ST030/ST035 re-ask → empathetic variance, never escalate
        if (status === "ST030") {
            const reply = applyStyleGuide(
                REASK_ST030_VARIANCE,
                styleCtx(state, register, inbound, "delivery_logistics", true),
            );
            logThought(state, `delivery_logistics re-ask on ST030 → variance, no escalation`);
            return { responseText: reply };
        }
        if (status === "ST035") {
            const reply = applyStyleGuide(
                REASK_ST035_VARIANCE,
                styleCtx(state, register, inbound, "delivery_logistics", true),
            );
            logThought(state, `delivery_logistics re-ask on ST035 → variance, no escalation`);
            return { responseText: reply };
        }
        // ST040+: legitimate carrier-chase — escalate
        if (status === "ST040" || status === "ST045") {
            const handoff = renderHandoff("shipping_eta_carrier_chase", handoffCtx);
            logThought(
                state,
                `delivery_logistics re-ask on ${status} → escalating shipping_eta_carrier_chase`,
            );
            return {
                responseText: handoff,
                escalated: true,
                escalationReasonOverride: "shipping_eta_carrier_chase",
                escalatePriority: priorityFor("shipping_eta_carrier_chase"),
            };
        }
        // ST050/ST060 re-ask: confirm delivery date, no escalation
        if (status === "ST050" || status === "ST060") {
            const dateLine = view.complete_date
                ? `El registro muestra entrega el ${view.complete_date}.`
                : "El registro muestra que ya fue entregado.";
            const reply = applyStyleGuide(
                dateLine,
                styleCtx(state, register, inbound, "delivery_logistics", true),
            );
            logThought(state, `delivery_logistics re-ask on ${status} → confirm delivery date`);
            return { responseText: reply };
        }
        // Other statuses re-ask falls through to first-pass copy below
    }

    // First-pass status-based reply. Copy is intentionally short because
    // the D12 length cap kicks in for delivery_logistics intents.
    let copy: string;
    if (ST_SHIPPING_COPY[status]) {
        copy = ST_SHIPPING_COPY[status];
    } else if (
        status === "ST010" ||
        status === "ST015" ||
        status === "ST020" ||
        status === "ST025" ||
        status === "ST030"
    ) {
        copy = ST_IN_PROGRESS_COPY;
    } else {
        copy = "Te avisamos por aquí cuando haya movimiento.";
    }

    const reply = applyStyleGuide(
        copy,
        styleCtx(state, register, inbound, "delivery_logistics", true),
    );
    logThought(
        state,
        `delivery_logistics first-pass on ${status} for ${so.svc_order_no}`,
    );
    return { responseText: reply };
}

// =============================================================================
// Helpers
// =============================================================================

function isFirstOutbound(state: WhatsAppStateType): boolean {
    const history = state.context?.conversation_history ?? [];
    return !history.some((m) => m.role === "assistant");
}

function styleCtx(
    state: WhatsAppStateType,
    register: Register,
    inbound: string,
    intent: string,
    didConcreteResolution: boolean,
): StyleContext {
    return {
        isFirstOutbound: isFirstOutbound(state),
        register,
        inboundMessage: inbound,
        intent,
        didConcreteResolution,
        // d2d_status_notifier (D3) drives the automatic follow-up promise.
        // Until D3c ships we leave this off; the promise phrase will be
        // softened by rule 6.
        availablePromiseHooks: new Set(),
    };
}

function logThought(state: WhatsAppStateType, note: string): void {
    const supabase = getSupabaseClient();
    if (!supabase) return;
    logAgentThought(supabase, {
        conversationId: state.context?.metadata?.conversation_id as string | undefined,
        phone: state.context?.customer?.phone_number,
        stepName: "delivery_logistics",
        thoughtContent: note,
    }).catch(() => {
        /* non-fatal */
    });
}

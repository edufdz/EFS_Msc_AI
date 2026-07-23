/**
 * Pricing Answer Node
 * ===================
 * Handles `pricing` intent. Every cost-exposing branch sources its number
 * from GSPN (`service_orders.estimated_cost_mxn` via `classifyPricingState`
 * through `planPricingResponse`). The `repair_pricing` estimate table is // ci-guard:allow repair_pricing
 * never read from this node — on WhatsApp, all prices are GSPN quotes.
 *
 * Routing summary:
 *   - No active SO        → ask for order number (no tool calls)
 *   - >3 active SOs       → ask customer to narrow (no tool calls)
 *   - 2 or 3 active SOs   → disambiguate with serial-comma list
 *   - Single active SO    → delegate to planPricingResponse and render
 *                            with this node's `pricing`-tagged copy.
 *
 * The planner variants map 1:1 to local copy constants. This node owns
 * all final text; the planner is a pure classifier.
 */

import {
    type WhatsAppStateType,
    getActiveOrders,
    getCustomerInfo,
} from "@/services/agents/whatsapp/graph/state";
import { logAgentThought } from "@/shared/supabase-logger";
import { getSupabaseClient } from "@/shared/supabase";
import { insertPendingCostFollowup } from "@/shared/cost-followup";
import { renderHandoff, priorityFor } from "@/shared/escalation-reasons";
import {
    applyStyleGuide,
    type Register,
} from "@/services/agents/whatsapp/post-processors/style-guide";
import { planPricingResponse } from "@/services/agents/whatsapp/graph/pricing-plan";
import type { ServiceOrderRowLike } from "@/shared/so-customer-view";
import type { ServiceOrderInfo } from "@/services/agents/whatsapp/models";

// =============================================================================
// Copies (pricing-tagged; length cap bucket is the compound "pricing" intent)
// =============================================================================

export const ASK_ORDER_COPY =
    "Para cotizarte con exactitud necesito tu número de orden. ¿Me lo compartes?";

// Spanish serial comma: "#A, #B y #C" — not "#A y #B y #C".
export function joinSpanish(items: string[]): string {
    if (items.length === 0) return "";
    if (items.length === 1) return items[0];
    if (items.length === 2) return `${items[0]} y ${items[1]}`;
    return `${items.slice(0, -1).join(", ")} y ${items[items.length - 1]}`;
}

export const MULTI_ORDER_CAP_COPY =
    "Veo varias órdenes activas a tu nombre. ¿Me compartes el número de la orden sobre la que preguntas?";

export function multiOrderDisambiguation(
    orders: ReadonlyArray<{ svc_order_no: string }>,
): string {
    if (orders.length > 3) return MULTI_ORDER_CAP_COPY;
    const names = orders.map((o) => `#${o.svc_order_no}`);
    return `Veo ${orders.length} órdenes activas a tu nombre: ${joinSpanish(
        names,
    )}. ¿Sobre cuál preguntas?`;
}

export const IN_WARRANTY_COPY =
    "Tu orden está en garantía interna. La reparación está cubierta sin costo.";

export const AWAITING_DIAGNOSIS_COPY =
    "Aún no tengo la cotización — el técnico la envía en cuanto termina el diagnóstico. Te aviso por aquí apenas la registre.";

export function intakeFeeCopy(fee: 290 | 390): string {
    return `Tu orden tiene registrada la cuota de ingreso de $${fee} MXN (cubre el diagnóstico). La cotización de la reparación te la envía el técnico por correo.`;
}

export function quotedCopy(totalMxn: number): string {
    return `La cotización de tu reparación es de $${totalMxn.toLocaleString(
        "es-MX",
    )} MXN e incluye la cuota de ingreso ya pagada. Los datos de pago te llegan por correo.`;
}

export const UNKNOWN_COPY =
    "Todavía no tenemos confirmada la información de costo. En cuanto el técnico la registre te aviso por aquí.";

// =============================================================================
// Node
// =============================================================================

export interface PricingAnswerOptions {
    register?: Register;
}

export async function pricingAnswerNode(
    state: WhatsAppStateType,
    opts: PricingAnswerOptions = {},
): Promise<Partial<WhatsAppStateType>> {
    const register: Register = opts.register ?? "default_formal";
    const orders = getActiveOrders(state);
    const inbound = state.context?.current_message?.content ?? "";
    const customer = getCustomerInfo(state);

    // No active SO → ask for order number. Never reach for estimates.
    if (orders.length === 0) {
        const reply = applyStyleGuide(
            ASK_ORDER_COPY,
            styleCtx(state, register, inbound, false),
        );
        logThought(state, "pricing_answer: no active SO, asking for order number");
        return { responseText: reply };
    }

    // Multiple active SOs → disambiguate. The bot can't pick for the
    // customer because the GSPN quote is per-order.
    if (orders.length > 1) {
        const reply = applyStyleGuide(
            multiOrderDisambiguation(orders),
            styleCtx(state, register, inbound, false),
        );
        logThought(
            state,
            `pricing_answer: ${orders.length} active SOs, disambiguating`,
        );
        return { responseText: reply };
    }

    // Single active SO → classify and render.
    const so = orders[0] as unknown as ServiceOrderRowLike;
    const plan = planPricingResponse(so);
    const handoffCtx = {
        customerFirstName: customer?.name?.split(/\s+/)[0],
        svcOrderNo: so.svc_order_no,
        register,
    };

    switch (plan.copyKey) {
        case "in_warranty": {
            runSideEffects(plan.sideEffects, so, customer?.phone_number);
            const reply = applyStyleGuide(
                IN_WARRANTY_COPY,
                styleCtx(state, register, inbound, true),
            );
            logThought(state, `pricing_answer: in_warranty on ${so.svc_order_no}`);
            return { responseText: reply };
        }
        case "awaiting_diagnosis": {
            runSideEffects(plan.sideEffects, so, customer?.phone_number);
            const reply = applyStyleGuide(
                AWAITING_DIAGNOSIS_COPY,
                styleCtx(state, register, inbound, true),
            );
            logThought(
                state,
                `pricing_answer: awaiting_diagnosis on ${so.svc_order_no} (cost_followup registered)`,
            );
            return { responseText: reply };
        }
        case "intake_fee_only": {
            const handoff = renderHandoff(plan.reason, handoffCtx);
            const reply = applyStyleGuide(
                `${intakeFeeCopy(plan.feeMxn)} ${handoff}`,
                styleCtx(state, register, inbound, true),
            );
            logThought(
                state,
                `pricing_answer: intake_fee_only (fee=${plan.feeMxn}) on ${so.svc_order_no}, escalating ${plan.reason}`,
            );
            return {
                responseText: reply,
                escalated: true,
                escalationReasonOverride: plan.reason,
                escalatePriority: priorityFor(plan.reason),
            };
        }
        case "quoted": {
            runSideEffects(plan.sideEffects, so, customer?.phone_number);
            const reply = applyStyleGuide(
                quotedCopy(plan.totalMxn),
                styleCtx(state, register, inbound, true),
            );
            logThought(
                state,
                `pricing_answer: quoted ($${plan.totalMxn.toLocaleString("es-MX")}) on ${so.svc_order_no}`,
            );
            return { responseText: reply };
        }
        case "quoted_payment_pending": {
            const handoff = renderHandoff(plan.reason, handoffCtx);
            const reply = applyStyleGuide(
                handoff,
                styleCtx(state, register, inbound, true),
            );
            logThought(
                state,
                `pricing_answer: payment_pending on ${so.svc_order_no} (total=$${plan.totalMxn.toLocaleString("es-MX")})`,
            );
            return {
                responseText: reply,
                escalated: true,
                escalationReasonOverride: plan.reason,
                escalatePriority: priorityFor(plan.reason),
            };
        }
        case "unknown":
        default: {
            const reply = applyStyleGuide(
                UNKNOWN_COPY,
                styleCtx(state, register, inbound, true),
            );
            logThought(
                state,
                `pricing_answer: unknown pricing state on ${so.svc_order_no}`,
            );
            return { responseText: reply };
        }
    }
}

// =============================================================================
// Helpers
// =============================================================================

function runSideEffects(
    effects: ReadonlyArray<{ kind: "register_cost_followup" }>,
    so: ServiceOrderRowLike,
    phone: string | undefined,
): void {
    for (const fx of effects) {
        if (fx.kind === "register_cost_followup") {
            const supa = getSupabaseClient();
            if (!supa || !phone) continue;
            insertPendingCostFollowup(supa, so.svc_order_no, phone).catch(() => {
                /* non-fatal */
            });
        }
    }
}

function isFirstOutbound(state: WhatsAppStateType): boolean {
    const history = state.context?.conversation_history ?? [];
    return !history.some((m) => m.role === "assistant");
}

function styleCtx(
    state: WhatsAppStateType,
    register: Register,
    inbound: string,
    didConcreteResolution: boolean,
) {
    return {
        isFirstOutbound: isFirstOutbound(state),
        register,
        inboundMessage: inbound,
        intent: "pricing",
        didConcreteResolution,
        availablePromiseHooks: new Set<string>(),
    };
}

function logThought(state: WhatsAppStateType, note: string): void {
    const supabase = getSupabaseClient();
    if (!supabase) return;
    logAgentThought(supabase, {
        conversationId: state.context?.metadata?.conversation_id as
            | string
            | undefined,
        phone: state.context?.customer?.phone_number,
        stepName: "pricing_answer",
        thoughtContent: note,
    }).catch(() => {
        /* non-fatal */
    });
}

// Re-export type for tests/consumers that want to type lists.
export type { ServiceOrderInfo };

/**
 * Warranty Answer Node (D7)
 * =========================
 * Handles `warranty_question` intent. Every cost-exposing branch routes
 * through D14's `classifyPricingState` so we never present a $290/$390
 * intake fee as the repair cost.
 *
 * Pricing-state branching:
 *   - in_warranty        → "garantía interna activa, cubierta sin costo"
 *                          (no cost exposed, no escalation)
 *   - awaiting_diagnosis → "costo pendiente, te aviso por aquí cuando
 *                          el técnico lo registre" + TODO: insert into
 *                          pending_cost_followup once D8 ships
 *   - intake_fee_only    → acknowledge intake fee ("cuota de ingreso")
 *                          + escalate `final_quote_request` so the
 *                          technician follows up by email
 *   - quoted             → expose total with the intake-already-applied
 *                          note; payment-pending check may still escalate
 *   - unknown / no SO    → ask for order number
 *
 * Payment-pending short-circuit: same as D6 — before branching on state,
 * detectPaymentPending() / paymentPendingEscalation() escalate to finance
 * when a quoted order sits unpaid on ST030/ST035.
 */

import {
    type WhatsAppStateType,
    getActiveOrders,
    getCustomerInfo,
} from "@/services/agents/whatsapp/graph/state";
import { logAgentThought } from "@/shared/supabase-logger";
import { getSupabaseClient } from "@/shared/supabase";
import { insertPendingCostFollowup } from "@/shared/cost-followup";
import { type ServiceOrderRowLike } from "@/shared/so-customer-view";
import {
    renderHandoff,
    priorityFor,
} from "@/shared/escalation-reasons";
import {
    applyStyleGuide,
    type Register,
} from "@/services/agents/whatsapp/post-processors/style-guide";
import { planPricingResponse } from "@/services/agents/whatsapp/graph/pricing-plan";

// =============================================================================
// Copies (kept tight; warranty_question is in the D12 concise-intents list)
// =============================================================================

const IN_WARRANTY_COPY =
    "Tu orden está con garantía interna activa. La reparación está cubierta sin costo.";

const AWAITING_DIAGNOSIS_COPY =
    "El diagnóstico aún no tiene costo. Te aviso por aquí cuando el técnico lo registre.";

const ASK_ORDER_COPY =
    "Para confirmarte la garantía, ¿me compartes tu número de orden?";

const UNKNOWN_WARRANTY_COPY =
    "Todavía no tenemos confirmada la garantía. En cuanto el técnico valide te aviso por aquí.";

// =============================================================================
// Node
// =============================================================================

export interface WarrantyAnswerOptions {
    register?: Register;
}

export async function warrantyAnswerNode(
    state: WhatsAppStateType,
    opts: WarrantyAnswerOptions = {},
): Promise<Partial<WhatsAppStateType>> {
    const register: Register = opts.register ?? "default_formal";
    const orders = getActiveOrders(state);
    const inbound = state.context?.current_message?.content ?? "";

    if (orders.length === 0) {
        const reply = applyStyleGuide(ASK_ORDER_COPY, {
            isFirstOutbound: isFirstOutbound(state),
            register,
            inboundMessage: inbound,
            intent: "warranty_question",
            didConcreteResolution: false,
        });
        logThought(state, "warranty_answer: no active SO, asking for order number");
        return { responseText: reply };
    }

    const so = orders[0] as unknown as ServiceOrderRowLike;
    const customer = getCustomerInfo(state);
    const handoffCtx = {
        customerFirstName: customer?.name?.split(/\s+/)[0],
        svcOrderNo: so.svc_order_no,
        register,
    };

    const plan = planPricingResponse(so);

    switch (plan.copyKey) {
        case "in_warranty": {
            const reply = applyStyleGuide(
                IN_WARRANTY_COPY,
                styleCtx(state, register, inbound, true),
            );
            logThought(state, `warranty_answer: in_warranty on ${so.svc_order_no}`);
            return { responseText: reply };
        }

        case "awaiting_diagnosis": {
            // D8 wiring — run the planner's register_cost_followup side-effect.
            for (const fx of plan.sideEffects) {
                if (fx.kind === "register_cost_followup") {
                    const supa = getSupabaseClient();
                    const phone = customer?.phone_number;
                    if (supa && phone) {
                        insertPendingCostFollowup(
                            supa,
                            so.svc_order_no,
                            phone,
                        ).catch(() => {
                            /* non-fatal */
                        });
                    }
                }
            }
            const reply = applyStyleGuide(
                AWAITING_DIAGNOSIS_COPY,
                styleCtx(state, register, inbound, true),
            );
            logThought(
                state,
                `warranty_answer: awaiting_diagnosis on ${so.svc_order_no} (cost_followup registered)`,
            );
            return { responseText: reply };
        }

        case "intake_fee_only": {
            const fee = plan.feeMxn;
            const acknowledge =
                `Tu orden tiene registrada la cuota de ingreso de $${fee} MXN que cubre el diagnóstico. La cotización de la reparación la emite el técnico por correo.`;
            const handoff = renderHandoff(plan.reason, handoffCtx);
            const reply = applyStyleGuide(
                `${acknowledge} ${handoff}`,
                // Use "pricing" intent here: it's a compound cost response and
                // NOT in the D12 concise-intent cap list, so the length rule
                // doesn't truncate the acknowledge + handoff.
                styleCtx(state, register, inbound, true, "pricing"),
            );
            logThought(
                state,
                `warranty_answer: intake_fee_only (fee=${fee}) on ${so.svc_order_no}, escalating ${plan.reason}`,
            );
            return {
                responseText: reply,
                escalated: true,
                escalationReasonOverride: plan.reason,
                escalatePriority: priorityFor(plan.reason),
            };
        }

        case "quoted": {
            const total = plan.totalMxn;
            const formatted = total.toLocaleString("es-MX");
            const copy =
                `La cotización de tu reparación es de $${formatted} MXN e incluye la cuota de ingreso ya pagada. Los datos de pago te llegan por correo.`;
            const reply = applyStyleGuide(
                copy,
                // Use "pricing" intent here: it's a compound cost response and
                // NOT in the D12 concise-intent cap list, so the length rule
                // doesn't truncate the acknowledge + handoff.
                styleCtx(state, register, inbound, true, "pricing"),
            );
            logThought(
                state,
                `warranty_answer: quoted ($${formatted}) on ${so.svc_order_no}`,
            );
            return { responseText: reply };
        }

        case "quoted_payment_pending": {
            // Payment-pending short-circuit: quoted, unpaid ST030/ST035 → finance.
            const handoff = renderHandoff(plan.reason, handoffCtx);
            const reply = applyStyleGuide(
                handoff,
                styleCtx(state, register, inbound, true),
            );
            logThought(
                state,
                `warranty_answer → payment_pending on ${so.svc_order_no}`,
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
                UNKNOWN_WARRANTY_COPY,
                styleCtx(state, register, inbound, true),
            );
            logThought(
                state,
                `warranty_answer: unknown pricing state on ${so.svc_order_no}`,
            );
            return { responseText: reply };
        }
    }
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
    didConcreteResolution: boolean,
    intentOverride: string | undefined = "warranty_question",
) {
    return {
        isFirstOutbound: isFirstOutbound(state),
        register,
        inboundMessage: inbound,
        intent: intentOverride,
        didConcreteResolution,
        availablePromiseHooks: new Set<string>(),
    };
}

function logThought(state: WhatsAppStateType, note: string): void {
    const supabase = getSupabaseClient();
    if (!supabase) return;
    logAgentThought(supabase, {
        conversationId: state.context?.metadata?.conversation_id as string | undefined,
        phone: state.context?.customer?.phone_number,
        stepName: "warranty_answer",
        thoughtContent: note,
    }).catch(() => {
        /* non-fatal */
    });
}

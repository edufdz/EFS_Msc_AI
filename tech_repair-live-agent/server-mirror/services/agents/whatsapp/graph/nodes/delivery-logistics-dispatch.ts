/**
 * Delivery Logistics Dispatcher
 * =============================
 * Fixes the "Maria tells carry-in customers their device ships home" bug.
 *
 * The `delivery_logistics` intent was wired directly to the D2D node
 * (`pipelines/d2d/graph/nodes/delivery-logistics.ts`), which emits
 * shipping/guía/paquetería copy for EVERY order regardless of service type.
 * Carry-in customers (device dropped off + picked up IN STORE, no shipping)
 * were told their device would be delivered "a domicilio" — wrong and
 * confusing.
 *
 * This dispatcher sits in front of that node and branches on `service_type`:
 *   - all active orders are `carry_in` → render in-store pickup copy here
 *     (never uses envío/guía/paquetería/domicilio).
 *   - mixed carry_in + d2d → ask for the folio to disambiguate. We must NOT
 *     guess from orders[0]: getActiveOrders sorts svc_order_no DESC, and a
 *     "D2D…" number sorts above a "417…" number, so the D2D order would
 *     always win the pick — exactly the trap that would misframe a carry-in.
 *   - d2d / other / null / no orders → delegate VERBATIM to the existing D2D
 *     node. D2D behaviour is 100% unchanged.
 *
 * Additive by design: the carry-in branch only fires when at least one active
 * order is classified `carry_in`. Everything else takes the pre-existing path.
 */

import {
    type WhatsAppStateType,
    getActiveOrders,
    getCustomerInfo,
} from "@/services/agents/whatsapp/graph/state";
import {
    deliveryLogisticsNode,
    type DeliveryLogisticsOptions,
} from "@/services/pipelines/d2d/graph/nodes/delivery-logistics";
import { translateStatusToState } from "@/shared/service-status-policy";
import {
    applyStyleGuide,
    type Register,
    type StyleContext,
} from "@/services/agents/whatsapp/post-processors/style-guide";
import { logAgentThought } from "@/shared/supabase-logger";
import { getSupabaseClient } from "@/shared/supabase";

// =============================================================================
// Carry-in reply copy (Mexican Spanish, tuteo). NEVER shipping language.
// =============================================================================

const CARRY_IN_READY_COPY =
    "Tu equipo ya está listo. Puedes pasar a recogerlo a nuestra tienda en Polanco, de lunes a sábado de 10:00 AM a 7:00 PM.";

const CARRY_IN_DELIVERED_COPY =
    "Tu equipo ya fue entregado. Gracias por tu confianza.";

const CARRY_IN_IN_PROGRESS_COPY =
    "Seguimos trabajando en tu equipo. Te avisaremos por aquí en cuanto esté listo para que puedas pasar a recogerlo a nuestra tienda.";

const CARRY_IN_MIXED_ASK_FOLIO_COPY =
    "Veo que tienes más de una orden con nosotros. ¿Me compartes el número de folio de la que quieres consultar? Así te doy la información correcta.";

// =============================================================================
// Dispatcher
// =============================================================================

export async function deliveryLogisticsDispatchNode(
    state: WhatsAppStateType,
    opts: DeliveryLogisticsOptions = {},
): Promise<Partial<WhatsAppStateType>> {
    const register: Register = opts.register ?? "default_formal";
    const orders = getActiveOrders(state);
    const inbound = state.context?.current_message?.content ?? "";

    const carryInOrders = orders.filter((o) => o.service_type === "carry_in");

    // No carry-in in the mix → the pre-existing D2D node handles everything
    // (d2d / other / null / no active orders). Behaviour unchanged.
    if (carryInOrders.length === 0) {
        return deliveryLogisticsNode(state, opts);
    }

    // Mixed carry-in + non-carry-in → never guess which order they mean.
    const nonCarryIn = orders.filter((o) => o.service_type !== "carry_in");
    if (nonCarryIn.length > 0) {
        const reply = applyStyleGuide(
            CARRY_IN_MIXED_ASK_FOLIO_COPY,
            styleCtx(state, register, inbound, false),
        );
        logThought(
            state,
            `delivery_logistics: mixed carry_in + non-carry_in (${orders.length} orders) → asking for folio`,
        );
        return { responseText: reply };
    }

    // All active orders are carry-in → in-store pickup framing keyed off the
    // carry-in semantic state (ST040 → ready_for_pickup, not "shipped").
    const so = carryInOrders[0];
    const semanticState = translateStatusToState("carry_in", so.status);

    let copy: string;
    if (semanticState === "ready_for_pickup") {
        copy = CARRY_IN_READY_COPY;
    } else if (semanticState === "delivered" || semanticState === "closed") {
        copy = CARRY_IN_DELIVERED_COPY;
    } else {
        // received / in_diagnosis / awaiting_parts / unknown → still in the shop.
        copy = CARRY_IN_IN_PROGRESS_COPY;
    }

    const reply = applyStyleGuide(
        copy,
        styleCtx(state, register, inbound, true),
    );
    logThought(
        state,
        `delivery_logistics: carry_in ${so.svc_order_no} status=${so.status} state=${semanticState} → in-store pickup copy`,
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
    didConcreteResolution: boolean,
): StyleContext {
    return {
        isFirstOutbound: isFirstOutbound(state),
        register,
        inboundMessage: inbound,
        intent: "delivery_logistics",
        didConcreteResolution,
        availablePromiseHooks: new Set(),
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
        stepName: "delivery_logistics_dispatch",
        thoughtContent: note,
    }).catch(() => {
        /* non-fatal */
    });
}

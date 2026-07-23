/**
 * WhatsApp Carry-in Prompt Addendum
 * =================================
 * Thin WhatsApp-side wrapper over the inbound/voice `buildCarryInAddendum`
 * so both channels render the SAME carry-in guardrail copy ("EN TIENDA, NO
 * hay envío/guía/paquetería") from a single source of truth.
 *
 * Why a wrapper instead of calling `buildCarryInAddendum` directly: the voice
 * function keys off `CustomerContext.activeOrders[].service_type`, whose item
 * type (`ActiveServiceOrder`) has more required fields than the WhatsApp
 * `ServiceOrderInfo`. The function only reads `.service_type`, so we adapt the
 * WhatsApp order shape structurally. The voice path is untouched.
 *
 * Returns `null` when no active order is carry-in — callers append `?? ""` so
 * the base prompt stays byte-identical for pure-D2D / other / null customers.
 */

import { buildCarryInAddendum } from "@/services/agents/inbound/prompts/carry-in-addendum";
import type { CustomerContext } from "@/services/agents/inbound/greeter-agent";
import type { ServiceOrderInfo } from "@/services/agents/whatsapp/models";

export function buildWhatsAppCarryInAddendum(
    orders: ServiceOrderInfo[],
): string | null {
    if (orders.length === 0) return null;

    // buildCarryInAddendum only reads context.activeOrders[].service_type;
    // adapt structurally and cast the rest.
    const activeOrders = orders.map((order) => ({
        service_type: order.service_type ?? null,
    })) as unknown as CustomerContext["activeOrders"];

    return buildCarryInAddendum({ activeOrders });
}

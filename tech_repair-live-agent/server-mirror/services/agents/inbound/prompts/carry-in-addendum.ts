/**
 * Carry-in Addendum (W2 Task 5)
 * =============================
 * Single addendum block appended to both status + pricing prompts when the
 * caller has at least one active carry-in service order. Renders the
 * in-store-pickup / counter-payment / correct-store-hours framing that
 * supersedes the prompts' default (D2D-flavored, shipping-aware) copy.
 *
 * Design constraints:
 *   - Single source of truth for carry-in voice copy — both subagents render
 *     the same words. Drift between status and pricing would surface to
 *     callers as inconsistent answers ("recogerlo" vs "te lo enviamos").
 *   - Returns `null` (not an empty string) when no carry-in orders are
 *     present — callers `?? ""` it so the base prompt stays unchanged for
 *     pure-D2D callers. This is what keeps Task 5 a strict extension rather
 *     than a behaviour change for D2D.
 *   - No LLM call here — pure string assembly keyed off the active-orders
 *     list that's already pre-loaded into the greeter context.
 *
 * @module services/agents/inbound/prompts/carry-in-addendum
 */

import type { CustomerContext } from "@/services/agents/inbound/greeter-agent";

// Bump this when the addendum copy changes — both prompts include this in
// their effective PROMPT_VERSION via getStatusInstructions / getPricingInstructions.
export const CARRY_IN_ADDENDUM_VERSION = "v1-2026-05-28";

/**
 * True when at least one of the caller's active orders is a carry-in.
 * The agent should render carry-in framing whenever this holds, even if
 * the customer also has D2D orders — the subagent disambiguates by order
 * number at the per-question level.
 */
export function hasCarryInOrder(context: CustomerContext | undefined): boolean {
    const orders = context?.activeOrders ?? [];
    return orders.some((o) => o.service_type === "carry_in");
}

/**
 * True when the caller has BOTH a carry-in AND a D2D active order. The
 * agent needs to disambiguate by order number before picking a framing —
 * the same caller may ask "¿ya está listo?" about either pipeline in the
 * same conversation.
 */
export function hasMixedPipelines(
    context: CustomerContext | undefined,
): boolean {
    const orders = context?.activeOrders ?? [];
    const types = new Set(orders.map((o) => o.service_type ?? "other"));
    return types.has("carry_in") && types.has("d2d");
}

/**
 * Build the carry-in framing block, or `null` when no carry-in order is
 * present. Spanish copy mirrors what the WhatsApp pickup-coordination node
 * will render in W3 — keep them in sync if either side changes wording.
 *
 * Store hours are sourced from `server/services/business-hours.ts:9`
 * (10 AM – 7 PM, Mon–Sat in Mexico City TZ). The prompts' pre-existing
 * "Información general" footer still says "9:00 AM - 6:00 PM" — a known
 * customer-facing copy gap (memory `tech_repair_service_hours`) tracked in W3.
 * This addendum supersedes that earlier line for carry-in callers; the
 * LLM follows the more-specific later instruction.
 */
export function buildCarryInAddendum(
    context: CustomerContext | undefined,
): string | null {
    if (!hasCarryInOrder(context)) return null;

    const mixed = hasMixedPipelines(context);

    const lines: string[] = [];
    lines.push("---");
    lines.push("");
    lines.push("REGLAS DEL FLUJO CARRY-IN (sustituyen las generales arriba):");
    lines.push("");
    lines.push(
        "El cliente dejó su equipo EN TIENDA y lo recoge EN TIENDA. NO hay envío, NO hay guía, NO hay paquetería. Si en algún momento usas las palabras 'envío', 'guía', 'paquetería' o 'te lo entregamos a domicilio' para una orden carry-in, estás dando información incorrecta.",
    );
    lines.push("");
    lines.push("CÓMO RESPONDER AL CLIENTE:");
    lines.push(
        "- '¿Ya está listo?' → si la orden está en 'ready_for_pickup', dile que ya puede pasar a recogerlo en la tienda. Si no, dile el estado actual y que le avisamos por mensaje cuando esté listo.",
    );
    lines.push(
        "- '¿Cuándo puedo pasar?' / '¿Qué horario tienen?' → el horario de la tienda es de lunes a sábado, 10:00 AM a 7:00 PM, en Polanco, CDMX.",
    );
    lines.push(
        "- '¿Cómo pago?' → puede pagar en la tienda en mostrador (efectivo, tarjeta) cuando pase a recoger, o por transferencia si ya recibió la cotización. El cargo de diagnóstico ($290 / $390) que pagó al dejarlo NO es el costo de la reparación — la cotización del técnico es aparte.",
    );
    lines.push(
        "- '¿Me lo pueden enviar?' → no, el servicio carry-in es solo en tienda. Si quiere envío a domicilio tendría que abrir una orden D2D nueva.",
    );

    if (mixed) {
        lines.push("");
        lines.push("ESTE CLIENTE TIENE ÓRDENES MIXTAS (carry-in + D2D):");
        lines.push(
            "- Antes de responder cualquier pregunta sobre estado o pago, pide el número de folio para saber de cuál orden está hablando.",
        );
        lines.push(
            "- Las reglas carry-in arriba aplican SÓLO a las órdenes carry-in. Para la orden D2D usa el guion general (con envío y guía) como hasta ahora.",
        );
    }

    return lines.join("\n");
}

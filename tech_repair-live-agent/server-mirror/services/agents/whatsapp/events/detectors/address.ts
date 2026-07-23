/**
 * Detector — Cambio / mención de domicilio
 * ========================================
 * Fires on ANY mention of an address (to be safe — a wrong delivery address is
 * expensive), classifying a sub-type:
 *   - 'cambio_solicitado' — the customer explicitly asks to change/correct it.
 *   - 'mencion'           — the address came up incidentally.
 *
 * The bot NEVER confirms a change (a human must verify before shipping):
 *   - cambio  → safe acuse "un asesor confirma tu dirección".
 *   - mencion → no acuse (botReply null), the bot answers the real question.
 *
 * Always escalates so the asesor can compare the REGISTERED address (from
 * service_orders.cust_address) against what the customer wrote.
 */

import { getActiveOrders } from "@/services/agents/whatsapp/graph/state";
import { getSupabaseClient } from "@/shared/supabase";
import type { DetectedEvent, EventDetectionContext, EventDetector } from "../types";
import { normalize } from "../text";

// Any of these = the message is talking about an address (accent-free).
const ADDRESS = [
    /\bdomicilio\b/,
    /\bdireccion\b/,
    /\bcalle\b/,
    /\bavenida\b/,
    /\bcolonia\b/,
    /\bfraccionamiento\b/,
    /\bcodigo postal\b/,
    /\bc\.?p\.?\s*\d/,
    /\bvivo en\b/,
    /\bmi casa\b/,
    /\bentreguenlo en\b/,
    /\bmandenlo a\b/,
    /\bnumero exterior\b/,
    /\bentregar(lo|me)? en\b/,
    // Phrases that imply an address even without the word "domicilio/direccion".
    /\bya no vivo\b/,
    /\bme mude\b/,
];

// Escalates the sub-type to an explicit change request. The change/update verb
// must be tied DIRECTLY to direccion/domicilio/casa — otherwise "cambié de
// número" / "cambio de plan" / "actualicé mi correo" (which co-occur with an
// address mention) would be mis-read as an address change and trigger the
// unsolicited "un asesor confirma tu dirección" acuse. A missed change just
// falls back to 'mencion', which still escalates — so erring toward mencion is
// safe.
const CHANGE = [
    /\bcambi\w*\s+(de\s+|mi\s+|la\s+|el\s+|tu\s+)?(direccion|domicilio|casa)\b/,
    /\bactuali[cz]\w*\s+(de\s+|mi\s+|la\s+|el\s+|tu\s+)?(direccion|domicilio|casa)\b/,
    /\botra direccion\b/,
    /\botro domicilio\b/,
    /\bnueva direccion\b/,
    /\bnuevo domicilio\b/,
    /\bya no vivo\b/,
    /\bme mude\b/,
    // corrige / corrigen / corrija / corrijan (tú + ustedes imperatives).
    /\bcorri(ge?n?|jan?) (mi )?(direccion|domicilio)\b/,
    /\bentreguenlo en otra\b/,
    /\bmandenlo a otra\b/,
];

/**
 * True when the accent-normalized message asks to CHANGE/correct the delivery
 * address (vs merely mentioning one). Exported for unit testing the classifier
 * independently of the DB lookup in detect().
 */
export function isAddressChange(normalizedMessage: string): boolean {
    return CHANGE.some((re) => re.test(normalizedMessage));
}

export const addressDetector: EventDetector = {
    name: "address",
    async detect(ctx: EventDetectionContext): Promise<DetectedEvent | null> {
        if (ctx.messageType !== "text") return null;
        const raw = ctx.message ?? "";
        const msg = normalize(raw);
        if (!msg) return null;
        if (!ADDRESS.some((re) => re.test(msg))) return null;

        const isChange = isAddressChange(msg);
        const svcOrderNo = getActiveOrders(ctx.state)[0]?.svc_order_no;

        // Registered delivery address for the active order (for the asesor to compare).
        let registered: string | null = null;
        if (svcOrderNo) {
            const supabase = getSupabaseClient();
            if (supabase) {
                const { data } = await supabase
                    .from("service_orders")
                    .select("cust_address")
                    .eq("svc_order_no", svcOrderNo)
                    .maybeSingle();
                registered =
                    typeof data?.cust_address === "string" && data.cust_address
                        ? data.cust_address
                        : null;
            }
        }

        const customerMessage = raw.trim().slice(0, 240);

        return {
            type: "address",
            subType: isChange ? "cambio_solicitado" : "mencion",
            label: `🏠 VERIFICAR DIRECCIÓN${isChange ? " (CAMBIO solicitado)" : ""} · Registrado: ${registered ?? "N/D"}`,
            details: {
                svc_order_no: svcOrderNo ?? null,
                registered_address: registered,
                customer_message: customerMessage,
            },
            // mención → bot answers normally (null); cambio → safe acuse.
            botReply: isChange
                ? "Sobre tu dirección de entrega, un asesor la confirma contigo en breve."
                : null,
        };
    },
};

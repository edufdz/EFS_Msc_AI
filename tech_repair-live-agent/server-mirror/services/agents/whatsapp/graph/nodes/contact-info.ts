/**
 * Contact Info Node (D5)
 * ======================
 * Deterministic answer for `contact_info_request` intent.
 * No LLM, no escalation, < 200ms latency.
 *
 * Why a dedicated node: before D1, these queries went to the LLM via
 * `general_support` and often resulted in escalation for something the
 * bot has in-memory (support phone, hours, address). Now they map to
 * a typed intent and this node renders a canned reply.
 *
 * The reply is register-aware via the D12 style guide (applied by the
 * caller of this node). The content is the same for both registers; the
 * post-processor handles pronoun swapping if needed.
 */

import { getWhatsAppDynamicConfig } from "@/services/agents/whatsapp/config";
import { getContactNumbers } from "@/shared/contact-numbers";
import { logAgentThought } from "@/shared/supabase-logger";
import { getSupabaseClient } from "@/shared/supabase";
import {
    type WhatsAppStateType,
    getCustomerInfo,
} from "@/services/agents/whatsapp/graph/state";

export async function contactInfoNode(
    state: WhatsAppStateType,
): Promise<Partial<WhatsAppStateType>> {
    const config = await getWhatsAppDynamicConfig();
    const { agentPhone, storePhone } = await getContactNumbers();

    // Two distinct lines, labeled by purpose: the agent line is the
    // self-service way to check order status by phone; the store line reaches
    // the store directly for anything that needs a person. Showing both keeps
    // the AI line as the default status fallback while making the human line
    // explicit for customers who want it.
    const lines = [
        `Para consultar el estado de su orden por teléfono, marque a la línea de atención: *${agentPhone}*.`,
        `Si necesita hablar directamente con la tienda, llame al *${storePhone}*.`,
        `Horario: ${config.businessHours}.`,
        `También puede visitarnos en: ${config.businessAddress}.`,
    ];
    const responseText = lines.join("\n");

    // Fire-and-forget observability
    const supabase = getSupabaseClient();
    if (supabase) {
        logAgentThought(supabase, {
            conversationId: state.context?.metadata?.conversation_id as
                | string
                | undefined,
            phone: getCustomerInfo(state)?.phone_number,
            stepName: "contact_info_reply",
            thoughtContent: `Deterministic contact-info reply emitted (agentPhone=${agentPhone}, storePhone=${storePhone})`,
        }).catch(() => {
            /* non-fatal */
        });
    }

    return { responseText };
}

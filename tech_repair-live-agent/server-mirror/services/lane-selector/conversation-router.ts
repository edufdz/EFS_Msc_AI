/**
 * Conversation router — resolves the lane for an inbound WhatsApp message.
 *
 * Three-step cascade: (1) phone↔SO link cache, (2) service_orders by phone,
 * (3) extract SO from messageText (if provided). The third step is the
 * carry-in fallback — TechRepair doesn't capture phones for 417-prefix orders,
 * so a carry-in customer's first message can only be identified by either
 * mentioning their SO number OR by being already in the cache from a past
 * interaction.
 *
 * **Critical default:** when the return is 'unknown' or 'ambiguous', the
 * caller MUST NOT silently default to D2D. For 'unknown', the agent should
 * ask for an order number ("¿me das tu número de orden?"). For 'ambiguous',
 * the agent asks the customer to pick which order this is about.
 *
 * @param conversationId — used as the foreign key on the agent_thoughts row
 * @param phone          — the customer's phone (raw form, will be normalized)
 * @param supabase       — Supabase client
 * @param messageText    — optional inbound message body. Pass it whenever
 *                          available; the cascade uses it to extract a SO
 *                          number and learn the phone↔SO link for next time.
 */

import type { SupabaseClient } from "@supabase/supabase-js";
import type { ResolvedLane } from "./types";
import { resolveByPhone } from "./internal";

export async function resolveServiceTypeForConversation(
    conversationId: string | null,
    phone: string,
    supabase: SupabaseClient,
    messageText: string | null = null,
): Promise<ResolvedLane> {
    return resolveByPhone(phone, supabase, "conversation", conversationId, messageText);
}

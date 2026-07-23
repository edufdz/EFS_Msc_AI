/**
 * Voice router — resolves the lane for an inbound phone call.
 *
 * Keyed on the caller-CLI E.164 phone (from the LiveKit webhook). Same
 * decision logic as the conversation router; logged separately in
 * `agent_thoughts.metadata.source = 'voice'` so dashboards can split
 * voice vs WhatsApp lane behavior.
 *
 * **Critical default:** the return value 'unknown' or 'ambiguous' MUST
 * NOT silently collapse to 'd2d'. For 'unknown', route to a human; for
 * 'ambiguous', the voice agent asks the customer to confirm the order
 * number before proceeding.
 */

import type { SupabaseClient } from "@supabase/supabase-js";
import type { ResolvedLane } from "./types";
import { resolveByPhone } from "./internal";

export async function resolveServiceTypeForVoice(
    callerPhoneE164: string,
    supabase: SupabaseClient,
): Promise<ResolvedLane> {
    return resolveByPhone(callerPhoneE164, supabase, "voice", null);
}

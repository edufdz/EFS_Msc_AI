/**
 * Cost-Followup Helper (D8)
 * =========================
 * Thin wrapper around the pending_cost_followup table + the predicate
 * the worker uses to decide when an SO has transitioned into the
 * notify-able state. Keeps the conditionals out of the worker body so
 * they can be unit-tested in isolation.
 *
 * Notify-able transition (see pricing-semantics.ts):
 *     { awaiting_diagnosis | intake_fee_only } → quoted
 *
 * i.e. the real repair quote now exists (cost > 390) and wasn't before.
 * We don't compare to the prior cost column; we check the current
 * PricingState against "quoted" and rely on the notified_at flag to
 * prevent duplicate sends.
 */

import type { SupabaseClient } from "@supabase/supabase-js";
import { classifyPricingState, type PricingState } from "./pricing-semantics";
import type { ServiceOrderRowLike } from "./so-customer-view";

/**
 * Returns true when the SO is ready for a cost-available notification:
 * PricingState is `quoted` (real repair quote, not intake fee), and the
 * caller has not yet notified the customer (caller checks notified_at
 * separately — this function is stateless).
 */
export function isNotifiableCostTransition(
    so: Pick<ServiceOrderRowLike, "warranty_type" | "estimated_cost_mxn">,
): boolean {
    const state: PricingState = classifyPricingState(so);
    return state.kind === "quoted";
}

/**
 * Write or no-op a pending cost followup for (svc_order_no, phone).
 * Uses ON CONFLICT DO NOTHING so repeated asks don't reset asked_at.
 * Safe to call from multiple nodes per inbound turn.
 */
export async function insertPendingCostFollowup(
    supabase: SupabaseClient,
    svcOrderNo: string,
    phone: string,
): Promise<void> {
    if (!svcOrderNo || !phone) return;
    await supabase.from("pending_cost_followup").upsert(
        {
            svc_order_no: svcOrderNo,
            phone,
        },
        {
            onConflict: "svc_order_no,phone",
            ignoreDuplicates: true,
        },
    );
}

/**
 * Mark the (svc_order_no, phone) row as notified now. Called by the
 * worker once the outbound template has been sent successfully.
 */
export async function markCostFollowupNotified(
    supabase: SupabaseClient,
    svcOrderNo: string,
    phone: string,
): Promise<void> {
    await supabase
        .from("pending_cost_followup")
        .update({ notified_at: new Date().toISOString() })
        .eq("svc_order_no", svcOrderNo)
        .eq("phone", phone);
}

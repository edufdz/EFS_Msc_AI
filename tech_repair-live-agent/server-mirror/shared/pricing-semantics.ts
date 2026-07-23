/**
 * Pricing Semantics for Out-of-Warranty TechRepair Service Orders
 * ============================================================
 * Classifies the `estimated_cost_mxn` field into a discriminated union
 * so downstream nodes can't accidentally present a $290/$390 intake
 * fee as the repair quote.
 *
 * The business flow (verified 2026-04-22 against SimTech Polanco, n=2607):
 *
 *   1. Customer drops off out-of-warranty equipment → pays $290 or $390
 *      as the intake/diagnostic fee at drop-off.
 *      `estimated_cost_mxn` is populated with this value.
 *
 *   2. Technician evaluates, emits the real repair quote (e.g. $5,408)
 *      via EMAIL from a human agent. This communication happens outside
 *      the bot's read surface.
 *
 *   3. Customer pays the delta ($5408 − $290 = $5118) by bank transfer.
 *      Finance validates the payment (via logistica.d2d@gruposim-tech.com).
 *
 *   4. Technician repairs the device (status progresses to ST035).
 *
 * Distribution observed in production (warranty='O', n=2607):
 *   - 32.3%  cost = null              → awaiting diagnosis
 *   - 26.0%  cost ∈ {290, 390}         → intake fee only (NOT the repair quote)
 *   - 41.7%  cost > 390                → actual repair quote
 *
 * Rule: the bot may expose `quoted` totals and acknowledge `intake_fee_only`
 * with explicit "cuota de ingreso" framing, but must never present
 * $290 / $390 as the repair cost. The `intake_fee_only` branch always
 * escalates `final_quote_request` so a human technician follows up.
 */

import type { ServiceOrderRowLike } from "./so-customer-view";

// =============================================================================
// Constants
// =============================================================================

/** Known intake-fee tiers at SimTech Polanco. Extend if ops confirms more. */
export const INTAKE_FEES = [290, 390] as const;
export type IntakeFeeAmount = (typeof INTAKE_FEES)[number];

/**
 * Token patterns in so_comment / remark that indicate the customer has
 * already settled payment. Must match case-insensitively.
 */
const PAID_TOKEN_RE = /pagad[oa]|paid|liquidad[oa]|saldado/i;

// =============================================================================
// Discriminated union
// =============================================================================

export type PricingState =
    | { kind: "in_warranty" }
    | { kind: "awaiting_diagnosis" }
    | { kind: "intake_fee_only"; feeMxn: IntakeFeeAmount }
    | { kind: "quoted"; totalMxn: number }
    | { kind: "unknown" };

// =============================================================================
// Classifier
// =============================================================================

/**
 * Determine the pricing state for a service order.
 *
 * Any cost-exposing renderer must branch on this before formatting.
 */
export function classifyPricingState(
    so: Pick<ServiceOrderRowLike, "warranty_type" | "estimated_cost_mxn">,
): PricingState {
    if (so.warranty_type === "I") return { kind: "in_warranty" };
    if (so.warranty_type !== "O") return { kind: "unknown" };

    const cost = so.estimated_cost_mxn;
    if (cost == null) return { kind: "awaiting_diagnosis" };

    // Narrow the type so TS knows the literal is one of the valid fees
    if (INTAKE_FEES.includes(cost as IntakeFeeAmount)) {
        return { kind: "intake_fee_only", feeMxn: cost as IntakeFeeAmount };
    }

    if (cost > 390) return { kind: "quoted", totalMxn: cost };

    // Values below 290 that are not 290/390 are anomalous — don't expose.
    return { kind: "unknown" };
}

// =============================================================================
// Payment-pending detector (D11, uses the classifier from D14)
// =============================================================================

/**
 * Detects the state where the AI cannot resolve the customer's ask without
 * human intervention: out-of-warranty, real repair quote known, sitting in
 * ST030 or ST035, but no evidence of payment in the so_comment / remark.
 *
 * NEVER fires on:
 *   - warranty='I' (in-warranty, no cost)
 *   - cost=null (diagnosis not complete)
 *   - cost ∈ {290, 390} (intake fee only; payment of the intake already happened)
 *   - any status outside {ST030, ST035}
 *   - any remark/so_comment matching pagado/paid/liquidado/saldado
 */
export function detectPaymentPending(
    so: Pick<
        ServiceOrderRowLike,
        "warranty_type" | "estimated_cost_mxn" | "status" | "so_comment" | "remark"
    >,
): boolean {
    const state = classifyPricingState(so);
    if (state.kind !== "quoted") return false;
    if (so.status !== "ST030" && so.status !== "ST035") return false;

    const haystack = `${so.so_comment ?? ""} ${so.remark ?? ""}`;
    if (PAID_TOKEN_RE.test(haystack)) return false;

    return true;
}

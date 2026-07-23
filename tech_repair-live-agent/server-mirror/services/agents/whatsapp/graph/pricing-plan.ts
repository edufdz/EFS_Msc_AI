/**
 * Pricing Plan Classifier
 * =======================
 * Pure function that maps a service order to a discriminated-union plan
 * describing what the caller should do — without producing any final text,
 * style-guide output, or intent tag.
 *
 * Why an ADT not a renderer: the same pricing-state logic is used by two
 * nodes (warranty_answer and pricing_answer), each with its own copy and
 * style-guide cap. A renderer with an `intent` parameter would fan that
 * complexity back into per-branch conditionals. This classifier stays
 * pure — callers own rendering, and the type signature makes it
 * impossible for this module to emit customer-facing text.
 *
 * Composition: paymentPendingEscalation (D11) runs first as a
 * short-circuit, then classifyPricingState (D14) resolves the remaining
 * variants. The `payment_pending` ordering is load-bearing and covered
 * by a dedicated unit test.
 */

import { classifyPricingState } from "@/shared/pricing-semantics";
import type { IntakeFeeAmount } from "@/shared/pricing-semantics";
import { paymentPendingEscalation } from "@/shared/payment-pending";
import type { EscalationReason } from "@/shared/escalation-reasons";
import type { ServiceOrderRowLike } from "@/shared/so-customer-view";

// =============================================================================
// Side-effect contract
// =============================================================================

export type PricingSideEffect = { kind: "register_cost_followup" };

// =============================================================================
// Plan ADT
// =============================================================================

export type PricingRenderPlan =
    | {
          kind: "reply";
          copyKey: "in_warranty";
          sideEffects: PricingSideEffect[];
      }
    | {
          kind: "reply";
          copyKey: "awaiting_diagnosis";
          sideEffects: PricingSideEffect[];
      }
    | {
          kind: "reply";
          copyKey: "unknown";
          sideEffects: PricingSideEffect[];
      }
    | {
          kind: "escalate";
          reason: Extract<EscalationReason, "final_quote_request">;
          copyKey: "intake_fee_only";
          feeMxn: IntakeFeeAmount;
      }
    | {
          kind: "escalate";
          reason: Extract<EscalationReason, "payment_pending">;
          copyKey: "quoted_payment_pending";
          totalMxn: number;
      }
    | {
          kind: "reply_with_amount";
          copyKey: "quoted";
          totalMxn: number;
          sideEffects: PricingSideEffect[];
      };

// =============================================================================
// Classifier
// =============================================================================

type PlannerInput = Pick<
    ServiceOrderRowLike,
    | "warranty_type"
    | "estimated_cost_mxn"
    | "status"
    | "so_comment"
    | "remark"
>;

export function planPricingResponse(so: PlannerInput): PricingRenderPlan {
    const paymentEsc = paymentPendingEscalation(so);
    if (paymentEsc) {
        const totalMxn = so.estimated_cost_mxn ?? 0;
        return {
            kind: "escalate",
            reason: paymentEsc.reason,
            copyKey: "quoted_payment_pending",
            totalMxn,
        };
    }

    const state = classifyPricingState(so);
    switch (state.kind) {
        case "in_warranty":
            return {
                kind: "reply",
                copyKey: "in_warranty",
                sideEffects: [],
            };
        case "awaiting_diagnosis":
            return {
                kind: "reply",
                copyKey: "awaiting_diagnosis",
                sideEffects: [{ kind: "register_cost_followup" }],
            };
        case "intake_fee_only":
            return {
                kind: "escalate",
                reason: "final_quote_request",
                copyKey: "intake_fee_only",
                feeMxn: state.feeMxn,
            };
        case "quoted":
            return {
                kind: "reply_with_amount",
                copyKey: "quoted",
                totalMxn: state.totalMxn,
                sideEffects: [],
            };
        case "unknown":
        default:
            return {
                kind: "reply",
                copyKey: "unknown",
                sideEffects: [],
            };
    }
}

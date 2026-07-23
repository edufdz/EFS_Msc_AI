/**
 * Payment-pending escalation helper (D11)
 * ======================================
 * Composes the D14 detector (`detectPaymentPending`) with the D13 taxonomy
 * and handoff copy so a node can ask "should I escalate for payment?" in
 * one call and get back either `null` (keep going) or the full artifact
 * it needs to return from the node function.
 *
 * Usage:
 *   const escalation = paymentPendingEscalation(so, { customerFirstName, svcOrderNo, register });
 *   if (escalation) {
 *       return {
 *           escalated: true,
 *           escalationReasonOverride: escalation.reason,
 *           escalatePriority: escalation.priority,
 *           responseText: escalation.replyText,
 *       };
 *   }
 */

import { detectPaymentPending } from "./pricing-semantics";
import {
    renderHandoff,
    priorityFor,
    type EscalationPriority,
    type EscalationReason,
    type HandoffContext,
} from "./escalation-reasons";
import type { ServiceOrderRowLike } from "./so-customer-view";

export interface PaymentPendingEscalation {
    reason: Extract<EscalationReason, "payment_pending">;
    priority: EscalationPriority;
    replyText: string;
}

/**
 * If the service order is in the payment-pending state per D14's detector,
 * return the escalation artifact (typed reason + priority + canned handoff
 * copy). Otherwise return null.
 */
export function paymentPendingEscalation(
    so: Pick<
        ServiceOrderRowLike,
        "warranty_type" | "estimated_cost_mxn" | "status" | "so_comment" | "remark"
    >,
    ctx: HandoffContext = {},
): PaymentPendingEscalation | null {
    if (!detectPaymentPending(so)) return null;
    return {
        reason: "payment_pending",
        priority: priorityFor("payment_pending"),
        replyText: renderHandoff("payment_pending", ctx),
    };
}

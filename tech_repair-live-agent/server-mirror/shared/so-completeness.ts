/**
 * SO Completeness Guard (D2)
 * ==========================
 * Replaces the legacy "Orden X sin datos completos (garantía: Y, costo:
 * sin dato). Se requiere revisión manual." escalation with a narrow rule
 * that only treats an SO as insufficient when BOTH identity AND phone are
 * missing. Missing diagnostic fields (IRIS codes, engineer_name, defect_desc)
 * are NEVER grounds for escalation.
 *
 * The literal "sin datos completos" emitter was already removed in
 * commit fb02145f; this guard enshrines the rule so a future deploy can't
 * regress it.
 *
 * Used by support.ts to gate the LLM's `[ESCALATE:MISSING_ORDER_DATA]`
 * marker: contact_sufficient / contact_only strip the marker, insufficient
 * escalates with the typed EscalationReason `so_record_missing_contact`.
 */

import type { ServiceOrderRowLike } from "./so-customer-view";

export type SOCompleteness =
    | "contact_sufficient"
    | "contact_only"
    | "insufficient";

/**
 * Classify the minimum-viable data state of a service order for the purpose
 * of deciding whether escalation on data grounds is warranted.
 *
 * - `contact_sufficient`: identity (svc_order_no + cust_name + any phone) AND
 *   repair context (warranty_type + status). Most common case; answer normally.
 * - `contact_only`: identity present, but warranty or status missing. Answer
 *   what we can, flag for a later GSPN resync — DO NOT escalate.
 * - `insufficient`: identity missing — the human queue needs to fix the
 *   underlying GSPN record. Escalate with `so_record_missing_contact`.
 */
export function assessSOCompleteness(
    so: Pick<
        ServiceOrderRowLike,
        | "svc_order_no"
        | "cust_name"
        | "contact_no"
        | "cust_mobile_phone"
        | "cust_home_phone"
        | "cust_office_phone"
        | "warranty_type"
        | "status"
    >,
): SOCompleteness {
    const hasContact = Boolean(
        so.svc_order_no &&
            so.cust_name &&
            (so.contact_no ||
                so.cust_mobile_phone ||
                so.cust_home_phone ||
                so.cust_office_phone),
    );
    const hasRepairContext = Boolean(so.warranty_type && so.status);

    if (hasContact && hasRepairContext) return "contact_sufficient";
    if (hasContact) return "contact_only";
    return "insufficient";
}

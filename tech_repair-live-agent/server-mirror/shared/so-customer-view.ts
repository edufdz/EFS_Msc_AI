/**
 * Service Order Customer View Projection
 * ======================================
 * Maps a raw service_orders row into a sanitized, customer-facing projection.
 * This is the ONLY layer that decides what a customer ever sees from an SO.
 *
 * Forbidden fields that must never be emitted (intentionally absent from
 * SOCustomerView): engineer_name, iris_*, repair_action_desc, defect_desc,
 * asc_job_no, imei, serial_no, raw model code, raw ST-codes.
 *
 * Why the shape exists at all: D4 of the Maria D2D plan. Pre-D4, the agent
 * interpolated raw SO rows into prompts and replies, leaking diagnostic
 * internals and sometimes creating the false-positive "sin datos completos"
 * escalation pattern. This projection is the source of truth for the
 * delivery-logistics, warranty-answer, and order-status response paths.
 */

// =============================================================================
// Input shape — accepts rows from supabase `service_orders` as well as the
// LangGraph ServiceOrderInfo shape. All fields are optional except the two
// required by SOCustomerView itself.
// =============================================================================

export interface ServiceOrderRowLike {
    svc_order_no: string;
    status: string;
    cust_name?: string | null;
    cust_mobile_phone?: string | null;
    cust_home_phone?: string | null;
    cust_office_phone?: string | null;
    contact_no?: string | null;
    warranty_type?: string | null;
    estimated_cost_mxn?: number | null;
    req_date?: string | Date | null;
    complete_date?: string | Date | null;
    delivery_date?: string | Date | null;
    last_synced_at?: string | Date | null;
    symptom_desc?: string | null;
    st_reason_desc?: string | null;
    model_name?: string | null;
    is_d2d?: boolean | null;
    service_type?: 'd2d' | 'carry_in' | 'other' | null;
    /** Technician comment text — used by pricing-semantics to detect paid tokens. */
    so_comment?: string | null;
    /** Free-form remark — may carry paid/saldado markers when finance applies a payment. */
    remark?: string | null;
}

// =============================================================================
// Output shape
// =============================================================================

export type WarrantyLabel = "En garantía" | "Fuera de garantía" | "Por confirmar";

export interface SOCustomerView {
    /** Canonical order number — always exposed. */
    svc_order_no: string;

    /** Customer name cleaned up (trimmed; "Cliente" fallback). */
    customer_name: string;

    /** Preferred phone in order: mobile → contact_no → home → office. Empty if none. */
    customer_contact: string;

    /** Humanized status (never raw ST-code). */
    human_status: string;

    /** Human-readable warranty. */
    warranty_label: WarrantyLabel;

    /** ISO date (YYYY-MM-DD) or null. */
    req_date: string | null;

    /** ISO date (YYYY-MM-DD) or null. */
    complete_date: string | null;

    /**
     * Cost exposure is RESTRICTED:
     * - warranty_type='I' → always null (in-warranty repairs are never charged)
     * - warranty_type='O' + intent in {pricing, warranty_question} → raw value
     * - everything else → null (caller must upgrade intent to see cost)
     *
     * Note: for D14 (intake-fee semantics), callers should also run
     * classifyPricingState on the raw row BEFORE deciding whether the
     * value here should actually be shown — $290/$390 are intake fees,
     * not repair quotes, and must never be presented as the repair cost.
     */
    estimated_cost_mxn: number | null;

    /**
     * Sanitized symptom description (codes stripped). Only populated when
     * opts.includeRepairReason is true — i.e. the customer explicitly asked
     * why the device is being repaired.
     */
    symptom_summary?: string;

    /** Customer-facing product name (model_name only, never model code). */
    device_name?: string;

    /** True if this SO uses door-to-door service. */
    is_d2d: boolean;

    /**
     * First-class pipeline discriminator. Set by the GSPN parser based on the
     * `asc_job_no` prefix — see `/SERVICE_TYPE_CLASSIFICATION.md` for the rule.
     * `'other'` covers TechRepair-internal channels (B2B / SES / RFA / etc.) and
     * orders without a work number assigned yet.
     */
    service_type: 'd2d' | 'carry_in' | 'other';
}

export interface ProjectOptions {
    /** Set when customer directly asks "por qué se reparó" / "qué le hicieron". */
    includeRepairReason?: boolean;

    /** Current intent string (e.g. "pricing", "warranty_question") — gates cost. */
    customerIntent?: string;
}

// =============================================================================
// Humanizers
// =============================================================================

/**
 * Map a TechRepair ST-code to its customer-facing Spanish phrase.
 *
 * Intentionally coarse: several ST-codes collapse onto the same phrase
 * because the customer doesn't need the distinction between e.g.
 * "Received" and "Center assigned".
 */
export function humanizeStatus(st: string | null | undefined): string {
    switch (st) {
        case "ST010":
        case "ST015":
            return "Recibido en el centro";
        case "ST020":
        case "ST025":
            return "En diagnóstico";
        case "ST030":
            return "En espera de refacciones";
        case "ST035":
            return "Reparación completada, en preparación para envío";
        case "ST040":
            return "Enviado";
        case "ST045":
            return "Devuelto";
        case "ST050":
            return "Entregado";
        case "ST055":
            return "Cerrado";
        case "ST060":
            return "Cambio físico";
        default:
            return "En proceso";
    }
}

export function humanizeWarranty(w: string | null | undefined): WarrantyLabel {
    if (w === "I") return "En garantía";
    if (w === "O") return "Fuera de garantía";
    return "Por confirmar";
}

/**
 * Spanish relative-time humanizer, e.g. "hace 2 horas".
 * Accepts an ISO string or Date; returns "hace un momento" for null/invalid.
 * `now` is injectable for deterministic tests.
 */
export function humanizeSyncAge(
    value: string | Date | null | undefined,
    now: Date = new Date(),
): string {
    if (!value) return "hace un momento";
    const then = value instanceof Date ? value : new Date(value);
    if (Number.isNaN(then.getTime())) return "hace un momento";

    const diffMs = Math.max(0, now.getTime() - then.getTime());
    const diffMin = Math.floor(diffMs / 60_000);
    if (diffMin < 1) return "hace un momento";
    if (diffMin < 60) return `hace ${diffMin} ${diffMin === 1 ? "minuto" : "minutos"}`;

    const diffHr = Math.floor(diffMin / 60);
    if (diffHr < 24) return `hace ${diffHr} ${diffHr === 1 ? "hora" : "horas"}`;

    const diffDay = Math.floor(diffHr / 24);
    return `hace ${diffDay} ${diffDay === 1 ? "día" : "días"}`;
}

// =============================================================================
// Helpers
// =============================================================================

function normalizePhone(so: ServiceOrderRowLike): string {
    return (
        so.cust_mobile_phone ||
        so.contact_no ||
        so.cust_home_phone ||
        so.cust_office_phone ||
        ""
    );
}

function normalizeDate(d: string | Date | null | undefined): string | null {
    if (!d) return null;
    const asDate = d instanceof Date ? d : new Date(d);
    if (Number.isNaN(asDate.getTime())) return null;
    return asDate.toISOString().slice(0, 10);
}

/**
 * Strip anything that looks like an internal code (IRIS, ST-codes, model codes,
 * parts numbers). Whitespace-normalized. Returns undefined when nothing
 * customer-facing remains.
 */
function sanitizeSymptom(text: string | null | undefined): string | undefined {
    if (!text) return undefined;
    const cleaned = text
        .replace(/\b(IRIS|ST0\d{2}|SM-[A-Z0-9]+|BN\d{2,}[-A-Z0-9]+)\b/gi, "")
        .replace(/\s+/g, " ")
        .trim();
    return cleaned || undefined;
}

// =============================================================================
// Projection
// =============================================================================

/**
 * Project a service order row into the customer-facing view.
 *
 * Cost rule: `estimated_cost_mxn` is null in the output unless the customer's
 * current intent is `pricing` or `warranty_question` AND the order is
 * out-of-warranty. In-warranty customers never see a cost number.
 *
 * IMPORTANT: this projection does NOT apply the intake-fee guardrail
 * ($290/$390 are diagnostic fees, not repair quotes). Callers that render
 * cost to the customer must additionally consult `classifyPricingState`
 * (D14) and route through the appropriate branch.
 */
export function projectForCustomer(
    so: ServiceOrderRowLike,
    opts: ProjectOptions = {},
): SOCustomerView {
    const { customerIntent, includeRepairReason } = opts;
    const isCostIntent =
        customerIntent === "pricing" || customerIntent === "warranty_question";
    const warrantyIsExternal = so.warranty_type === "O";

    const symptom = includeRepairReason
        ? sanitizeSymptom(so.symptom_desc) ?? sanitizeSymptom(so.st_reason_desc)
        : undefined;

    return {
        svc_order_no: so.svc_order_no,
        customer_name: (so.cust_name ?? "").trim() || "Cliente",
        customer_contact: normalizePhone(so),
        human_status: humanizeStatus(so.status),
        warranty_label: humanizeWarranty(so.warranty_type),
        req_date: normalizeDate(so.req_date),
        complete_date: normalizeDate(so.complete_date),
        estimated_cost_mxn:
            warrantyIsExternal && isCostIntent
                ? so.estimated_cost_mxn ?? null
                : null,
        symptom_summary: symptom,
        device_name: so.model_name ?? undefined,
        is_d2d: so.is_d2d === true,
        // service_type comes from the DB (populated by the GSPN parser per the
        // rule documented in /SERVICE_TYPE_CLASSIFICATION.md). Fallback is
        // 'other' — keeps callers that pre-date the column from being
        // wrong-classified as 'd2d' or 'carry_in'.
        service_type: so.service_type ?? 'other',
    };
}

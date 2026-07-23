/**
 * FAKE SHIM — Greeter Agent (types only)
 * ======================================
 * The production greeter is a LiveKit *voice* agent; the WhatsApp agent
 * only imports the `CustomerContext` type from it (used by the carry-in
 * prompt addendum). Both type definitions below are VERBATIM from
 * pulpoo-final (`services/agents/inbound/greeter-agent.ts` and
 * `services/agents/inbound/active-orders.ts`); the voice runtime class is
 * intentionally absent.
 */

export interface ActiveServiceOrder {
    svc_order_no: string;
    status: string;
    warranty_type: "I" | "O" | null;
    estimated_cost_mxn: number | null;
    model_name: string | null;
    service_type: "d2d" | "carry_in" | "other" | null;
    /** Customer name as it appears on the SO row — used for ambiguity check */
    cust_name: string | null;
}

export interface CustomerContext {
    name?: string;
    phone?: string;
    customerId?: string;
    interactionCount?: number;
    /** Formatted summary of past interactions for prompt injection */
    memorySummary?: string;
    // ─── CRM Fields (Task 2.1 & 2.2) ───
    /** Moving average (0-10) of customer frustration */
    frustrationIndex?: number;
    /** Most recent sentiment label */
    lastSentiment?: string;
    /** How the customer wants to be addressed */
    preferredName?: string;
    /** Preferred channel for follow-ups */
    preferredContactChannel?: "whatsapp" | "voice" | "any";
    /** TechRepair device model */
    primaryDeviceModel?: string;
    /** Known warranty status */
    warrantyStatus?: "active" | "expired" | "unknown";
    /** Customer escalation risk flag */
    escalationRisk?: boolean;
    /**
     * Open service orders matched to the caller's phone at session start.
     * Routing hint only — the StatusAgent still re-validates folios via
     * anti-fabrication gating before disclosing per-SO state.
     */
    activeOrders?: ActiveServiceOrder[];
}

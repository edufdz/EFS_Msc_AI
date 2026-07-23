/**
 * Lane-selector — shared types.
 *
 * The lane-selector resolves which pipeline (D2D or carry-in) an inbound
 * conversation, voice call, or sync write should be routed to. Its public
 * contract is the four-value `LaneDecision` and the `ResolvedLane` envelope.
 *
 * `service_type` on a candidate order has the four DB-level values
 * ('d2d' | 'carry_in' | 'other' | null) — see
 * `/SERVICE_TYPE_CLASSIFICATION.md`. The lane-selector reduces them to the
 * four routing decisions: 'd2d', 'carry_in', 'unknown', 'ambiguous'.
 */

export type LaneDecision = "d2d" | "carry_in" | "unknown" | "ambiguous";

/** A candidate service_order considered during lane resolution. */
export interface LaneCandidateOrder {
    svc_order_no: string;
    service_type: "d2d" | "carry_in" | "other" | null;
    status: string;
}

/** Outcome of a lane resolution call. Always logged to agent_thoughts. */
export interface ResolvedLane {
    /** The four-value decision. */
    decision: LaneDecision;
    /** Definitive pipeline match; NULL for unknown/ambiguous. */
    service_type: "d2d" | "carry_in" | null;
    /** Active service_orders considered (capped at LOOKUP_LIMIT). */
    candidate_orders: LaneCandidateOrder[];
    /** Short human-readable string, surfaced via agent_thoughts.metadata. */
    reasoning: string;
}

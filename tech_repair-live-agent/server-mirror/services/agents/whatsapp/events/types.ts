/**
 * Event Detection — Types
 * =======================
 * An extensible framework for spotting specific, business-critical customer
 * actions in a live WhatsApp turn (payment receipt sent, address mentioned,
 * order received, …). Each detector is a self-contained pluggable unit; adding
 * a new event = adding a new EventDetector to the registry.
 *
 * A detected event drives two things downstream (see escalation-on-event):
 *  - an immediate, TAGGED escalation so a human sees exactly what happened, and
 *  - an interaction_history row so the "Interactions" view can surface it.
 */

import type { WhatsAppStateType } from "@/services/agents/whatsapp/graph/state";

/** Closed set of detectable event kinds. Adding a detector = adding a member. */
export type EventType = "payment_receipt" | "address" | "order_received";

/** Address sub-type: an incidental mention vs an explicit change request. */
export type AddressSubType = "mencion" | "cambio_solicitado";

export interface EventDetectionContext {
    /** Current message text — for media this is the vision/PDF transcript. */
    message: string;
    /**
     * WhatsApp message type ('text' | 'image' | 'document' | 'audio' | …). Left
     * as an open string deliberately: detectors filter it (`!== 'text'`), the set
     * is the full WhatsApp surface, not just the three the detectors act on.
     */
    messageType: string;
    /** Full graph state (active orders, customer, history, etc.). */
    state: WhatsAppStateType;
}

export interface DetectedEvent {
    /** Machine type — a closed union so a typo can't silently miss a badge/dedup. */
    type: EventType;
    /** Human-readable headline for the asesor (becomes the escalation title). */
    label: string;
    /** Optional sub-type (only meaningful for `address`). */
    subType?: AddressSubType;
    /**
     * Structured detail (folio/monto, registered vs mentioned address, …). Still a
     * loose bag for now; TODO: discriminate on `type` once the raw_analysis payload
     * is promoted to a shared producer/consumer type (follow-up).
     */
    details: Record<string, unknown>;
    /**
     * Acuse to send the customer, or null/undefined to let the bot answer the
     * message normally (used for an incidental address mention). The bot NEVER
     * confirms an action it can't perform.
     */
    botReply?: string | null;
}

export interface EventDetector {
    /** Stable name for logs. */
    name: string;
    /** Return a DetectedEvent if this detector fires, else null. Must be safe. */
    detect(ctx: EventDetectionContext): Promise<DetectedEvent | null>;
}

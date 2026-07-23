/**
 * Memory Prompt Types
 * ===================
 * The contract consumed by `render-memory-block.ts` to produce the Spanish
 * "[Memoria del cliente]" prompt block.
 *
 * A resolver that populates this shape will be wired in a follow-up PR as a
 * thin projection over `getCustomerSnapshot()` (extracted from
 * `routes/customer-360.ts`). Keeping the types standalone means the
 * renderer + invariant/snapshot tests can ship today, and the resolver lands
 * atop a single source of truth once the customer-360 aggregate body is
 * factored out of its Hono route.
 */

import type { PreferredLanguage } from "@/shared/aggregate-preferred-language";

// ─── Source provenance ─────────────────────────────────────────────────────

export type NameSource =
    | "gspn_sync"        // most recent service_orders row for this phone
    | "customer_memory"  // customer_memory.name
    | "profile"          // WhatsApp conversation profile name
    | "gspn_live"        // live GSPN fetch (future)
    | "human";           // operator / AI-captured correction (future)

// 4-tier. `verified` is reserved for future human-source corrections.
export type NameConfidence = "verified" | "high" | "medium" | "low";

export type { PreferredLanguage };

export interface RecentSoReference {
    svc_order_no: string;
    last_referenced_at: string;
    hours_since_last_referenced: number;
    still_active_in_gspn: boolean;
    last_known_status: string | null;
    last_known_device_model: string | null;
}

/**
 * Curated, durable knowledge about the PERSON — sourced from the materialized
 * `customer_memory.dossier` (devices, NPS, derived signals) plus the latest
 * `memory_history` snapshot (communication_style, personal_context from the
 * extraction). Null when we know nothing durable yet. Surfaced by the renderer
 * as the "Lo que sabemos del cliente" section.
 */
export interface CustomerKnowledge {
    devices: string[];
    last_nps: number | null;
    is_detractor: boolean;
    recurring_issue: boolean;
    vip: boolean;
    communication_style: string | null;
    personal_context: string | null;
}

export interface ResolvedMemory {
    // Identity
    resolved_customer_name: string | null;
    name_source: NameSource | null;
    name_confidence: NameConfidence | null;

    // SO context carry-over (30-day reference window, max 5, newest-first)
    recent_so_references: RecentSoReference[];

    // Behavioral signals
    prior_escalations_30d: number;
    last_interaction_at: string | null;
    preferred_language: PreferredLanguage;
    frustration_index: number;
    escalation_risk: boolean;

    // Durable person knowledge (dossier + latest snapshot). Null = nothing known.
    customer_knowledge: CustomerKnowledge | null;
}

/**
 * Empty `ResolvedMemory` — used by the renderer's "cold customer" fixture
 * and as the default when no resolver is wired yet.
 */
export const EMPTY_RESOLVED_MEMORY: ResolvedMemory = {
    resolved_customer_name: null,
    name_source: null,
    name_confidence: null,
    recent_so_references: [],
    prior_escalations_30d: 0,
    last_interaction_at: null,
    preferred_language: null,
    frustration_index: 0,
    escalation_risk: false,
    customer_knowledge: null,
};

/**
 * Lane-selector — internal helpers.
 *
 * NOT exported from the barrel. The three router files
 * (conversation-router, voice-router, sync-router) are the public surface;
 * they delegate the decision logic + audit logging to these helpers.
 */

import type { SupabaseClient } from "@supabase/supabase-js";
import { TECH_REPAIR_SO_REGEX } from "@/shared/tech_repair-so";
import { expandPhoneVariants } from "@/shared/phone";
import type { LaneCandidateOrder, LaneDecision, ResolvedLane } from "./types";

/** Hard cap on candidate orders fetched per lookup. Prevents pathological per-customer scans. */
export const LOOKUP_LIMIT = 10;

/** Statuses we exclude from "active" service_orders when resolving the lane. */
const TERMINAL_STATUSES = ["ST055"]; // 'closed' — terminal

/** Where in the cascade a positive identification was made. Recorded in agent_thoughts.metadata.cascade_step. */
type CascadeStep =
    | "phone_link_cache" // hit the customer_phone_links table — fast path
    | "service_orders_by_phone" // standard lookup, works for D2D
    | "so_extracted_from_message" // fallback for carry-in first-message — extracted SO from text
    | "no_match"; // nothing identified the customer

/** Normalize any phone to its last 10 digits (Mexico tenant convention). */
export function normalizePhone(raw: string | null | undefined): string {
    if (!raw) return "";
    return String(raw).replace(/\D/g, "").slice(-10);
}

/**
 * Look up active service_orders for a normalized phone. Searches both
 * `contact_no` and `cust_mobile_phone` because the GSPN sync writes to
 * different columns depending on which TechRepair endpoint enriched the row.
 *
 * Returns an empty array if the phone can't be normalized to 10 digits or
 * if the query errors — caller treats either as 'unknown'.
 */
export async function lookupOrdersByPhone(
    rawPhone: string,
    supabase: SupabaseClient,
): Promise<LaneCandidateOrder[]> {
    const cleaned = normalizePhone(rawPhone);
    if (cleaned.length !== 10) return [];

    // Hit the generated last-10 columns (indexed in migration 0058) instead
    // of leading-`%` ilike on raw contact_no / cust_mobile_phone. The raw
    // columns drift between formats (E.164, parenthesized, dashed) — the
    // generated columns normalize to digits-only so an exact match is
    // both faster and more correct.
    const orFilter = [
        `contact_no_last10.eq.${cleaned}`,
        `cust_mobile_phone_last10.eq.${cleaned}`,
    ].join(",");

    const terminalList = `(${TERMINAL_STATUSES.map((s) => `"${s}"`).join(",")})`;

    const { data, error } = await supabase
        .from("service_orders")
        .select("svc_order_no, service_type, status")
        .or(orFilter)
        .not("status", "in", terminalList)
        .order("created_at", { ascending: false })
        .limit(LOOKUP_LIMIT);

    if (error) {
        console.error("[lane-selector] phone lookup error:", error.message);
        return [];
    }

    return (data ?? []) as LaneCandidateOrder[];
}

/**
 * Decide the lane from a list of candidate orders.
 *
 * **Critical default:** 'unknown' or 'ambiguous' results MUST NEVER silently
 * collapse to 'd2d' (or 'carry_in'). Caller branches at the call site.
 *
 * Rule (preserves the four-value contract from `types.ts`):
 *   - 0 orders                              → 'unknown'
 *   - All orders are 'other' or NULL        → 'unknown' (no pipeline applies)
 *   - 1+ orders 'd2d', 0 'carry_in'         → 'd2d'
 *   - 1+ orders 'carry_in', 0 'd2d'         → 'carry_in'
 *   - Both 'd2d' AND 'carry_in' present     → 'ambiguous'
 *
 * 'other' service_type orders are filtered out before computing the
 * type set — they're not pipeline candidates, so they don't influence
 * the decision (e.g., a B2B + a real D2D for the same customer → 'd2d',
 * not 'ambiguous').
 */
export function decideLane(orders: LaneCandidateOrder[]): LaneDecision {
    if (orders.length === 0) return "unknown";

    const types = new Set<"d2d" | "carry_in">();
    for (const order of orders) {
        if (order.service_type === "d2d" || order.service_type === "carry_in") {
            types.add(order.service_type);
        }
    }

    if (types.size === 0) return "unknown"; // all 'other' or NULL — no pipeline applies
    if (types.size === 1) {
        return types.has("d2d") ? "d2d" : "carry_in";
    }
    return "ambiguous";
}

/** Build a one-line reasoning string for agent_thoughts.metadata.reasoning. */
export function buildReasoning(
    decision: LaneDecision,
    orders: LaneCandidateOrder[],
    cascadeStep: CascadeStep = "no_match",
): string {
    const stepSuffix = cascadeStep === "no_match" ? "" : ` (via ${cascadeStep})`;
    if (orders.length === 0) {
        return "no active service_orders found for phone (cascade exhausted)";
    }
    if (decision === "ambiguous") {
        const types = orders.map((o) => o.service_type ?? "null").join(",");
        return `${orders.length} active orders span multiple pipelines: [${types}]${stepSuffix}`;
    }
    if (decision === "unknown") {
        const allOther = orders.every((o) => o.service_type === "other" || o.service_type === null);
        if (allOther) {
            return `${orders.length} active orders, none in a routed pipeline (all 'other' or NULL)${stepSuffix}`;
        }
        return `${orders.length} active orders but none classifiable${stepSuffix}`;
    }
    return `${orders.length} active order(s), all ${decision}${stepSuffix}`;
}

// =============================================================================
// Cascade lookups — phone↔SO identification with multiple fallbacks
// =============================================================================

/**
 * Step 1 of the cascade — look up the customer_phone_links cache.
 *
 * The lane-selector populates this table when it discovers a phone↔SO
 * association (typically from extracting an SO number from inbound message
 * text). Subsequent messages from the same phone hit this cache and skip
 * the slower fallbacks. Joined to service_orders so closed orders (ST055)
 * naturally drop out.
 */
export async function lookupKnownPhoneLink(
    rawPhone: string,
    supabase: SupabaseClient,
): Promise<LaneCandidateOrder[]> {
    const cleaned = normalizePhone(rawPhone);
    if (cleaned.length !== 10) return [];

    const terminalList = `(${TERMINAL_STATUSES.map((s) => `"${s}"`).join(",")})`;

    // Phones drift between bare 10-digit and E.164 across write sites.
    // `customer_phone_links.phone` is normalized to 10 digits at write
    // time today, but a single divergent writer (or a future migration
    // shift to E.164) would silently miss every cache hit. Match every
    // plausible variant defensively.
    const phoneVariants = expandPhoneVariants(cleaned);

    const { data, error } = await supabase
        .from("customer_phone_links")
        .select(
            "svc_order_no, service_type, service_orders!inner(status)",
        )
        .in("phone", phoneVariants)
        .not("service_orders.status", "in", terminalList)
        .order("learned_at", { ascending: false })
        .limit(LOOKUP_LIMIT);

    if (error) {
        console.error("[lane-selector] customer_phone_links lookup error:", error.message);
        return [];
    }

    return (data ?? []).map((row) => {
        const so = row as Record<string, unknown> & { service_orders?: { status?: string } };
        return {
            svc_order_no: so.svc_order_no as string,
            service_type: (so.service_type ?? null) as LaneCandidateOrder["service_type"],
            status: so.service_orders?.status ?? "",
        };
    });
}

/** Extract the first TechRepair SO number from a message body. Returns null if none found. */
export function extractSONumberFromText(text: string | null | undefined): string | null {
    if (!text) return null;
    const matches = text.match(TECH_REPAIR_SO_REGEX);
    return matches?.[0] ?? null;
}

/**
 * Step 3 of the cascade — look up a single service_order by svc_order_no
 * and return it as a LaneCandidateOrder if it's still active. Used when
 * the customer mentions an SO in their message text.
 */
export async function lookupOrderBySO(
    svcOrderNo: string,
    supabase: SupabaseClient,
): Promise<LaneCandidateOrder | null> {
    const terminalList = `(${TERMINAL_STATUSES.map((s) => `"${s}"`).join(",")})`;

    const { data, error } = await supabase
        .from("service_orders")
        .select("svc_order_no, service_type, status, id")
        .eq("svc_order_no", svcOrderNo)
        .not("status", "in", terminalList)
        .limit(1);

    if (error) {
        console.error("[lane-selector] svc_order_no lookup error:", error.message);
        return null;
    }
    if (!data || data.length === 0) return null;

    const row = data[0] as Record<string, unknown>;
    return {
        svc_order_no: row.svc_order_no as string,
        service_type: (row.service_type ?? null) as LaneCandidateOrder["service_type"],
        status: (row.status ?? "") as string,
    };
}

/**
 * Save a phone↔SO association so future messages from the same phone hit
 * the customer_phone_links cache (Step 1 of the cascade). Idempotent —
 * uses ON CONFLICT to avoid duplicate-key errors when the same link is
 * "discovered" multiple times.
 *
 * Failure to save does NOT fail the caller — losing one cache write is
 * better than failing to route a customer.
 */
export async function learnPhoneSOLink(
    phone: string,
    svcOrderNo: string,
    serviceType: "d2d" | "carry_in" | "other" | null,
    learnedVia: string,
    supabase: SupabaseClient,
): Promise<void> {
    const cleaned = normalizePhone(phone);
    if (cleaned.length !== 10 || !svcOrderNo) return;

    // Need the service_order_id (uuid) for the FK. One extra query, but
    // happens at most once per (phone, SO) pair.
    // maybeSingle: a typo'd SO (the expected case here, not an error) yields
    // null without throwing. `.single()` would have raised "expected single
    // row" on the typo path, which is the most-common code path through
    // this function during normal use.
    const { data: orderRow, error: lookupErr } = await supabase
        .from("service_orders")
        .select("id")
        .eq("svc_order_no", svcOrderNo)
        .maybeSingle();

    if (lookupErr) {
        console.error(
            `[lane-selector] learnPhoneSOLink: lookup error for ${svcOrderNo}:`,
            lookupErr.message,
        );
        return;
    }
    if (!orderRow) {
        // Typo or stale link — silently skip (no audit-row spam for a
        // routine miss).
        return;
    }

    const { error } = await supabase.from("customer_phone_links").upsert(
        {
            phone: cleaned,
            service_order_id: (orderRow as { id: string }).id,
            svc_order_no: svcOrderNo,
            service_type: serviceType,
            learned_via: learnedVia,
        },
        { onConflict: "phone,service_order_id", ignoreDuplicates: false },
    );

    if (error) {
        console.error("[lane-selector] learnPhoneSOLink upsert error:", error.message);
    }
}

/** Map a definitive decision to its service_type column value (NULL for unknown/ambiguous). */
export function decisionToServiceType(decision: LaneDecision): "d2d" | "carry_in" | null {
    return decision === "d2d" ? "d2d" : decision === "carry_in" ? "carry_in" : null;
}

/**
 * Generic agent_thoughts logger — usable from anywhere in the codebase
 * for any reasoning category. The lane-selector's `logLaneDecision`,
 * `logEscalationReason`, and `logMemoryRetrieval` are typed wrappers
 * around this primitive. Future thought categories (policy_skip,
 * warranty_decision, etc.) wrap the same primitive.
 *
 * Failure to log does NOT fail the caller — we'd rather act on the
 * decision without an audit trail than refuse to act because logging
 * is down. The error is console-logged for ops.
 */
export async function logAgentThought(
    supabase: SupabaseClient,
    args: {
        conversationId?: string | null;
        serviceType?: "d2d" | "carry_in" | "other" | null;
        thoughtType: string;
        metadata: Record<string, unknown>;
    },
): Promise<void> {
    const { error } = await supabase.from("agent_thoughts").insert({
        conversation_id: args.conversationId ?? null,
        service_type: args.serviceType ?? null,
        thought_type: args.thoughtType,
        metadata: args.metadata,
    });

    if (error) {
        console.error(
            `[agent_thoughts] failed to log thought_type='${args.thoughtType}':`,
            error.message,
        );
    }
}

/**
 * Typed wrapper for thought_type='lane_decision'. Used by the three lane
 * routers. Always sets `service_type` from the decision.
 */
export async function logLaneDecision(
    supabase: SupabaseClient,
    args: {
        conversationId?: string | null;
        decision: LaneDecision;
        candidateOrders: LaneCandidateOrder[];
        reasoning: string;
        phone?: string;
        source: "conversation" | "voice" | "sync";
        cascadeStep?: CascadeStep;
    },
): Promise<void> {
    await logAgentThought(supabase, {
        conversationId: args.conversationId,
        serviceType: decisionToServiceType(args.decision),
        thoughtType: "lane_decision",
        metadata: {
            decision: args.decision,
            candidate_orders: args.candidateOrders,
            reasoning: args.reasoning,
            source: args.source,
            ...(args.phone ? { phone: args.phone } : {}),
            ...(args.cascadeStep ? { cascade_step: args.cascadeStep } : {}),
        },
    });
}

/**
 * Typed wrapper for thought_type='escalation_reason'. Call from any place
 * that decides to hand a conversation to a human moderator. Captures the
 * trigger + the contextual reason so a reviewer can answer "why was this
 * escalated?" later.
 *
 * NOT yet wired into the existing escalation paths
 * (escalation-rules-engine.ts, escalation-scheduler.ts, etc.) — those
 * call sites get migrated to use this helper in a follow-up task.
 * Available now for any new code path that needs it.
 */
export async function logEscalationReason(
    supabase: SupabaseClient,
    args: {
        conversationId?: string | null;
        serviceType?: "d2d" | "carry_in" | "other" | null;
        /** Category of the escalation trigger (e.g. 'frustration_threshold_hit', 'sla_deadline_breach', 'explicit_human_request'). */
        trigger: string;
        /** One-line human-readable explanation for ops review. */
        reason: string;
        /** Anything else worth pinning for debugging — frustration index, SO number, message text, etc. */
        context?: Record<string, unknown>;
    },
): Promise<void> {
    await logAgentThought(supabase, {
        conversationId: args.conversationId,
        serviceType: args.serviceType,
        thoughtType: "escalation_reason",
        metadata: {
            trigger: args.trigger,
            reason: args.reason,
            ...(args.context ?? {}),
        },
    });
}

/**
 * Typed wrapper for thought_type='memory_retrieval'. Call from any place
 * that consults the customer memory store (CRM, prior conversations,
 * preferences, etc.) to record what was queried and what came back.
 *
 * Useful for debugging conversations where the agent appeared to ignore
 * customer context: was memory queried at all? What was found / not found?
 *
 * NOT yet wired into the existing memory paths — available for new code.
 */
export async function logMemoryRetrieval(
    supabase: SupabaseClient,
    args: {
        conversationId?: string | null;
        serviceType?: "d2d" | "carry_in" | "other" | null;
        /** Identifier(s) used to find the customer (phone, email, conversation_id, etc.). */
        lookupKeys: Record<string, unknown>;
        /** Categories or queries that were executed against the memory store. */
        queriesExecuted: string[];
        /** Number of facts/rows that came back. */
        resultsFound: number;
        /** The actual facts that came back (kept short — full payload doesn't belong here). */
        factsRetrieved?: string[];
        /** Categories that were queried but produced no results — useful for debugging memory gaps. */
        factsNotFound?: string[];
        /** Why the memory was consulted at this point. */
        reason: string;
    },
): Promise<void> {
    await logAgentThought(supabase, {
        conversationId: args.conversationId,
        serviceType: args.serviceType,
        thoughtType: "memory_retrieval",
        metadata: {
            lookup_keys: args.lookupKeys,
            queries_executed: args.queriesExecuted,
            results_found: args.resultsFound,
            ...(args.factsRetrieved ? { facts_retrieved: args.factsRetrieved } : {}),
            ...(args.factsNotFound ? { facts_NOT_found: args.factsNotFound } : {}),
            reason: args.reason,
        },
    });
}

/**
 * Compose the full resolution pipeline used by both conversation-router
 * and voice-router. Runs a 3-step cascade:
 *
 *   1. customer_phone_links cache (fast — known links from past interactions)
 *   2. service_orders by phone   (works for D2D — TechRepair captures phone there)
 *   3. extract SO from messageText (only if provided — fallback for carry-in
 *      first-message customers; learns the link for next time)
 *
 * Voice callers don't have message text, so step 3 is skipped — voice
 * always relies on cache + service_orders. The fallback only fires for
 * conversation-router calls where messageText is supplied.
 */
export async function resolveByPhone(
    phone: string,
    supabase: SupabaseClient,
    source: "conversation" | "voice",
    conversationId: string | null = null,
    messageText: string | null = null,
): Promise<ResolvedLane> {
    let candidate_orders: LaneCandidateOrder[] = [];
    let cascadeStep: CascadeStep = "no_match";

    // Step 1 — known phone↔SO link cache.
    candidate_orders = await lookupKnownPhoneLink(phone, supabase);
    if (candidate_orders.length > 0) cascadeStep = "phone_link_cache";

    // Step 2 — standard service_orders lookup (D2D customers).
    if (candidate_orders.length === 0) {
        candidate_orders = await lookupOrdersByPhone(phone, supabase);
        if (candidate_orders.length > 0) cascadeStep = "service_orders_by_phone";
    }

    // Step 3 — extract SO from inbound message text (carry-in first-message
    // path). Only meaningful for conversation-router. If we find one, learn
    // the link so step 1 short-circuits next time.
    if (candidate_orders.length === 0 && messageText) {
        const extractedSO = extractSONumberFromText(messageText);
        if (extractedSO) {
            const order = await lookupOrderBySO(extractedSO, supabase);
            if (order) {
                candidate_orders = [order];
                cascadeStep = "so_extracted_from_message";
                // Fire-and-forget: learn the association for next time.
                await learnPhoneSOLink(phone, order.svc_order_no, order.service_type, "so_in_message", supabase);
            }
        }
    }

    const decision = decideLane(candidate_orders);
    const reasoning = buildReasoning(decision, candidate_orders, cascadeStep);

    await logLaneDecision(supabase, {
        conversationId,
        decision,
        candidateOrders: candidate_orders,
        reasoning,
        phone,
        source,
        cascadeStep,
    });

    return {
        decision,
        service_type: decisionToServiceType(decision),
        candidate_orders,
        reasoning,
    };
}

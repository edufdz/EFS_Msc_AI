/**
 * Service Status Policy — shared lookup + cache.
 *
 * Reads the `service_status_policy` table (created in W1 Task 8 migration
 * 0056) and exposes a typed accessor that pipelines and workers consult
 * before taking customer-facing actions (outbound calls, proactive
 * WhatsApp sends, status disclosure).
 *
 * Pipeline modules (`pipelines/d2d/policy.ts`, `pipelines/carry-in/policy.ts`)
 * are thin wrappers that fix `serviceType` and delegate here. The shared
 * cache + translation logic lives in this single file so the pipelines
 * never duplicate or drift.
 *
 * Lint note: `shared/` cannot import from `pipelines/` (W1 Task 4 lint
 * rule), but `pipelines/` CAN import from `shared/`. That's the
 * direction we use.
 */

import type { SupabaseClient } from "@supabase/supabase-js";

export interface ServicePolicy {
    outbound_call_permitted: boolean;
    proactive_status_disclosure: boolean;
    whatsapp_proactive_send_permitted: boolean;
}

/**
 * Default policy when a (service_type, state) pair has no row in the
 * table. Permissive — preserves existing behavior for any state we
 * haven't catalogued yet. Restricting requires an explicit INSERT.
 */
export const DEFAULT_POLICY: ServicePolicy = {
    outbound_call_permitted: true,
    proactive_status_disclosure: true,
    whatsapp_proactive_send_permitted: true,
};

/**
 * Translate a TechRepair GSPN status code (e.g. 'ST040') to a semantic
 * state name (e.g. 'shipped' or 'ready_for_pickup'). Most ST-codes map
 * to the same state across pipelines; ST040 is the notable split (D2D
 * 'shipped' vs carry-in 'ready_for_pickup').
 *
 * If the input doesn't match a known ST-code, it's returned unchanged
 * — assume the caller already passed a state name.
 */
export function translateStatusToState(
    serviceType: "d2d" | "carry_in" | "other",
    status: string | null | undefined,
): string {
    if (!status) return "unknown";

    // Pipeline-independent mappings
    switch (status) {
        case "ST010":
        case "ST015":
            return "received";
        case "ST020":
        case "ST025":
            return "in_diagnosis";
        case "ST030":
            return "awaiting_parts";
        case "ST050":
            return "delivered";
        case "ST055":
            return "closed";
        case "ST060":
            // TechRepair GSPN ST060 is "physical exchange complete" — the
            // device has been returned to the customer. Semantically
            // equivalent to 'delivered' for policy purposes (it IS the
            // final transfer of the device back to the customer). No
            // separate 'physical_exchange' state is seeded in the
            // policy table; mapping ST060 to its own state name would
            // fall through DEFAULT_POLICY (permit-all), which is
            // exactly the silent-permit-all bug we want to avoid.
            return "delivered";
    }

    // Pipeline-specific: ST040 means different things per pipeline.
    if (status === "ST040") {
        return serviceType === "d2d" ? "shipped" : "ready_for_pickup";
    }

    // An ST-shaped input not in any switch above is a new GSPN code we
    // haven't mapped — surface it in logs so the gap is visible.
    // The fallthrough still passes the value through unchanged so
    // policy lookup uses DEFAULT_POLICY, but at least the warning
    // tells us why we keep seeing permit-all for the new code.
    if (/^ST\d{3}$/.test(status)) {
        console.warn(
            `[service-status-policy] unmapped GSPN status code: ${status} (service_type=${serviceType})`,
        );
    }

    // Caller may have passed a semantic name already (e.g., from tests
    // or from code that already translated). Return as-is.
    return status;
}

// =============================================================================
// In-memory cache
// =============================================================================

interface CacheEntry {
    map: Map<string, ServicePolicy>;
    loadedAt: number;
}

const CACHE_TTL_MS = 60_000; // 60s — table is small and changes manually
const cacheByServiceType = new Map<string, CacheEntry>();

async function loadPolicies(
    serviceType: "d2d" | "carry_in" | "other",
    supabase: SupabaseClient,
): Promise<Map<string, ServicePolicy>> {
    const cached = cacheByServiceType.get(serviceType);
    if (cached && Date.now() - cached.loadedAt < CACHE_TTL_MS) {
        return cached.map;
    }

    const { data, error } = await supabase
        .from("service_status_policy")
        .select(
            "state, outbound_call_permitted, proactive_status_disclosure, whatsapp_proactive_send_permitted",
        )
        .eq("service_type", serviceType);

    if (error) {
        console.error(
            `[service-status-policy] Failed to load ${serviceType} policies:`,
            error.message,
        );
        // Stale-cache fallback: previously-loaded policy still beats
        // nothing. But cold-cache + load error would silently fall
        // through to DEFAULT_POLICY (permit-all) on every subsequent
        // lookup until the next refresh — defeats the gate. Throw so
        // the caller's audit (`lookup_failed_default_permissive`)
        // actually records what happened.
        if (cached?.map) return cached.map;
        throw new Error(
            `service-status-policy: cold-cache load failed for ${serviceType}: ${error.message}`,
        );
    }

    const map = new Map<string, ServicePolicy>();
    for (const row of (data ?? []) as Array<
        ServicePolicy & { state: string }
    >) {
        map.set(row.state, {
            outbound_call_permitted: row.outbound_call_permitted,
            proactive_status_disclosure: row.proactive_status_disclosure,
            whatsapp_proactive_send_permitted: row.whatsapp_proactive_send_permitted,
        });
    }
    cacheByServiceType.set(serviceType, { map, loadedAt: Date.now() });
    return map;
}

/** Force-clear the cache. Useful for tests or after a manual policy UPDATE. */
export function clearPolicyCache(): void {
    cacheByServiceType.clear();
}

// =============================================================================
// Public lookup
// =============================================================================

/**
 * Look up the policy for a (serviceType, status-or-state) pair. Accepts
 * either a TechRepair ST-code (translated internally) or a semantic state
 * name. Returns DEFAULT_POLICY if no row matches — permissive default
 * preserves current behavior for unenumerated states.
 */
export async function getPolicyForServiceType(
    serviceType: "d2d" | "carry_in" | "other",
    statusOrState: string | null | undefined,
    supabase: SupabaseClient,
): Promise<ServicePolicy> {
    const state = translateStatusToState(serviceType, statusOrState);
    const policies = await loadPolicies(serviceType, supabase);
    return policies.get(state) ?? DEFAULT_POLICY;
}

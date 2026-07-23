/**
 * App Config — DB-backed Feature Flags
 * =====================================
 * Reads configuration from the `app_config` Supabase table with a 30-second
 * in-memory cache. Allows zero-downtime toggling of feature flags without
 * restarting the service (important because restarts kill active voice calls
 * and drop in-progress WhatsApp conversations).
 *
 * Usage:
 *   const enabled = await getAppConfig("memory_enhanced_prompts", true);
 */

import { getSupabaseClient } from "./supabase";

// =============================================================================
// Cache
// =============================================================================

const CACHE_TTL_MS = 30_000; // 30 seconds

interface CacheEntry {
    value: unknown;
    fetchedAt: number;
}

const cache = new Map<string, CacheEntry>();

// =============================================================================
// Public API
// =============================================================================

/**
 * Get a config value from the `app_config` table.
 *
 * Returns the cached value if fresh (<30s old), otherwise fetches from DB.
 * On error (DB down, table missing), returns `defaultValue` — never throws.
 *
 * @param key          The config key (e.g., "memory_enhanced_prompts")
 * @param defaultValue Fallback when key is missing or on error
 */
export async function getAppConfig<T = unknown>(
    key: string,
    defaultValue: T,
): Promise<T> {
    const now = Date.now();
    const cached = cache.get(key);

    if (cached && now - cached.fetchedAt < CACHE_TTL_MS) {
        return cached.value as T;
    }

    try {
        const client = getSupabaseClient();
        if (!client) return defaultValue;

        const { data, error } = await client
            .from("app_config")
            .select("value")
            .eq("key", key)
            .maybeSingle();

        if (error || !data) {
            // Cache the default to avoid hammering DB on missing keys
            cache.set(key, { value: defaultValue, fetchedAt: now });
            return defaultValue;
        }

        const value = data.value as T;
        cache.set(key, { value, fetchedAt: now });
        return value;
    } catch {
        // Non-fatal: return default on any error
        return defaultValue;
    }
}

/**
 * Convenience: check if the memory enhancement feature flag is enabled.
 * Defaults to `true` so new deployments get the enhanced behavior.
 */
export async function isMemoryEnhancedPromptsEnabled(): Promise<boolean> {
    return getAppConfig<boolean>("memory_enhanced_prompts", true);
}

/**
 * Convenience: check if the background memory sweep is enabled. Defaults to
 * `true` so it keeps running as today, but gives ops a redeploy-free kill switch
 * (the sweep incurs an LLM call per processed conversation). Set the `app_config`
 * row `memory_sweep_enabled` to `false` to pause it within the 30s cache TTL.
 */
export async function isMemorySweepEnabled(): Promise<boolean> {
    return getAppConfig<boolean>("memory_sweep_enabled", true);
}

/**
 * Invalidate a cached config entry (for testing).
 */
export function _invalidateConfigCache(key?: string): void {
    if (key) {
        cache.delete(key);
    } else {
        cache.clear();
    }
}

/**
 * FAKE SHIM — Dynamic Agent Configuration Loader
 * ==============================================
 * Verbatim logic from the production module for `loadAgentConfig` and
 * `loadAllInboundConfigs` (they read the `agent_configurations` table via
 * the injected Supabase client — which in the simulation is the fake DB).
 * The only removal is `buildAgentTTS`, which depended on @livekit/agents
 * (voice-only; never used by the WhatsApp agent).
 */

import { getSupabaseClient } from "@/shared/supabase";

// =============================================================================
// TYPES
// =============================================================================

export interface DynamicAgentConfig {
    system_prompt?: string | null;
    prompts?: Record<string, string> | null;
    llm_provider?: string;
    llm_model?: string;
    llm_temperature?: number;
    stt_provider?: string;
    stt_model?: string;
    stt_language?: string;
    tts_provider?: string;
    tts_model?: string;
    tts_voice_id?: string;
    tts_voice_speed?: number;
    tts_language?: string;
    agent_name?: string;
    max_response_length?: number;
    escalation_threshold?: number;
    batch_delay_ms?: number;
    auto_return_timeout_minutes?: number | null;
    auto_return_silent_cleanup_hours?: number | null;
    pipeline_mode?: 'modular' | 'realtime';
    realtime_model?: string;
    realtime_voice?: string;
    max_concurrent_calls?: number;
    extra_config?: Record<string, unknown> | null;
}

// =============================================================================
// LOADERS (with TTL cache)
// =============================================================================

const CONFIG_CACHE_TTL_MS = 60_000; // 60 seconds
const _configCache = new Map<string, { data: DynamicAgentConfig | null; ts: number }>();

/**
 * Load configuration for a single agent by ID.
 * Results are cached in-memory for 60 seconds to avoid a DB query per message.
 * Returns null if DB is unavailable or no config row exists.
 */
export async function loadAgentConfig(
    agentId: string
): Promise<DynamicAgentConfig | null> {
    // Return cached value if fresh
    const cached = _configCache.get(agentId);
    if (cached && Date.now() - cached.ts < CONFIG_CACHE_TTL_MS) {
        return cached.data;
    }

    try {
        const client = getSupabaseClient();
        if (!client) {
            console.warn("[DynamicConfig] Supabase client not available, using defaults");
            return cached?.data ?? null;
        }

        const { data, error } = await client
            .from("agent_configurations")
            .select(
                "system_prompt, prompts, llm_provider, llm_model, llm_temperature, " +
                "stt_provider, stt_model, stt_language, " +
                "tts_provider, tts_model, tts_voice_id, tts_voice_speed, tts_language, " +
                "agent_name, max_response_length, escalation_threshold, batch_delay_ms, " +
                "auto_return_timeout_minutes, auto_return_silent_cleanup_hours, " +
                "pipeline_mode, realtime_model, realtime_voice, max_concurrent_calls, " +
                "extra_config"
            )
            .eq("agent_id", agentId)
            .maybeSingle();

        if (error) {
            console.warn(`[DynamicConfig] Query failed for ${agentId}:`, error.message);
            return cached?.data ?? null;
        }

        const result = data as DynamicAgentConfig | null;
        _configCache.set(agentId, { data: result, ts: Date.now() });
        return result;
    } catch (err) {
        console.warn("[DynamicConfig] Failed to load config:", err);
        return cached?.data ?? null;
    }
}

/**
 * Load configs for all inbound agents in a single query.
 * Returns a Map keyed by agent_id (e.g. 'greeter', 'status', 'pricing').
 */
export async function loadAllInboundConfigs(): Promise<Map<string, DynamicAgentConfig>> {
    const configs = new Map<string, DynamicAgentConfig>();

    try {
        const client = getSupabaseClient();
        if (!client) {
            console.warn("[DynamicConfig] Supabase client not available, using defaults");
            return configs;
        }

        const { data, error } = await client
            .from("agent_configurations")
            .select(
                "agent_id, system_prompt, prompts, llm_provider, llm_model, llm_temperature, " +
                "stt_provider, stt_model, stt_language, " +
                "tts_provider, tts_model, tts_voice_id, tts_voice_speed, tts_language, " +
                "agent_name, max_response_length, escalation_threshold, batch_delay_ms, " +
                "auto_return_timeout_minutes, auto_return_silent_cleanup_hours, " +
                "pipeline_mode, realtime_model, realtime_voice, max_concurrent_calls, " +
                "extra_config"
            )
            .in("agent_id", ["greeter", "status", "pricing"]);

        if (error) {
            console.warn("[DynamicConfig] Batch query failed:", error.message);
            return configs;
        }

        if (data) {
            for (const row of (data as unknown as Record<string, unknown>[])) {
                const agentId = row.agent_id as string;
                const { agent_id: _, ...config } = row;
                configs.set(agentId, config as DynamicAgentConfig);
            }
        }

        console.log(`[DynamicConfig] Loaded ${configs.size} inbound config(s)`);
        return configs;
    } catch (err) {
        console.warn("[DynamicConfig] Failed to load inbound configs:", err);
        return configs;
    }
}

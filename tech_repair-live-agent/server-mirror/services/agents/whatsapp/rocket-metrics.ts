/**
 * ROCKET Metrics
 * ==============
 * Fire-and-forget metric emission to rocket_metrics Supabase table.
 */

import { getSupabaseClient } from "@/shared/supabase";

export interface RocketMetric {
    conversationId?: string;
    phone?: string;
    laneId: 1 | 2;
    modelUsed: string;
    intent?: string;
    cacheHit: boolean;
    cacheReadTokens: number;
    cacheWriteTokens: number;
    totalTokens: number;
    latencyMs: number;
    escalatedLane: boolean;
}

/**
 * Emit a ROCKET metric to the rocket_metrics table.
 * Fire-and-forget — errors are swallowed.
 */
export function emitRocketMetric(metric: RocketMetric): void {
    const supabase = getSupabaseClient();
    if (!supabase) return;

    // [sim] Promise.resolve wrap: type-only (.catch on PromiseLike), behavior unchanged
    Promise.resolve(supabase
        .from("rocket_metrics")
        .insert({
            conversation_id: metric.conversationId ?? null,
            phone: metric.phone ?? null,
            lane_id: metric.laneId,
            model_used: metric.modelUsed,
            intent: metric.intent ?? null,
            cache_hit: metric.cacheHit,
            cache_read_tokens: metric.cacheReadTokens,
            cache_write_tokens: metric.cacheWriteTokens,
            total_tokens: metric.totalTokens,
            latency_ms: metric.latencyMs,
            escalated_lane: metric.escalatedLane,
        }))
        .then(({ error }) => {
            if (error) {
                console.warn("[rocket-metrics] Insert failed (non-fatal):", error.message);
            }
        })
        .catch(() => {/* non-fatal */});
}

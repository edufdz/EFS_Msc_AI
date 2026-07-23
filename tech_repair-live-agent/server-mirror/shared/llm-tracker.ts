/**
 * Unified LLM Usage Tracker
 * =========================
 * Callback-based approach: attach a UsageTrackingHandler at model creation
 * via createTrackedLLM(). Every .invoke() is automatically tracked.
 *
 * Also exports trackLLMUsage() for the WhatsApp agent dual-write path,
 * where tokens come from the graph state rather than a callback.
 */

import { BaseCallbackHandler } from "@langchain/core/callbacks/base";
import type { LLMResult } from "@langchain/core/outputs";
import { getSupabaseClient } from "./supabase";
import {
    OPENAI_LLM_PRICING,
    ANTHROPIC_LLM_PRICING,
    GOOGLE_LLM_PRICING,
} from "@/data/pricing-reference";

// =============================================================================
// Types
// =============================================================================

type Provider = "openai" | "anthropic" | "google";

interface TokenCounts {
    inputTokens: number;
    outputTokens: number;
    cacheReadTokens: number;
    cacheWriteTokens: number;
}

export interface CreateTrackedLLMOptions {
    provider: Provider;
    model: string;
    callSite: string;
    context?: { conversationId?: string; phone?: string };
    temperature?: number;
    maxTokens?: number;
    /** Extra LLM constructor options (e.g. anthropicApiKey) */
    extras?: Record<string, unknown>;
}

// =============================================================================
// Callback Handler
// =============================================================================

class UsageTrackingHandler extends BaseCallbackHandler {
    name = "usage_tracking";
    private startMs = 0;

    constructor(
        private callSite: string,
        private provider: Provider,
        private model: string,
        private ctx?: { conversationId?: string; phone?: string },
    ) {
        super();
    }

    handleLLMStart(): void {
        this.startMs = Date.now();
    }

    handleLLMEnd(output: LLMResult): void {
        const latencyMs = Date.now() - this.startMs;

        // Extract tokens from LLMResult.llmOutput (provider-specific)
        const tokens = this.provider === "anthropic"
            ? extractAnthropicTokens(output)
            : extractOpenAITokens(output);

        insertUsageRow({
            callSite: this.callSite,
            model: this.model,
            provider: this.provider,
            conversationId: this.ctx?.conversationId,
            phone: this.ctx?.phone,
            tokens,
            latencyMs,
        });
    }
}

// =============================================================================
// Token Extraction (from LLMResult)
// =============================================================================

function extractOpenAITokens(output: LLMResult): TokenCounts {
    const u = output.llmOutput?.tokenUsage as Record<string, number> | undefined;
    if (u) {
        return {
            inputTokens: u.promptTokens ?? 0,
            outputTokens: u.completionTokens ?? 0,
            cacheReadTokens: 0,
            cacheWriteTokens: 0,
        };
    }
    // Fallback: check first generation's message response_metadata
    const msg = (output.generations?.[0]?.[0] as any)?.message;
    const meta = msg?.response_metadata?.tokenUsage ?? msg?.usage_metadata;
    if (meta) {
        return {
            inputTokens: meta.promptTokens ?? meta.input_tokens ?? 0,
            outputTokens: meta.completionTokens ?? meta.output_tokens ?? 0,
            cacheReadTokens: 0,
            cacheWriteTokens: 0,
        };
    }
    return { inputTokens: 0, outputTokens: 0, cacheReadTokens: 0, cacheWriteTokens: 0 };
}

function extractAnthropicTokens(output: LLMResult): TokenCounts {
    // Anthropic puts usage in llmOutput
    const u = output.llmOutput?.usage as Record<string, number> | undefined;
    if (u) {
        return {
            inputTokens: u.input_tokens ?? 0,
            outputTokens: u.output_tokens ?? 0,
            cacheReadTokens: u.cache_read_input_tokens ?? 0,
            cacheWriteTokens: u.cache_creation_input_tokens ?? 0,
        };
    }
    // Fallback: check first generation's message
    const msg = (output.generations?.[0]?.[0] as any)?.message;
    const usage = msg?.response_metadata?.usage;
    if (usage) {
        return {
            inputTokens: usage.input_tokens ?? 0,
            outputTokens: usage.output_tokens ?? 0,
            cacheReadTokens: usage.cache_read_input_tokens ?? 0,
            cacheWriteTokens: usage.cache_creation_input_tokens ?? 0,
        };
    }
    return { inputTokens: 0, outputTokens: 0, cacheReadTokens: 0, cacheWriteTokens: 0 };
}

// =============================================================================
// Cost Computation
// =============================================================================

function computeCost(model: string, provider: string, tokens: TokenCounts): number {
    if (provider === "anthropic") {
        const pricing = ANTHROPIC_LLM_PRICING[model];
        if (!pricing) return 0;
        return (
            (tokens.inputTokens * pricing.input) / 1_000_000 +
            (tokens.outputTokens * pricing.output) / 1_000_000 +
            (pricing.cacheRead ? (tokens.cacheReadTokens * pricing.cacheRead) / 1_000_000 : 0) +
            (pricing.cacheWrite ? (tokens.cacheWriteTokens * pricing.cacheWrite) / 1_000_000 : 0)
        );
    }
    if (provider === "openai") {
        const pricing = OPENAI_LLM_PRICING[model];
        if (!pricing) return 0;
        return (
            (tokens.inputTokens * pricing.input) / 1_000_000 +
            (tokens.outputTokens * pricing.output) / 1_000_000
        );
    }
    if (provider === "google") {
        const pricing = GOOGLE_LLM_PRICING[model];
        if (!pricing) return 0;
        return (
            (tokens.inputTokens * pricing.input) / 1_000_000 +
            (tokens.outputTokens * pricing.output) / 1_000_000
        );
    }
    return 0;
}

// =============================================================================
// DB Insert (fire-and-forget)
// =============================================================================

function insertUsageRow(params: {
    callSite: string;
    model: string;
    provider: Provider;
    conversationId?: string;
    phone?: string;
    tokens: TokenCounts;
    latencyMs?: number;
}): void {
    const supabase = getSupabaseClient();
    if (!supabase) return;

    const costUsd = computeCost(params.model, params.provider, params.tokens);

    // [sim] Promise.resolve wrap: type-only (.catch on PromiseLike), behavior unchanged
    Promise.resolve(supabase
        .from("llm_usage")
        .insert({
            call_site: params.callSite,
            conversation_id: params.conversationId ?? null,
            phone: params.phone ?? null,
            provider: params.provider,
            model: params.model,
            input_tokens: params.tokens.inputTokens,
            output_tokens: params.tokens.outputTokens,
            cache_read_tokens: params.tokens.cacheReadTokens,
            cache_write_tokens: params.tokens.cacheWriteTokens,
            cost_usd: costUsd,
            latency_ms: params.latencyMs ?? null,
        }))
        .then(({ error }) => {
            if (error) console.warn("[llm-tracker] Insert failed (non-fatal):", error.message);
        })
        .catch(() => {/* non-fatal */});
}

// =============================================================================
// Factory: createTrackedLLM
// =============================================================================

/**
 * Create a ChatOpenAI or ChatAnthropic instance with automatic usage tracking.
 * Every .invoke() / .withStructuredOutput().invoke() is tracked via callbacks.
 */
export async function createTrackedLLM(opts: CreateTrackedLLMOptions) {
    const handler = new UsageTrackingHandler(opts.callSite, opts.provider, opts.model, opts.context);

    if (opts.provider === "anthropic") {
        const { ChatAnthropic } = await import("@langchain/anthropic");
        return new ChatAnthropic({
            model: opts.model,
            temperature: opts.temperature ?? 0,
            maxTokens: opts.maxTokens,
            callbacks: [handler],
            ...opts.extras,
        });
    }

    const { ChatOpenAI } = await import("@langchain/openai");
    return new ChatOpenAI({
        modelName: opts.model,
        temperature: opts.temperature ?? 0,
        callbacks: [handler],
        ...opts.extras,
    });
}

// =============================================================================
// Manual tracker (for WhatsApp agent dual-write where tokens come from state)
// =============================================================================

/**
 * Track LLM usage manually — fire-and-forget.
 * Used when tokens are already extracted (e.g. WhatsApp agent graph state).
 */
export function trackLLMUsage(params: {
    callSite: string;
    model: string;
    provider: Provider;
    conversationId?: string;
    phone?: string;
    latencyMs?: number;
    inputTokens?: number;
    outputTokens?: number;
    cacheReadTokens?: number;
    cacheWriteTokens?: number;
}): void {
    insertUsageRow({
        callSite: params.callSite,
        model: params.model,
        provider: params.provider,
        conversationId: params.conversationId,
        phone: params.phone,
        tokens: {
            inputTokens: params.inputTokens ?? 0,
            outputTokens: params.outputTokens ?? 0,
            cacheReadTokens: params.cacheReadTokens ?? 0,
            cacheWriteTokens: params.cacheWriteTokens ?? 0,
        },
        latencyMs: params.latencyMs,
    });
}

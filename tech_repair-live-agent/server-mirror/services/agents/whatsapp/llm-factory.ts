/**
 * LLM Factory
 * ============
 * Centralized chat-model instantiation.
 *
 * Nodes call `createLLM()` to get the Anthropic primary. When the caller
 * also wants provider failover (so a customer never sees the Spanish
 * fallback just because Anthropic is having a bad day), they additionally
 * call `createFallbackModel()` and compose via `withProviderFallback()`.
 *
 * Composition happens at the call site — NOT inside createLLM — because
 * `.withStructuredOutput()` / `.bindTools()` are BaseChatModel methods
 * that RunnableWithFallbacks doesn't expose, so the wrap MUST come last:
 *
 *   const primary  = createLLM(lane);
 *   const fallback = createFallbackModel(lane);
 *   const llm = withProviderFallback(
 *       primary.withStructuredOutput(schema),   // only if needed
 *       fallback?.withStructuredOutput(schema) ?? null,
 *   );
 */

import { ChatAnthropic } from "@langchain/anthropic";
import { ChatOpenAI } from "@langchain/openai";
import type { Runnable } from "@langchain/core/runnables";
import type { LaneConfig } from "./lane-selector";
import { getWhatsAppConfig } from "./config";

// Current GPT-5 flagship. Swap for a cheaper tier (e.g. "gpt-4.1-mini")
// if cost under sustained Anthropic outage becomes a concern.
const FALLBACK_MODEL = "gpt-5.2";

/** Primary chat model from the lane config (Anthropic). */
export function createLLM(laneConfig: LaneConfig | null): ChatAnthropic {
    const config = getWhatsAppConfig();

    const model = laneConfig?.model ?? config.lane1Model;
    const maxTokens = laneConfig?.maxResponseTokens ?? config.lane1MaxTokens;

    return new ChatAnthropic({
        model,
        maxTokens,
        temperature: 0.3,
        anthropicApiKey: config.anthropicApiKey,
    });
}

/**
 * Fallback chat model (OpenAI gpt-5.2) or null if OPENAI_API_KEY isn't set.
 * Matches the primary's maxTokens so downstream truncation is unchanged.
 */
export function createFallbackModel(
    laneConfig: LaneConfig | null,
): ChatOpenAI | null {
    const config = getWhatsAppConfig();
    if (!config.openaiApiKey) return null;

    const maxTokens = laneConfig?.maxResponseTokens ?? config.lane1MaxTokens;

    return new ChatOpenAI({
        model: FALLBACK_MODEL,
        maxTokens,
        temperature: 0.3,
        apiKey: config.openaiApiKey,
    });
}

/**
 * Wrap a primary Runnable with a single fallback (or return it unchanged
 * if no fallback is configured). The result is still a Runnable, so
 * .pipe(prompt), .invoke(), etc. all work.
 */
export function withProviderFallback<I, O>(
    primary: Runnable<I, O>,
    fallback: Runnable<I, O> | null,
): Runnable<I, O> {
    return fallback ? primary.withFallbacks([fallback]) : primary;
}

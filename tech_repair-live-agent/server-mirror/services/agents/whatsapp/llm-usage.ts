/**
 * LLM Usage Extraction
 * ====================
 * Extracts token usage from LangChain AIMessage responses.
 */

import type { AIMessage } from "@langchain/core/messages";
import type { LLMUsage } from "./graph/state";

/**
 * Extract usage from a LangChain response.
 *
 * LangChain standardizes usage in `response.usage_metadata` for all providers.
 * Anthropic cache fields come through `response.response_metadata.usage`.
 */
export function extractUsage(result: unknown): LLMUsage {
    try {
        const msg = result as AIMessage;

        // Anthropic-specific: cache fields in response_metadata.usage
        // [sim] type-only cast — usage shape is untyped in @langchain/core 1.1.46
        const raw = msg?.response_metadata?.usage as Record<string, number> | undefined;
        // LangChain standard: usage_metadata
        const std = msg?.usage_metadata as Record<string, number> | undefined;

        return {
            cacheReadTokens: raw?.cache_read_input_tokens ?? 0,
            cacheWriteTokens: raw?.cache_creation_input_tokens ?? 0,
            totalInputTokens: std?.input_tokens ?? raw?.input_tokens ?? 0,
            totalOutputTokens: std?.output_tokens ?? raw?.output_tokens ?? 0,
        };
    } catch {
        return { cacheReadTokens: 0, cacheWriteTokens: 0, totalInputTokens: 0, totalOutputTokens: 0 };
    }
}

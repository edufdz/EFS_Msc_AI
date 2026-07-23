/**
 * Context Summarizer
 * ==================
 * Summarizes conversation history when it exceeds maxContextTurns.
 * Uses claude-haiku-4-5-20251001 with low token budget.
 */

import { HumanMessage, SystemMessage } from "@langchain/core/messages";
import { createTrackedLLM } from "@/shared/llm-tracker";

const SUMMARIZATION_PROMPT = `Summarize this conversation in 2 sentences max in Spanish. Include: customer name, SO number if mentioned, key issue, any commitments made.`;

/**
 * Summarize conversation history if it exceeds maxTurns.
 *
 * Returns a summary of older messages plus the most recent messages.
 * If the history is short enough, returns null summary and the full history.
 */
export async function summarizeIfNeeded(
    history: Array<{ role: string; content: string; timestamp: string }>,
    maxTurns: number,
    anthropicApiKey: string,
    context?: { conversationId?: string; phone?: string },
): Promise<{ summary: string | null; recentHistory: typeof history }> {
    if (history.length <= maxTurns) {
        return { summary: null, recentHistory: history };
    }

    // Split: older messages to summarize, recent to keep
    const olderMessages = history.slice(0, history.length - maxTurns);
    const recentHistory = history.slice(-maxTurns);

    const conversationText = olderMessages
        .map((m) => `[${m.role}]: ${m.content}`)
        .join("\n");

    try {
        const llm = await createTrackedLLM({
            provider: "anthropic",
            model: "claude-haiku-4-5-20251001",
            callSite: "context_summarizer",
            context,
            maxTokens: 200,
            extras: { anthropicApiKey },
        });

        const response = await llm.invoke([
            new SystemMessage(SUMMARIZATION_PROMPT),
            new HumanMessage(conversationText),
        ]);

        const summary = typeof response.content === "string"
            ? response.content
            : "";

        return { summary, recentHistory };
    } catch (err) {
        console.warn("[context-summarizer] Summarization failed (non-fatal):", err);
        // On failure, just trim without summary
        return { summary: null, recentHistory };
    }
}

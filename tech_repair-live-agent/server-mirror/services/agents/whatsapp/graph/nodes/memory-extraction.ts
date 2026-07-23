/**
 * Memory Extraction Node
 * ======================
 * LangGraph node that fires after the support node handles a GOODBYE intent.
 *
 * Delegates the extraction + persistence to the shared `extractAndPersistMemory`
 * (semantic facts + CRM fields + interaction record + memory_history snapshot),
 * then runs the GOODBYE-only side effects (auto-escalation rules + grading).
 *
 * This node returns immediately — the extraction runs in the background
 * so it never delays the customer-facing response node.
 *
 * @see extractAndPersistMemory() — shared writer used by GOODBYE and the sweep
 */

import { extractAndPersistMemory, hasActionableInsights } from "@/services/meta/memory-persistence";
import { logAgentThought } from "@/shared/supabase-logger";
import { getSupabaseClient, getAppId } from "@/shared/supabase";
import type { WhatsAppStateType } from "@/services/agents/whatsapp/graph/state";

// =============================================================================
// Memory Extraction Node
// =============================================================================

export async function memoryExtractionNode(
    state: WhatsAppStateType,
): Promise<Partial<WhatsAppStateType>> {
    const phone = state.context?.customer?.phone_number;
    const history = state.context?.conversation_history ?? [];

    if (!phone || history.length === 0) {
        return {};
    }

    const conversationId = state.context?.metadata?.conversation_id as string | undefined;
    const transcript = history
        .filter(m => m.content)
        .map(m => `${m.role}: ${m.content}`)
        .join("\n");

    const supabase = getSupabaseClient();
    if (!supabase) {
        return {};
    }

    // Log extraction trigger
    logAgentThought(supabase, {
        conversationId,
        phone,
        stepName: "memory_extraction_triggered",
        thoughtContent: `Memory extraction fired on GOODBYE. Transcript length: ${transcript.length} chars, ${history.length} messages`,
    }).catch(() => {/* non-fatal */});

    // Fire-and-forget — never blocks the response node
    (async () => {
        try {
            const result = await extractAndPersistMemory(supabase, {
                phone,
                conversationId,
                transcript,
                source: "whatsapp",
            });

            if (!hasActionableInsights(result)) {
                // No insights to act on. Two cases land here:
                //  1. Debounced — another extraction for this phone ran within 60s
                //     and already handled the GOODBYE side effects.
                //  2. Extraction failed (result.failed) — persistence already
                //     logged it. We must NOT run rules/grading on fabricated
                //     neutral sentiment, so we bail.
                // The "no new facts" case DOES carry insights, so it falls through
                // and runs the rules + grading below (matching the pre-refactor GOODBYE).
                return;
            }

            const insights = result.insights;
            const interactionId = result.interactionId;

            // GOODBYE-only: evaluate auto-escalation rules (call_frequency, sentiment, etc.)
            try {
                const { evaluateRules } = await import("@/services/escalation-rules-engine");
                const appId = getAppId();
                if (appId) {
                    const { triggered, ruleName } = await evaluateRules(supabase, {
                        phone,
                        channel: "whatsapp",
                        sentimentScore: insights.sentiment_score,
                        orgId: appId,
                    });
                    if (triggered && conversationId) {
                        await supabase
                            .from("whatsapp_conversations")
                            .update({ status: "escalated" })
                            .eq("id", conversationId);
                        console.info(`[MemoryExtractionNode] Auto-escalation triggered: ${ruleName}`);
                    }
                }
            } catch (err) {
                console.warn("[MemoryExtractionNode] Rule evaluation failed (non-fatal):", err);
            }

            // GOODBYE-only: grade interaction (async, non-blocking)
            if (conversationId) {
                try {
                    const { gradeInteraction } = await import("@/services/analysis/interaction-grader");
                    gradeInteraction({
                        conversationId,
                        phone,
                        interactionId: interactionId ?? null,
                        transcript,
                        sentimentScore: insights.sentiment_score,
                        outcome: insights.resolution_status ?? "unknown",
                    }).catch(err => {
                        console.warn("[MemoryExtractionNode] Grading failed (non-fatal):", err);
                    });
                } catch (err) {
                    console.warn("[MemoryExtractionNode] Grading import failed (non-fatal):", err);
                }
            }

            // Persistence logs only when a snapshot was actually written. The
            // "no new facts" path runs rules + grading above but persists
            // nothing, so claiming "Saved ... snapshot" here would be false.
            if (result.wrote) {
                console.info(
                    `[MemoryExtractionNode] Saved ${result.factsCount} facts + CRM + interaction + snapshot for ${phone}`
                );

                logAgentThought(supabase, {
                    conversationId,
                    phone,
                    stepName: "memory_extraction_complete",
                    thoughtContent: `Extracted ${result.factsCount} fact(s): ${insights.customer_facts.slice(0, 2).join("; ")}${result.factsCount > 2 ? "..." : ""} | CRM: escalation=${insights.escalation_risk}, sentiment=${insights.sentiment_score}`,
                }).catch(() => {/* non-fatal */});
            }
        } catch (err) {
            console.warn("[MemoryExtractionNode] Extraction failed after retries (non-fatal):", err);
        }
    })();

    // Return immediately — do not wait for the async extraction
    return {};
}

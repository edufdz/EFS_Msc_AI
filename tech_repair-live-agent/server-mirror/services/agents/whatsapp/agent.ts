/**
 * WhatsApp Agent Entry Point
 * ==========================
 * Provides the main execution interface for the WhatsApp AI agent.
 * Used by the gateway orchestrator to process incoming messages.
 */

import { HumanMessage } from "@langchain/core/messages";
import { getGraph, _resetGraph } from "./graph/builder";
import { createInitialState } from "./graph/state";
import {
    type AssembledContext,
    type AgentResponse,
    AssembledContextSchema,
} from "./models";
import { selectLane, type LaneId } from "./lane-selector";
import { summarizeIfNeeded } from "./context-summarizer";
import { emitRocketMetric } from "./rocket-metrics";
import { trackLLMUsage } from "@/shared/llm-tracker";
import { getSupabaseClient, getAppId } from "@/shared/supabase";
import { escalateDetectedEvent } from "./events/escalate-event";
import { getWhatsAppConfig } from "./config";
import { getSurveyOrchestrator } from "@/services/surveys/survey-orchestrator";

// =============================================================================
// WhatsApp Agent
// =============================================================================

/** Max time to wait for a single graph invocation before aborting */
const GRAPH_TIMEOUT_MS = 30_000;

/**
 * Choose the customer-facing reply text. A detected-event acuse (e.g. "Recibí tu
 * comprobante") REPLACES the normal answer — EXCEPT when the turn escalates,
 * where the handoff message (`responseText`) must win. Otherwise an escalated
 * customer would be told "Recibí tu comprobante" instead of being handed to a
 * human. The event itself is still recorded/tagged via escalateDetectedEvent
 * regardless, so dropping the acuse text here loses nothing but the courtesy.
 */
export function chooseResponseText(
    acuses: string[],
    result: { escalated?: boolean; responseText?: string | null },
): string {
    if (acuses.length > 0 && !result.escalated) {
        return acuses.join(" ");
    }
    return result.responseText || "No response generated.";
}

export class WhatsAppAgent {
    private graphReady = false;

    /**
     * Execute the WhatsApp agent for a single message turn.
     *
     * @param context The assembled context from the gateway/orchestrator
     * @param threadId Conversation thread ID for checkpoint persistence
     * @returns AgentResponse with response text, intent, tools used, etc.
     */
    async execute(
        context: AssembledContext,
        threadId: string,
    ): Promise<AgentResponse> {
        // Validate input context
        const parsed = AssembledContextSchema.safeParse(context);
        if (!parsed.success) {
            console.error(
                "[whatsapp-agent] Invalid context:",
                parsed.error.message,
            );
            return {
                response_text:
                    "Lo siento, hubo un error procesando su mensaje. Por favor intente nuevamente.",
                intent: "unknown",
                confidence: 0,
                tool_calls: [],
                should_close: false,
                metadata: { error: "Invalid context" },
            };
        }

        try {
            const startMs = Date.now();
            const config = getWhatsAppConfig();

            // 0. Survey interception — si el cliente tiene una encuesta activa,
            //    el orchestrator maneja el turno y saltamos LangGraph.
            //    Para clientes sin encuesta activa, retorna null y seguimos normal.
            try {
                const surveyOrch = getSurveyOrchestrator();
                const phone = parsed.data.customer?.phone_number;
                const conversationId = parsed.data.metadata?.conversation_id as string | undefined;
                if (phone) {
                    const surveyResult = await surveyOrch.handle({
                        phone,
                        conversationId: conversationId ?? null,
                        message: parsed.data.current_message.content,
                    });
                    if (surveyResult) {
                        console.info(
                            `[whatsapp-agent] Survey turn handled (survey=${surveyResult.metadata.survey_id})`,
                        );
                        return {
                            response_text: surveyResult.response_text,
                            intent: "survey",
                            confidence: 1,
                            tool_calls: [],
                            should_close: surveyResult.completed,
                            metadata: {
                                survey_id: surveyResult.metadata.survey_id,
                                survey_turn_kind: surveyResult.metadata.turn_kind,
                                survey_status_after: surveyResult.metadata.survey_status_after,
                            },
                        };
                    }
                }
            } catch (surveyErr) {
                // Si el survey orchestrator falla, NO bloqueamos el agente. Fallback
                // al flow normal de LangGraph — vale más responder al cliente que
                // perder el turno.
                console.error(
                    "[whatsapp-agent] Survey orchestrator error, falling back to LangGraph:",
                    surveyErr,
                );
            }

            // 1. Select processing lane (one-way upgrade: lane 2 is sticky)
            const currentLane = parsed.data.metadata?.lane_id as LaneId | undefined;
            const laneConfig = selectLane(parsed.data, currentLane);

            // 2. Summarize history if it exceeds maxContextTurns
            const conversationId = parsed.data.metadata?.conversation_id as string | undefined;
            const phone = parsed.data.customer?.phone_number;
            const { summary, recentHistory } = await summarizeIfNeeded(
                parsed.data.conversation_history,
                laneConfig.maxContextTurns,
                config.anthropicApiKey,
                { conversationId, phone },
            );
            if (summary) {
                parsed.data.metadata.conversation_summary = summary;
            }
            parsed.data.conversation_history = recentHistory;

            const graph = await getGraph();
            if (!graph) {
                throw new Error("Failed to initialize graph");
            }
            const initialState = createInitialState(parsed.data, laneConfig);

            // Invoke the graph with thread-based checkpointing + timeout guard
            const result = await this.invokeWithTimeout(
                graph,
                initialState,
                parsed.data.current_message.content,
                threadId,
            );

            // 3. Emit ROCKET metrics (fire-and-forget)
            const latencyMs = Date.now() - startMs;
            const usage = result.llmUsage ?? { cacheReadTokens: 0, cacheWriteTokens: 0, totalInputTokens: 0, totalOutputTokens: 0 };
            emitRocketMetric({
                conversationId,
                phone,
                laneId: laneConfig.laneId,
                modelUsed: laneConfig.model,
                intent: result.intent,
                cacheHit: usage.cacheReadTokens > 0,
                cacheReadTokens: usage.cacheReadTokens,
                cacheWriteTokens: usage.cacheWriteTokens,
                totalTokens: usage.totalInputTokens + usage.totalOutputTokens,
                latencyMs,
                escalatedLane: false,
            });
            trackLLMUsage({
                callSite: "whatsapp_agent",
                model: laneConfig.model,
                provider: "anthropic",
                conversationId,
                phone,
                inputTokens: usage.totalInputTokens,
                outputTokens: usage.totalOutputTokens,
                cacheReadTokens: usage.cacheReadTokens,
                cacheWriteTokens: usage.cacheWriteTokens,
                latencyMs,
            });

            // Fire tagged escalations for business-critical events spotted this
            // turn (payment receipt, address mention, order received). Flags for
            // a human — does NOT hand off the conversation. Fire-and-forget so it
            // never blocks or fails the customer reply.
            const detectedEvents = result.detectedEvents ?? [];
            if (detectedEvents.length > 0) {
                const sb = getSupabaseClient();
                if (sb) {
                    const convId = context.metadata?.conversation_id as string | undefined;
                    for (const detectedEvent of detectedEvents) {
                        void escalateDetectedEvent(sb, {
                            appId: getAppId() ?? undefined,
                            conversationId: convId,
                            phone: context.customer.phone_number,
                            customerName: context.customer.name,
                            event: detectedEvent,
                        });
                    }
                }
            }

            // Bot reply per event: when a detected event carries an acuse it
            // REPLACES the reply (payment / order received / address CHANGE). A
            // null acuse (an incidental address mention) leaves the normal answer
            // untouched so the bot still answers what the customer actually asked.
            const acuses = detectedEvents
                .map((detectedEvent: { botReply?: string | null }) => detectedEvent.botReply)
                .filter((reply: unknown): reply is string => typeof reply === "string" && reply.length > 0);
            // When the turn escalates, the handoff text wins over any acuse.
            const responseText = chooseResponseText(acuses, result);

            return {
                response_text: responseText,
                intent: result.intent,
                confidence: result.intentConfidence,
                tool_calls: result.toolCalls ?? [],
                escalation: result.escalated
                    ? {
                        escalated: true,
                        escalated_at: new Date().toISOString(),
                        reason: result.escalationReason,
                    }
                    : undefined,
                should_close:
                    result.intent === "goodbye" ||
                    result.humanTakenOver === true,
                metadata: {
                    ...(result.error ? { error: result.error } : {}),
                    laneId: laneConfig.laneId,
                    modelUsed: laneConfig.model,
                },
            };
        } catch (err) {
            console.error("[whatsapp-agent] Execution error:", err);
            return {
                response_text:
                    "Lo siento, ocurrió un error inesperado. Por favor intente más tarde o comuníquese directamente al centro de servicio.",
                intent: "unknown",
                confidence: 0,
                tool_calls: [],
                should_close: false,
                metadata: {
                    error: err instanceof Error ? err.message : String(err),
                },
            };
        }
    }

    /**
     * Wrap graph.invoke with a timeout so a hung LLM call
     * doesn't block webhook processing forever.
     */
    private invokeWithTimeout(
        graph: Awaited<ReturnType<typeof getGraph>>,
        initialState: ReturnType<typeof createInitialState>,
        messageContent: string,
        threadId: string,
    ): Promise<any> {
        return new Promise((resolve, reject) => {
            const timer = setTimeout(() => {
                reject(new Error(`Graph execution timed out after ${GRAPH_TIMEOUT_MS}ms`));
            }, GRAPH_TIMEOUT_MS);

            graph!.invoke(
                {
                    ...initialState,
                    messages: [new HumanMessage(messageContent)],
                },
                { configurable: { thread_id: threadId } },
            )
            .then((result: any) => { clearTimeout(timer); resolve(result); })
            .catch((err: any) => { clearTimeout(timer); reject(err); });
        });
    }
}

// Singleton
let _agent: WhatsAppAgent | null = null;

/**
 * Get the WhatsApp agent singleton.
 */
export function getWhatsAppAgent(): WhatsAppAgent {
    if (!_agent) {
        _agent = new WhatsAppAgent();
    }
    return _agent;
}

/** Reset for testing. */
export function _resetAgent(): void {
    _agent = null;
    _resetGraph();
}

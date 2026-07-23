/**
 * Support Node
 * ============
 * Handles general support inquiries, greetings, goodbyes,
 * confirmations, and rejections via LLM.
 */

import { ChatPromptTemplate } from "@langchain/core/prompts";
import { getWhatsAppDynamicConfig } from "@/services/agents/whatsapp/config";
import { IntentType } from "@/services/agents/whatsapp/models";
import { SUPPORT_USER_PROMPT, getSupportSystemPrompt } from "@/services/agents/whatsapp/prompts/support";
import { buildWhatsAppCarryInAddendum } from "@/services/agents/whatsapp/prompts/carry-in";
import { loadAgentConfig } from "@/services/agents/shared/dynamic-config";
import { logAgentThought } from "@/shared/supabase-logger";
import { getSupabaseClient } from "@/shared/supabase";
import { AgentMemory, buildCrmOverrides } from "@/shared/memory";
import { detectEscalationSignals, processSignals } from "@/services/agents/shared/signals";
import { renderOrderCards } from "@/services/orchestrator/response-renderer";
import { getContactNumbers } from "@/shared/contact-numbers";
import { applyCorrections, parseCorrections } from "./customer-corrections";
import type { ResolvedMemory } from "@/services/orchestrator/memory-types";
import {
    createLLM,
    createFallbackModel,
    withProviderFallback,
} from "@/services/agents/whatsapp/llm-factory";
import { extractUsage } from "@/services/agents/whatsapp/llm-usage";
import { assessSOCompleteness } from "@/shared/so-completeness";
import type { ServiceOrderRowLike } from "@/shared/so-customer-view";
import {
    type WhatsAppStateType,
    getCustomerInfo,
    getActiveOrders,
    formatConversationHistory,
    getSessionInfo,
} from "@/services/agents/whatsapp/graph/state";

// =============================================================================
// GOODBYE is the only intent that doesn't need LLM — it's terminal and
// context-free. Everything else goes through the LLM with full context.
// =============================================================================

const GOODBYE_RESPONSE =
    "¡Gracias por contactarnos! 🙏 Si necesita algo más, no dude en escribirnos. ¡Que tenga un excelente día!";

// =============================================================================
// Support Node
// =============================================================================

export async function supportNode(
    state: WhatsAppStateType,
): Promise<Partial<WhatsAppStateType>> {
    const config = await getWhatsAppDynamicConfig();
    const intent = state.intent;

    // GOODBYE is the only fast-path — terminal, no context needed
    if (intent === IntentType.GOODBYE) {
        return { responseText: GOODBYE_RESPONSE };
    }

    // The two customer-facing lines: agentPhone (self-service status) feeds the
    // order cards and {support_phone}; storePhone feeds the new {store_phone}.
    const { agentPhone, storePhone } = await getContactNumbers();

    // Log memory injection when semantic context is present
    const memoryContext = state.context?.memory_context ?? "";
    if (memoryContext) {
        const supabase = getSupabaseClient();
        if (supabase) {
            const factCount = (memoryContext.match(/^- /gm) ?? []).length;
            logAgentThought(supabase, {
                conversationId: state.context?.metadata?.conversation_id as string | undefined,
                phone: state.context?.customer?.phone_number,
                stepName: "memory_injection",
                thoughtContent: `Injected ${factCount} semantic fact(s) into support prompt`,
            }).catch(() => {/* non-fatal */ });
        }
    }

    // Full LLM response — all intents (greeting, confirmation, rejection,
    // general support, unknown) get the same treatment: full context, CRM
    // profile, order data, conversation history, and semantic memory.
    try {
        const dbConfig = await loadAgentConfig("whatsapp");
        const llm = withProviderFallback(
            createLLM(state.laneConfig),
            createFallbackModel(state.laneConfig),
        );

        const customer = getCustomerInfo(state);
        const orders = getActiveOrders(state);

        const customerInfo = customer
            ? `Nombre: ${customer.name ?? "No disponible"}, Tel: ${customer.phone_number}, Interacciones: ${customer.interaction_count}`
            : "No customer info available.";

        // ─── Load CRM Profile for Context Injection ───
        let crmOverrides = "";
        if (customer?.phone_number) {
            try {
                const memory = new AgentMemory();
                const profile = await memory.getCustomerProfile(customer.phone_number);
                const block = await buildCrmOverrides({
                    ...profile,
                    lastTopic: profile.lastTopic,
                    interactionCount: profile.interactionCount,
                    hasActiveOrders: orders.length > 0,
                });
                if (block) {
                    crmOverrides = `\n${block}`;
                }
            } catch (err) {
                // Non-fatal: if CRM load fails, continue without overrides
                console.warn("[support] Failed to load CRM profile:", err);
            }
        }

        // ─── Pre-render verified data cards ───
        // Cards are formatted with verified GSPN data. The LLM is instructed
        // to include them verbatim — it writes the conversational wrapper but
        // never generates factual claims (prices, statuses, dates) itself.
        const orderCards = renderOrderCards(
            orders.map(o => ({
                id: '',
                svc_order_no: o.svc_order_no,
                status: o.status,
                device_model: o.model_name ?? '',
                repair_cost_mxn: o.repair_cost_mxn ?? null,
                warranty_type: o.warranty_type ?? null,
                created_at: '',
                estimated_completion: o.estimated_completion ?? null,
                is_d2d: o.is_d2d,
                service_type: o.service_type ?? null,
                iris_condition_desc: o.iris_condition_desc ?? null,
                iris_symptom_desc: o.iris_symptom_desc ?? null,
                iris_defect_desc: o.iris_defect_desc ?? null,
                iris_repair_desc: o.iris_repair_desc ?? null,
            })),
            agentPhone,
        );
        const activeOrders = orderCards.formatted;

        const supportPromptOverride = dbConfig?.prompts?.support;
        let systemPrompt = await getSupportSystemPrompt(supportPromptOverride, crmOverrides);
        // Append the carry-in guardrail when any active order is carry_in (same
        // block as the voice agent). Null (no carry-in) → base prompt unchanged.
        const carryInAddendum = buildWhatsAppCarryInAddendum(orders);
        if (carryInAddendum) {
            systemPrompt += `\n\n${carryInAddendum}`;
        }
        const prompt = ChatPromptTemplate.fromMessages([
            ["system", systemPrompt],
            ["human", SUPPORT_USER_PROMPT],
        ]);

        const chain = prompt.pipe(llm);
        const response = await chain.invoke({
            business_name: config.businessName,
            business_address: config.businessAddress,
            business_hours: config.businessHours,
            support_phone: agentPhone,
            store_phone: storePhone,
            business_email: config.businessEmail,
            max_length: config.maxResponseLength,
            customer_info: customerInfo,
            memory_directives: state.context?.memory_directives ?? "",
            memory_context: state.context?.memory_context ?? "",
            active_orders: activeOrders,
            conversation_history: formatConversationHistory(state),
            current_message: state.context?.current_message?.content ?? "",
        });

        const rawText =
            typeof response.content === "string" ? response.content : "";

        // ─── Parse customer-correction markers (e.g. [CORRECT:preferred_name|JC|"no, soy JC"]) ───
        // The marker is stripped from the customer-facing text BEFORE any
        // other processing so escalation regexes operate on clean text.
        // Persistence is fire-and-forget — a DB hiccup must not block the reply.
        const correctionResult = parseCorrections(rawText);
        if (correctionResult.applied.length > 0 && customer?.phone_number) {
            const supaForCorrection = getSupabaseClient();
            if (supaForCorrection) {
                applyCorrections({
                    phone: customer.phone_number,
                    corrections: correctionResult.applied,
                    supabase: supaForCorrection,
                    conversationId: state.context?.metadata?.conversation_id as string | undefined,
                }).catch((err) => {
                    console.warn("[support] applyCorrections failed (non-fatal):", err);
                });
            }
        }
        const text = correctionResult.cleanText;

        // ─── Per-turn memory instrumentation (fire-and-forget) ───
        // One row per Maria turn, scoped to agent_type='maria' so the
        // customer-360 Memory tab can show "what memory was available vs
        // what the agent actually used". Detection is heuristic — the LLM
        // doesn't tell us directly, we infer from what shipped in `text`.
        // If the row write fails, the reply still ships; the absent row
        // shows up as a gap in the weekly aggregate, which is a signal
        // either way.
        if (customer?.phone_number) {
            const supaForInstr = getSupabaseClient();
            if (supaForInstr) {
                const resolved = state.context?.memory_resolved as
                    | ResolvedMemory
                    | undefined;
                const textLower = text.toLowerCase();
                const nameUsed =
                    !!resolved?.resolved_customer_name &&
                    textLower.includes(resolved.resolved_customer_name.toLowerCase());
                const soUsed =
                    !!resolved?.recent_so_references?.some((r) =>
                        text.includes(r.svc_order_no),
                    );
                // Short-circuit heuristic: very brief reply that isn't a
                // cold-open greeting. Indicates the agent is acknowledging
                // a known state vs re-asking from scratch.
                const isGreetingOpener = /^(hola|buenos|buenas|qué tal|hi|hello)\b/i.test(text);
                const shortCircuit = text.length > 0 && text.length < 80 && !isGreetingOpener;

                supaForInstr
                    .from("interaction_history")
                    .insert({
                        phone: customer.phone_number,
                        channel: "whatsapp",
                        topic: "turn_instrumentation",
                        summary: text.slice(0, 200),
                        agent_type: "maria",
                        svc_order_no: orders[0]?.svc_order_no ?? null,
                        created_at: new Date().toISOString(),
                        metadata: {
                            memory_resolved_name_used: nameUsed,
                            memory_so_context_used: soUsed,
                            memory_short_circuit_taken: shortCircuit,
                            memory_corrections_recorded: correctionResult.applied.length,
                            conversation_id:
                                state.context?.metadata?.conversation_id ?? null,
                            had_directives:
                                (state.context?.memory_directives?.length ?? 0) > 0,
                        },
                    })
                    .then(({ error }) => {
                        if (error) {
                            console.warn(
                                "[support] turn instrumentation write failed (non-fatal):",
                                error.message,
                            );
                        }
                    });
            }
        }

        // ─── Mid-conversation signal detection (fire-and-forget) ───
        const customerMessage = state.context?.current_message?.content ?? "";
        if (customerMessage && customer?.phone_number) {
            const signals = detectEscalationSignals(customerMessage);
            if (signals.escalationTriggered || signals.frustrationDetected || signals.transferRequested) {
                // Fire-and-forget: update DB + log
                processSignals(customer.phone_number, signals, {
                    conversationId: state.context?.metadata?.conversation_id as string | undefined,
                    channel: "whatsapp",
                }).catch(() => {/* non-fatal */});

                // If escalation triggered, propagate immediately via state
                if (signals.escalationTriggered) {
                    const ESCALATE_MARKER = /\[ESCALATE:(\w+)\]/;
                    const escalateMatch = text.match(ESCALATE_MARKER);
                    const cleanText = escalateMatch ? text.replace(ESCALATE_MARKER, '').trim() : text;
                    return {
                        responseText: cleanText,
                        escalated: true,
                        escalationReason: `Señal de escalación detectada: ${signals.escalationMatch ?? "riesgo alto"}`,
                        llmUsage: extractUsage(response),
                    };
                }
            }
        }

        // Detect [ESCALATE:REASON] marker from prompt rules (e.g. rule 19 — address change)
        const ESCALATE_MARKER = /\[ESCALATE:(\w+)\]/;
        const escalateMatch = text.match(ESCALATE_MARKER);
        if (escalateMatch) {
            const marker = escalateMatch[1];
            const cleanText = text.replace(ESCALATE_MARKER, '').trim();

            // D2 guard: for MISSING_ORDER_DATA specifically, gate through the
            // SO-completeness check. If identity + phone are present, the bot
            // has enough to keep the conversation alive; strip the marker and
            // do NOT escalate. Emit an escalation_gate_bypassed audit row.
            if (marker === "MISSING_ORDER_DATA" && orders.length > 0) {
                const activeOrder = orders[0] as unknown as ServiceOrderRowLike;
                const completeness = assessSOCompleteness(activeOrder);
                if (completeness === "contact_sufficient" || completeness === "contact_only") {
                    const supa = getSupabaseClient();
                    if (supa) {
                        logAgentThought(supa, {
                            conversationId: state.context?.metadata?.conversation_id as string | undefined,
                            phone: customer?.phone_number,
                            stepName: "escalation_gate_bypassed",
                            thoughtContent: `Stripped [ESCALATE:MISSING_ORDER_DATA] — ${JSON.stringify({
                                svc_order_no: activeOrder.svc_order_no,
                                warranty_type: activeOrder.warranty_type ?? null,
                                status: activeOrder.status,
                                completeness,
                            })}`,
                        }).catch(() => {/* non-fatal */});
                    }
                    return { responseText: cleanText, llmUsage: extractUsage(response) };
                }
                // Insufficient → escalate with typed D13 reason (enum value)
                return {
                    responseText: cleanText,
                    escalated: true,
                    escalationReasonOverride: "so_record_missing_contact",
                    llmUsage: extractUsage(response),
                };
            }

            return {
                responseText: cleanText,
                escalated: true,
                escalationReason: `Auto-escalado: ${marker.replace(/_/g, ' ').toLowerCase()}`,
                llmUsage: extractUsage(response),
            };
        }

        return { responseText: text, llmUsage: extractUsage(response) };
    } catch (err) {
        console.error("[support] Node error:", err);
        return {
            responseText:
                "Lo siento, tuve un problema procesando su solicitud. ¿Podría reformular su pregunta?",
            error: `Support error: ${err instanceof Error ? err.message : String(err)}`,
        };
    }
}

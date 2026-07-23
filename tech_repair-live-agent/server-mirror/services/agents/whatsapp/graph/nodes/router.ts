/**
 * Router Node
 * ===========
 * Intent classification using keyword matching + LLM fallback.
 */

import { z } from "zod";
import { ChatPromptTemplate } from "@langchain/core/prompts";
import { IntentType, INTENT_VALUES_V1, INTENT_VALUES_V2 } from "@/services/agents/whatsapp/models";
import { ROUTER_USER_PROMPT, getRouterSystemPrompt } from "@/services/agents/whatsapp/prompts/router";
import { loadAgentConfig } from "@/services/agents/shared/dynamic-config";
import { logAgentThought } from "@/shared/supabase-logger";
import { getSupabaseClient } from "@/shared/supabase";
import {
    createLLM,
    createFallbackModel,
    withProviderFallback,
} from "@/services/agents/whatsapp/llm-factory";
import { extractUsage } from "@/services/agents/whatsapp/llm-usage";
import { getWhatsAppDynamicConfig } from "@/services/agents/whatsapp/config";
import {
    type WhatsAppStateType,
    formatConversationHistory,
} from "@/services/agents/whatsapp/graph/state";

// =============================================================================
// Intent Descriptions (version-aware)
// =============================================================================

const INTENT_DESCRIPTIONS_V1: Record<string, string> = {
    [IntentType.ORDER_STATUS]:
        "Customer wants to check the status of their repair order or service order number",
    [IntentType.PRICING]:
        "Customer wants to know repair costs, pricing, or get a quote",
    [IntentType.GENERAL_SUPPORT]:
        "General questions about services, hours, location, or other support needs",
    [IntentType.GREETING]:
        "Customer is greeting or starting a conversation (hola, hi, buenos días, etc.)",
    [IntentType.GOODBYE]:
        "Customer is ending the conversation (gracias, bye, adiós, etc.)",
    [IntentType.ESCALATION]:
        "Customer explicitly asks to talk to a human agent or supervisor",
    [IntentType.CONFIRMATION]:
        "Customer confirms or agrees with something (sí, ok, de acuerdo, etc.)",
    [IntentType.REJECTION]:
        "Customer declines or disagrees (no, no gracias, etc.)",
};

const INTENT_DESCRIPTIONS_V2: Record<string, string> = {
    [IntentType.ORDER_STATUS]:
        "Customer asks about the current stage/status of a specific repair order (usually with a 10+ digit order number)",
    [IntentType.PRICING]:
        "Customer asks how much the repair will cost, for a quote, or compares a quoted amount (cuánto cuesta, costo, cotización, precio)",
    [IntentType.WARRANTY_QUESTION]:
        "Customer asks whether a repair is covered by warranty, if it's 'sin costo', or questions an out-of-warranty classification (garantía, cubierto, sin costo, fuera de garantía). Distinct from PRICING — here they want to know coverage, not the amount.",
    [IntentType.DELIVERY_LOGISTICS]:
        "Customer asks about shipping / delivery / courier of their device. Keywords: paquetería, guía, envío, rastreo, entrega, cuándo llega, cuándo me la mandan, ya la enviaron, número de guía.",
    [IntentType.CONTACT_INFO_REQUEST]:
        "Customer asks for a phone number, address, or way to contact the service center directly (cuál es el número, cómo les marco, teléfono, contacto, donde están).",
    [IntentType.NEW_SYMPTOM_REPORT]:
        "Customer reports a NEW problem or additional symptom on a device that's already in for repair (cámara también falla, además se calienta, favor de revisar también). Not a first-time diagnostic — they're adding info.",
    [IntentType.COMPLAINT_OR_FRUSTRATION]:
        "Customer is upset, frustrated, escalating language, threats, legal/PROFECO mentions, or venting without asking a concrete question (inaceptable, profeco, demanda, robo, pésimo servicio, me dejaron esperando).",
    [IntentType.EXPLICIT_HUMAN_REQUEST]:
        "Customer explicitly asks to talk to a human / agent / supervisor / real person (humano, asesor, persona real, no bot, hablar con alguien).",
    [IntentType.GREETING]:
        "Customer is greeting or starting a conversation (hola, hi, buenos días, etc.)",
    [IntentType.GOODBYE]:
        "Customer is ending the conversation (gracias, bye, adiós, etc.)",
    [IntentType.CONFIRMATION]:
        "Customer confirms or agrees with something (sí, ok, de acuerdo, perfecto, enterado).",
    [IntentType.UNKNOWN]:
        "Intent cannot be determined — ask a one-turn clarifier.",
};

// =============================================================================
// Keyword Map (v2). For v1, any v2-only intent falls through to the LLM.
// =============================================================================

/**
 * Keyword → intent map for fast classification. Ordering matters: more
 * specific intents go first. A message like "¿cuánto cuesta la reparación?"
 * contains both "reparación" (status) and "cuánto" (pricing); we want
 * PRICING to win.
 */
const KEYWORD_MAP: Array<{ keywords: string[]; intent: string }> = [
    // Most specific patterns first
    {
        keywords: [
            "inaceptable", "profeco", "demanda", "robo",
            "pésimo", "pesimo", "me dejaron esperando",
            "mal servicio", "mala atención", "mala atencion",
        ],
        intent: IntentType.COMPLAINT_OR_FRUSTRATION,
    },
    {
        keywords: [
            "humano", "asesor", "persona real",
            "no bot", "agente humano",
        ],
        intent: IntentType.EXPLICIT_HUMAN_REQUEST,
    },
    {
        keywords: [
            "paquetería", "paqueteria", "guía", "guia",
            "envío", "envio", "envían", "envian",
            "enviaron", "enviaran", "enviarán", "enviarlo",
            "enviado", "enviada", "mandaron", "mandan",
            "entrega", "rastreo",
            "cuándo llega", "cuando llega",
            "cuándo me la mandan", "cuando me la mandan",
            "fecha de envío", "fecha de envio",
        ],
        intent: IntentType.DELIVERY_LOGISTICS,
    },
    {
        keywords: [
            "contacto", "teléfono", "telefono", "número", "numero",
            "llamar", "marcar", "cómo les marco", "como les marco",
            "dónde están", "donde estan", "dirección del centro",
        ],
        intent: IntentType.CONTACT_INFO_REQUEST,
    },
    {
        keywords: [
            "garantía", "garantia", "cubierto", "sin costo",
            "fuera de garantía", "fuera de garantia",
            "en garantía", "en garantia",
        ],
        intent: IntentType.WARRANTY_QUESTION,
    },
    // PRICING before ORDER_STATUS: cost questions often also mention
    // "reparación" which would otherwise match order_status first.
    {
        keywords: [
            "precio", "costo", "cost", "cotización", "quote",
            "cuánto", "cuanto", "how much", "tarifa", "rate",
        ],
        intent: IntentType.PRICING,
    },
    {
        keywords: [
            "estado", "orden", "status", "pedido", "seguimiento",
            "tracking", "reparación", "repair", "svc",
        ],
        intent: IntentType.ORDER_STATUS,
    },
    {
        keywords: [
            "hola", "hello", "hi", "buenos días", "buenas tardes",
            "buenas noches", "hey", "buen día",
        ],
        intent: IntentType.GREETING,
    },
    {
        keywords: [
            "adiós", "adios", "bye", "chao",
            "hasta luego", "goodbye", "nos vemos",
        ],
        intent: IntentType.GOODBYE,
    },
    // CONFIRMATION, REJECTION, NEW_SYMPTOM_REPORT removed from keyword matching —
    // too context-dependent. The LLM classifies these with full history.
];

/**
 * WhatsApp paste-history detection (Deliverable 10).
 * WhatsApp exports always include a bracketed timestamp like "[12/04/26, 3:45 p.m.]".
 * When we see this, the customer is quoting prior history — high-priority escalation.
 */
export const WHATSAPP_PASTE_REGEX =
    /\[\d{1,2}\/\d{1,2}\/\d{2,4},?\s*\d{1,2}:\d{2}(:\d{2})?\s*[ap]\.?\s*m\.?\]/i;

/**
 * Filter an intent value to one that's valid for the requested taxonomy version.
 * Maps legacy intents to their v2 equivalents (or falls through to UNKNOWN).
 * Exported for unit testing.
 */
export function normalizeIntentForVersion(
    intent: string,
    version: "v1" | "v2",
): string {
    if (version === "v1") {
        // If a v2-only intent slipped through, collapse it to general_support
        // so the legacy router continues to work.
        if (!INTENT_VALUES_V1.includes(intent as typeof INTENT_VALUES_V1[number])) {
            return IntentType.GENERAL_SUPPORT;
        }
        return intent;
    }
    // v2: map legacy values to equivalents
    if (intent === IntentType.GENERAL_SUPPORT) return IntentType.UNKNOWN;
    if (intent === IntentType.ESCALATION) return IntentType.EXPLICIT_HUMAN_REQUEST;
    if (intent === IntentType.REJECTION) return IntentType.CONFIRMATION;
    if (!INTENT_VALUES_V2.includes(intent as typeof INTENT_VALUES_V2[number])) {
        return IntentType.UNKNOWN;
    }
    return intent;
}

// =============================================================================
// Classification Functions
// =============================================================================

/**
 * Fast keyword-based classification.
 * Returns null if no keyword match is found.
 * Exported for unit testing.
 */
export function classifyByKeywords(
    text: string,
): { intent: string; confidence: number } | null {
    const lower = text.toLowerCase().trim();

    for (const { keywords, intent } of KEYWORD_MAP) {
        for (const keyword of keywords) {
            const escaped = keyword.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
            const regex = new RegExp(`(?:^|\\s|[\xBF\xA1])${escaped}(?:\\s|$|[\\?!,\\.])`, 'i');
            if (regex.test(lower)) {
                return { intent, confidence: 0.8 };
            }
        }
    }
    return null;
}

/** Structured-output schema for intent classification. Version-aware. */
function makeClassificationSchema(version: "v1" | "v2") {
    const values = version === "v1" ? INTENT_VALUES_V1 : INTENT_VALUES_V2;
    return z.object({
        intent: z.enum(values as unknown as [string, ...string[]])
            .describe("The classified intent of the customer message"),
        confidence: z.number().min(0).max(1)
            .describe("Confidence score from 0 to 1"),
    });
}

/**
 * LLM-based classification fallback using structured output.
 */
async function classifyByLLM(
    text: string,
    history: string,
    laneConfig: import("@/services/agents/whatsapp/lane-selector").LaneConfig | null,
    version: "v1" | "v2",
): Promise<{ intent: string; confidence: number; usage: import("@/services/agents/whatsapp/graph/state").LLMUsage }> {
    const dbConfig = await loadAgentConfig("whatsapp");
    const primary = createLLM(laneConfig);
    const fallback = createFallbackModel(laneConfig);

    const descriptions = version === "v1" ? INTENT_DESCRIPTIONS_V1 : INTENT_DESCRIPTIONS_V2;
    const intentDescriptions = Object.entries(descriptions)
        .map(([k, v]) => `- ${k}: ${v}`)
        .join("\n");

    const routerPromptOverride = dbConfig?.prompts?.router;
    const prompt = ChatPromptTemplate.fromMessages([
        ["system", getRouterSystemPrompt(routerPromptOverride)],
        ["human", ROUTER_USER_PROMPT],
    ]);

    const schema = makeClassificationSchema(version);
    // Compose structured-output FIRST on each provider, then wrap with fallback.
    // `.withStructuredOutput` is a BaseChatModel method that RunnableWithFallbacks
    // doesn't expose — see llm-factory.ts header for the rationale.
    const structuredLLM = withProviderFallback(
        primary.withStructuredOutput(schema, { includeRaw: true }),
        fallback?.withStructuredOutput(schema, { includeRaw: true }) ?? null,
    );
    const chain = prompt.pipe(structuredLLM);
    const result = (await chain.invoke({
        intent_descriptions: intentDescriptions,
        conversation_history: history,
        current_message: text,
    })) as { parsed: { intent: string; confidence: number }; raw: unknown };

    return {
        intent: normalizeIntentForVersion(result.parsed.intent, version),
        confidence: result.parsed.confidence,
        usage: extractUsage(result.raw),
    };
}

// =============================================================================
// Router Node
// =============================================================================

/**
 * Router node: classifies the current message intent.
 *
 * Strategy: keyword match first (fast + cheap), LLM fallback if no match.
 */
export async function routerNode(
    state: WhatsAppStateType,
): Promise<Partial<WhatsAppStateType>> {
    const currentMessage = state.context?.current_message?.content ?? "";
    const history = formatConversationHistory(state);

    const conversationId = state.context?.metadata?.conversation_id as string | undefined;
    const phone = state.context?.customer?.phone_number;

    const dynamicConfig = await getWhatsAppDynamicConfig();
    const version = dynamicConfig.intentTaxonomyVersion;
    const fallbackIntent = version === "v1" ? IntentType.GENERAL_SUPPORT : IntentType.UNKNOWN;

    try {
        // Paste-history fast path (Deliverable 10): customer pasted WhatsApp
        // export block → bypass classifier, escalate with high priority.
        if (WHATSAPP_PASTE_REGEX.test(currentMessage)) {
            const supabase = getSupabaseClient();
            if (supabase) {
                logAgentThought(supabase, {
                    conversationId,
                    phone,
                    stepName: "intent_classification",
                    thoughtContent: "Paste-history regex matched → complaint_or_frustration, priority=high",
                }).catch(() => {/* non-fatal */ });
            }
            const complaintIntent = version === "v1"
                ? IntentType.ESCALATION
                : IntentType.COMPLAINT_OR_FRUSTRATION;
            return {
                intent: complaintIntent,
                intentConfidence: 1,
                taxonomyVersion: version,
                escalatePriority: "high",
                escalationReasonOverride: "customer_quoting_history",
            };
        }

        // Try keyword classification first
        const keywordResult = classifyByKeywords(currentMessage);

        if (keywordResult) {
            const normalized = normalizeIntentForVersion(keywordResult.intent, version);
            const supabase = getSupabaseClient();
            if (supabase) {
                logAgentThought(supabase, {
                    conversationId,
                    phone,
                    stepName: "intent_classification",
                    thoughtContent: `Keyword match → ${normalized} (confidence ${keywordResult.confidence.toFixed(2)}, taxonomy ${version})`,
                }).catch(() => {/* non-fatal */ });
            }
            return {
                intent: normalized,
                intentConfidence: keywordResult.confidence,
                taxonomyVersion: version,
            };
        }

        // Fall back to LLM
        const llmResult = await classifyByLLM(currentMessage, history, state.laneConfig, version);

        const supabase = getSupabaseClient();
        if (supabase) {
            logAgentThought(supabase, {
                conversationId,
                phone,
                stepName: "intent_classification",
                thoughtContent: `LLM classification → ${llmResult.intent} (confidence ${llmResult.confidence.toFixed(2)}, taxonomy ${version})`,
            }).catch(() => {/* non-fatal */ });
        }

        return {
            intent: llmResult.intent,
            intentConfidence: llmResult.confidence,
            taxonomyVersion: version,
            llmUsage: llmResult.usage,
        };
    } catch (err) {
        // On error, default to safe fallback (general_support in v1, unknown in v2 → clarifier)
        console.error("[router] Classification error:", err);
        return {
            intent: fallbackIntent,
            intentConfidence: 0.3,
            taxonomyVersion: version,
            error: `Router error: ${err instanceof Error ? err.message : String(err)}`,
        };
    }
}

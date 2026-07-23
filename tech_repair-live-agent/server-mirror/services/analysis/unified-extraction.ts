/**
 * Unified Interaction Extraction
 * ==============================
 *
 * Extracts structured insights from both voice call and WhatsApp transcripts
 * using a unified Zod schema and LLM pipeline. Supports both unstructured facts
 * (for semantic memory) and structured CRM fields (for deterministic routing/personalization).
 *
 * Used by:
 * - inbound/agent.ts (voice call end-of-call extraction)
 * - whatsapp/graph/nodes/memory-extraction.ts (WhatsApp GOODBYE intent)
 *
 * @module services/analysis/unified-extraction
 */

import { z } from "zod";
import { createTrackedLLM } from "@/shared/llm-tracker";
import { withRetry } from "@/utils/retry";

// ─── Schemas ───────────────────────────────────────────────────────────────────

/**
 * Unified schema for extracting insights from both voice and WhatsApp interactions.
 * Combines unstructured semantic facts with structured CRM fields.
 */
export const UnifiedInteractionSchema = z.object({
  // Core extraction fields
  customer_facts: z
    .array(z.string())
    .describe(
      "Durable, PERSON-centric facts about the customer for semantic memory (mem0): who they are, their devices, recurring concerns, stated preferences, personal context they share. NOT momentary emotions or one-off logistics."
    ),
  sentiment_score: z
    .number()
    .int()
    .min(1)
    .max(5)
    .describe("Customer sentiment: 1=very negative, 3=neutral, 5=very positive"),
  resolution_status: z
    .enum(["resolved", "pending", "escalated", "unknown"])
    .describe("Whether the customer's issue was resolved or escalated"),
  summary: z
    .string()
    .describe("Brief summary of the interaction in Spanish"),

  // CRM fields
  preferred_name: z
    .string()
    .optional()
    .describe(
      "How the customer wants to be addressed (only if explicitly stated)"
    ),
  primary_device_model: z
    .string()
    .optional()
    .describe(
      "TechRepair device model mentioned (e.g., Galaxy S24 Ultra, Galaxy A52)"
    ),
  warranty_status: z
    .enum(["active", "expired", "unknown"])
    .optional()
    .describe(
      "Known warranty status (only if explicitly stated, otherwise omit)"
    ),
  escalation_risk: z
    .boolean()
    .default(false)
    .describe(
      "True if customer threatened PROFECO, bad review, legal action, or BBB"
    ),

  // Enrichment fields (memory layer improvement)
  customer_claims_repeat_contact: z
    .boolean()
    .default(false)
    .describe(
      "True ONLY if the customer explicitly says they have contacted before about this problem. Do NOT infer this — only set true when customer states it directly."
    ),
  issue_category: z
    .enum(["hardware", "software", "logistics", "warranty", "billing", "general"])
    .optional()
    .describe(
      "Primary issue category: hardware (screen, battery, charging), software (OS, apps), logistics (shipping, pickup), warranty (coverage disputes), billing (payment, refund), general (hours, location, other)"
    ),
  urgency_level: z
    .enum(["low", "medium", "high", "critical"])
    .optional()
    .describe(
      "Customer urgency: low (general inquiry), medium (active repair), high (deadline mentioned), critical (legal threats, PROFECO, device needed urgently)"
    ),
  preferred_contact_channel: z
    .enum(["whatsapp", "voice", "any"])
    .optional()
    .describe(
      "Only if customer explicitly states a contact preference (e.g., 'prefiero que me llamen', 'escríbanme por WhatsApp'). Omit if not stated."
    ),

  // ─── Durable person-knowledge fields (memory layer, person-centric) ───────
  // Stable traits of the PERSON that help the agent treat a returning customer
  // as someone it already knows. Extracted only when the conversation reveals
  // them; optional so functionCalling keeps accepting the schema.
  communication_style: z
    .string()
    .optional()
    .describe(
      "One or two words for HOW the customer communicates, if clearly observable (e.g., 'formal', 'casual', 'breve', 'muy detallado', 'impaciente'). Omit if not clear."
    ),
  personal_context: z
    .string()
    .optional()
    .describe(
      "Durable personal circumstance the customer reveals that should inform future service (e.g., 'trabaja de noche, prefiere mensajes en la mañana', 'el equipo es de su mamá', 'lo necesita para trabajar'). One short phrase in Spanish. Omit if none shared."
    ),

  // ─── Voice-intake fields (written to calls.intake.confirmed) ──────────────
  // These mirror the four parameters operators need to act on a voice call
  // post-hoc: who, what folio, what problem, what kind of call. The agent
  // captures these naturally during the conversation; we extract from the
  // transcript at shutdown rather than asking the LLM to call a tool per fact.
  claimed_caller_name: z
    .string()
    .optional()
    .describe(
      "Name the customer SAID on the call (e.g., 'Soy Juan', 'me llamo Pedro'). Distinct from any name already on file. Omit if the customer never said their name."
    ),
  claimed_model_name: z
    .string()
    .optional()
    .describe(
      "Specific TechRepair model the customer mentioned on this call (e.g., 'Galaxy S25', 'Note 20 Ultra'). May differ from primary_device_model when the customer is asking about a device other than their main one. Omit if not mentioned."
    ),
  reported_symptom: z
    .string()
    .optional()
    .describe(
      "Free-text description of the problem the customer reported (e.g., 'la pantalla parpadea', 'no carga la batería'). One short sentence in Spanish. Omit if no symptom was discussed."
    ),
  call_intent: z
    .enum(["status_check", "quote", "callback", "complaint", "other"])
    .optional()
    .describe(
      "Primary reason for the call: status_check (asking about an existing repair), quote (asking about cost of a new repair), callback (wants someone to call back), complaint (unhappy with prior service), other. Inferred from the conversation arc."
    ),
});

export type UnifiedInteractionInsights = z.infer<
  typeof UnifiedInteractionSchema
>;

// Legacy type for backward compat
export type CallInsights = UnifiedInteractionInsights;

// ─── Extraction Prompt ──────────────────────────────────────────────────────

const EXTRACTION_PROMPT = `Analiza la siguiente transcripción de interacción con TechRepair (llamada o WhatsApp) y extrae:

**Campos Requeridos:**
1. customer_facts: Lista de 3-5 hechos DURABLES y centrados en la PERSONA (quién es, sus dispositivos, preocupaciones recurrentes, preferencias declaradas, contexto personal que comparte). IGNORAR emociones del momento y detalles logísticos de un solo uso.
2. sentiment_score: Puntuación del sentimiento (1=muy frustrado, 3=neutral, 5=muy satisfecho).
3. resolution_status: "resolved", "pending", "escalated", o "unknown".
4. summary: Resumen breve en español.

**Campos Estructurados CRM (extraer SOLO si se menciona explícitamente):**
5. preferred_name: Cómo el cliente quiere ser llamado (ej: "Llámame Pancho" → "Pancho"). Omitir si no se menciona.
6. primary_device_model: Modelo de dispositivo TechRepair mencionado (ej: "Galaxy S24 Ultra", "Galaxy A52"). Omitir si no se menciona.
7. warranty_status: "active" (garantía vigente), "expired" (vencida), o "unknown". Solo si se menciona explícitamente; omitir en caso contrario.
8. escalation_risk: true si el cliente mencionó PROFECO, reseña negativa, acción legal, o BBB. false por defecto.

**Campos de Enriquecimiento:**
9. customer_claims_repeat_contact: true SOLO si el cliente DICE EXPLÍCITAMENTE que ya contactó antes sobre este problema (ej: "ya llamé la semana pasada", "es la tercera vez que pregunto"). NO inferir — solo cuando el cliente lo afirma directamente.
10. issue_category: Categoría principal del problema: "hardware" (pantalla, batería, carga, agua), "software" (sistema, apps), "logistics" (envío, recolección, entrega), "warranty" (cobertura, disputas), "billing" (pago, reembolso), "general" (horarios, ubicación, otro). Omitir si no aplica.
11. urgency_level: "low" (consulta general), "medium" (reparación activa), "high" (plazo mencionado), "critical" (amenaza legal, PROFECO, dispositivo urgente).
12. preferred_contact_channel: Solo si el cliente lo dice explícitamente (ej: "prefiero que me llamen" → "voice", "escríbanme por WhatsApp" → "whatsapp"). Omitir si no se menciona.

**Campos de Intake de Voz (lo que el equipo necesita para dar seguimiento):**
13. claimed_caller_name: El nombre que el cliente DIJO en la llamada (ej: "Soy Juan", "le habla Pedro Martínez"). Omitir si nunca dijo su nombre.
14. claimed_model_name: El modelo TechRepair específico que el cliente mencionó EN ESTA llamada (ej: "Galaxy S25", "Note 20 Ultra"). Puede diferir de primary_device_model. Omitir si no se mencionó.
15. reported_symptom: Descripción en texto libre del problema reportado (ej: "la pantalla parpadea", "no carga la batería"). Una frase corta en español. Omitir si no se habló de ningún síntoma.
16. call_intent: Razón principal de la llamada: "status_check" (preguntar por una reparación existente), "quote" (preguntar el costo de una reparación nueva), "callback" (quiere que le devuelvan la llamada), "complaint" (inconforme con servicio previo), "other".

**Campos de Conocimiento Durable de la Persona (extraer SOLO si la conversación lo revela claramente):**
17. communication_style: Una o dos palabras de CÓMO se comunica el cliente (ej: "formal", "casual", "breve", "muy detallado", "impaciente"). Omitir si no es claro.
18. personal_context: Una circunstancia personal durable que el cliente revela y que debería informar el servicio futuro (ej: "trabaja de noche, prefiere mensajes en la mañana", "el equipo es de su mamá", "lo necesita para trabajar"). Una frase corta en español. Omitir si no comparte ninguna.

**Instrucciones Críticas:**
- Responde SOLO con JSON válido.
- No incluyas campos CRM o de enriquecimiento si no hay evidencia explícita.
- customer_facts debe ser un array de strings.
- customer_claims_repeat_contact captura lo que el CLIENTE DICE, no lo que tú inferirías.
- Los campos de Intake de Voz (13-16) capturan lo que pasó EN ESTA llamada, no historial.`;

/**
 * A successful extraction OR an explicit failure. We deliberately do NOT collapse
 * a failed LLM call into an empty-but-valid insights object: callers stamp a
 * `last_extracted_at` high-water mark on empty results, and a transient failure
 * masquerading as "no facts" would permanently and silently lose that customer's
 * memory (the sweep never reopens a settled conversation). `ok` lets callers tell
 * "we looked and there was nothing" apart from "we never got an answer".
 */
export type ExtractionResult =
  | { ok: true; insights: UnifiedInteractionInsights }
  | { ok: false; error: unknown };

/** Retry policy shared by every extraction call site (was duplicated per caller). */
const EXTRACTION_RETRY = {
  maxAttempts: 3,
  initialDelayMs: 500,
  // Schema/parse errors are deterministic — retrying can't help. Everything else
  // (timeouts, 429s, network blips) is transient and worth retrying.
  retryIf: (err: unknown) =>
    !(err instanceof SyntaxError) && !((err as { constructor?: { name?: string } })?.constructor?.name === "ZodError"),
  onRetry: (err: unknown, attempt: number) => {
    console.warn(`[UnifiedExtraction] Retry attempt ${attempt}:`, err);
  },
};

/** Single LLM invocation. THROWS on any failure so withRetry can act on it. */
async function invokeExtraction(
  transcript: string,
  context?: { conversationId?: string; phone?: string },
): Promise<UnifiedInteractionInsights> {
  const modelName = process.env.OPENAI_MODEL ?? "gpt-4o-mini";
  const model = await createTrackedLLM({
    provider: "openai",
    model: modelName,
    callSite: "unified_extraction",
    context,
  });

  // OpenAI's strict structured-output mode rejects Zod `.optional()` fields,
  // and UnifiedInteractionSchema has many. Function-calling mode accepts
  // optionals — without it every extraction throws and falls back to empty.
  const structuredModel = model.withStructuredOutput(UnifiedInteractionSchema, {
    method: "functionCalling",
  });
  // [sim] type-only cast — zod 3.25 inference drift on .default() fields
  return (await structuredModel.invoke([
    { role: "system", content: EXTRACTION_PROMPT },
    { role: "user", content: transcript },
  ])) as UnifiedInteractionInsights;
}

/**
 * Extract structured insights from a call or WhatsApp transcript.
 * Works with both voice (post-call) and text (WhatsApp) transcripts.
 *
 * Retries transient failures internally (the retry lives here now, not at each
 * caller). Never throws — returns `{ ok: false }` after retries are exhausted so
 * the turn never crashes, but the caller can distinguish failure from empty.
 */
export async function extractInteractionInsights(
  transcript: string,
  context?: { conversationId?: string; phone?: string },
): Promise<ExtractionResult> {
  try {
    const insights = await withRetry(() => invokeExtraction(transcript, context), EXTRACTION_RETRY);
    return { ok: true, insights };
  } catch (err) {
    console.error("[UnifiedExtraction] Failed to extract insights after retries:", err);
    return { ok: false, error: err };
  }
}

/**
 * Legacy function name for backward compatibility.
 * Delegates to extractInteractionInsights() and throws on failure (its callers
 * predate the discriminated result and expect a plain insights object or a throw).
 */
export async function extractCallInsights(transcript: string): Promise<CallInsights> {
  const result = await extractInteractionInsights(transcript);
  if (!result.ok) throw result.error ?? new Error("extraction failed");
  return result.insights;
}

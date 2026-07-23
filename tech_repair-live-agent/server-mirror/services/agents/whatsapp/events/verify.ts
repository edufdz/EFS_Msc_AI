/**
 * Event Verifier (second stage)
 * =============================
 * The keyword detectors are fast but naive — they fire on surface patterns and
 * can't tell "ya me llegó, gracias" (a happy confirmation) from "ya me llegó
 * pero a la dirección equivocada" (a complaint). This verifier runs ONLY when at
 * least one detector fired (so it's cheap), asking a small LLM to confirm or
 * suppress each candidate considering negation, contradiction and sarcasm.
 *
 * Always runs (no flag). On verifier error the fail policy is PER EVENT TYPE
 * (see FAIL_OPEN_TYPES): types whose only effect is a human-side flag fail OPEN
 * (over-flagging is cheap), but order_received — which sends a customer-facing
 * "your order arrived" acuse — fails CLOSED, because emitting that to someone who
 * is actually complaining during an OpenAI outage is a visible wrong message.
 * Every fail-open emits a greppable metric line so a verifier outage is observable.
 *
 * Mirrors the existing EscalationContextChecker pattern (fast signal → LLM
 * confirm before acting).
 */

import { z } from "zod";
import { createTrackedLLM } from "@/shared/llm-tracker";
import type { DetectedEvent, EventDetectionContext } from "./types";

/** Hard cap on the inline verifier LLM call so it never stalls the reply. */
const VERIFY_TIMEOUT_MS = 4000;

/**
 * On verifier failure, which event types survive (fail-open). These only raise a
 * human-side flag, so over-flagging during an outage is low-harm. order_received
 * is deliberately absent — it fails CLOSED because it drives a customer-facing acuse.
 */
const FAIL_OPEN_TYPES = new Set<string>(["payment_receipt", "address"]);

const VerifySchema = z.object({
    events: z.array(
        z.object({
            type: z.string(),
            confirmed: z.boolean(),
            reason: z.string().optional(),
        }),
    ),
});

const VERIFY_PROMPT = `Eres un verificador de eventos en una conversación de servicio TechRepair. Un sistema rápido por palabras clave detectó posibles eventos en el mensaje del cliente. Para CADA evento candidato, decide si es REALMENTE ese evento, considerando negaciones, contradicciones, quejas y sarcasmo.

Tipos de evento:
- order_received: el cliente confirma con gusto/neutral que YA recibió su equipo. Si dice que llegó PERO mal (dirección equivocada, roto, incompleto, tarde con molestia), NO es order_received (confirmed=false) — es una queja.
- address: el cliente menciona, da o pide cambiar SU PROPIO domicilio de entrega. NO confirmado (confirmed=false) si el cliente PREGUNTA por la dirección o ubicación de la TIENDA/sucursal/centro de servicio (ej. "¿cuál es su dirección?", "¿dónde están ubicados?", "pásenme su dirección") — ahí pide un dato, no da el suyo.
- payment_receipt: el cliente envió un comprobante de pago real. Confirmado si el contenido es un recibo/transferencia/depósito.

Ejemplos:
- "ya me llegó, gracias" → order_received confirmed=true
- "ya me llegó pero a la dirección equivocada" → order_received confirmed=false (es queja); address confirmed=true
- "ya me llegó pero está roto" → order_received confirmed=false (queja)
- "no me ha llegado, cambien mi dirección" → address confirmed=true
- "mi domicilio es Av Reforma 123" → address confirmed=true (da el suyo)
- "¿cuál es su dirección? quiero ir a la tienda" → address confirmed=false (pide la de la tienda)
- "¿dónde están ubicados?" → address confirmed=false (pregunta por la tienda)

Devuelve un arreglo "events" con cada {type, confirmed, reason}. Incluye TODOS los candidatos.`;

function buildInput(message: string, candidates: DetectedEvent[]): string {
    const list = candidates
        .map((c) => `- ${c.type}${c.subType ? ` (${c.subType})` : ""}`)
        .join("\n");
    return `Mensaje del cliente:\n"${message}"\n\nEventos candidatos:\n${list}`;
}

/**
 * Confirm/suppress candidate events. Returns the subset that survives. Fail-open.
 */
export async function verifyDetectedEvents(
    candidates: DetectedEvent[],
    ctx: EventDetectionContext,
): Promise<DetectedEvent[]> {
    if (candidates.length === 0) return [];

    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
        const modelName = process.env.OPENAI_MODEL ?? "gpt-4o-mini";
        const model = await createTrackedLLM({
            provider: "openai",
            model: modelName,
            callSite: "event_verifier",
            // The verifier runs INLINE on the customer-facing turn. Cap the
            // per-call timeout so an OpenAI slowdown can't stall the reply; no
            // retries (the outer race below would fire before a retry helps).
            extras: { timeout: VERIFY_TIMEOUT_MS, maxRetries: 0 },
        });
        const structured = model.withStructuredOutput(VerifySchema, {
            method: "functionCalling",
        });

        // Hard deadline regardless of client behavior — on timeout we fail open
        // (the catch below returns the candidates unchanged).
        const result = (await Promise.race([
            structured.invoke([
                { role: "system", content: VERIFY_PROMPT },
                { role: "user", content: buildInput(ctx.message, candidates) },
            ]),
            new Promise<never>((_, reject) => {
                timer = setTimeout(
                    () => reject(new Error("event verifier timeout")),
                    VERIFY_TIMEOUT_MS + 500,
                );
            }),
        ])) as z.infer<typeof VerifySchema>;

        // Map verdicts by type. Keep a candidate unless the verifier explicitly
        // said confirmed=false (fail-open on anything it didn't address).
        const suppressed = new Set(
            result.events.filter((e) => e.confirmed === false).map((e) => e.type),
        );
        const kept = candidates.filter((c) => !suppressed.has(c.type));

        if (kept.length !== candidates.length) {
            console.info(
                `[event-verify] suppressed: ${[...suppressed].join(", ")} (from ${candidates
                    .map((c) => c.type)
                    .join(", ")})`,
            );
        }
        return kept;
    } catch (err) {
        // Per-type fail policy: keep human-flag types, drop customer-facing ones.
        const kept = candidates.filter((c) => FAIL_OPEN_TYPES.has(c.type));
        const dropped = candidates.filter((c) => !FAIL_OPEN_TYPES.has(c.type));
        // Greppable metric line — count these to detect a verifier outage.
        console.warn(
            `[event-verify] fail-open verifier_error kept=[${kept.map((c) => c.type).join(",")}] dropped_fail_closed=[${dropped.map((c) => c.type).join(",")}]:`,
            err,
        );
        return kept;
    } finally {
        if (timer) clearTimeout(timer);
    }
}

/**
 * Structured Escalation Taxonomy for Maria (TechRepair WhatsApp AI)
 * ==============================================================
 * Replaces free-text `escalation_reason` strings with a typed Zod enum and
 * a `renderHandoff()` generator that produces a short (15–30 word) Spanish
 * message naming the concrete team that's taking over. The handoff line is
 * sent to the customer BEFORE the conversation is marked escalated — no
 * more generic "transferida a un agente humano" bounce.
 *
 * Why this exists: the human escalation queue runs at 0.66% resolution
 * partly because moderators have no structured triage signal, and
 * customers re-ping after the bounce because it feels like abandonment
 * rather than a handoff. Typed reasons + named-handler copy changes
 * ergonomics at both ends.
 */

import { z } from "zod";

// =============================================================================
// Enum
// =============================================================================

/**
 * Every escalation must map to one of these values. Free-text reasons are
 * no longer accepted downstream — the dashboard filters by this enum and
 * each value carries a pre-authored handoff message.
 */
export const EscalationReasonSchema = z.enum([
    // Logistics (handled by logística)
    "address_change",
    "tracking_guide_request",
    "tracking_guide_email",
    "shipping_eta_carrier_chase",
    "missing_accessory",
    "return_damage_claim",

    // Finance (handled by finanzas)
    "payment_confirmation",
    "payment_submitted",
    "payment_pending",

    // Technical / quote (handled by técnico)
    "final_quote_request",
    "technical_report_request",
    "diagnosis_dispute",
    "new_symptom_report",
    "post_repair_warranty_claim",

    // Workflow / service-change (handled by asesor / equipo)
    "cancel_repair_request",
    "replacement_request",
    "document_received_confirm",
    "so_record_missing_contact",

    // Signal-driven (handled by asesor)
    "customer_quoting_history",
    "repeated_lookup_failure",
    "complaint_escalation",
    "explicit_human_request",

    // Fallback
    "unknown_hard_question",
]);

export type EscalationReason = z.infer<typeof EscalationReasonSchema>;

// =============================================================================
// Priority map
// =============================================================================

export type EscalationPriority = "normal" | "high";

export const PRIORITY_MAP: Record<EscalationReason, EscalationPriority> = {
    complaint_escalation: "high",
    customer_quoting_history: "high",
    payment_pending: "high",
    return_damage_claim: "high",

    address_change: "normal",
    tracking_guide_request: "normal",
    tracking_guide_email: "normal",
    payment_confirmation: "normal",
    payment_submitted: "normal",
    final_quote_request: "normal",
    technical_report_request: "normal",
    diagnosis_dispute: "normal",
    cancel_repair_request: "normal",
    replacement_request: "normal",
    shipping_eta_carrier_chase: "normal",
    missing_accessory: "normal",
    post_repair_warranty_claim: "normal",
    document_received_confirm: "normal",
    new_symptom_report: "normal",
    so_record_missing_contact: "normal",
    repeated_lookup_failure: "normal",
    explicit_human_request: "normal",
    unknown_hard_question: "normal",
};

// =============================================================================
// Handoff copy
// =============================================================================

export type Register = "formal" | "informal" | "default_formal";

export interface HandoffContext {
    /** Optional first name to include in the handoff (not used by all reasons). */
    customerFirstName?: string | null;
    /** Optional service-order number — some templates reference it inline. */
    svcOrderNo?: string | null;
    /** Pronoun register — defaults to formal when unknown. */
    register?: Register;
    /**
     * Real store direct line. When provided AND the reason is in
     * STORE_PHONE_REASONS (the human-frustration cluster), renderHandoff
     * appends an offer to call the store directly — so a frustrated customer
     * who isn't getting resolution reaches a person, not the AI line. Omit it
     * (or use a non-store reason) and the handoff is unchanged.
     */
    storePhone?: string | null;
}

/**
 * Reasons where offering the live store line helps the customer. These are the
 * "I need a human now / I'm frustrated / I'm not getting resolution" cluster —
 * a phone call to a person is genuinely faster than a WhatsApp callback here.
 *
 * Finance / logistics / technical reasons are intentionally excluded: those
 * need backend work (confirming a payment, generating a guide, a technician's
 * quote) that a phone call cannot accelerate, so they stay callback-by-WhatsApp.
 */
export const STORE_PHONE_REASONS: ReadonlySet<EscalationReason> = new Set([
    "complaint_escalation",
    "explicit_human_request",
    "customer_quoting_history",
    // Candidate for inclusion once detectRepetitionBreak's
    // `repeated_lookup_failure` signal is wired into a live escalation path
    // (it is defined but unconsumed today).
]);

/**
 * Whether a given reason should append the store-phone offer (and the context
 * actually carries a store number).
 */
export function offersStorePhone(
    reason: EscalationReason,
    ctx: HandoffContext,
): boolean {
    return STORE_PHONE_REASONS.has(reason) && isValidStorePhone(ctx.storePhone);
}

function isValidStorePhone(value: unknown): value is string {
    return typeof value === "string" && /^\+?\d{10,15}$/.test(value.trim());
}

interface Variants {
    formal: string;
    informal: string;
}

/**
 * Canonical handoff copy per reason. Derived from 130+ human-agent replies
 * so the bot's handoff tone matches how humans actually open a takeover.
 * Rules (enforced by tests):
 *   - Each string is 15–30 words.
 *   - Each string names a concrete handler (logística, finanzas, asesor,
 *     técnico, equipo, or paquetería).
 *   - No emojis. No bullets. No markdown.
 */
const HANDOFF_COPY: Record<EscalationReason, Variants> = {
    address_change: {
        formal:
            "Le pido al equipo de logística que ajuste la dirección. Le confirman por este medio antes de que salga el envío.",
        informal:
            "Le pido al equipo de logística que ajuste la dirección. Te confirman por este medio antes de que salga el envío.",
    },
    tracking_guide_request: {
        formal:
            "La guía se genera cuando su equipo pase a envío. En cuanto la paquetería la emita, le llega por este medio.",
        informal:
            "La guía se genera cuando tu equipo pase a envío. En cuanto la paquetería la emita, te llega por este medio.",
    },
    tracking_guide_email: {
        formal:
            "Aviso a logística para que le reenvíen la guía al correo registrado. Si necesita actualizar el correo, avíseme para confirmarlo.",
        informal:
            "Aviso a logística para que te reenvíen la guía al correo registrado. Si necesitas actualizar el correo, avísame para confirmarlo.",
    },
    payment_confirmation: {
        formal:
            "El área de finanzas confirma los pagos. Les aviso de su caso, le responden en cuanto lo validen.",
        informal:
            "El área de finanzas confirma los pagos. Les aviso de tu caso, te responden en cuanto lo validen.",
    },
    payment_submitted: {
        formal:
            "Recibido, paso su comprobante con finanzas. Ellos confirman la aplicación del pago y le responden por aquí.",
        informal:
            "Recibido, paso tu comprobante con finanzas. Ellos confirman la aplicación del pago y te responden por aquí.",
    },
    payment_pending: {
        formal:
            "Le conecto con un asesor de finanzas para confirmar el pago de su orden y darle seguimiento por este medio.",
        informal:
            "Te conecto con un asesor de finanzas para confirmar el pago de tu orden y darte seguimiento por este medio.",
    },
    final_quote_request: {
        formal:
            "La cotización final la emite el técnico por correo una vez terminado el diagnóstico. Le aviso al equipo para que se la envíen.",
        informal:
            "La cotización final la emite el técnico por correo una vez terminado el diagnóstico. Les aviso para que te la manden.",
    },
    technical_report_request: {
        formal:
            "El reporte técnico se lo envía el técnico al correo registrado. Le aviso a logística para que se lo reenvíen.",
        informal:
            "El reporte técnico te lo envía el técnico al correo registrado. Aviso a logística para que te lo reenvíen.",
    },
    diagnosis_dispute: {
        formal:
            "Paso su comentario con el técnico para que revise el diagnóstico nuevamente. Le contactan con la respuesta.",
        informal:
            "Paso tu comentario con el técnico para que revise el diagnóstico nuevamente. Te contactan con la respuesta.",
    },
    cancel_repair_request: {
        formal:
            "Le conecto con un asesor del equipo para procesar la cancelación de su orden y confirmarle los pasos por este medio.",
        informal:
            "Te conecto con un asesor del equipo para procesar la cancelación de tu orden y confirmarte los pasos por este medio.",
    },
    replacement_request: {
        formal:
            "Paso su solicitud de reposición con el equipo para que la revisen. Le contactan con la respuesta.",
        informal:
            "Paso tu solicitud de reposición con el equipo para que la revisen. Te contactan con la respuesta.",
    },
    shipping_eta_carrier_chase: {
        formal:
            "Verifico con el equipo de logística qué dice la paquetería. Le responden hoy mismo con el detalle.",
        informal:
            "Verifico con el equipo de logística qué dice la paquetería. Te responden hoy mismo con el detalle.",
    },
    missing_accessory: {
        formal:
            "Paso el reporte del accesorio faltante con logística para que revisen el paquete recibido. Le contactan con el resultado.",
        informal:
            "Paso el reporte del accesorio faltante con logística para que revisen el paquete recibido. Te contactan con el resultado.",
    },
    return_damage_claim: {
        formal:
            "Lamento que haya llegado así. Paso el caso con el equipo de logística de inmediato para revisar el envío.",
        informal:
            "Lamento que haya llegado así. Paso el caso con el equipo de logística de inmediato para revisar el envío.",
    },
    post_repair_warranty_claim: {
        formal:
            "Le conecto con el técnico y el equipo para revisar la garantía post-reparación de su equipo. Le responden con el seguimiento por aquí.",
        informal:
            "Te conecto con el técnico y el equipo para revisar la garantía post-reparación de tu equipo. Te responden con el seguimiento por aquí.",
    },
    document_received_confirm: {
        formal:
            "Recibido, confirmo con el equipo que lo tengan registrado en su orden y le responden por este medio con el acuse.",
        informal:
            "Recibido, confirmo con el equipo que lo tengan registrado en tu orden y te responden por este medio con el acuse.",
    },
    new_symptom_report: {
        formal:
            "Gracias por avisar. Paso la nota con el técnico para que la valide y le responde por aquí.",
        informal:
            "Gracias por avisar. Paso la nota con el técnico para que la valide y te responde por aquí.",
    },
    so_record_missing_contact: {
        formal:
            "Un momento, necesito que alguien del equipo revise los datos de su orden. Le responden en breve.",
        informal:
            "Un momento, necesito que alguien del equipo revise los datos de tu orden. Te responden en breve.",
    },
    customer_quoting_history: {
        formal:
            "Entiendo la frustración. Un asesor del equipo toma su caso directamente y le responde por este medio en los próximos minutos.",
        informal:
            "Entiendo la frustración. Un asesor del equipo toma tu caso directamente y te responde por este medio en los próximos minutos.",
    },
    repeated_lookup_failure: {
        formal:
            "Déjeme pasar esto con el equipo, necesitan revisar sus datos manualmente. Le responden en breve.",
        informal:
            "Déjame pasar esto con el equipo, necesitan revisar tus datos manualmente. Te responden en breve.",
    },
    complaint_escalation: {
        formal:
            "Un asesor del equipo toma su caso directamente en los próximos minutos para darle seguimiento puntual y resolver la situación.",
        informal:
            "Un asesor del equipo toma tu caso directamente en los próximos minutos para darte seguimiento puntual y resolver la situación.",
    },
    explicit_human_request: {
        formal:
            "Por supuesto, un asesor del equipo le atiende en breve por este mismo medio para darle seguimiento personalizado.",
        informal:
            "Por supuesto, un asesor del equipo te atiende en breve por este mismo medio para darte seguimiento personalizado.",
    },
    unknown_hard_question: {
        formal:
            "Un asesor del equipo le atiende directamente por este medio para resolver esto con la información que necesita.",
        informal:
            "Un asesor del equipo te atiende directamente por este medio para resolver esto con la información que necesitas.",
    },
};

/**
 * Render the customer-facing handoff message for the given reason.
 * `register` defaults to formal when omitted or set to `default_formal`.
 */
export function renderHandoff(
    reason: EscalationReason,
    ctx: HandoffContext = {},
): string {
    const register = ctx.register ?? "default_formal";
    const variants = HANDOFF_COPY[reason];
    const base = register === "informal" ? variants.informal : variants.formal;

    // For the human-frustration cluster, append a direct-store offer so the
    // customer reaches a person now instead of waiting on a WhatsApp callback.
    // Appended AFTER the canonical copy on purpose — the 15–30-word / named-
    // handler invariants are enforced against the canonical strings only.
    if (offersStorePhone(reason, ctx)) {
        const phone = (ctx.storePhone as string).trim();
        const offer =
            register === "informal"
                ? `Si prefieres hablar de inmediato, marca directamente a la tienda al ${phone}.`
                : `Si prefiere hablar de inmediato, marque directamente a la tienda al ${phone}.`;
        return `${base} ${offer}`;
    }

    return base;
}

/**
 * Convenience: priority lookup for a reason.
 */
export function priorityFor(reason: EscalationReason): EscalationPriority {
    return PRIORITY_MAP[reason];
}

/**
 * Type guard — is the given string a valid EscalationReason? Useful at
 * boundaries where we receive a raw string from state or an LLM marker.
 */
export function isEscalationReason(value: unknown): value is EscalationReason {
    return EscalationReasonSchema.safeParse(value).success;
}

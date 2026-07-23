/**
 * Detector — Orden recibida
 * =========================
 * The customer confirms they got their device. Text-only; fires on clear
 * positive confirmations and NOT on negatives ("sigo esperando", "ya casi").
 * The agent acknowledges warmly (botReply) and a human is flagged so they can
 * close the case / trigger a satisfaction survey.
 *
 * Matching runs on accent-normalized text (see ./text) because accents break
 * `\b` word boundaries in JS regex.
 */

import { getActiveOrders } from "@/services/agents/whatsapp/graph/state";
import type { DetectedEvent, EventDetectionContext, EventDetector } from "../types";
import { normalize } from "../text";

// Negatives FIRST — if any match, this is NOT a confirmation of receipt.
const NEGATIVE = [
    /\bno me ha llegado\b/,
    /\bno (me )?ha\b.*\blleg/,
    /\bsigo esperando\b/,
    /\baun no\b/,
    /\btodavia no\b/,
    /\bcuando (me )?(va a )?lleg/,
    /\bya casi\b/,
    /\bcuando lo recibo\b/,
];

// Positive confirmations of receipt (accent-free).
const POSITIVE = [
    /\bya me llego\b/,
    /\bya llego\b/,
    /\bya lo recibi\b/,
    /\bya la recibi\b/,
    /\blo recibi\b/,
    /\bya me (lo )?entregaron\b/,
    /\bya lo tengo\b/,
    /\bya me entregaron\b/,
    /\bme llego (mi|el)\b/,
];

export const orderReceivedDetector: EventDetector = {
    name: "order_received",
    async detect(ctx: EventDetectionContext): Promise<DetectedEvent | null> {
        if (ctx.messageType !== "text") return null;
        const msg = normalize(ctx.message ?? "");
        if (!msg) return null;

        if (NEGATIVE.some((re) => re.test(msg))) return null;
        if (!POSITIVE.some((re) => re.test(msg))) return null;

        const svcOrderNo = getActiveOrders(ctx.state)[0]?.svc_order_no;

        return {
            type: "order_received",
            label: svcOrderNo
                ? `📦 Cliente confirmó que recibió su orden ${svcOrderNo}`
                : "📦 Cliente confirmó que recibió su orden",
            details: svcOrderNo ? { svc_order_no: svcOrderNo } : {},
            botReply: "¡Qué gusto que ya lo tienes! 🙌 Cualquier cosa, aquí estamos.",
        };
    },
};

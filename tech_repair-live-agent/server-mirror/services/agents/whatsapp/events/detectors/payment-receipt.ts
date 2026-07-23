/**
 * Detector — Comprobante de pago
 * ==============================
 * Payment receipts arrive as IMAGES or PDFs. The media pipeline already
 * transcribes them (Claude Vision for images, Gemini for PDFs); those prompts
 * now prefix a receipt with the [COMPROBANTE] marker. This detector reads the
 * transcript that reaches the turn as `message` and fires when it is a receipt
 * (marker, or ≥2 payment keywords as a fallback).
 *
 * The agent acknowledges without confirming the payment is valid (a human in
 * finance verifies it), and the escalation flags it for that human.
 */

import { getActiveOrders } from "@/services/agents/whatsapp/graph/state";
import type { DetectedEvent, EventDetectionContext, EventDetector } from "../types";
import { normalize } from "../text";

const RECEIPT_MARKER = /\[comprobante\]/i;

const RECEIPT_KEYWORDS = [
    /\bcomprobante\b/,
    /\btransferencia\b/,
    /\bdeposito\b/,
    /\bspei\b/,
    /\breferencia\b/,
    /\bmonto\b/,
    /\bpago (realizado|efectuado|recibido)\b/,
    /\bclabe\b/,
    /\$\s?\d/,
];

export const paymentReceiptDetector: EventDetector = {
    name: "payment_receipt",
    async detect(ctx: EventDetectionContext): Promise<DetectedEvent | null> {
        // Receipts are media (image or PDF/document), never plain text.
        if (ctx.messageType !== "image" && ctx.messageType !== "document") return null;
        const raw = ctx.message ?? "";
        if (!raw) return null;

        const norm = normalize(raw);
        const isReceipt =
            RECEIPT_MARKER.test(raw) ||
            RECEIPT_KEYWORDS.filter((re) => re.test(norm)).length >= 2;
        if (!isReceipt) return null;

        const svcOrderNo = getActiveOrders(ctx.state)[0]?.svc_order_no;

        return {
            type: "payment_receipt",
            label: svcOrderNo
                ? `💳 Comprobante de pago enviado (orden ${svcOrderNo})`
                : "💳 Comprobante de pago enviado",
            details: {
                svc_order_no: svcOrderNo ?? null,
                media_type: ctx.messageType,
                transcript: raw.slice(0, 300),
            },
            botReply: "Recibí tu comprobante 📄, lo paso a revisión y te confirmamos en breve.",
        };
    },
};

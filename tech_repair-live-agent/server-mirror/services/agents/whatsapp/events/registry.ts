/**
 * Event Detection — Registry
 * ==========================
 * The list of active detectors and the runner that fans out over them. To add a
 * new event, implement an EventDetector and push it here — nothing else changes.
 * Detectors run in parallel and each is isolated: a thrown detector yields null
 * and never blocks the turn.
 */

import type { DetectedEvent, EventDetectionContext, EventDetector } from "./types";
import { orderReceivedDetector } from "./detectors/order-received";
import { addressDetector } from "./detectors/address";
import { paymentReceiptDetector } from "./detectors/payment-receipt";

// Detectors are registered here as they land. Adding an event = adding a line.
export const EVENT_DETECTORS: EventDetector[] = [
    orderReceivedDetector,
    addressDetector,
    paymentReceiptDetector,
];

/**
 * Run every registered detector against the turn and return the events that
 * fired. Order-independent; safe — a detector error is logged and dropped.
 */
export async function runEventDetectors(
    ctx: EventDetectionContext,
): Promise<DetectedEvent[]> {
    if (EVENT_DETECTORS.length === 0) return [];

    const results = await Promise.all(
        EVENT_DETECTORS.map((detector) =>
            detector.detect(ctx).catch((err) => {
                console.warn(`[event-detector:${detector.name}] failed (non-fatal):`, err);
                return null;
            }),
        ),
    );

    return results.filter((event): event is DetectedEvent => event !== null);
}

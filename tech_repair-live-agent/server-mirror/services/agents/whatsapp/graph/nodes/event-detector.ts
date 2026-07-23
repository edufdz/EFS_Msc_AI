/**
 * Event Detector Node
 * ===================
 * Runs FIRST on every inbound turn (START → event_detector → router), before
 * intent routing, so business-critical customer actions (payment receipt,
 * address mention, order received) are spotted regardless of intent. It only
 * records what it detected into state.detectedEvents — the escalation + acuse
 * happen downstream so this node stays side-effect-free and fast.
 */

import type { WhatsAppStateType } from "@/services/agents/whatsapp/graph/state";
import { runEventDetectors } from "@/services/agents/whatsapp/events/registry";
import { verifyDetectedEvents } from "@/services/agents/whatsapp/events/verify";

export async function eventDetectorNode(
    state: WhatsAppStateType,
): Promise<Partial<WhatsAppStateType>> {
    const message = state.context?.current_message?.content ?? "";
    const messageType = state.context?.current_message?.type ?? "text";

    // Stage 1: fast keyword detectors. Stage 2 (AI verifier) runs ONLY if a
    // candidate fired — it confirms/suppresses based on context (negation,
    // contradiction, sarcasm) so we never act on a false positive like
    // "ya me llegó pero a la dirección equivocada".
    const candidates = await runEventDetectors({ message, messageType, state });
    const detectedEvents =
        candidates.length > 0
            ? await verifyDetectedEvents(candidates, { message, messageType, state })
            : candidates;

    if (detectedEvents.length > 0) {
        console.info(
            `[event-detector] fired: ${detectedEvents.map((e) => e.type).join(", ")}`,
        );
    }

    return { detectedEvents };
}

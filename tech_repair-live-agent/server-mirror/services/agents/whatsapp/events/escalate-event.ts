/**
 * Escalate a Detected Event
 * =========================
 * Turns a DetectedEvent into an immediate, TAGGED escalation for a human plus an
 * interaction_history row for the "Interactions" view.
 *
 * IMPORTANT: this does NOT flip the conversation to 'escalated' and does NOT send
 * a handoff message — these are FLAGS for human attention (verify the address,
 * register the payment), not a full handoff. The AI keeps handling the chat; the
 * customer-facing acuse (if any) is decided separately by the bot-reply step.
 *
 * Dedup: one open escalation per (conversation, event type) so a customer who
 * mentions their address three times doesn't spawn three escalations — but the
 * interaction timeline still records each mention.
 */

import type { SupabaseClient } from "@supabase/supabase-js";
import { EscalatedTaskRepository } from "@/db/repositories/escalated-task.repository";
import { sendEscalationPush } from "@/services/notifications/push-bridge";
import type { DetectedEvent } from "./types";

export interface EscalateEventArgs {
    appId?: string;
    conversationId?: string;
    phone: string;
    customerName?: string | null;
    event: DetectedEvent;
}

async function recordEventInteraction(
    supabase: SupabaseClient,
    phone: string,
    event: DetectedEvent,
): Promise<void> {
    const svcOrderNo =
        typeof event.details?.svc_order_no === "string"
            ? (event.details.svc_order_no as string)
            : null;
    const { error } = await supabase.from("interaction_history").insert({
        phone,
        channel: "whatsapp",
        topic: `event:${event.type}`,
        summary: event.label,
        agent_type: "system",
        svc_order_no: svcOrderNo,
        created_at: new Date().toISOString(),
    });
    if (error) {
        console.warn("[escalate-event] interaction insert failed (non-fatal):", error.message);
    }
}

export async function escalateDetectedEvent(
    supabase: SupabaseClient,
    args: EscalateEventArgs,
): Promise<void> {
    const { appId, conversationId, phone, customerName, event } = args;
    if (!phone) return;

    try {
        // Dedup: skip a new escalation if an OPEN one of the same event type
        // already exists for this conversation — but still log the interaction.
        if (conversationId) {
            const { data: existing, error: dedupErr } = await supabase
                .from("escalated_tasks")
                .select("id")
                .eq("conversation_id", conversationId)
                .eq("raw_analysis->>event_type", event.type)
                .not("status", "in", "(resolved,dismissed)")
                .limit(1);
            if (dedupErr) {
                // Can't confirm whether an open escalation already exists. Don't
                // let this silently fall through to create — that's how a transient
                // query error becomes a duplicate. Log it and proceed deliberately:
                // for these human-flag events, an explained duplicate is safer than
                // dropping a payment/address flag.
                console.warn(
                    `[escalate-event] dedup query failed for ${event.type}; proceeding to create:`,
                    dedupErr.message,
                );
            } else if (existing && existing.length > 0) {
                await recordEventInteraction(supabase, phone, event);
                return;
            }
        }

        const repo = new EscalatedTaskRepository(supabase);
        await repo.create({
            app_id: appId,
            conversation_id: conversationId,
            source_type: "whatsapp",
            customer_name: customerName ?? undefined,
            customer_phone: phone,
            ai_summary: event.label, // human-visible headline, e.g. "VERIFICAR DIRECCIÓN…"
            raw_analysis: {
                event_type: event.type,
                sub_type: event.subType ?? null,
                trigger: "event_detector",
                ...event.details,
            },
        });

        sendEscalationPush({
            target_role: "ADMIN",
            org_id: "default",
            title: "Evento detectado",
            body: `${customerName || phone}: ${event.label}`,
        }).catch((err: unknown) =>
            console.error("[escalate-event] push failed:", err),
        );

        await recordEventInteraction(supabase, phone, event);
    } catch (err) {
        // payment_receipt/address are business-critical human flags (a customer's
        // payment proof, a delivery-address correction). A dropped flag here has no
        // retry and no other signal, so surface it at error level for alerting
        // rather than burying it as a non-fatal warning.
        const critical = event.type === "payment_receipt" || event.type === "address";
        const logFn = critical ? console.error : console.warn;
        logFn(
            `[escalate-event] ${critical ? "DROPPED business-critical flag" : "failed"} for ${event.type} — manual follow-up may be required:`,
            err,
        );
    }
}

/**
 * AssembledContext Builder
 * ========================
 * Simulation-side replacement for pulpoo-final's gateway/orchestrator
 * context assembly: builds the exact `AssembledContext` shape the WhatsApp
 * agent expects, sourcing the customer and active orders from the fake DB
 * (same tables the production assembler reads from Supabase).
 */

import type { AssembledContext } from "@/services/agents/whatsapp/models";
import { STATUS_CODE_LABELS } from "@/services/gspn/constants";
import type { FakeSupabaseClient } from "./fake-db/fake-supabase";
import { FAKE_CUSTOMER } from "./fake-db/seed";

export interface SessionState {
    sessionId: string;
    history: Array<{ role: string; content: string; timestamp: string }>;
    laneId: 1 | 2 | undefined;
    turnCount: number;
}

const ACTIVE_STATUSES_EXCLUDED = new Set(["ST050", "ST055"]); // delivered / closed

/**
 * Message type resolution. Phase C's connector only sends text, so media
 * turns are simulated with the same markers the production media pipeline
 * prefixes onto transcripts: "[COMPROBANTE] ..." arrives as an image
 * (payment receipt), "[imagen]"/"[documento]" force those types too.
 */
export function resolveMessageType(message: string, explicit?: string): string {
    if (explicit) return explicit;
    if (/\[comprobante\]/i.test(message)) return "image";
    if (/^\[imagen\]/i.test(message)) return "image";
    if (/^\[documento\]/i.test(message)) return "document";
    return "text";
}

export async function buildAssembledContext(
    client: FakeSupabaseClient,
    session: SessionState,
    message: string,
    messageType = "text",
): Promise<AssembledContext> {
    const nowIso = new Date().toISOString();

    // Customer profile from the fake CRM
    const { data: memory } = await client
        .from("customer_memory")
        .select("*")
        .eq("phone", FAKE_CUSTOMER.phone)
        .maybeSingle();

    // Active (non-terminal) service orders for this customer
    const { data: orders } = await client
        .from("service_orders")
        .select("*")
        .eq("contact_no", FAKE_CUSTOMER.localPhone);

    const activeOrders = ((orders ?? []) as Record<string, any>[])
        .filter((o) => !ACTIVE_STATUSES_EXCLUDED.has(o.status))
        .map((o) => ({
            svc_order_no: String(o.svc_order_no),
            status: String(o.status),
            status_label: STATUS_CODE_LABELS[o.status] ?? String(o.status),
            model_name: o.model_name ?? undefined,
            repair_cost_mxn: typeof o.repair_cost_mxn === "number" ? o.repair_cost_mxn : undefined,
            warranty_type: o.warranty_type ?? undefined,
            estimated_completion: o.estimated_completion ?? undefined,
            is_d2d: o.is_d2d === true,
            service_type: (o.service_type ?? null) as "d2d" | "carry_in" | "other" | null,
            iris_condition_desc: o.iris_condition_desc ?? undefined,
            iris_symptom_desc: o.iris_symptom_desc ?? undefined,
            iris_defect_desc: o.iris_defect_desc ?? undefined,
            iris_repair_desc: o.iris_repair_desc ?? undefined,
        }));

    return {
        session: {
            window_open: true,
            window_expires_at: new Date(Date.now() + 23 * 3600_000).toISOString(),
            minutes_remaining: 23 * 60,
            requires_template: false,
        },
        customer: {
            phone_number: FAKE_CUSTOMER.phone,
            wa_id: FAKE_CUSTOMER.waId,
            name: (memory?.name as string | undefined) ?? FAKE_CUSTOMER.name,
            customer_id: (memory?.customer_id as string | undefined) ?? FAKE_CUSTOMER.customerId,
            interaction_count: (memory?.interaction_count as number | undefined) ?? 0,
        },
        active_orders: activeOrders,
        conversation_history: session.history,
        current_message: {
            id: `wamid.sim.${session.sessionId}.${session.turnCount}`,
            type: messageType,
            content: message,
            timestamp: nowIso,
        },
        metadata: {
            conversation_id: session.sessionId,
            ...(session.laneId ? { lane_id: session.laneId } : {}),
            channel: "whatsapp",
            simulation: true,
        },
    };
}

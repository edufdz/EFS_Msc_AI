/**
 * Customer Corrections
 * ====================
 * Parses `[CORRECT:field|value|reason]` markers emitted by the WhatsApp
 * agent in response to explicit customer corrections, validates them
 * against a server-side whitelist, and persists them via AgentMemory.
 *
 * Why a marker (not a LangChain tool): the support node makes a single
 * `chain.invoke()` call rather than running a tool-loop. The existing
 * `[ESCALATE:X]` marker pattern is the in-tree convention for agent
 * side-effects; this follows the same shape.
 *
 * Whitelist rationale:
 *   - preferred_name        — pure customer preference; safe to accept
 *   - primary_device_model  — when GSPN has no order on file yet
 *
 * Deliberately excluded:
 *   - phone / email   → require human verification in GSPN
 *   - warranty_status → only TechRepair's authoritative system can say
 *   - address         → escalate to human (see SUPPORT rule 19)
 */

import type { SupabaseClient } from "@supabase/supabase-js";
import { AgentMemory } from "@/shared/memory";

const CORRECT_MARKER_RE = /\[CORRECT:([^|\]]+)\|([^|\]]+)\|([^\]]+)\]/g;

const ALLOWED_FIELDS = new Set([
    "preferred_name",
    "primary_device_model",
]);

const MAX_VALUE_LEN = 200;
const MAX_REASON_LEN = 500;

export interface ParsedCorrection {
    field: "preferred_name" | "primary_device_model";
    value: string;
    reason: string;
}

export interface CorrectionResult {
    applied: ParsedCorrection[];
    rejected: Array<{ raw: string; error_code: string }>;
    cleanText: string;
}

/**
 * Extract all `[CORRECT:...]` markers from the LLM's response text,
 * validate each, and return the parsed-and-validated corrections plus
 * the text with the markers stripped out.
 *
 * Validation failures are collected, not thrown — the LLM should never
 * crash the response just because it formatted a marker wrong.
 */
export function parseCorrections(text: string): CorrectionResult {
    const applied: ParsedCorrection[] = [];
    const rejected: Array<{ raw: string; error_code: string }> = [];

    const matches = Array.from(text.matchAll(CORRECT_MARKER_RE));
    for (const m of matches) {
        const raw = m[0];
        const field = m[1].trim();
        const value = m[2].trim();
        const reason = m[3].trim();

        if (!ALLOWED_FIELDS.has(field)) {
            rejected.push({ raw, error_code: "field_not_whitelisted" });
            continue;
        }
        if (!value || value.length > MAX_VALUE_LEN) {
            rejected.push({ raw, error_code: "value_invalid_length" });
            continue;
        }
        if (!reason || reason.length > MAX_REASON_LEN) {
            rejected.push({ raw, error_code: "reason_invalid_length" });
            continue;
        }

        applied.push({
            field: field as ParsedCorrection["field"],
            value,
            reason,
        });
    }

    // Strip every marker (applied or rejected) — the customer must never see them.
    const cleanText = text.replace(CORRECT_MARKER_RE, "").replace(/\s+$/gm, "").trim();

    return { applied, rejected, cleanText };
}

/**
 * Persist applied corrections. Updates `customer_memory` for whitelisted
 * fields and appends one `interaction_history` row per correction with
 * `metadata.source='human_correction'` so audit can show the chain
 * "customer said X → agent emitted marker → DB updated to Y".
 *
 * Non-throwing: a DB hiccup must not break the customer's reply. Errors
 * are logged and the caller proceeds. The reply has already been generated.
 */
export async function applyCorrections(args: {
    phone: string;
    corrections: ParsedCorrection[];
    supabase: SupabaseClient;
    conversationId?: string;
}): Promise<void> {
    if (args.corrections.length === 0) return;

    const memory = new AgentMemory(args.supabase);
    const now = new Date().toISOString();

    for (const c of args.corrections) {
        try {
            // 1. Update customer_memory via the existing typed updater.
            //    Only the two whitelisted fields land here — no raw column passthrough.
            await memory.updateCustomerProfile(args.phone, {
                [c.field === "preferred_name"
                    ? "preferredName"
                    : "primaryDeviceModel"]: c.value,
            });

            // 2. Append an interaction_history audit row. agent_type='maria'
            //    aligns with the per-turn instrumentation rows so the
            //    Memory & Context tab can show corrections alongside turns.
            await args.supabase.from("interaction_history").insert({
                phone: args.phone,
                channel: "whatsapp",
                topic: "customer_correction",
                summary: `Correction: ${c.field} = ${c.value}`,
                outcome: "applied",
                agent_type: "maria",
                created_at: now,
                metadata: {
                    source: "human_correction",
                    field: c.field,
                    value: c.value,
                    reason: c.reason,
                    conversation_id: args.conversationId ?? null,
                },
            });
        } catch (err) {
            // Bug here is silent for the customer but visible in logs.
            // We intentionally do not retry — the next turn will re-derive.
            console.warn(
                `[customer-corrections] Failed to apply ${c.field}:`,
                err,
            );
        }
    }
}

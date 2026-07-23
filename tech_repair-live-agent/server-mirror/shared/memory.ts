/**
 * Shared Agent Memory — V1
 * =========================
 * Simple memory layer shared across all agents (WhatsApp + Inbound).
 *
 * V1 scope (3 questions only):
 *   1. Who is the customer?       → CustomerProfile
 *   2. What are they calling about? → current topic from assembled context
 *   3. What just happened?        → recent interaction notes
 *
 * Backed by Supabase tables — no embeddings, no semantic search, no
 * personality modeling. V2+ will layer on sentiment, preferences, and
 * cross-channel intelligence on top of this foundation.
 *
 * Usage:
 *   const memory = new AgentMemory();
 *   const profile = await memory.getCustomerProfile("+525512345678");
 *   await memory.recordInteraction({ phone, channel, topic, summary, outcome });
 *   const recent = await memory.getRecentInteractions("+525512345678", 5);
 */

import type { SupabaseClient } from "@supabase/supabase-js";
import { getSupabaseClient } from "./supabase";
import { logMemoryRetrieval } from "@/services/lane-selector";

// =============================================================================
// Types
// =============================================================================

/** Who is the customer? */
export interface CustomerProfile {
    phone: string;
    name?: string;
    customerId?: string;
    /** Total interactions across all channels */
    interactionCount: number;
    /** When we first saw this customer */
    firstSeenAt?: string;
    /** When we last interacted */
    lastSeenAt?: string;
    /** Most recent topic they contacted us about */
    lastTopic?: string;

    // ─── CRM Fields (Task 2.1 & 2.2) ───
    /** Moving average (0-10) of customer frustration. Drives escalation routing. */
    frustrationIndex: number;
    /** Most recent sentiment label (e.g., "muy frustrado", "neutral", "muy satisfecho"). */
    lastSentiment?: string;
    /** How the customer wants to be addressed (e.g., "Pancho"). */
    preferredName?: string;
    /** Preferred channel for follow-ups: "whatsapp", "voice", or "any". */
    preferredContactChannel?: "whatsapp" | "voice" | "any";
    /** TechRepair device model (e.g., "Galaxy S24 Ultra") learned from interactions. */
    primaryDeviceModel?: string;
    /** Known warranty status: "active", "expired", or "unknown". */
    warrantyStatus?: "active" | "expired" | "unknown";
    /** Flag set to true if customer threatened PROFECO, bad reviews, or legal action. */
    escalationRisk: boolean;
}

/** A single past interaction record */
export interface InteractionRecord {
    id?: string;
    phone: string;
    channel: "voice" | "whatsapp" | "web" | "system";
    topic: string;
    summary: string;
    outcome?: string;
    agentType?: string;
    svcOrderNo?: string;
    createdAt: string;
}

/** New interaction to record */
export interface RecordInteractionParams {
    phone: string;
    channel: "voice" | "whatsapp" | "web" | "system";
    topic: string;
    summary: string;
    outcome?: string;
    agentType?: string;
    svcOrderNo?: string;
    sentimentScore?: number;
    /** Structured metadata stored in the JSONB column (issue_category, urgency_level, etc.) */
    metadata?: Record<string, unknown>;
}

// =============================================================================
// AgentMemory
// =============================================================================

export class AgentMemory {
    private client: SupabaseClient | null;

    constructor(client?: SupabaseClient | null) {
        this.client = client ?? null;
    }

    private ensureClient(): SupabaseClient {
        if (!this.client) {
            this.client = getSupabaseClient();
        }
        if (!this.client) {
            throw new Error("Supabase not configured for AgentMemory");
        }
        return this.client;
    }

    // ==========================================================================
    // 1. Who is the customer?
    // ==========================================================================

    /**
     * Get or create a customer profile by phone number.
     *
     * Returns basic identity info + interaction count + last topic.
     */
    async getCustomerProfile(phone: string): Promise<CustomerProfile> {
        const client = this.ensureClient();

        const { data } = await client
            .from("customer_memory")
            .select("*")
            .eq("phone", phone)
            .maybeSingle();

        // Audit log — fire-and-forget so the customer-profile read stays fast.
        // Logged for both hit (returns existing) and miss (creates fresh below)
        // so ops can answer "did we look up this customer? what did we find?".
        const factsRetrieved = data
            ? [
                  ...(data.name ? [`name=${data.name}`] : []),
                  ...(data.preferred_name ? [`preferred_name=${data.preferred_name}`] : []),
                  ...(typeof data.frustration_index === "number"
                      ? [`frustration_index=${data.frustration_index}`]
                      : []),
                  ...(data.preferred_contact_channel
                      ? [`preferred_contact_channel=${data.preferred_contact_channel}`]
                      : []),
                  ...(data.warranty_status ? [`warranty_status=${data.warranty_status}`] : []),
                  ...(data.last_topic ? [`last_topic=${data.last_topic}`] : []),
              ]
            : [];
        logMemoryRetrieval(client, {
            lookupKeys: { phone },
            queriesExecuted: ["customer_profile"],
            resultsFound: data ? 1 : 0,
            factsRetrieved,
            reason: data
                ? "agent fetching customer profile"
                : "agent fetching customer profile — first-time customer (creating minimal row)",
        }).catch(() => {
            /* fire-and-forget — log failures don't break the caller */
        });

        if (data) {
            return {
                phone: data.phone,
                name: data.name ?? undefined,
                customerId: data.customer_id ?? undefined,
                interactionCount: data.interaction_count ?? 0,
                firstSeenAt: data.first_seen_at ?? undefined,
                lastSeenAt: data.last_seen_at ?? undefined,
                lastTopic: data.last_topic ?? undefined,
                // CRM fields (Task 2.1 & 2.2)
                frustrationIndex: data.frustration_index ?? 0,
                lastSentiment: data.last_sentiment ?? undefined,
                preferredName: data.preferred_name ?? undefined,
                preferredContactChannel: data.preferred_contact_channel ?? undefined,
                primaryDeviceModel: data.primary_device_model ?? undefined,
                warrantyStatus: data.warranty_status ?? undefined,
                escalationRisk: data.escalation_risk ?? false,
            };
        }

        // First time — create a minimal profile
        const now = new Date().toISOString();
        await client.from("customer_memory").insert({
            phone,
            interaction_count: 0,
            first_seen_at: now,
            last_seen_at: now,
            frustration_index: 0,
            escalation_risk: false,
        });

        return {
            phone,
            interactionCount: 0,
            firstSeenAt: now,
            lastSeenAt: now,
            frustrationIndex: 0,
            escalationRisk: false,
        };
    }

    /**
     * Update customer profile fields (identity, preferences, risk assessment).
     *
     * Only updates non-null values — prevents blanking out known data when a new
     * interaction doesn't detect a field. For example, if a call doesn't mention
     * a preferred name, we don't want to overwrite a name learned in a prior call.
     *
     * Called when we learn new info from context or conversation.
     */
    async updateCustomerProfile(
        phone: string,
        updates: {
            name?: string;
            customerId?: string;
            // CRM fields
            preferredName?: string;
            primaryDeviceModel?: string;
            warrantyStatus?: "active" | "expired" | "unknown";
            escalationRisk?: boolean;
            preferredContactChannel?: "whatsapp" | "voice" | "any";
            // Conversation-derived signals (used by TabMemory cards)
            lastTopic?: string;
            touchLastSeen?: boolean;
        },
    ): Promise<void> {
        const client = this.ensureClient();
        const data: Record<string, unknown> = {};

        // Identity fields
        if (updates.name) data.name = updates.name;
        if (updates.customerId) data.customer_id = updates.customerId;

        // CRM fields (only if explicitly provided)
        if (updates.preferredName) data.preferred_name = updates.preferredName;
        if (updates.primaryDeviceModel) data.primary_device_model = updates.primaryDeviceModel;
        if (updates.warrantyStatus) data.warranty_status = updates.warrantyStatus;
        if (updates.escalationRisk !== undefined) data.escalation_risk = updates.escalationRisk;
        if (updates.preferredContactChannel) data.preferred_contact_channel = updates.preferredContactChannel;

        // Conversation-derived signals. Used by TabMemory's "Falla reportada"
        // and "Contexto" cards so a Recalcular click actually refreshes them.
        // interaction_count is INTENTIONALLY not touched here — the recompute
        // scheduler fires every 10 min and would inflate the counter into
        // meaninglessness; it stays owned by recordInteraction (end-of-convo).
        if (updates.lastTopic) data.last_topic = updates.lastTopic;
        if (updates.touchLastSeen) data.last_seen_at = new Date().toISOString();

        if (Object.keys(data).length > 0) {
            data.updated_at = new Date().toISOString();
            await client.from("customer_memory").update(data).eq("phone", phone);
        }
    }

    // ==========================================================================
    // 2 & 3. What are they calling about? / What just happened?
    // ==========================================================================

    /**
     * Record a completed interaction.
     *
     * Also bumps the customer's interaction count and updates last_seen/last_topic.
     */
    async recordInteraction(params: RecordInteractionParams): Promise<string | null> {
        const client = this.ensureClient();
        const now = new Date().toISOString();

        // Insert interaction record
        const insertData: Record<string, unknown> = {
            phone: params.phone,
            channel: params.channel,
            topic: params.topic,
            summary: params.summary,
            outcome: params.outcome,
            agent_type: params.agentType,
            svc_order_no: params.svcOrderNo,
            created_at: now,
        };
        if (params.sentimentScore !== undefined) {
            insertData.sentiment_score = params.sentimentScore;
        }
        if (params.metadata && Object.keys(params.metadata).length > 0) {
            insertData.metadata = params.metadata;
        }
        const { data } = await client.from("interaction_history").insert(insertData).select("id").single();

        // Update customer profile: bump count, set last topic/seen
        // Use upsert to handle race conditions
        await client.rpc("increment_interaction_count", {
            p_phone: params.phone,
            p_last_topic: params.topic,
            p_last_seen_at: now,
        });

        return data?.id ?? null;
    }

    /**
     * Get the N most recent interactions for a customer.
     *
     * Answers: "What just happened in recent interactions?"
     */
    async getRecentInteractions(
        phone: string,
        limit = 5,
    ): Promise<InteractionRecord[]> {
        const client = this.ensureClient();

        const { data } = await client
            .from("interaction_history")
            .select("*")
            .eq("phone", phone)
            .order("created_at", { ascending: false })
            .limit(limit);

        if (!data) return [];

        return data.map((row) => ({
            id: row.id,
            phone: row.phone,
            channel: row.channel,
            topic: row.topic,
            summary: row.summary,
            outcome: row.outcome ?? undefined,
            agentType: row.agent_type ?? undefined,
            svcOrderNo: row.svc_order_no ?? undefined,
            createdAt: row.created_at,
        }));
    }

    // ==========================================================================
    // Convenience: build full context for an agent
    // ==========================================================================

    /**
     * Build a complete memory context for an agent interaction.
     *
     * Combines all 3 V1 questions into a single object.
     */
    async getContext(phone: string): Promise<{
        profile: CustomerProfile;
        recentInteractions: InteractionRecord[];
    }> {
        const [profile, recentInteractions] = await Promise.all([
            this.getCustomerProfile(phone),
            this.getRecentInteractions(phone),
        ]);

        return { profile, recentInteractions };
    }
}

// =============================================================================
// Shared CRM Override Builder
// =============================================================================

import { isMemoryEnhancedPromptsEnabled } from "./app-config";

/** Max characters for the CRM override block to stay within token budget. */
const MAX_CRM_OVERRIDE_CHARS = 500;

/** Fields used to build deterministic CRM override instructions */
export interface CrmOverrideFields {
    escalationRisk?: boolean;
    frustrationIndex?: number;
    primaryDeviceModel?: string;
    preferredName?: string;
    warrantyStatus?: "active" | "expired" | "unknown";
    /** Most recent topic the customer contacted about. */
    lastTopic?: string;
    /** Total interaction count across all channels. */
    interactionCount?: number;
    /** When true, skip device/warranty overrides (GSPN is authoritative). */
    hasActiveOrders?: boolean;
}

/**
 * Build CRM override instruction block from customer profile fields.
 * Returns an empty string when no overrides apply, or a formatted
 * "INSTRUCCIONES CRÍTICAS" block for prompt injection.
 *
 * When the `memory_enhanced_prompts` config flag is OFF, falls back to
 * the original single-threshold behavior (frustration > 7 only).
 *
 * Overrides are built in priority order so truncation (at 500 chars)
 * always preserves the most safety-critical information:
 *   1. Frustration / escalation risk (safety — never truncated)
 *   2. Last topic / repeat contact warning
 *   3. Interaction count / frequent customer
 *   4. Device model / warranty (lowest priority, skipped when orders exist)
 *
 * Used by both voice (greeter) and WhatsApp (support) agents.
 */
export async function buildCrmOverrides(fields: CrmOverrideFields): Promise<string> {
    const enhanced = await isMemoryEnhancedPromptsEnabled();

    // Priority-ordered override list (highest priority first)
    const overrides: string[] = [];

    // ── Priority 1: Frustration / escalation risk (safety-critical) ──
    if (!enhanced) {
        // Legacy behavior: single threshold
        if (fields.escalationRisk || (fields.frustrationIndex ?? 0) > 7) {
            overrides.push("CRÍTICO: Cliente de alto riesgo de escalada. Sé conciso, empático y ofrece transferencia a humano ante cualquier fricción.");
        }
    } else {
        // Enhanced: graduated frustration levels
        const fi = fields.frustrationIndex ?? 0;
        if (fields.escalationRisk || fi >= 8) {
            overrides.push("CRÍTICO: Cliente de alto riesgo de escalada. Sé conciso, empático y ofrece transferencia a humano ante cualquier fricción.");
        } else if (fi >= 6) {
            overrides.push("PRECAUCIÓN: Cliente frecuentemente frustrado. No hagas preguntas innecesarias. Si no resuelves en 2 mensajes, sugiere transferencia a humano.");
        } else if (fi >= 4) {
            overrides.push("ATENTO: Cliente con frustración moderada. Sé especialmente claro y conciso. Ofrece proactivamente ayuda.");
        }
    }

    if (!enhanced) {
        // Legacy: device + name + warranty only
        if (fields.primaryDeviceModel) {
            overrides.push(`Dispositivo del cliente: ${fields.primaryDeviceModel}. No preguntes qué dispositivo tienen.`);
        }
        if (fields.preferredName) {
            overrides.push(`Dirígete siempre a ellos como ${fields.preferredName}.`);
        }
        if (fields.warrantyStatus) {
            const warrantyMsg = fields.warrantyStatus === "active"
                ? "Su garantía está vigente. No menciones si el dispositivo no está en reparación."
                : fields.warrantyStatus === "expired"
                    ? "Su garantía ha expirado. Menciona opciones de pago al cotizar reparaciones."
                    : null;
            if (warrantyMsg) overrides.push(warrantyMsg);
        }
    } else {
        // ── Priority 2: Last topic / repeat contact ──
        if (fields.lastTopic) {
            overrides.push(`El cliente posiblemente contacta OTRA VEZ por: ${fields.lastTopic}. Reconoce su historial sin que te lo pida.`);
        }

        // ── Priority 3: Frequent customer ──
        if ((fields.interactionCount ?? 0) > 5) {
            overrides.push("Cliente frecuente — ya conoce el proceso. Sé directo, omite explicaciones básicas.");
        }

        // ── Priority 4: Device + warranty (skip when GSPN provides authoritative data) ──
        if (!fields.hasActiveOrders) {
            if (fields.primaryDeviceModel) {
                overrides.push(`Dispositivo del cliente: ${fields.primaryDeviceModel}. No preguntes qué dispositivo tienen.`);
            }
            if (fields.warrantyStatus) {
                const warrantyMsg = fields.warrantyStatus === "active"
                    ? "Su garantía está vigente. No menciones si el dispositivo no está en reparación."
                    : fields.warrantyStatus === "expired"
                        ? "Su garantía ha expirado. Menciona opciones de pago al cotizar reparaciones."
                        : null;
                if (warrantyMsg) overrides.push(warrantyMsg);
            }
        }

        if (fields.preferredName) {
            overrides.push(`Dirígete siempre a ellos como ${fields.preferredName}.`);
        }
    }

    if (overrides.length === 0) return "";

    // Truncate from tail (lowest priority) to stay within token budget
    let result = `\nINSTRUCCIONES CRÍTICAS:\n`;
    for (const line of overrides) {
        if (result.length + line.length + 1 > MAX_CRM_OVERRIDE_CHARS) break;
        result += line + "\n";
    }

    return result.trimEnd();
}

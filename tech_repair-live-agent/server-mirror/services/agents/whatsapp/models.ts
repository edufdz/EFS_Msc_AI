/**
 * WhatsApp Agent Models
 * =====================
 * Zod schemas mirroring the types from shared/types.
 */

import { z } from "zod/v4";

// =============================================================================
// Enums
// =============================================================================

export const MessageType = {
    TEXT: "text",
    IMAGE: "image",
    AUDIO: "audio",
    DOCUMENT: "document",
    LOCATION: "location",
    INTERACTIVE: "interactive",
    BUTTON: "button",
    REACTION: "reaction",
    STICKER: "sticker",
    UNKNOWN: "unknown",
} as const;
export type MessageType = (typeof MessageType)[keyof typeof MessageType];

export const IntentType = {
    // v1 + v2 shared
    ORDER_STATUS: "order_status",
    PRICING: "pricing",
    GREETING: "greeting",
    GOODBYE: "goodbye",
    CONFIRMATION: "confirmation",
    UNKNOWN: "unknown",
    // v1 only (kept for backward compatibility when INTENT_TAXONOMY_VERSION=v1)
    GENERAL_SUPPORT: "general_support",
    ESCALATION: "escalation",
    REJECTION: "rejection",
    // v2 additions — replace general_support with concrete buckets and
    // split escalation into explicit-human vs. complaint/frustration
    DELIVERY_LOGISTICS: "delivery_logistics",
    CONTACT_INFO_REQUEST: "contact_info_request",
    WARRANTY_QUESTION: "warranty_question",
    NEW_SYMPTOM_REPORT: "new_symptom_report",
    COMPLAINT_OR_FRUSTRATION: "complaint_or_frustration",
    EXPLICIT_HUMAN_REQUEST: "explicit_human_request",
} as const;
export type IntentType = (typeof IntentType)[keyof typeof IntentType];

/** Valid intent values by taxonomy version. */
export const INTENT_VALUES_V1 = [
    "order_status", "pricing", "general_support", "greeting", "goodbye",
    "escalation", "confirmation", "rejection", "unknown",
] as const;

export const INTENT_VALUES_V2 = [
    "order_status", "pricing", "warranty_question", "delivery_logistics",
    "contact_info_request", "new_symptom_report", "complaint_or_frustration",
    "explicit_human_request", "greeting", "goodbye", "confirmation", "unknown",
] as const;

export const ConversationStatus = {
    ACTIVE: "active",
    WAITING_CUSTOMER: "waiting_customer",
    ESCALATED: "escalated",
    RESOLVED: "resolved",
    CLOSED: "closed",
} as const;

// =============================================================================
// Context Models (input from gateway/orchestrator)
// =============================================================================

export const SessionInfoSchema = z.object({
    window_open: z.boolean(),
    window_expires_at: z.string(),
    minutes_remaining: z.number().int(),
    requires_template: z.boolean(),
});
export type SessionInfo = z.infer<typeof SessionInfoSchema>;

export const CustomerInfoSchema = z.object({
    phone_number: z.string(),
    wa_id: z.string().optional(),
    name: z.string().optional(),
    customer_id: z.string().optional(),
    interaction_count: z.number().int().default(0),
});
export type CustomerInfo = z.infer<typeof CustomerInfoSchema>;

export const ServiceOrderInfoSchema = z.object({
    svc_order_no: z.string(),
    status: z.string(),
    status_label: z.string().optional(),
    model_name: z.string().optional(),
    repair_cost_mxn: z.number().optional(),
    warranty_type: z.string().optional(),
    estimated_completion: z.string().optional(),
    is_d2d: z.boolean().default(false),
    // Pipeline classifier (asc_job_no prefix): 'd2d' = envío a domicilio,
    // 'carry_in' = recolección en tienda, 'other' = canales internos.
    // Load-bearing for the delivery-logistics dispatcher and the carry-in
    // prompt addendum — without it the agent defaults to D2D shipping copy
    // for carry-in customers. Optional/nullable so pre-classification rows
    // and the D2D path stay unchanged. Zod strips unknown keys on parse, so
    // this MUST be declared here or `service_type` is dropped at agent.ts.
    service_type: z.enum(["d2d", "carry_in", "other"]).nullable().optional(),
    iris_condition_desc: z.string().optional(),
    iris_symptom_desc: z.string().optional(),
    iris_defect_desc: z.string().optional(),
    iris_repair_desc: z.string().optional(),
});
export type ServiceOrderInfo = z.infer<typeof ServiceOrderInfoSchema>;

export const HistoryMessageSchema = z.object({
    role: z.string(),
    content: z.string(),
    timestamp: z.string(),
});

export const CurrentMessageSchema = z.object({
    id: z.string(),
    type: z.string(),
    content: z.string(),
    timestamp: z.string(),
});

/**
 * M6: estado de encuestas del cliente inyectado al contexto del agente.
 * Lo computa survey-state-builder.buildAgentState() y se agrega en
 * whatsapp-agent-adapter.mapToAgentContext(). Permite al agente ajustar tono
 * (empatía con detractores), respetar opt-outs, no ofrecer encuestas
 * recientes, etc. Opcional — si el builder no está disponible queda undefined.
 */
export const AgentSurveyStateSchema = z.object({
    last_survey_sent_at: z.string().nullable(),
    last_survey_status: z.string().nullable(),
    last_nps_score: z.number().nullable(),
    last_resolution: z.boolean().nullable(),
    days_since_last_survey: z.number().nullable(),
    opted_out_until: z.string().nullable(),
    total_surveys: z.number(),
    is_detractor: z.boolean(),
    is_promoter: z.boolean(),
});
export type AgentSurveyState = z.infer<typeof AgentSurveyStateSchema>;

export const AssembledContextSchema = z.object({
    session: SessionInfoSchema,
    customer: CustomerInfoSchema,
    active_orders: z.array(ServiceOrderInfoSchema).default([]),
    conversation_history: z.array(HistoryMessageSchema).default([]),
    current_message: CurrentMessageSchema,
    metadata: z.record(z.string(), z.unknown()).default({}),
    // Semantic recall from mem0 — advisory only, de-shadowed against memory_resolved
    memory_context: z.string().optional(),
    // Authoritative directives rendered from ResolvedMemory
    memory_directives: z.string().optional(),
    // The raw ResolvedMemory object — passthrough for instrumentation + audit.
    // Validated structurally inside resolveMemory; loose z.unknown() here so we
    // don't duplicate the ResolvedMemory shape across modules.
    memory_resolved: z.unknown().optional(),
    survey_state: AgentSurveyStateSchema.optional(),
});
export type AssembledContext = z.infer<typeof AssembledContextSchema>;

// =============================================================================
// Response Models (output to gateway)
// =============================================================================

export const ToolCallSchema = z.object({
    tool_name: z.string(),
    tool_input: z.record(z.string(), z.unknown()),
    tool_output: z.unknown(),
});
export type ToolCall = z.infer<typeof ToolCallSchema>;

export const EscalationInfoSchema = z.object({
    escalated: z.boolean(),
    escalated_at: z.string().optional(),
    escalated_to: z.string().optional(),
    reason: z.string().optional(),
});

export const AgentResponseSchema = z.object({
    response_text: z.string(),
    intent: z.string(),
    confidence: z.number().default(0),
    tool_calls: z.array(ToolCallSchema).default([]),
    escalation: EscalationInfoSchema.optional(),
    should_close: z.boolean().default(false),
    metadata: z.record(z.string(), z.unknown()).default({}),
});
export type AgentResponse = z.infer<typeof AgentResponseSchema>;

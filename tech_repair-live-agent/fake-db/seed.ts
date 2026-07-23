/**
 * Fake Database Seed — ONE fully-specified fake customer
 * ======================================================
 * Valeria Mendoza García is the single fake client every simulated
 * conversation runs against. She has data behind EVERY api the agent can
 * reach: two service orders (one D2D out-of-warranty with a pending quote,
 * one carry-in in-warranty sitting at ready-for-pickup — the disclosure-
 * gate state), a CRM memory profile, interaction history, the production
 * service_status_policy seed rows (verbatim from migration 0057/0059),
 * and an active auto-escalation rule.
 *
 * ALL DATA IS FICTITIOUS. No real customer, phone number, IMEI or order
 * number appears here.
 */

import type { Row } from "./fake-supabase";

// ---------------------------------------------------------------------------
// The fake customer
// ---------------------------------------------------------------------------

export const FAKE_CUSTOMER = {
    /** WhatsApp wa_id / normalized phone as stored by the gateway. */
    phone: "5215587654321",
    /** 10-digit local form as it appears on GSPN service orders. */
    localPhone: "5587654321",
    name: "Valeria Mendoza García",
    preferredName: "Vale",
    customerId: "CUST-0084213",
    waId: "5215587654321",
} as const;

/** Main order: D2D, Galaxy S24 Ultra, out of warranty, quote pending payment. */
export const SO_D2D = "4151234567";
/** Second order: carry-in, Galaxy Watch6, in warranty, READY FOR PICKUP (ST040). */
export const SO_CARRY_IN = "4149876543";

const NOW = Date.now();
const daysAgo = (d: number) => new Date(NOW - d * 86_400_000).toISOString();
const daysFromNow = (d: number) => new Date(NOW + d * 86_400_000).toISOString();
const dateOnly = (iso: string) => iso.slice(0, 10);

// ---------------------------------------------------------------------------
// Tables
// ---------------------------------------------------------------------------

export function buildSeedTables(): Record<string, Row[]> {
    return {
        // =====================================================================
        // service_orders — populated in production by the GSPN poller
        // =====================================================================
        service_orders: [
            {
                id: "so-row-1",
                svc_order_no: SO_D2D,
                status: "ST030", // awaiting parts
                status_changed_at: daysAgo(2),
                service_type: "d2d",
                is_d2d: true,
                model_name: "Galaxy S24 Ultra 256GB",
                cust_name: "VALERIA MENDOZA GARCIA",
                cust_mobile_phone: FAKE_CUSTOMER.localPhone,
                cust_home_phone: null,
                cust_office_phone: null,
                contact_no: FAKE_CUSTOMER.localPhone,
                cust_address: "Av. Insurgentes Sur 1425, Int. 702, Col. Insurgentes Mixcoac, 03920 CDMX",
                warranty_type: "O", // out of warranty → quote applies
                estimated_cost_mxn: 3480,
                repair_cost_mxn: 3480,
                req_date: dateOnly(daysAgo(9)),
                complete_date: null,
                delivery_date: null,
                estimated_completion: dateOnly(daysFromNow(5)),
                last_synced_at: daysAgo(0.05),
                symptom_desc: "SymCode1: 131 SymDesc1: No or faulty display / SymCode2: 746 SymDesc2: Touchscreen not tracking",
                symptom_codes: [
                    { code: "131", desc: "No or faulty display" },
                    { code: "746", desc: "Pointing device / touchscreen not track" },
                ],
                st_reason_desc: "Waiting for display assembly part",
                defect_desc: "Cracked AMOLED panel, touch IC intermittent",
                repair_action_desc: "Replace OCTA display assembly SM-S928B",
                iris_condition_desc: "Screen cracked after drop, device powers on",
                iris_symptom_desc: "Display shattered, intermittent touch response",
                iris_defect_desc: "OCTA assembly fractured",
                iris_repair_desc: "OCTA replacement pending parts arrival",
                so_comment: "Se cotizó cambio de display. Pendiente de pago del cliente para pedir refacción.",
                remark: "",
                created_at: daysAgo(9),
            },
            {
                id: "so-row-2",
                svc_order_no: SO_CARRY_IN,
                status: "ST040", // carry_in → ready_for_pickup (disclosure-gated!)
                status_changed_at: daysAgo(1),
                service_type: "carry_in",
                is_d2d: false,
                model_name: "Galaxy Watch6 44mm",
                cust_name: "VALERIA MENDOZA GARCIA",
                cust_mobile_phone: FAKE_CUSTOMER.localPhone,
                cust_home_phone: null,
                cust_office_phone: null,
                contact_no: FAKE_CUSTOMER.localPhone,
                cust_address: null,
                warranty_type: "I", // in warranty → never charged
                estimated_cost_mxn: 0,
                repair_cost_mxn: 0,
                req_date: dateOnly(daysAgo(20)),
                complete_date: dateOnly(daysAgo(1)),
                delivery_date: null,
                estimated_completion: dateOnly(daysAgo(1)),
                last_synced_at: daysAgo(0.05),
                symptom_desc: "SymCode1: 111 SymDesc1: NO POWER",
                symptom_codes: [{ code: "111", desc: "NO POWER" }],
                st_reason_desc: "Battery swollen, no power on",
                defect_desc: "Swollen battery",
                repair_action_desc: "Battery replacement under warranty",
                iris_condition_desc: "Device does not power on",
                iris_symptom_desc: "No power, battery swollen",
                iris_defect_desc: "Battery cell failure",
                iris_repair_desc: "Battery replaced, QC passed",
                so_comment: "Reparación en garantía concluida.",
                remark: "",
                created_at: daysAgo(20),
            },
        ],

        // =====================================================================
        // customer_memory — the CRM profile AgentMemory reads/writes
        // =====================================================================
        customer_memory: [
            {
                id: "cm-row-1",
                phone: FAKE_CUSTOMER.phone,
                name: FAKE_CUSTOMER.name,
                customer_id: FAKE_CUSTOMER.customerId,
                interaction_count: 6,
                first_seen_at: daysAgo(120),
                last_seen_at: daysAgo(1),
                last_topic: "estado de reparación",
                frustration_index: 2.4,
                last_sentiment: "neutral",
                preferred_name: FAKE_CUSTOMER.preferredName,
                preferred_contact_channel: "whatsapp",
                primary_device_model: "Galaxy S24 Ultra 256GB",
                warranty_status: "expired",
                escalation_risk: false,
                memory_history: [
                    {
                        at: daysAgo(9),
                        channel: "whatsapp",
                        insights: ["Cliente dejó el S24 Ultra para reparación de pantalla (D2D)."],
                    },
                    {
                        at: daysAgo(4),
                        channel: "voice",
                        insights: ["Preguntó por el costo de la reparación; se le explicó la cotización de $3,480 MXN."],
                    },
                ],
                last_extracted_at: daysAgo(4),
                updated_at: daysAgo(1),
                created_at: daysAgo(120),
            },
        ],

        // =====================================================================
        // interaction_history — past touchpoints (fed to prompts + rules engine)
        // =====================================================================
        interaction_history: [
            {
                id: "ih-row-1",
                phone: FAKE_CUSTOMER.phone,
                channel: "whatsapp",
                topic: "recepción de equipo",
                summary: "Cliente confirmó recolección D2D del Galaxy S24 Ultra por pantalla rota.",
                outcome: "resolved",
                agent_type: "whatsapp",
                svc_order_no: SO_D2D,
                sentiment_score: 3,
                created_at: daysAgo(9),
            },
            {
                id: "ih-row-2",
                phone: FAKE_CUSTOMER.phone,
                channel: "voice",
                topic: "cotización",
                summary: "Se informó cotización de $3,480 MXN por cambio de display fuera de garantía. Cliente lo pensaría.",
                outcome: "follow_up_pending",
                agent_type: "inbound",
                svc_order_no: SO_D2D,
                sentiment_score: 3,
                created_at: daysAgo(4),
            },
        ],

        // =====================================================================
        // service_status_policy — VERBATIM production seed (migrations 0057+0059)
        // =====================================================================
        service_status_policy: [
            // carry-in
            { service_type: "carry_in", state: "received", outbound_call_permitted: true, proactive_status_disclosure: true, whatsapp_proactive_send_permitted: true },
            { service_type: "carry_in", state: "in_diagnosis", outbound_call_permitted: true, proactive_status_disclosure: true, whatsapp_proactive_send_permitted: true },
            { service_type: "carry_in", state: "awaiting_parts", outbound_call_permitted: true, proactive_status_disclosure: true, whatsapp_proactive_send_permitted: true },
            { service_type: "carry_in", state: "ready_for_pickup", outbound_call_permitted: false, proactive_status_disclosure: false, whatsapp_proactive_send_permitted: false }, // THE critical seed
            { service_type: "carry_in", state: "delivered", outbound_call_permitted: true, proactive_status_disclosure: true, whatsapp_proactive_send_permitted: true },
            { service_type: "carry_in", state: "closed", outbound_call_permitted: false, proactive_status_disclosure: false, whatsapp_proactive_send_permitted: false },
            // d2d
            { service_type: "d2d", state: "received", outbound_call_permitted: true, proactive_status_disclosure: true, whatsapp_proactive_send_permitted: true },
            { service_type: "d2d", state: "in_diagnosis", outbound_call_permitted: true, proactive_status_disclosure: true, whatsapp_proactive_send_permitted: true },
            { service_type: "d2d", state: "awaiting_parts", outbound_call_permitted: true, proactive_status_disclosure: true, whatsapp_proactive_send_permitted: true },
            { service_type: "d2d", state: "shipped", outbound_call_permitted: true, proactive_status_disclosure: true, whatsapp_proactive_send_permitted: true },
            { service_type: "d2d", state: "delivered", outbound_call_permitted: true, proactive_status_disclosure: true, whatsapp_proactive_send_permitted: true },
            { service_type: "d2d", state: "closed", outbound_call_permitted: false, proactive_status_disclosure: false, whatsapp_proactive_send_permitted: false },
            // other
            { service_type: "other", state: "received", outbound_call_permitted: false, proactive_status_disclosure: false, whatsapp_proactive_send_permitted: false },
            { service_type: "other", state: "in_diagnosis", outbound_call_permitted: false, proactive_status_disclosure: false, whatsapp_proactive_send_permitted: false },
            { service_type: "other", state: "closed", outbound_call_permitted: false, proactive_status_disclosure: false, whatsapp_proactive_send_permitted: false },
            { service_type: "other", state: "awaiting_parts", outbound_call_permitted: false, proactive_status_disclosure: false, whatsapp_proactive_send_permitted: false },
            { service_type: "other", state: "ready_for_pickup", outbound_call_permitted: false, proactive_status_disclosure: false, whatsapp_proactive_send_permitted: false },
            { service_type: "other", state: "delivered", outbound_call_permitted: false, proactive_status_disclosure: false, whatsapp_proactive_send_permitted: false },
        ],

        // =====================================================================
        // app_config — feature flags
        // =====================================================================
        app_config: [
            { key: "memory_enhanced_prompts", value: true },
            { key: "memory_sweep_enabled", value: false },
        ],

        // =====================================================================
        // escalation_rules — one active auto-escalation rule (call frequency)
        // =====================================================================
        escalation_rules: [
            {
                id: "rule-1",
                org_id: "default",
                name: "Contactos repetidos (3 en 7 días)",
                trigger_type: "call_frequency",
                trigger_config: { max_calls: 3, within_days: 7 },
                is_active: true,
                created_by: null,
                created_at: daysAgo(60),
                updated_at: daysAgo(60),
            },
        ],

        // =====================================================================
        // Empty-but-known tables (agent writes land here; harness inspects them)
        // =====================================================================
        agent_configurations: [], // empty → env defaults, verbatim prompts apply
        escalated_tasks: [],
        escalation_shadow_log: [],
        pending_cost_followup: [],
        rocket_metrics: [],
        whatsapp_conversations: [],
        whatsapp_messages: [],
        memory_logs: [],
        thought_logs: [],
        tool_invocations: [],
        interaction_grades: [],
        customer_phone_links: [],
        dashboard_notifications: [],
        calls: [],
        participants: [],
        transcripts: [],
        transcript_segments: [],
        call_metrics: [],
        agent_performance: [],
        sentiment_analysis: [],
        call_tags: [],
        call_notes: [],
    };
}

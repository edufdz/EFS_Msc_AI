/**
 * FAKE SHIM — Context Assembler (types only)
 * ==========================================
 * The production context assembler builds AssembledContext from live
 * Supabase + Meta data; in the simulation that job belongs to the /chat
 * server harness (server.ts). The copied code only imports TYPES from this
 * module (`ServiceOrderInfo` via response-renderer), reproduced VERBATIM
 * from pulpoo-final `services/orchestrator/context-assembler.ts`.
 */

export interface ServiceOrderInfo {
  id: string
  svc_order_no: string
  status: string
  device_model: string
  repair_cost_mxn: number | null
  warranty_type: string | null
  created_at: string
  estimated_completion: string | null
  is_d2d: boolean
  service_type: 'd2d' | 'carry_in' | 'other' | null
  iris_condition_desc: string | null
  iris_symptom_desc: string | null
  iris_defect_desc: string | null
  iris_repair_desc: string | null
}

export interface ConversationHistory {
  messages: Array<{
    role: 'customer' | 'assistant' | 'system'
    content: string | null
    timestamp: string
    source: string
    ai_intent?: string | null
  }>
  summary: string | null
  message_count: number
}

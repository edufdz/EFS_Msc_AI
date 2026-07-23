/**
 * TechRepair Service Types
 * =====================
 * Shared type definitions for the TechRepair service platform.
 * Originally referenced as '@tech_repair-polanco/types'.
 */

import { z } from 'zod'

// =============================================================================
// WhatsApp Enums
// =============================================================================

export type WAMessageType =
  | 'text'
  | 'image'
  | 'audio'
  | 'video'
  | 'document'
  | 'location'
  | 'contacts'
  | 'template'
  | 'interactive'
  | 'reaction'
  | 'system'

export type WAMessageDirection = 'inbound' | 'outbound'

export type WAMessageSource = 'customer' | 'ai_agent' | 'human_agent' | 'system'

export type WAMessageStatus = 'pending' | 'sent' | 'delivered' | 'read' | 'failed'

export type WAConversationStatus = 'active' | 'escalated' | 'expired' | 'closed'

export type WAConversationChannel = 'customer_initiated' | 'business_initiated'

export type WATemplateStatus = 'approved' | 'pending' | 'rejected' | 'disabled'

export type WATemplateCategory = 'authentication' | 'marketing' | 'utility'

export type WATemplateSendStatus =
  | 'pending'
  | 'pending_approval'
  | 'sent'
  | 'delivered'
  | 'read'
  | 'replied'
  | 'failed'
  | 'escalated'

export type EmailTemplateStatus = 'draft' | 'active' | 'disabled' | 'archived'

export type EmailTemplateCategory = 'repair_status' | 'pickup_confirmation' | 'invoice' | 'general'

export type EmailSendStatus = 'pending' | 'sent' | 'delivered' | 'bounced' | 'complained' | 'failed' | 'replied'

export type EmailBounceType = 'hard' | 'soft' | 'undetermined'

// =============================================================================
// WhatsApp Core Types
// =============================================================================

export interface WAConversation {
  id: string
  phone_number: string
  wa_id: string
  customer_name: string | null
  customer_id: string | null
  status: WAConversationStatus
  channel: WAConversationChannel
  window_opened_at: string
  window_expires_at: string
  last_customer_message_at: string | null
  last_business_message_at: string | null
  langgraph_thread_id: string | null
  current_graph_node: string | null
  active_service_order_id: string | null
  conversation_summary: string | null
  tags: string[]
  message_count: number
  escalated_at: string | null
  escalated_to: string | null
  escalation_reason: string | null
  is_human_handling: boolean
  taken_over_at: string | null
  taken_over_by_user_id: string | null
  metadata: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface WAMessage {
  id: string
  conversation_id: string
  wamid: string | null
  direction: WAMessageDirection
  message_type: WAMessageType
  source: WAMessageSource
  text_body: string | null
  media_url: string | null
  media_mime_type: string | null
  media_caption: string | null
  media_transcript: string | null
  media_storage_path: string | null
  media_expires_at: string | null
  template_name: string | null
  template_parameters: Record<string, unknown> | null
  interactive_payload: Record<string, unknown> | null
  location_data: Record<string, unknown> | null
  status: WAMessageStatus
  status_updated_at: string | null
  error_code: string | null
  error_message: string | null
  ai_confidence_score: number | null
  ai_intent_detected: string | null
  ai_tool_calls: Record<string, unknown>[] | null
  ai_processing_time_ms: number | null
  graph_node: string | null
  graph_checkpoint_id: string | null
  metadata: Record<string, unknown>
  created_at: string
}

export interface WATemplate {
  id: string
  meta_template_id: string
  name: string
  language: string
  category: WATemplateCategory
  status: WATemplateStatus
  components: Array<{
    type: 'HEADER' | 'BODY' | 'FOOTER' | 'BUTTONS'
    format?: 'TEXT' | 'IMAGE' | 'VIDEO' | 'DOCUMENT'
    text?: string
    example?: {
      header_text?: string[]
      body_text?: string[][]
    }
    buttons?: Array<{
      type: 'QUICK_REPLY' | 'URL' | 'PHONE_NUMBER'
      text: string
      url?: string
      phone_number?: string
    }>
  }>
  parameter_schema: Record<string, unknown> | null
  example_values: Record<string, unknown> | null
  usage_count: number
  last_used_at: string | null
  success_rate: number | null
  description: string | null
  tags: string[]
  outbound_enabled: boolean
  // Meta verification — populated by webhook / list-API sync.
  // Meta names this 'reason' on the webhook and 'rejected_reason' on the list API.
  rejection_reason: string | null
  last_meta_sync_at: string | null
  // Local optimistic edit-cap counters. Meta enforces 10 edits / 30d authoritatively;
  // we track locally to pre-empt Meta's cryptic "edit_limit_reached" for pilot users.
  edits_in_current_window: number
  edit_window_started_at: string | null
  last_edited_at: string | null
  created_at: string
  updated_at: string
}

export interface WATemplateSend {
  id: string
  template_id: string
  conversation_id: string | null
  phone_number: string
  customer_name: string | null
  customer_id: string | null
  parameters: Record<string, unknown>
  rendered_preview: string | null
  service_order_id: string | null
  notification_type: string | null
  status: WATemplateSendStatus
  wamid: string | null
  sent_at: string | null
  delivered_at: string | null
  read_at: string | null
  replied_at: string | null
  failed_at: string | null
  error_code: string | null
  error_message: string | null
  response_deadline_at: string | null
  escalation_scheduled: boolean
  escalated_to_call: boolean
  escalated_at: string | null
  call_queue_id: string | null
  is_simulation: boolean
  simulation_response: string | null
  batch_id: string | null
  batch_sequence: number | null
  trigger_status: string | null
  created_by: string | null
  /**
   * Populated when an operator rejects a pending_approval send via
   * `POST /dashboard/template-sends/:id/reject` (which marks the row failed).
   * NULL for delivery failures (Meta API errors). Distinguishes these two
   * conceptually distinct kinds of `status='failed'` rows.
   */
  rejected_by_id: string | null
  rejected_by_name: string | null
  /**
   * Set when an operator dismisses this failed send from the email-fallback
   * list (see `POST /email/whatsapp-fallback/:sendId/discard`). NULL means
   * the row is still actionable.
   */
  discarded_at: string | null
  discarded_by: string | null
  created_at: string
}

// =============================================================================
// Template Trigger Types
// =============================================================================

/** Condition operator for template trigger guard evaluation */
export type TriggerConditionOp =
  | 'eq'
  | 'neq'
  | 'not_null'
  | 'is_null'
  | 'icontains'
  | 'icontains_any'
  | 'not_icontains'

/** A single guard condition in a template trigger rule */
export interface TriggerCondition {
  field: string
  op: TriggerConditionOp
  value?: string | string[]
}

/** A parameter mapping entry for template body params */
export interface TriggerParamEntry {
  source: string
  fallback?: string
  format?: 'currency_mxn'
}

/** DB row from template_triggers table */
export interface TemplateTrigger {
  id: string
  template_id: string
  trigger_status: string
  priority: number
  conditions: TriggerCondition[]
  param_map: TriggerParamEntry[]
  requires_approval: boolean
  enabled: boolean
  description: string | null
  created_at: string
  updated_at: string
}

// =============================================================================
// Email Types
// =============================================================================

export interface EmailTemplateVariable {
  name: string
  required: boolean
}

// Template Design (block-based editor)

export interface HeadingBlock {
  type: 'heading'
  id: string
  level: 1 | 2 | 3
  text: string
  align?: 'left' | 'center'
}

export interface ParagraphBlock {
  type: 'paragraph'
  id: string
  text: string
}

export interface HighlightBlock {
  type: 'highlight'
  id: string
  text: string
}

export interface BulletListBlock {
  type: 'bulletList'
  id: string
  items: string[]
}

export interface DividerBlock {
  type: 'divider'
  id: string
}

export interface SignatureBlock {
  type: 'signature'
  id: string
  text: string
}

export interface SpacerBlock {
  type: 'spacer'
  id: string
  height?: number
}

export type TemplateBlock =
  | HeadingBlock
  | ParagraphBlock
  | HighlightBlock
  | BulletListBlock
  | DividerBlock
  | SignatureBlock
  | SpacerBlock

export interface TemplateDesign {
  blocks: TemplateBlock[]
}

export interface EmailTemplate {
  id: string
  name: string
  subject: string
  html_body: string
  text_body: string | null
  variables_schema: EmailTemplateVariable[]
  category: EmailTemplateCategory
  status: EmailTemplateStatus
  created_by: string | null
  created_at: string
  updated_at: string
  design_json: unknown | null
}

export interface EmailSend {
  id: string
  template_id: string
  recipient_email: string
  recipient_name: string | null
  subject_rendered: string
  variables: Record<string, unknown>
  ses_message_id: string | null
  status: EmailSendStatus
  bounce_type: EmailBounceType | null
  complaint_type: string | null
  error_message: string | null
  sent_at: string | null
  delivered_at: string | null
  bounced_at: string | null
  complained_at: string | null
  created_by: string | null
  service_order_id: string | null
  trigger_status: string | null
  notification_type: string | null
  replied_at: string | null
  reply_from: string | null
  reply_snippet: string | null
  smtp_message_id: string | null
  escalation_id: string | null
  /**
   * Set when this email was sent as the manual backup for a failed WhatsApp
   * template send (`whatsapp_template_sends.id`). NULL for all other origins
   * (cron status-change pipeline, manual /email/send, etc.).
   */
  source_whatsapp_send_id: string | null
  created_at: string
}

export interface EmailStats {
  total: number
  pending: number
  sent: number
  delivered: number
  bounced: number
  complained: number
  failed: number
  delivery_rate: number
  bounce_rate: number
}

// =============================================================================
// WhatsApp Webhook Types
// =============================================================================

export interface WAWebhookMessage {
  id: string
  from: string
  type: 'text' | 'image' | 'audio' | 'video' | 'document' | 'location' | 'contacts' | 'reaction' | 'interactive'
  timestamp: string
  text?: { body: string }
  image?: { id: string; mime_type: string; caption?: string }
  audio?: { id: string; mime_type: string }
  video?: { id: string; mime_type: string; caption?: string }
  document?: { id: string; mime_type: string; filename: string }
  location?: { latitude: number; longitude: number; name?: string; address?: string }
  contacts?: Array<{ name: { formatted_name: string } }>
  interactive?: {
    type: 'button_reply' | 'list_reply'
    button_reply?: { id: string; title: string }
    list_reply?: { id: string; title: string; description?: string }
  }
}

export interface WAWebhookStatus {
  id: string
  status: 'sent' | 'delivered' | 'read' | 'failed'
  errors?: Array<{ code: number; title: string }>
}

export interface WAWebhookPayload {
  object: string
  entry: Array<{
    changes: Array<{
      field: string
      value: {
        messages?: WAWebhookMessage[]
        statuses?: WAWebhookStatus[]
        contacts?: Array<{ wa_id: string; profile?: { name?: string } }>
      }
    }>
  }>
}

// =============================================================================
// Zod Schemas
// =============================================================================

export const WAWebhookPayloadSchema = z.object({
  object: z.string(),
  entry: z.array(z.object({
    changes: z.array(z.object({
      field: z.string(),
      value: z.object({
        messages: z.array(z.object({
          id: z.string(),
          from: z.string(),
          type: z.string(),
          timestamp: z.string(),
          text: z.object({ body: z.string() }).optional(),
          image: z.object({ id: z.string(), mime_type: z.string(), caption: z.string().optional() }).optional(),
          audio: z.object({ id: z.string(), mime_type: z.string() }).optional(),
          video: z.object({ id: z.string(), mime_type: z.string(), caption: z.string().optional() }).optional(),
          document: z.object({ id: z.string(), mime_type: z.string(), filename: z.string() }).optional(),
          location: z.object({ latitude: z.number(), longitude: z.number(), name: z.string().optional(), address: z.string().optional() }).optional(),
          contacts: z.array(z.object({ name: z.object({ formatted_name: z.string() }) })).optional(),
          interactive: z.object({
            type: z.string(),
            button_reply: z.object({ id: z.string(), title: z.string() }).optional(),
            list_reply: z.object({ id: z.string(), title: z.string(), description: z.string().optional() }).optional(),
          }).optional(),
        })).optional(),
        statuses: z.array(z.object({
          id: z.string(),
          status: z.string(),
          errors: z.array(z.object({ code: z.number(), title: z.string() })).optional(),
        })).optional(),
        contacts: z.array(z.object({
          wa_id: z.string(),
          profile: z.object({ name: z.string().optional() }).optional(),
        })).optional(),
        // Template status update webhooks (message_template_status_update field)
        event: z.string().optional(),
        message_template_id: z.number().optional(),
        message_template_name: z.string().optional(),
        message_template_language: z.string().optional(),
        reason: z.string().optional(),
      }).passthrough(),
    })),
  })),
})

export const MexicanPhoneSchema = z.string()
  .min(10, 'Phone number must be at least 10 digits')
  .transform((val) => {
    // Strip non-numeric characters
    const digits = val.replace(/\D/g, '')
    // Normalize to +52 format
    if (digits.startsWith('52')) return `+${digits}`
    if (digits.startsWith('1') && digits.length === 11) return `+52${digits.slice(1)}`
    if (digits.length === 10) return `+52${digits}`
    return `+${digits}`
  })

// Matches any GSPN status code in the canonical lowercase form the notification
// pipeline uses (derived from `${gspn_status}.toLowerCase()`). The voice-enabled
// whitelist lives in `outbound_dispatch_rules` — any row ops toggles on there
// must be dispatchable here without a redeploy. The regex is a defensive filter
// against typos; the whitelist gate in `routes/outbound/index.ts` is the real
// authorization layer.
export const NotificationTypeEnum = z
  .string()
  .regex(/^st\d{3}$/, 'notification_type must match /^st\\d{3}$/ (e.g. "st025")')

export const WarrantyTypeEnum = z.enum(['in_warranty', 'out_of_warranty', 'extended'])

export const CreateEmailTemplateSchema = z.object({
  name: z.string().min(1, 'Name is required'),
  subject: z.string().min(1, 'Subject is required'),
  html_body: z.string().optional(),
  text_body: z.string().nullable().optional(),
  variables_schema: z.array(z.object({
    name: z.string(),
    required: z.boolean(),
  })).optional(),
  category: z.enum(['repair_status', 'pickup_confirmation', 'invoice', 'general']).default('general'),
  status: z.enum(['draft', 'active', 'disabled', 'archived']).default('draft'),
  design_json: z.unknown().optional(),
}).refine(
  (data) => data.html_body || data.design_json,
  { message: 'Either html_body or design_json must be provided' }
)

export const UpdateEmailTemplateSchema = z.object({
  name: z.string().min(1).optional(),
  subject: z.string().min(1).optional(),
  html_body: z.string().min(1).optional(),
  text_body: z.string().nullable().optional(),
  variables_schema: z.array(z.object({
    name: z.string(),
    required: z.boolean(),
  })).optional(),
  category: z.enum(['repair_status', 'pickup_confirmation', 'invoice', 'general']).optional(),
  status: z.enum(['draft', 'active', 'disabled', 'archived']).optional(),
  design_json: z.unknown().optional(),
})

export const SendEmailRequestSchema = z.object({
  template_id: z.string().uuid('Invalid template ID'),
  recipient_email: z.string().email('Invalid email address'),
  recipient_name: z.string().nullable().optional(),
  variables: z.record(z.string(), z.unknown()).default({}),
  service_order_id: z.string().optional(),
})

export const PreviewEmailTemplateSchema = z.object({
  variables: z.record(z.string(), z.unknown()).default({}),
})

export const UpdateEmailBrandSettingsSchema = z.object({
  company_name: z.string().optional(),
  logo_url: z.string().url().optional(),
  primary_color: z.string().optional(),
  secondary_color: z.string().optional(),
  footer_text: z.string().optional(),
  support_email: z.string().email().optional(),
  support_phone: z.string().optional(),
  website_url: z.string().url().optional(),
  social_links: z.record(z.string(), z.string()).optional(),
})

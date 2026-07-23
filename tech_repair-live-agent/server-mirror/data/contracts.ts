/**
 * Data Contracts
 * ==============
 * Defines the shape of the data layer the Core expects from Apps.
 * Apps implement these interfaces to provide data access.
 *
 * CONNECT ARCHITECTURE:
 * - Core defines what data it needs via interfaces
 * - Apps provide implementations (adapters)
 * - This allows Apps to swap data sources (Supabase, SQL, mock, etc.)
 */

import type { SupabaseClient } from '@supabase/supabase-js'
import type {
  WAConversation,
  WAConversationStatus,
  WAConversationChannel,
  WAMessage,
  WAMessageDirection,
  WAMessageSource,
  WAMessageType,
  WAMessageStatus,
  WATemplate,
} from './types'

// =============================================================================
// PAGINATION TYPES
// =============================================================================

/**
 * Pagination options for list queries
 */
export interface PaginationOptions {
  page: number
  limit: number
}

/**
 * Paginated result wrapper
 */
export interface PaginatedResult<T> {
  data: T[]
  pagination: {
    page: number
    limit: number
    total: number
    pages: number
  }
}

// =============================================================================
// DATA ADAPTER INTERFACE
// =============================================================================

/**
 * Conversation data operations required by the Core
 */
export interface ConversationAdapter {
  findById(id: string): Promise<WAConversation | null>
  findByPhoneNumber(phoneNumber: string): Promise<WAConversation | null>
  findByWaId(waId: string): Promise<WAConversation | null>
  findAll(
    pagination: PaginationOptions,
    filters?: {
      status?: WAConversationStatus
      phone_number?: string
      customer_id?: string
      search?: string
      date_from?: string
      date_to?: string
    }
  ): Promise<PaginatedResult<WAConversation>>
  findActive(limit?: number): Promise<WAConversation[]>
  create(data: {
    phone_number: string
    wa_id: string
    customer_name?: string
    customer_id?: string
    channel: WAConversationChannel
    active_service_order_id?: string
  }): Promise<WAConversation>
  update(id: string, data: Partial<WAConversation>): Promise<WAConversation>
  escalate(id: string, escalatedTo: string, reason?: string): Promise<WAConversation>
  close(id: string): Promise<WAConversation>
  getStats(filters?: { date_from?: string; date_to?: string }): Promise<{
    active: number
    escalated: number
    closed: number
    total: number
  }>
}

/**
 * Message data operations required by the Core
 */
export interface MessageAdapter {
  findById(id: string): Promise<WAMessage | null>
  findByWamid(wamid: string): Promise<WAMessage | null>
  findByConversationId(
    conversationId: string,
    pagination: PaginationOptions
  ): Promise<PaginatedResult<WAMessage>>
  getRecentMessages(conversationId: string, limit?: number): Promise<WAMessage[]>
  create(data: {
    conversation_id: string
    wamid?: string
    direction: WAMessageDirection
    source: WAMessageSource
    message_type: WAMessageType
    text_body?: string | null
    media_url?: string
    media_mime_type?: string
    media_caption?: string
    template_name?: string
    template_parameters?: Record<string, unknown>
    interactive_payload?: Record<string, unknown>
    location_data?: Record<string, unknown>
    ai_confidence_score?: number
    ai_intent_detected?: string
    ai_tool_calls?: Record<string, unknown>[]
    metadata?: Record<string, unknown>
  }): Promise<WAMessage>
  updateStatus(id: string, data: { status?: WAMessageStatus }): Promise<void>
  markSent(id: string, wamid: string): Promise<void>
  markDelivered(id: string): Promise<void>
  markRead(id: string): Promise<void>
  markFailed(id: string, errorCode: string, errorMessage: string): Promise<void>
}

/**
 * Template data operations required by the Core
 */
export interface TemplateAdapter {
  findById(id: string): Promise<WATemplate | null>
  findByName(name: string): Promise<WATemplate | null>
  findAll(
    pagination: PaginationOptions,
    filters?: {
      status?: 'approved' | 'pending' | 'rejected' | 'disabled'
      category?: 'authentication' | 'marketing' | 'utility'
    }
  ): Promise<PaginatedResult<WATemplate>>
  findApproved(language?: string): Promise<WATemplate[]>
  create(data: {
    name: string
    language: string
    category: string
    components: unknown[]
    parameter_schema?: Record<string, unknown>
    description?: string
    tags?: string[]
  }): Promise<WATemplate>
  update(id: string, data: Partial<WATemplate>): Promise<WATemplate>
  delete(id: string): Promise<void>
  createSend(data: {
    template_id: string
    conversation_id: string
    phone_number: string
    parameters: Record<string, unknown>
    is_simulation: boolean
    created_by: string
  }): Promise<{ id: string }>
  markSendSent(id: string, wamid: string): Promise<void>
  setResponseDeadline(id: string, deadline: string): Promise<void>
  getSendStats(templateId?: string, dateRange?: { startDate: string; endDate: string }): Promise<{
    total: number
    sent: number
    delivered: number
    read: number
    replied: number
    failed: number
  }>
  getAnalytics(dateRange?: { startDate: string; endDate: string }): Promise<{
    aggregate: {
      pending: number; pending_approval: number; sent: number; delivered: number
      read: number; replied: number; failed: number; escalated: number; total: number
    }
    perTemplate: Array<{
      template_id: string; send_count: number; failed_count: number
      delivered_count: number; last_used_at: string | null
    }>
  }>
  // Meta edit flow — see template.repository.ts for full rationale.
  // Atomic reserve-then-confirm over the 30-day edit cap and 24h cooldown
  // that Meta enforces on template edits. reserveEditSlot throws
  // EditSlotUnavailableError on guard failure; the route layer translates
  // that into a 429 with the specific reason code.
  reserveEditSlot(id: string): Promise<{
    edits_in_current_window: number
    edit_window_started_at: string
    last_edited_at: string
  }>
  releaseEditSlot(id: string): Promise<void>
  forceMaxEditCounter(id: string): Promise<void>
  findSyncHealth(): Promise<{
    last_meta_sync_at: string | null
    worker_last_beat_at: string | null
    last_sync_error: string | null
  }>
}

/**
 * Email template data operations required by the Core
 */
export interface EmailTemplateAdapter {
  findById(id: string): Promise<unknown | null>
  findActive(): Promise<unknown[]>
  findAll(
    pagination: PaginationOptions,
    filters?: {
      status?: 'draft' | 'active' | 'disabled'
      category?: string
      name_search?: string
    }
  ): Promise<PaginatedResult<unknown>>
  create(data: Record<string, unknown>): Promise<unknown>
  update(id: string, data: Record<string, unknown>): Promise<unknown>
  delete(id: string): Promise<void>
}

/**
 * Email send data operations required by the Core
 */
export interface EmailSendAdapter {
  findById(id: string): Promise<unknown | null>
  findBySesMessageId(sesMessageId: string): Promise<unknown | null>
  findAll(
    pagination: PaginationOptions,
    filters?: {
      status?: string
      template_id?: string
      recipient_email?: string
      date_from?: string
      date_to?: string
    }
  ): Promise<PaginatedResult<unknown>>
  create(data: Record<string, unknown>): Promise<{ id: string }>
  markSent(id: string, sesMessageId: string): Promise<void>
  markDelivered(id: string): Promise<void>
  markFailed(id: string, errorMessage: string): Promise<void>
  markBounced(id: string, bounceType: string): Promise<void>
  markComplained(id: string, complaintType: string | null): Promise<void>
  getStats(templateId?: string): Promise<Record<string, number>>
}

/**
 * Email brand settings operations required by the Core
 */
export interface EmailBrandAdapter {
  get(): Promise<unknown>
  update(data: Record<string, unknown>, updatedBy: string): Promise<unknown>
}

/**
 * Escalated task data operations required by the Core
 */
export interface EscalatedTaskAdapter {
  findById(id: string): Promise<unknown | null>
  findAll(
    pagination: PaginationOptions,
    filters?: {
      status?: string
      source_type?: string
      assigned_moderator_id?: string
    }
  ): Promise<PaginatedResult<unknown>>
  create(data: {
    conversation_id?: string
    room_name?: string
    source_type: 'whatsapp' | 'voice' | 'manual'
    customer_name?: string
    customer_phone: string
    ai_summary?: string
    sla_hours?: number
  }): Promise<unknown>
  update(id: string, data: Record<string, unknown>): Promise<unknown>
  addHistoryEntry(id: string, entry: {
    action: string
    from_status?: string
    to_status?: string
    actor_id: string
    actor_name?: string
    notes?: string
  }): Promise<void>
  findOverdue(): Promise<unknown[]>
  getStats(): Promise<{
    overdue_count: number
    by_status: Record<string, number>
    avg_resolution_hours: number | null
  }>
}

// =============================================================================
// COMPLETE DATA ADAPTER
// =============================================================================

/**
 * TechRepair Data Adapter Interface
 *
 * This tells the App what data tools the Core needs.
 * Apps implement this interface by wiring up their repositories.
 *
 * @example
 * // In your App's adapter.ts:
 * export function createPolancoAdapter(supabase: SupabaseClient): TechRepairDataAdapter {
 *   return {
 *     conversations: new ConversationRepository(supabase),
 *     messages: new MessageRepository(supabase),
 *     templates: new TemplateRepository(supabase),
 *     emailTemplates: new EmailTemplateRepository(supabase),
 *     emailSends: new EmailSendRepository(supabase),
 *     emailBrands: new EmailBrandRepository(supabase),
 *   }
 * }
 */
export interface TechRepairDataAdapter {
  conversations: ConversationAdapter
  messages: MessageAdapter
  templates: TemplateAdapter
  emailTemplates: EmailTemplateAdapter
  emailSends: EmailSendAdapter
  emailBrands: EmailBrandAdapter
  escalatedTasks?: EscalatedTaskAdapter
}

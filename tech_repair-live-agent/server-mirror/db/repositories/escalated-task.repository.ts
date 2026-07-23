/**
 * Escalated Task Repository
 * =========================
 * Repository for managing escalated task persistence.
 * All escalation-related database operations go through this repository.
 *
 * Responsibility: Escalated task CRUD, history tracking, SLA queries, stats
 * Allowed to know: Supabase client, escalated_tasks table structure
 * Must NOT know: AI verifier, orchestrator, push notifications
 */

import type { SupabaseClient } from '@supabase/supabase-js'
import type { PaginationOptions, PaginatedResult } from './types'
import { isWithinBusinessHours, getNextBusinessWindow, addBusinessHours } from '@/services/business-hours'

// ============================================================================
// Types
// ============================================================================

export type EscalationStatus =
  | 'new'
  | 'verified'
  | 'assigned'
  | 'in_progress'
  | 'resolved'
  | 'dismissed'

export type EscalationSource = 'whatsapp' | 'voice' | 'manual' | 'email' | 'system'

/** Pipeline an escalation belongs to (escalated_tasks.service_type enum). */
export type EscalationServiceType = 'carry_in' | 'd2d' | 'other'

export type VerificationStatus = 'pending' | 'verified' | 'failed'

export type ResolutionType =
  | 'agent_resolved'
  | 'warranty_issued'
  | 'refund_processed'
  | 'customer_satisfied'
  | 'referred_to_store'
  | 'closed_administrative'

export interface EscalatedTask {
  id: string
  org_id: string | null
  app_id: string | null
  conversation_id: string | null
  room_name: string | null
  source_type: EscalationSource
  service_type: EscalationServiceType | null
  customer_name: string | null
  customer_phone: string
  ai_summary: string | null
  memory_context: string | null
  verified_evidence: Record<string, unknown>[]
  contradictions: Record<string, unknown>[]
  verification_status: VerificationStatus
  raw_analysis: Record<string, unknown> | null
  status: EscalationStatus
  assigned_moderator_id: string | null
  assigned_by_id: string | null
  history: HistoryEntry[]
  resolution_notes: string | null
  resolution_type: ResolutionType | null
  follow_up_needed: boolean
  escalated_at: string
  sla_deadline: string
  completed_at: string | null
  pulpoo_task_id: string | null
  created_at: string
  updated_at: string
}

export interface HistoryEntry {
  action: string
  from_status?: string
  to_status?: string
  actor_id: string
  actor_name?: string
  timestamp: string
  notes?: string
}

export interface EscalatedTaskFilters {
  org_id?: string
  app_id?: string
  status?: EscalationStatus
  source_type?: EscalationSource
  assigned_moderator_id?: string
  verification_status?: VerificationStatus
  open_only?: boolean
  overdue_only?: boolean
}

export interface CreateEscalatedTaskDTO {
  org_id?: string
  app_id?: string
  conversation_id?: string
  room_name?: string
  source_type: EscalationSource
  customer_name?: string
  customer_phone: string
  ai_summary?: string
  memory_context?: string
  sla_hours?: number
  /** Stash extra context (e.g. email reply subject/snippet) for UI banners. */
  raw_analysis?: Record<string, unknown>
  /** Auto-assign the new task to a moderator. Used by manual escalations
   * (mod escaló por su cuenta → la toma directo) but NOT by auto flows. */
  assigned_moderator_id?: string
  /** Who originated the escalation (escalation actor). NULL for system /
   * automatic flows. */
  assigned_by_id?: string
}

export type CallbackPriority = 'urgent' | 'normal' | 'low'

/**
 * DTO for creating a voice-originated callback escalation. Requires the
 * columns added by migration `20260514150000_voice_intake_and_callback.sql`.
 *
 * Window encoding: `promised_callback_at` is when we made the promise
 * (typically `now()` at the time of the LLM tool call); `window_hours`
 * is how long we said it would take. The SLA deadline is computed as
 * `promised_callback_at + window_hours * 3600s` when `window_hours` is
 * present.
 *
 * `window_hours` is OPTIONAL — the inbound agent may promise a callback
 * without committing to a specific time ("alguien te va a llamar" without
 * a 2/4/24-hour figure). When omitted, the row records that a callback
 * was promised but the deadline-based overdue queries skip it (correctly
 * — there's no SLA to violate). The Escalations UI shows these as
 * "unscheduled callback" and ops decides when to pick them up.
 */
export interface CreateVoiceCallbackDTO {
  app_id?: string
  org_id?: string
  room_name: string
  call_id?: string
  customer_phone: string
  customer_name?: string
  ai_summary: string
  reason: string
  context_summary: string
  what_needs_solving: string
  priority: CallbackPriority
  promised_callback_at: Date
  window_hours?: number
  callback_number: string
  svc_order_no?: string
  /** Pipeline tag so the operator queue can filter voice callbacks by lane. */
  service_type?: EscalationServiceType
  /** Extra structured context (e.g. carry-in typed reason + operator queue). */
  raw_analysis?: Record<string, unknown>
  /** [sim] type-only: field is written at createVoiceCallback but was missing from the DTO upstream. */
  memory_context?: Record<string, unknown> | null
}

/**
 * DTO for an escalation raised by an automated background rule (no customer
 * channel): the carry-in 24h quote SLA tracker, the 5-day inactive-close job.
 * Always `source_type='system'`. Carries the typed `service_type`,
 * `svc_order_no`, `reason`, `priority`, and `context_summary` columns so the
 * operator queue can triage by pipeline + rule without probing JSONB.
 */
export interface CreateSystemTaskDTO {
  app_id?: string
  org_id?: string
  service_type?: EscalationServiceType
  svc_order_no?: string
  customer_phone: string
  customer_name?: string
  /** Stable machine reason, e.g. 'quote_sla_breach', 'inactive_5_day_close'. */
  reason: string
  priority?: CallbackPriority
  context_summary?: string
  ai_summary?: string
  /** Override the DB default (4h) SLA deadline when the rule wants a tighter one. */
  sla_hours?: number
  raw_analysis?: Record<string, unknown>
}

export interface UpdateEscalatedTaskDTO {
  status?: EscalationStatus
  assigned_moderator_id?: string | null
  assigned_by_id?: string | null
  resolution_notes?: string
  resolution_type?: ResolutionType
  follow_up_needed?: boolean
  // null clears the timestamp (used when reopening a previously resolved task);
  // undefined leaves the existing value alone.
  completed_at?: string | null
  ai_summary?: string
  memory_context?: string
  verified_evidence?: Record<string, unknown>[]
  contradictions?: Record<string, unknown>[]
  verification_status?: VerificationStatus
  raw_analysis?: Record<string, unknown>
  pulpoo_task_id?: string | null
}

export interface EscalatedTaskStats {
  /** Open + non-stale + past SLA. Excludes the abandoned backlog. */
  overdue_count: number
  /** Open escalations with activity in the last STALE_AFTER_DAYS days. */
  active_count: number
  /** Open escalations untouched for > STALE_AFTER_DAYS days (abandoned backlog). */
  stale_count: number
  /** Resolved + dismissed within the requested date range (period throughput). */
  resolved_count: number
  /** Counts by status for escalations created within the date range (pie chart). */
  by_status: Record<EscalationStatus, number>
  /** Avg resolution time for tasks resolved within the requested date range. */
  avg_resolution_hours: number | null
}

/** Open escalations untouched for longer than this are treated as abandoned. */
export const STALE_AFTER_DAYS = 7

// ============================================================================
// Repository Implementation
// ============================================================================

export class EscalatedTaskRepository {
  constructor(private supabase: SupabaseClient) {}

  /**
   * Find an existing escalation for a conversation that should be reused
   * instead of creating a new one. Returns the most recent task that is
   * either:
   *   - currently active (status: new, verified, assigned, in_progress), or
   *   - resolved/dismissed within the last `recentHours` window (default 72h).
   *
   * Used by the orchestrator's handleEscalation to prevent the "N escalations
   * for one customer" pattern when the moderator clicks unescalate, the
   * customer messages again, and the AI re-escalates. 72h covers the common
   * Friday-evening → Monday-morning gap when moderators don't work weekends.
   */
  async findActiveOrRecentByConversation(
    conversationId: string,
    recentHours: number = 72,
  ): Promise<EscalatedTask | null> {
    const { data, error } = await this.supabase
      .from('escalated_tasks')
      .select('*')
      .eq('conversation_id', conversationId)
      .order('created_at', { ascending: false })
      .limit(1)
      .maybeSingle()

    if (error) throw error
    if (!data) return null

    const task = this.mapToEscalatedTask(data)
    const ACTIVE = ['new', 'verified', 'assigned', 'in_progress']
    if (ACTIVE.includes(task.status)) return task

    if (task.completed_at) {
      const completedMs = new Date(task.completed_at).getTime()
      const cutoffMs = Date.now() - recentHours * 3_600_000
      if (completedMs >= cutoffMs) return task
    }

    return null
  }

  /**
   * Find escalated task by ID
   */
  async findById(id: string): Promise<EscalatedTask | null> {
    const { data, error } = await this.supabase
      .from('escalated_tasks')
      .select('*')
      .eq('id', id)
      .single()

    if (error) {
      if (error.code === 'PGRST116') return null
      throw error
    }

    return this.mapToEscalatedTask(data)
  }

  /**
   * List escalated tasks with optional filters and pagination.
   * Filtering by role is done by the caller (API layer) using filters.
   */
  async findAll(
    options?: PaginationOptions,
    filters?: EscalatedTaskFilters
  ): Promise<PaginatedResult<EscalatedTask>> {
    const page = options?.page ?? 0
    const limit = options?.limit ?? 20

    let query = this.supabase
      .from('escalated_tasks')
      .select('*', { count: 'exact' })

    if (filters?.app_id) {
      query = query.eq('app_id', filters.app_id)
    } else if (filters?.org_id) {
      query = query.eq('org_id', filters.org_id)
    }
    if (filters?.status) {
      query = query.eq('status', filters.status)
    } else if (filters?.open_only || filters?.overdue_only) {
      query = query.not('status', 'in', '(resolved,dismissed)')
    }
    if (filters?.overdue_only) {
      query = query.lt('sla_deadline', new Date().toISOString())
    }
    if (filters?.source_type) {
      query = query.eq('source_type', filters.source_type)
    }
    if (filters?.assigned_moderator_id) {
      query = query.eq('assigned_moderator_id', filters.assigned_moderator_id)
    }
    if (filters?.verification_status) {
      query = query.eq('verification_status', filters.verification_status)
    }

    const { data, count, error } = await query
      .order('escalated_at', { ascending: false })
      .range(page * limit, (page + 1) * limit - 1)

    if (error) throw error

    return {
      data: (data ?? []).map((row) => this.mapToEscalatedTask(row)),
      pagination: {
        page,
        limit,
        total: count ?? 0,
        pages: Math.ceil((count ?? 0) / limit),
      },
    }
  }

  /**
   * Create a new escalated task
   */
  async create(dto: CreateEscalatedTaskDTO): Promise<EscalatedTask> {
    const insertData: Record<string, unknown> = {
      source_type: dto.source_type,
      customer_phone: dto.customer_phone,
    }

    if (dto.org_id) insertData.org_id = dto.org_id
    if (dto.app_id) insertData.app_id = dto.app_id
    if (dto.conversation_id) insertData.conversation_id = dto.conversation_id
    if (dto.room_name) insertData.room_name = dto.room_name
    if (dto.customer_name) insertData.customer_name = dto.customer_name
    if (dto.ai_summary) insertData.ai_summary = dto.ai_summary
    if (dto.memory_context) insertData.memory_context = dto.memory_context
    if (dto.raw_analysis) insertData.raw_analysis = dto.raw_analysis
    if (dto.assigned_moderator_id) insertData.assigned_moderator_id = dto.assigned_moderator_id
    if (dto.assigned_by_id) insertData.assigned_by_id = dto.assigned_by_id

    // SLA deadline counted in BUSINESS hours (Mon-Sat 10am-7pm MX), so a case
    // opened at 6pm Friday isn't "overdue" overnight or over the weekend.
    // Defaults to 4 business hours when the caller doesn't specify sla_hours.
    // (Voice callbacks set sla_deadline themselves via createVoiceCallback and
    // never pass through here.)
    insertData.sla_deadline = addBusinessHours(new Date(), dto.sla_hours ?? 4).toISOString()

    const { data, error } = await this.supabase
      .from('escalated_tasks')
      .insert(insertData)
      .select()
      .single()

    if (error) throw error

    return this.mapToEscalatedTask(data)
  }

  /**
   * Create an escalated task originated from a voice call (inbound or
   * outbound). Writes the typed callback columns added in migration
   * `20260514150000_voice_intake_and_callback.sql`.
   */
  async createVoiceCallback(dto: CreateVoiceCallbackDTO): Promise<EscalatedTask> {
    // Callbacks happen only during store service hours (Mon-Sat 10AM-7PM
    // America/Mexico_City). The promised window the bot spoke may land
    // outside hours — clamp the SLA deadline so it always falls inside.
    // What the bot promised stays in `promised_callback_window_hours`
    // for audit; what the team must actually do by is `sla_deadline`.
    const intendedTarget = dto.window_hours
      ? new Date(dto.promised_callback_at.getTime() + dto.window_hours * 3_600_000)
      : null
    const slaDeadline =
      intendedTarget && isWithinBusinessHours(intendedTarget)
        ? intendedTarget
        : getNextBusinessWindow(intendedTarget ?? dto.promised_callback_at)

    const insertData: Record<string, unknown> = {
      source_type: 'voice',
      customer_phone: dto.customer_phone,
      room_name: dto.room_name,
      ai_summary: dto.ai_summary,
      reason: dto.reason,
      context_summary: dto.context_summary,
      what_needs_solving: dto.what_needs_solving,
      priority: dto.priority,
      promised_callback_at: dto.promised_callback_at.toISOString(),
      // Leave NULL when the agent didn't commit to a specific window —
      // ops sees these as "unscheduled callback" in the dashboard.
      promised_callback_window_hours: dto.window_hours ?? null,
      callback_number: dto.callback_number,
      // Mirror the deadline onto sla_deadline so existing overdue logic
      // (sla_deadline < now()) keeps working alongside the new
      // idx_escalated_tasks_callback_sla expression index.
      sla_deadline: slaDeadline.toISOString(),
    }

    // TODO(app_id-guard): a null/undefined app_id silently produces an
    // unscoped row that the app-scoped pendientes read filters out (this was
    // the voice-escalation invisibility bug — workers not calling setAppId()).
    // Harden create()/createVoiceCallback() to warn or reject on missing
    // app_id instead of inserting NULL. Tracked as a follow-up.
    if (dto.app_id) insertData.app_id = dto.app_id
    if (dto.org_id) insertData.org_id = dto.org_id
    if (dto.call_id) insertData.call_id = dto.call_id
    if (dto.customer_name) insertData.customer_name = dto.customer_name
    if (dto.svc_order_no) insertData.svc_order_no = dto.svc_order_no
    if (dto.service_type) insertData.service_type = dto.service_type
    if (dto.raw_analysis) insertData.raw_analysis = dto.raw_analysis
    if (dto.memory_context) insertData.memory_context = dto.memory_context

    const { data, error } = await this.supabase
      .from('escalated_tasks')
      .insert(insertData)
      .select()
      .single()

    if (error) throw error

    return this.mapToEscalatedTask(data)
  }

  /**
   * Create an escalated task raised by an automated background rule
   * (`source_type='system'`). Used by the carry-in SLA tracker and the
   * inactive-close job. Sets the typed pipeline/order/reason columns so ops
   * can filter `WHERE service_type='carry_in' AND reason='quote_sla_breach'`
   * directly.
   */
  async createSystemTask(dto: CreateSystemTaskDTO): Promise<EscalatedTask> {
    const insertData: Record<string, unknown> = {
      source_type: 'system',
      customer_phone: dto.customer_phone,
      reason: dto.reason,
    }

    if (dto.app_id) insertData.app_id = dto.app_id
    if (dto.org_id) insertData.org_id = dto.org_id
    if (dto.service_type) insertData.service_type = dto.service_type
    if (dto.svc_order_no) insertData.svc_order_no = dto.svc_order_no
    if (dto.customer_name) insertData.customer_name = dto.customer_name
    if (dto.priority) insertData.priority = dto.priority
    if (dto.context_summary) insertData.context_summary = dto.context_summary
    if (dto.ai_summary) insertData.ai_summary = dto.ai_summary
    if (dto.raw_analysis) insertData.raw_analysis = dto.raw_analysis

    if (dto.sla_hours) {
      const deadline = new Date()
      deadline.setHours(deadline.getHours() + dto.sla_hours)
      insertData.sla_deadline = deadline.toISOString()
    }

    const { data, error } = await this.supabase
      .from('escalated_tasks')
      .insert(insertData)
      .select()
      .single()

    if (error) throw error

    return this.mapToEscalatedTask(data)
  }

  /**
   * Update an existing escalated task
   */
  async update(id: string, dto: UpdateEscalatedTaskDTO): Promise<EscalatedTask> {
    const updateData: Record<string, unknown> = {}

    if (dto.status !== undefined) updateData.status = dto.status
    if (dto.assigned_moderator_id !== undefined) updateData.assigned_moderator_id = dto.assigned_moderator_id
    if (dto.assigned_by_id !== undefined) updateData.assigned_by_id = dto.assigned_by_id
    if (dto.resolution_notes !== undefined) updateData.resolution_notes = dto.resolution_notes
    if (dto.resolution_type !== undefined) updateData.resolution_type = dto.resolution_type
    if (dto.follow_up_needed !== undefined) updateData.follow_up_needed = dto.follow_up_needed
    if (dto.completed_at !== undefined) updateData.completed_at = dto.completed_at
    if (dto.ai_summary !== undefined) updateData.ai_summary = dto.ai_summary
    if (dto.memory_context !== undefined) updateData.memory_context = dto.memory_context
    if (dto.verified_evidence !== undefined) updateData.verified_evidence = dto.verified_evidence
    if (dto.contradictions !== undefined) updateData.contradictions = dto.contradictions
    if (dto.verification_status !== undefined) updateData.verification_status = dto.verification_status
    if (dto.raw_analysis !== undefined) updateData.raw_analysis = dto.raw_analysis
    if (dto.pulpoo_task_id !== undefined) updateData.pulpoo_task_id = dto.pulpoo_task_id

    const { data, error } = await this.supabase
      .from('escalated_tasks')
      .update(updateData)
      .eq('id', id)
      .select()
      .single()

    if (error) throw error

    return this.mapToEscalatedTask(data)
  }

  /**
   * Append a history entry to the JSONB history array.
   * Uses Supabase RPC to atomically append (avoids read-then-write race).
   */
  async addHistoryEntry(id: string, entry: Omit<HistoryEntry, 'timestamp'>): Promise<void> {
    const fullEntry: HistoryEntry = {
      ...entry,
      timestamp: new Date().toISOString(),
    }

    const { error } = await this.supabase.rpc('append_escalation_history', {
      p_task_id: id,
      p_entry: fullEntry,
    })

    if (error) throw error
  }

  /**
   * Find tasks with overdue SLA (deadline passed, still open)
   */
  async findOverdue(appId?: string): Promise<EscalatedTask[]> {
    let query = this.supabase
      .from('escalated_tasks')
      .select('*')
      .lt('sla_deadline', new Date().toISOString())
      .not('status', 'in', '(resolved,dismissed)')

    if (appId) {
      query = query.eq('app_id', appId)
    }

    const { data, error } = await query
      .order('sla_deadline', { ascending: true })

    if (error) throw error

    return (data ?? []).map((row) => this.mapToEscalatedTask(row))
  }

  /**
   * Get escalation statistics for the dashboard.
   *
   * - active/stale/overdue are a CURRENT snapshot (not date-scoped): "active"
   *   = open with activity in the last STALE_AFTER_DAYS days; the abandoned
   *   backlog (open but untouched > STALE_AFTER_DAYS) is split out as "stale"
   *   so it stops inflating active/overdue forever.
   * - resolved_count / avg_resolution_hours / by_status are scoped to
   *   [startDate, endDate] (resolved by completed_at, by_status by escalated_at).
   *   Omitting the range counts all-time.
   */
  async getStats(
    appId?: string,
    startDate?: string,
    endDate?: string
  ): Promise<EscalatedTaskStats> {
    let query = this.supabase
      .from('escalated_tasks')
      .select('status, escalated_at, completed_at, sla_deadline, updated_at, source_type, conversation_id, room_name')

    if (appId) {
      query = query.eq('app_id', appId)
    }

    const { data, error } = await query

    if (error) throw error

    // Sync / template-failure escalations (GSPN ops: whatsapp source, no
    // conversation, service order stashed in room_name) are NOT customer
    // escalations — the inbox routes them to a separate "Revisión" tray and
    // excludes them via !review_kind. Mirror that here so the dashboard KPIs
    // count only real customer escalations.
    const isSyncEscalation = (row: { source_type?: unknown; conversation_id?: unknown; room_name?: unknown }) =>
      row.source_type === 'whatsapp' && !row.conversation_id && !!row.room_name
    const rows = (data ?? []).filter((row) => !isSyncEscalation(row))
    const now = new Date()
    const staleBefore = new Date(now.getTime() - STALE_AFTER_DAYS * 86_400_000)
    const rangeStart = startDate ? new Date(startDate) : null
    const rangeEnd = endDate ? new Date(endDate) : null

    const OPEN_STATUSES: EscalationStatus[] = ['new', 'verified', 'assigned', 'in_progress']

    // Count by status (all-time)
    const by_status: Record<EscalationStatus, number> = {
      new: 0,
      verified: 0,
      assigned: 0,
      in_progress: 0,
      resolved: 0,
      dismissed: 0,
    }

    let active_count = 0
    let stale_count = 0
    let overdue_count = 0
    let resolved_count = 0
    let total_resolution_hours = 0
    let resolution_basis = 0

    for (const row of rows) {
      const status = row.status as EscalationStatus

      // Status distribution (pie chart) — scoped to escalations CREATED within
      // the selected period, not all-time.
      if (status in by_status) {
        const escalatedAt = row.escalated_at ? new Date(row.escalated_at as string) : null
        const escInRange =
          !!escalatedAt &&
          (!rangeStart || escalatedAt >= rangeStart) &&
          (!rangeEnd || escalatedAt <= rangeEnd)
        if (escInRange) by_status[status]++
      }

      if (OPEN_STATUSES.includes(status)) {
        // Stale = open but untouched for > STALE_AFTER_DAYS. Excluded from the
        // live counts so the abandoned backlog doesn't read as active/overdue.
        const updatedAt = row.updated_at ? new Date(row.updated_at as string) : now
        if (updatedAt < staleBefore) {
          stale_count++
        } else {
          active_count++
          if (row.sla_deadline && new Date(row.sla_deadline as string) < now) {
            overdue_count++
          }
        }
      }

      // Throughput: resolved/dismissed with completed_at inside the period.
      if ((status === 'resolved' || status === 'dismissed') && row.completed_at) {
        const completedAt = new Date(row.completed_at as string)
        const inRange =
          (!rangeStart || completedAt >= rangeStart) && (!rangeEnd || completedAt <= rangeEnd)
        if (inRange) {
          resolved_count++
          // Avg resolution time: only genuinely resolved (not dismissed).
          if (status === 'resolved' && row.escalated_at) {
            total_resolution_hours +=
              (completedAt.getTime() - new Date(row.escalated_at as string).getTime()) /
              (1000 * 60 * 60)
            resolution_basis++
          }
        }
      }
    }

    return {
      overdue_count,
      active_count,
      stale_count,
      resolved_count,
      by_status,
      avg_resolution_hours: resolution_basis > 0
        ? Math.round((total_resolution_hours / resolution_basis) * 10) / 10
        : null,
    }
  }

  /**
   * Count active (non-closed) escalations per assigned moderator.
   * Returns a map of moderator_id → active escalation count.
   */
  async getActiveCountByModerator(appId?: string): Promise<Record<string, number>> {
    let query = this.supabase
      .from('escalated_tasks')
      .select('assigned_moderator_id')
      .not('assigned_moderator_id', 'is', null)
      .not('status', 'in', '(resolved,dismissed)')

    if (appId) {
      query = query.eq('app_id', appId)
    }

    const { data, error } = await query

    if (error) throw error

    const counts: Record<string, number> = {}
    for (const row of data ?? []) {
      const modId = row.assigned_moderator_id as string
      counts[modId] = (counts[modId] || 0) + 1
    }
    return counts
  }

  /**
   * Find all unassigned, open escalations for an org.
   */
  async findUnassigned(appId: string): Promise<EscalatedTask[]> {
    const { data, error } = await this.supabase
      .from('escalated_tasks')
      .select('*')
      .eq('app_id', appId)
      .is('assigned_moderator_id', null)
      .not('status', 'in', '(resolved,dismissed)')
      .order('escalated_at', { ascending: true })

    if (error) throw error

    return (data ?? []).map((row) => this.mapToEscalatedTask(row))
  }

  // ============================================================================
  // Analytics Methods (Ticket 1.2)
  // ============================================================================

  /**
   * Get escalation trends grouped by day or week within a date range.
   */
  async getTrends(
    appId: string,
    startDate: string,
    endDate: string,
    _groupBy: 'day' | 'week' = 'day'
  ): Promise<{
    trends: Array<{ date: string; total: number; resolved: number; dismissed: number; avg_resolution_hours: number | null }>
    by_source: Record<string, number>
    sla_compliance: { met: number; breached: number; rate: number }
  }> {
    const { data, error } = await this.supabase
      .from('escalated_tasks')
      .select('status, source_type, escalated_at, completed_at, sla_deadline')
      .eq('app_id', appId)
      .gte('escalated_at', startDate)
      .lte('escalated_at', endDate)

    if (error) throw error

    const rows = data ?? []

    // Group by date
    const dayMap = new Map<string, { total: number; resolved: number; dismissed: number; resolution_hours: number[] }>()
    const sourceMap: Record<string, number> = {}
    let slaMet = 0
    let slaBreached = 0

    for (const row of rows) {
      const dateKey = (row.escalated_at as string).slice(0, 10) // YYYY-MM-DD

      if (!dayMap.has(dateKey)) {
        dayMap.set(dateKey, { total: 0, resolved: 0, dismissed: 0, resolution_hours: [] })
      }
      const bucket = dayMap.get(dateKey)!
      bucket.total++

      const status = row.status as string
      if (status === 'resolved') {
        bucket.resolved++
        if (row.completed_at && row.escalated_at) {
          const hours = (new Date(row.completed_at as string).getTime() - new Date(row.escalated_at as string).getTime()) / (1000 * 60 * 60)
          bucket.resolution_hours.push(hours)
        }
      } else if (status === 'dismissed') {
        bucket.dismissed++
      }

      // Source breakdown
      const src = row.source_type as string
      sourceMap[src] = (sourceMap[src] || 0) + 1

      // SLA compliance (only for resolved/dismissed)
      if (status === 'resolved' || status === 'dismissed') {
        if (row.completed_at && row.sla_deadline) {
          if (new Date(row.completed_at as string) <= new Date(row.sla_deadline as string)) {
            slaMet++
          } else {
            slaBreached++
          }
        }
      }
    }

    const trends = Array.from(dayMap.entries())
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([date, d]) => ({
        date,
        total: d.total,
        resolved: d.resolved,
        dismissed: d.dismissed,
        avg_resolution_hours: d.resolution_hours.length > 0
          ? Math.round((d.resolution_hours.reduce((a, b) => a + b, 0) / d.resolution_hours.length) * 10) / 10
          : null,
      }))

    const slaTotal = slaMet + slaBreached
    return {
      trends,
      by_source: sourceMap,
      sla_compliance: {
        met: slaMet,
        breached: slaBreached,
        rate: slaTotal > 0 ? Math.round((slaMet / slaTotal) * 1000) / 10 : 100,
      },
    }
  }

  /**
   * Get AI-generated themes from recent escalation summaries.
   */
  async getRecentSummaries(appId: string, limit = 50): Promise<string[]> {
    const { data, error } = await this.supabase
      .from('escalated_tasks')
      .select('ai_summary')
      .eq('app_id', appId)
      .not('ai_summary', 'is', null)
      .order('escalated_at', { ascending: false })
      .limit(limit)

    if (error) throw error

    return (data ?? [])
      .map((r) => r.ai_summary as string)
      .filter(Boolean)
  }

  // ============================================================================
  // Sync Helpers (Ticket 2.2)
  // ============================================================================

  /**
   * Find non-terminal escalations that have a linked Pulpoo task.
   * Used by reverse sync to check if Pulpoo status has changed.
   */
  async findWithPulpooTasks(appId?: string): Promise<EscalatedTask[]> {
    let query = this.supabase
      .from('escalated_tasks')
      .select('*')
      .not('pulpoo_task_id', 'is', null)
      .not('status', 'in', '(resolved,dismissed)')

    if (appId) {
      query = query.eq('app_id', appId)
    }

    const { data, error } = await query
    if (error) throw error
    return (data ?? []).map((row) => this.mapToEscalatedTask(row as Record<string, unknown>))
  }

  // ============================================================================
  // Private Helpers
  // ============================================================================

  private mapToEscalatedTask(row: Record<string, unknown>): EscalatedTask {
    return {
      id: row.id as string,
      org_id: row.org_id as string | null,
      app_id: (row.app_id as string) ?? null,
      conversation_id: row.conversation_id as string | null,
      room_name: row.room_name as string | null,
      source_type: row.source_type as EscalationSource,
      service_type: (row.service_type as EscalationServiceType) ?? null,
      customer_name: row.customer_name as string | null,
      customer_phone: row.customer_phone as string,
      ai_summary: row.ai_summary as string | null,
      memory_context: (row.memory_context as string) ?? null,
      verified_evidence: (row.verified_evidence as Record<string, unknown>[]) ?? [],
      contradictions: (row.contradictions as Record<string, unknown>[]) ?? [],
      verification_status: (row.verification_status as VerificationStatus) ?? 'pending',
      raw_analysis: row.raw_analysis as Record<string, unknown> | null,
      status: row.status as EscalationStatus,
      assigned_moderator_id: row.assigned_moderator_id as string | null,
      assigned_by_id: row.assigned_by_id as string | null,
      history: (row.history as HistoryEntry[]) ?? [],
      resolution_notes: row.resolution_notes as string | null,
      resolution_type: (row.resolution_type as ResolutionType) ?? null,
      follow_up_needed: (row.follow_up_needed as boolean) ?? false,
      escalated_at: row.escalated_at as string,
      sla_deadline: row.sla_deadline as string,
      completed_at: row.completed_at as string | null,
      pulpoo_task_id: row.pulpoo_task_id as string | null,
      created_at: row.created_at as string,
      updated_at: row.updated_at as string,
    }
  }
}

/**
 * Escalation Rules Engine
 * =======================
 * Evaluates active auto-escalation rules after interactions.
 * Called from agent post-interaction hooks.
 */

import type { SupabaseClient } from '@supabase/supabase-js'
import { EscalationRulesRepository, type EscalationRule } from '@/db/repositories/escalation-rules.repository'
import { EscalatedTaskRepository } from '@/db/repositories/escalated-task.repository'
import { getAppId } from '@/shared/supabase'
import { logEscalationReason } from '@/services/lane-selector'

interface EvaluationContext {
  phone: string
  channel: 'voice' | 'whatsapp' | 'web'
  sentimentScore?: number
  orgId: string
}

/**
 * Evaluate all active rules for an org after an interaction.
 * Creates an escalation if any rule triggers.
 */
export async function evaluateRules(
  supabase: SupabaseClient,
  context: EvaluationContext,
): Promise<{ triggered: boolean; ruleName?: string }> {
  const rulesRepo = new EscalationRulesRepository(supabase)
  const rules = await rulesRepo.findActive(context.orgId)

  if (rules.length === 0) return { triggered: false }

  for (const rule of rules) {
    const result = await evaluateRule(supabase, rule, context)
    if (result.triggered) {
      await createAutoEscalation(supabase, rule, context, result.svcOrderNo)
      return { triggered: true, ruleName: rule.name }
    }
  }

  return { triggered: false }
}

async function evaluateRule(
  supabase: SupabaseClient,
  rule: EscalationRule,
  context: EvaluationContext,
): Promise<{ triggered: boolean; svcOrderNo?: string }> {
  const config = rule.trigger_config

  switch (rule.trigger_type) {
    case 'call_frequency': {
      const maxCalls = (config.max_calls as number) ?? 3
      const withinDays = (config.within_days as number) ?? 7
      const since = new Date(Date.now() - withinDays * 86400000).toISOString()

      const { count, error } = await supabase
        .from('interaction_history')
        .select('*', { count: 'exact', head: true })
        .eq('phone', context.phone)
        .gte('created_at', since)

      if (error) {
        console.error('[RulesEngine] Call frequency query error:', error)
        return { triggered: false }
      }

      return { triggered: (count ?? 0) >= maxCalls }
    }

    case 'sentiment_threshold': {
      if (context.sentimentScore === undefined) return { triggered: false }

      const threshold = (config.threshold as number) ?? 0.3
      // Normalize: threshold 0.3 maps to score <= 1.5 on 1-5 scale
      const scoreThreshold = threshold * 5
      const wouldTrigger = context.sentimentScore <= scoreThreshold

      // Shadow mode for WhatsApp: log but don't trigger until shadow_expires_at
      const shadowExpires = config.shadow_expires_at as string | undefined
      const inShadow = context.channel !== 'voice'
        && shadowExpires
        && new Date(shadowExpires) > new Date()

      if (inShadow) {
        if (wouldTrigger) {
          console.info(`[RulesEngine:Shadow] WA sentiment would trigger: score=${context.sentimentScore}, threshold=${scoreThreshold}, phone=${context.phone}`)
          // Log shadow trigger for analysis
          supabase.from('escalation_shadow_log').insert({
            rule_name: rule.name,
            phone: context.phone,
            channel: context.channel,
            sentiment_score: context.sentimentScore,
            would_have_triggered: true,
          }).then(({ error }) => {
            if (error) console.warn('[RulesEngine:Shadow] Failed to log:', error)
          })
        }
        return { triggered: false }
      }

      // WhatsApp without shadow mode, or voice channel — trigger normally
      return { triggered: wouldTrigger }
    }

    case 'gspn_status_duration': {
      // Per-interaction check: when a customer calls/messages, check if THEIR orders are stuck.
      // A broader scan of ALL orders runs in evaluateStatusDurationRules() after each sync cycle.
      const statusCode = config.status_code as string
      const maxHours = (config.max_hours as number) ?? 48
      if (!statusCode) return { triggered: false }

      // 1. Find this customer's service order numbers from interaction history
      const { data: interactions, error: intError } = await supabase
        .from('interaction_history')
        .select('svc_order_no')
        .eq('phone', context.phone)
        .not('svc_order_no', 'is', null)
        .order('created_at', { ascending: false })
        .limit(5)

      if (intError || !interactions?.length) return { triggered: false }

      const orderNos = [...new Set(interactions.map(i => i.svc_order_no as string))]

      // 2. Check if any of those orders is stuck in the target status longer than max_hours.
      //    service_orders.status_changed_at is updated by the sync worker on every status change.
      const cutoff = new Date(Date.now() - maxHours * 3600000).toISOString()

      const { data: stuckOrders, error: soError } = await supabase
        .from('service_orders')
        .select('svc_order_no')
        .in('svc_order_no', orderNos)
        .eq('status', statusCode)
        .lte('status_changed_at', cutoff)
        .limit(1)

      if (soError) {
        console.error('[RulesEngine] Status duration query error:', soError)
        return { triggered: false }
      }

      if (!stuckOrders?.length) return { triggered: false }

      // 3. Dedup: check if there's already an active or recently closed escalation for this order.
      //    See shouldSkipEscalation() for the full dedup logic (24h cooldown, etc.)
      const stuckOrderNo = stuckOrders[0].svc_order_no
      const skip = await shouldSkipEscalation(supabase, context.orgId, stuckOrderNo)
      if (skip) return { triggered: false }

      return { triggered: true, svcOrderNo: stuckOrderNo }
    }

    case 'repeat_issue_same_order': {
      // Detect when a customer has contacted multiple times about the same service order.
      // Uses the authoritative DB record (not the LLM's customer_claims_repeat_contact).
      const maxContacts = (config.max_contacts as number) ?? 3
      const withinDays = (config.within_days as number) ?? 14
      const since = new Date(Date.now() - withinDays * 86400000).toISOString()

      // Find this customer's interactions with service order numbers
      const { data: orderInteractions, error: oiError } = await supabase
        .from('interaction_history')
        .select('svc_order_no')
        .eq('phone', context.phone)
        .not('svc_order_no', 'is', null)
        .gte('created_at', since)

      if (oiError || !orderInteractions?.length) return { triggered: false }

      // Count interactions per order number
      const orderCounts = new Map<string, number>()
      for (const row of orderInteractions) {
        const orderNo = row.svc_order_no as string
        orderCounts.set(orderNo, (orderCounts.get(orderNo) ?? 0) + 1)
      }

      // Check if any order exceeds the threshold
      for (const [orderNo, count] of orderCounts) {
        if (count >= maxContacts) {
          // Dedup: check existing escalation for this order
          const skip = await shouldSkipEscalation(supabase, context.orgId, orderNo)
          if (!skip) {
            return { triggered: true, svcOrderNo: orderNo }
          }
        }
      }

      return { triggered: false }
    }

    default:
      return { triggered: false }
  }
}

/**
 * Dedup logic for gspn_status_duration escalations.
 *
 * Returns true (skip) if:
 * - There's an OPEN escalation for this order (new, verified, assigned, in_progress)
 * - There's a RESOLVED escalation for this order closed less than 24h ago (give TechRepair time)
 * - There's a DISMISSED escalation for this order closed less than 24h ago (cooldown for accidental dismissals)
 *
 * Returns false (proceed) if:
 * - No escalation exists for this order
 * - Last escalation was resolved/dismissed more than 24h ago and order is still stuck
 */
async function shouldSkipEscalation(
  supabase: SupabaseClient,
  orgId: string,
  svcOrderNo: string,
): Promise<boolean> {
  const COOLDOWN_MS = 24 * 3600000 // 24 hours

  // Check for any escalation mentioning this order number
  const { data: escalations } = await supabase
    .from('escalated_tasks')
    .select('id, status, completed_at')
    .eq('org_id', orgId)
    .ilike('ai_summary', `%Orden: ${svcOrderNo}%`)
    .order('created_at', { ascending: false })
    .limit(1)

  if (!escalations?.length) return false // No prior escalation → proceed

  const latest = escalations[0]

  // OPEN escalation → skip (someone is on it)
  if (['new', 'verified', 'assigned', 'in_progress'].includes(latest.status)) {
    console.info(`[RulesEngine] Skip — open escalation exists for order ${svcOrderNo}`)
    return true
  }

  // RESOLVED or DISMISSED within 24h → skip (cooldown)
  if (latest.completed_at) {
    const closedAt = new Date(latest.completed_at).getTime()
    const hoursSinceClosed = (Date.now() - closedAt) / 3600000

    if (Date.now() - closedAt < COOLDOWN_MS) {
      console.info(`[RulesEngine] Skip — order ${svcOrderNo} escalation ${latest.status} ${Math.round(hoursSinceClosed)}h ago (24h cooldown)`)
      return true
    }
  }

  // Resolved/dismissed > 24h ago and order still stuck → proceed with re-escalation
  return false
}

async function createAutoEscalation(
  supabase: SupabaseClient,
  rule: EscalationRule,
  context: EvaluationContext,
  svcOrderNo?: string,
): Promise<void> {
  const taskRepo = new EscalatedTaskRepository(supabase)

  // Check if there's already an open escalation for this customer
  const { data: existing } = await supabase
    .from('escalated_tasks')
    .select('id')
    .eq('customer_phone', context.phone)
    .eq('org_id', context.orgId)
    .not('status', 'in', '(resolved,dismissed)')
    .limit(1)

  if (existing && existing.length > 0) {
    console.info(`[RulesEngine] Skipping auto-escalation — open escalation exists for ${context.phone}`)
    return
  }

  // Look up customer name from memory
  const { data: profile } = await supabase
    .from('customer_memory')
    .select('name')
    .eq('phone', context.phone)
    .single()

  // Include svc_order_no in summary if available (used by shouldSkipEscalation for dedup)
  const summaryParts = [`Auto-escalado por regla: ${rule.name}`]
  if (svcOrderNo) summaryParts.push(`Orden: ${svcOrderNo}`)

  const task = await taskRepo.create({
    org_id: context.orgId,
    app_id: getAppId() ?? undefined,
    source_type: context.channel === 'voice' ? 'voice' : context.channel === 'whatsapp' ? 'whatsapp' : 'manual',
    customer_phone: context.phone,
    customer_name: profile?.name ?? null,
    ai_summary: summaryParts.join(' | '),
  })

  await taskRepo.addHistoryEntry(task.id, {
    action: 'auto_escalated',
    to_status: 'new',
    actor_id: 'system',
    actor_name: 'Sistema',
    notes: `Regla activada: ${rule.name} (${rule.trigger_type})`,
  })

  // Audit log — record why this escalation was created in agent_thoughts so
  // ops can later answer "what triggered this escalation?" with one query.
  await logEscalationReason(supabase, {
    trigger: `auto_rule:${rule.trigger_type}`,
    reason: `Regla auto-escalation activada: ${rule.name}`,
    context: {
      rule_id: rule.id,
      rule_name: rule.name,
      channel: context.channel,
      phone: context.phone,
      svc_order_no: svcOrderNo,
      escalated_task_id: task.id,
    },
  })

  console.info(`[RulesEngine] Auto-escalation created: ${task.id} (rule: ${rule.name})`)
}

// =============================================================================
// SCHEDULED STATUS DURATION CHECK (runs after each GSPN sync cycle)
// =============================================================================

interface StatusDurationResult {
  rulesChecked: number
  ordersScanned: number
  escalationsCreated: number
  skipped: number
  details: Array<{ svc_order_no: string; action: 'created' | 'skipped'; reason: string }>
}

/**
 * Scan ALL service orders for status duration violations.
 *
 * Called after each GSPN sync cycle (every 10 min during business hours).
 * Unlike the per-interaction evaluateRule(), this checks every order in the system —
 * catches stuck orders even if the customer never called.
 *
 * Dedup logic (shouldSkipEscalation):
 * - Open escalation exists for this order → skip
 * - Resolved/dismissed < 24h ago → skip (cooldown)
 * - Resolved/dismissed > 24h ago and still stuck → re-escalate
 */
export async function evaluateStatusDurationRules(
  supabase: SupabaseClient,
  orgId: string,
): Promise<StatusDurationResult> {
  const result: StatusDurationResult = {
    rulesChecked: 0,
    ordersScanned: 0,
    escalationsCreated: 0,
    skipped: 0,
    details: [],
  }

  // 1. Load active gspn_status_duration rules for this org
  const rulesRepo = new EscalationRulesRepository(supabase)
  const allRules = await rulesRepo.findActive(orgId)
  const durationRules = allRules.filter(r => r.trigger_type === 'gspn_status_duration')

  if (durationRules.length === 0) return result
  result.rulesChecked = durationRules.length

  const taskRepo = new EscalatedTaskRepository(supabase)

  // 2. For each rule, find stuck orders (capped at 50 per rule per cycle)
  for (const rule of durationRules) {
    const statusCode = rule.trigger_config.status_code as string
    const maxHours = (rule.trigger_config.max_hours as number) ?? 48
    if (!statusCode) continue

    const cutoff = new Date(Date.now() - maxHours * 3600000).toISOString()

    const { data: stuckOrders, error } = await supabase
      .from('service_orders')
      .select('svc_order_no, contact_no, cust_name')
      .eq('status', statusCode)
      .eq('service_type', 'd2d')
      .lte('status_changed_at', cutoff)
      .limit(50)

    if (error) {
      console.error(`[RulesEngine:Sync] Query error for rule ${rule.name}:`, error)
      continue
    }

    if (!stuckOrders?.length) continue
    result.ordersScanned += stuckOrders.length

    // 3. Batch-fetch recent escalations for all stuck orders to avoid N+1
    //    30-day window covers the 24h cooldown with wide margin; older escalations are irrelevant for dedup
    const orderNos = stuckOrders.map(o => o.svc_order_no)
    const escalationWindow = new Date(Date.now() - 30 * 24 * 3600000).toISOString()
    const { data: existingEscalations } = await supabase
      .from('escalated_tasks')
      .select('id, status, completed_at, ai_summary')
      .eq('org_id', orgId)
      .gte('created_at', escalationWindow)
      .order('created_at', { ascending: false })

    // Build a map: svc_order_no → latest escalation
    const escalationMap = new Map<string, { id: string; status: string; completed_at: string | null }>()
    if (existingEscalations) {
      for (const esc of existingEscalations) {
        for (const orderNo of orderNos) {
          if (!escalationMap.has(orderNo) && esc.ai_summary?.includes(`Orden: ${orderNo}`)) {
            escalationMap.set(orderNo, { id: esc.id, status: esc.status, completed_at: esc.completed_at })
          }
        }
      }
    }

    const COOLDOWN_MS = 24 * 3600000

    for (const order of stuckOrders) {
      // Inline dedup using pre-fetched escalation map
      const latest = escalationMap.get(order.svc_order_no)
      let skip = false

      if (latest) {
        if (['new', 'verified', 'assigned', 'in_progress'].includes(latest.status)) {
          skip = true
        } else if (latest.completed_at && Date.now() - new Date(latest.completed_at).getTime() < COOLDOWN_MS) {
          skip = true
        }
      }

      if (skip) {
        result.skipped++
        result.details.push({
          svc_order_no: order.svc_order_no,
          action: 'skipped',
          reason: 'existing escalation or cooldown',
        })
        continue
      }

      // Create escalation with order info (no customer interaction needed)
      const task = await taskRepo.create({
        org_id: orgId,
        app_id: getAppId() ?? undefined,
        source_type: 'manual', // system-detected, not from a call/message
        customer_phone: order.contact_no || '',
        customer_name: order.cust_name || null,
        ai_summary: `Auto-escalado por regla: ${rule.name} | Orden: ${order.svc_order_no} | Estado ${statusCode} por más de ${maxHours}h`,
      })

      await taskRepo.addHistoryEntry(task.id, {
        action: 'auto_escalated',
        to_status: 'new',
        actor_id: 'system',
        actor_name: 'Sistema',
        notes: `Regla activada por sync: ${rule.name} (${statusCode} > ${maxHours}h)`,
      })

      // Audit log — record why this stuck-order escalation was created.
      await logEscalationReason(supabase, {
        trigger: `auto_rule:gspn_status_duration`,
        reason: `Status ${statusCode} stuck > ${maxHours}h — ${rule.name}`,
        context: {
          rule_id: rule.id,
          rule_name: rule.name,
          status_code: statusCode,
          max_hours: maxHours,
          svc_order_no: order.svc_order_no,
          escalated_task_id: task.id,
        },
      })

      result.escalationsCreated++
      result.details.push({
        svc_order_no: order.svc_order_no,
        action: 'created',
        reason: `${statusCode} stuck for > ${maxHours}h`,
      })

      console.info(`[RulesEngine:Sync] Escalation created for order ${order.svc_order_no} (rule: ${rule.name})`)
    }
  }

  if (result.escalationsCreated > 0 || result.skipped > 0) {
    console.info(`[RulesEngine:Sync] Duration check complete: ${result.escalationsCreated} created, ${result.skipped} skipped, ${result.ordersScanned} scanned`)
  }

  return result
}

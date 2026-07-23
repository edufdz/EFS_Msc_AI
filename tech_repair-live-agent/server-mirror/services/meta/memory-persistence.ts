/**
 * Shared customer-memory persistence.
 * ===================================
 * The end-of-conversation GOODBYE node and the background memory sweep both need
 * to extract insights from a transcript and persist them to `customer_memory` +
 * `interaction_history` + semantic memory. This module is the single writer they
 * share, so both paths stay in sync and the `memory_history` snapshot (which the
 * Customer-360 "Memoria IA" panel reads) is written for EVERY customer — not just
 * escalated ones.
 *
 * At-most-once (best-effort): each successful run stamps
 * `customer_memory.last_extracted_at`. The sweep only reprocesses a conversation
 * with new customer messages since that stamp, and a 60s debounce stops GOODBYE
 * and a near-simultaneous sweep tick from double-extracting the same activity.
 * Not a hard exactly-once guarantee: the stamp is per-phone (a distinct second
 * conversation for the same phone can be skipped), and the read-then-stamp is not
 * atomic, so two truly concurrent runs can still double-extract. A failed
 * extraction never stamps, so it is retried rather than silently lost.
 */

import type { SupabaseClient } from '@supabase/supabase-js'
import {
  extractInteractionInsights,
  type UnifiedInteractionInsights,
} from '@/services/analysis/unified-extraction'
import { AgentMemory } from '@/shared/memory'
import { getSemanticMemory } from '@/shared/semantic-memory'
import { withRetry } from '@/utils/retry'

/** Rolling history cap — older snapshots are dropped. Shared with recompute. */
export const MAX_MEMORY_HISTORY = 20

/** Debounce window: skip if memory was extracted for this customer this recently. */
const DEDUP_WINDOW_MS = 60_000

const SENTIMENT_LABELS: Record<number, string> = {
  1: 'muy frustrado',
  2: 'frustrado',
  3: 'neutral',
  4: 'satisfecho',
  5: 'muy satisfecho',
}

type ExtractedInsights = UnifiedInteractionInsights

export type MemorySource = 'whatsapp' | 'sweep' | 'auto-recompute'

export interface ExtractAndPersistResult {
  /** True if a snapshot was written (false when debounced or no facts). */
  wrote: boolean
  factsCount: number
  interactionId?: string
  insights?: ExtractedInsights
  /**
   * True when the LLM extraction itself failed (after retries). Distinct from the
   * debounce/no-facts cases: `insights` is absent AND the high-water mark was NOT
   * advanced, so the sweep will retry this conversation rather than skip it forever.
   */
  failed?: boolean
}

/**
 * Whether a GOODBYE caller should run its side effects (escalation rules +
 * grading) for this result. True whenever insights are present — INCLUDING the
 * "no new facts written" case (wrote=false but insights exist), where we still
 * have sentiment/resolution to act on. Only the debounce case (no insights, a
 * recent extraction already handled the activity) returns false.
 */
export function hasActionableInsights(
  result: ExtractAndPersistResult,
): result is ExtractAndPersistResult & { insights: ExtractedInsights } {
  return result.insights != null
}

/**
 * Append a full snapshot to `customer_memory.memory_history`, capped to the most
 * recent MAX_MEMORY_HISTORY entries. Optionally stamps `last_extracted_at` (the
 * best-effort high-water mark). The customer_memory row must already exist.
 */
export async function appendCustomerMemorySnapshot(
  supabase: SupabaseClient,
  phone: string,
  snapshot: Record<string, unknown>,
  opts: { stampExtractedAt?: boolean } = {},
): Promise<void> {
  const { data: row } = await supabase
    .from('customer_memory')
    .select('memory_history')
    .eq('phone', phone)
    .maybeSingle()

  const prior = Array.isArray(row?.memory_history) ? (row.memory_history as unknown[]) : []
  const history = [...prior, snapshot].slice(-MAX_MEMORY_HISTORY)

  const now = new Date().toISOString()
  const update: Record<string, unknown> = { memory_history: history, updated_at: now }
  if (opts.stampExtractedAt) update.last_extracted_at = now

  await supabase.from('customer_memory').update(update).eq('phone', phone)
}

/**
 * Advance the best-effort high-water mark (`last_extracted_at`) WITHOUT writing
 * a snapshot. Used when an extraction ran but found no facts: we DID look at the
 * conversation, so the sweep must not re-extract (and re-bill) the same messages
 * every tick — only a newer customer message reopens it. Upserts so a
 * never-before-seen customer still gets the mark; on conflict it only touches
 * last_extracted_at/updated_at, leaving any existing profile fields intact.
 * Best-effort: a stamp failure must not fail the extraction.
 */
export async function stampExtractedAt(supabase: SupabaseClient, phone: string): Promise<void> {
  const now = new Date().toISOString()
  const { error } = await supabase
    .from('customer_memory')
    .upsert({ phone, last_extracted_at: now, updated_at: now }, { onConflict: 'phone' })
  if (error) {
    console.warn('[extractAndPersistMemory] stampExtractedAt failed (non-fatal):', error.message)
  }
}

/**
 * Extract insights from a transcript and persist them: semantic facts (mem0), CRM
 * fields, frustration index, an interaction record, and a `memory_history` snapshot
 * stamped with `last_extracted_at`. Returns the insights + interaction id so callers
 * can run their own follow-up side effects (GOODBYE: escalation rules + grading).
 *
 * Side-effect parity with the previous GOODBYE IIFE for steps 1–5; the snapshot +
 * stamp are the additive piece that fills "Memoria IA" for non-escalated customers.
 */
export async function extractAndPersistMemory(
  supabase: SupabaseClient,
  args: { phone: string; conversationId?: string; transcript: string; source: MemorySource },
): Promise<ExtractAndPersistResult> {
  const { phone, conversationId, transcript, source } = args
  if (!phone || !transcript) return { wrote: false, factsCount: 0 }

  // Debounce on the high-water mark — cheapest check first.
  const { data: lastRow } = await supabase
    .from('customer_memory')
    .select('last_extracted_at')
    .eq('phone', phone)
    .maybeSingle()
  if (lastRow?.last_extracted_at) {
    const age = Date.now() - new Date(lastRow.last_extracted_at as string).getTime()
    if (age < DEDUP_WINDOW_MS) return { wrote: false, factsCount: 0 }
  }

  const retryOpts = {
    maxAttempts: 3,
    initialDelayMs: 500,
    onRetry: (err: unknown, attempt: number) => {
      console.warn(`[extractAndPersistMemory] Retry attempt ${attempt}:`, err)
    },
  }

  // Retry now lives inside extractInteractionInsights; it returns a discriminated
  // result instead of throwing or masquerading a failure as empty insights.
  const extraction = await extractInteractionInsights(transcript, { conversationId, phone })
  if (!extraction.ok) {
    // The LLM call failed (after retries). Crucially do NOT advance the high-water
    // mark: a transient failure must look different from "we looked and found
    // nothing", or the sweep would skip this settled conversation forever and
    // silently lose the customer's memory. `failed` lets GOODBYE callers skip
    // escalation/grading rather than act on fabricated neutral sentiment.
    console.error(
      '[extractAndPersistMemory] extraction failed, NOT stamping high-water mark:',
      extraction.error,
    )
    return { wrote: false, factsCount: 0, failed: true }
  }
  const insights = extraction.insights

  if (!insights.customer_facts || insights.customer_facts.length === 0) {
    // Extraction SUCCEEDED but there's nothing durable to persist. Now it is safe
    // to advance the high-water mark so the sweep doesn't re-extract (and re-bill)
    // the same messages every tick — only a newer customer message reopens it.
    await stampExtractedAt(supabase, phone)
    return { wrote: false, factsCount: 0, insights }
  }

  const memory = new AgentMemory(supabase)

  // 1. Store facts to semantic memory (mem0 embeddings).
  await withRetry(
    () => getSemanticMemory().addFacts(phone, insights.customer_facts, 'whatsapp'),
    retryOpts,
  )

  // 2. Ensure the customer_memory row exists before the snapshot UPDATE.
  await memory.getCustomerProfile(phone)

  // 3. Update CRM fields (only non-null values).
  await withRetry(
    () =>
      memory.updateCustomerProfile(phone, {
        preferredName: insights.preferred_name,
        primaryDeviceModel: insights.primary_device_model,
        warrantyStatus: insights.warranty_status,
        escalationRisk: insights.escalation_risk,
        preferredContactChannel: insights.preferred_contact_channel,
      }),
    retryOpts,
  )

  // 4. Update frustration index via RPC.
  await withRetry(
    () =>
      Promise.resolve(
        supabase.rpc('update_frustration_index', {
          p_phone: phone,
          p_sentiment_score: insights.sentiment_score,
          p_last_sentiment: SENTIMENT_LABELS[insights.sentiment_score] ?? 'neutral',
        }),
      ).then(({ error }) => {
        if (error) throw error
      }),
    retryOpts,
  ).catch((err: unknown) => {
    console.warn('[extractAndPersistMemory] Failed to update frustration index after retries:', err)
  })

  // 5. Record interaction in interaction_history + bump count.
  const interactionMetadata: Record<string, unknown> = {}
  if (insights.issue_category) interactionMetadata.issue_category = insights.issue_category
  if (insights.urgency_level) interactionMetadata.urgency_level = insights.urgency_level
  if (insights.customer_claims_repeat_contact)
    interactionMetadata.customer_claims_repeat_contact = true

  const interactionId = await withRetry(
    () =>
      memory.recordInteraction({
        phone,
        channel: 'whatsapp',
        topic: insights.summary ?? 'Conversación',
        summary: insights.summary ?? '',
        outcome: insights.resolution_status ?? 'unknown',
        agentType: 'ai',
        sentimentScore: insights.sentiment_score,
        metadata: Object.keys(interactionMetadata).length > 0 ? interactionMetadata : undefined,
      }),
    { ...retryOpts, initialDelayMs: 300 },
  )

  // 6. Append the rolling memory_history snapshot + stamp the high-water mark.
  //    THIS is the piece the previous GOODBYE flow was missing: it fills the
  //    Customer-360 "Memoria IA" panel for every customer, not just escalated ones.
  await appendCustomerMemorySnapshot(
    supabase,
    phone,
    {
      at: new Date().toISOString(),
      source,
      sentiment_score: insights.sentiment_score,
      sentiment_label: SENTIMENT_LABELS[insights.sentiment_score] ?? 'neutral',
      resolution_status: insights.resolution_status,
      summary: insights.summary,
      facts: insights.customer_facts,
      preferred_name: insights.preferred_name ?? null,
      primary_device_model: insights.primary_device_model ?? null,
      warranty_status: insights.warranty_status ?? null,
      escalation_risk: insights.escalation_risk,
      // Issue signals — feed TabMemory's "Falla reportada" fallback. Parity with
      // the recompute snapshot so end-of-conversation extraction carries them too.
      issue_category: insights.issue_category ?? null,
      reported_symptom: insights.reported_symptom ?? null,
      // Durable person traits (Task 7) — surfaced in the prompt via resolveMemory.
      communication_style: insights.communication_style ?? null,
      personal_context: insights.personal_context ?? null,
    },
    { stampExtractedAt: true },
  )

  return {
    wrote: true,
    factsCount: insights.customer_facts.length,
    interactionId: interactionId ?? undefined,
    insights,
  }
}

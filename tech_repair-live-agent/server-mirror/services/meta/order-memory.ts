/**
 * Order Memory — remember folios the customer typed.
 * ===================================================
 * Carry-in orders carry a phone only ~7.5% of the time, so the phone lookup in
 * the context assembler can't find them and the agent asks for the folio. When
 * the customer types it and we confirm it exists, we remember it here so a later
 * message — even a new conversation — already knows the order.
 *
 * Storage reuses what already exists (no migration):
 *   - whatsapp_conversations.active_service_order_id  → within the conversation
 *   - customer_memory.metadata.known_service_orders   → across conversations
 *     (metadata is a free-form jsonb the sweep's dossier rebuild never touches)
 *
 * This is a FALLBACK to the phone lookup, not a replacement: the phone path
 * still runs first; remembered folios only fill the carry-in-without-phone gap.
 */

import type { SupabaseClient } from '@supabase/supabase-js'
import { AgentMemory } from '@/shared/memory'

/** Cap the remembered list so it can't grow unbounded. */
const MAX_KNOWN_ORDERS = 10

/** Read the folios a customer has previously given us (keyed by their phone). */
export async function getKnownServiceOrders(
  supabase: SupabaseClient,
  phone: string,
): Promise<string[]> {
  if (!phone) return []
  const { data } = await supabase
    .from('customer_memory')
    .select('metadata')
    .eq('phone', phone)
    .maybeSingle()
  const known = (data?.metadata as { known_service_orders?: unknown } | null)?.known_service_orders
  return Array.isArray(known) ? known.filter((f): f is string => typeof f === 'string' && !!f) : []
}

/**
 * Remember a confirmed folio for this customer: link it to the current
 * conversation and append it to customer_memory.metadata.known_service_orders.
 * Fire-and-forget — callers should not await failures into the response path.
 */
export async function rememberServiceOrder(
  supabase: SupabaseClient,
  args: { phone?: string; conversationId?: string; svcOrderNo: string },
): Promise<void> {
  const { phone, conversationId, svcOrderNo } = args
  if (!svcOrderNo) return

  // Resolve the SO row id so we can pin it as the conversation's active order.
  const { data: order } = await supabase
    .from('service_orders')
    .select('id')
    .eq('svc_order_no', svcOrderNo)
    .maybeSingle()

  if (conversationId && order?.id) {
    await supabase
      .from('whatsapp_conversations')
      .update({ active_service_order_id: order.id })
      .eq('id', conversationId)
  }

  if (!phone) return

  // Append to the per-customer remembered list (read-modify-write, preserving
  // any other metadata keys). Ensure the row exists first.
  await new AgentMemory(supabase).getCustomerProfile(phone)
  const { data: row } = await supabase
    .from('customer_memory')
    .select('metadata')
    .eq('phone', phone)
    .maybeSingle()

  const metadata = (row?.metadata as Record<string, unknown> | null) ?? {}
  const prior = Array.isArray(metadata.known_service_orders)
    ? (metadata.known_service_orders as unknown[]).filter(
        (f): f is string => typeof f === 'string' && !!f,
      )
    : []
  if (prior.includes(svcOrderNo)) return // already remembered

  const known = [...prior, svcOrderNo].slice(-MAX_KNOWN_ORDERS)
  await supabase
    .from('customer_memory')
    .update({ metadata: { ...metadata, known_service_orders: known }, updated_at: new Date().toISOString() })
    .eq('phone', phone)
}

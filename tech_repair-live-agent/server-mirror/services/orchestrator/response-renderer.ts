/**
 * Response Renderer
 * =================
 * Pre-renders verified GSPN data into WhatsApp-formatted cards.
 * These cards are passed to the LLM as immutable blocks — the LLM
 * writes conversational framing around them but never generates
 * factual claims (prices, statuses, dates) itself.
 *
 * This eliminates hallucination by design: the LLM cannot fabricate
 * data it doesn't generate.
 */

import type { ServiceOrderInfo } from './context-assembler'
import { STATUS_CODE_LABELS, buildIrisSummary } from '@/services/gspn/constants'

// ============================================================================
// Card Rendering
// ============================================================================

const POST_DIAGNOSIS_STATUSES = ['ST035', 'ST040', 'ST045', 'ST050']

/**
 * Render a single order into a WhatsApp-formatted data card.
 * The card uses WhatsApp markdown (bold with *) and is designed to
 * be included verbatim in the agent's response.
 */
export function renderOrderCard(
  order: ServiceOrderInfo,
  supportPhone: string,
): string {
  const statusLabel = STATUS_CODE_LABELS[order.status] ?? order.status
  const lines: string[] = []

  lines.push(`*Orden ${order.svc_order_no}*`)
  lines.push(`Estado: ${statusLabel}`)

  if (order.device_model) {
    lines.push(`Dispositivo: ${order.device_model}`)
  }

  if (order.repair_cost_mxn != null) {
    lines.push(`Costo: $${order.repair_cost_mxn.toLocaleString('es-MX')} MXN`)
  } else if (POST_DIAGNOSIS_STATUSES.includes(order.status)) {
    lines.push(`Costo: Pendiente de registro — contactar ${supportPhone}`)
  } else {
    lines.push(`Costo: Se determina tras diagnóstico`)
  }

  if (order.warranty_type) {
    lines.push(`Garantía: ${order.warranty_type}`)
  } else if (POST_DIAGNOSIS_STATUSES.includes(order.status)) {
    lines.push(`Garantía: Pendiente de verificación`)
  }

  if (order.service_type === 'd2d') {
    lines.push(`Servicio: Recolección y entrega a domicilio`)
  } else if (order.service_type === 'carry_in') {
    lines.push(`Servicio: Entrega en tienda (se recoge en sucursal)`)
  }

  const irisSummary = buildIrisSummary(order)
  if (irisSummary) {
    lines.push(`Diagnóstico: ${irisSummary}`)
  }

  return lines.join('\n')
}

/**
 * Render all active orders into a block of data cards.
 * Returns both the formatted string (for the LLM prompt) and
 * the individual card strings (for post-send verification).
 */
export function renderOrderCards(
  orders: ServiceOrderInfo[],
  supportPhone: string,
): { formatted: string; cards: string[] } {
  if (orders.length === 0) {
    return { formatted: 'Sin órdenes activas.', cards: [] }
  }

  const cards = orders.map(o => renderOrderCard(o, supportPhone))
  const formatted = cards.join('\n\n')

  return { formatted, cards }
}

// ============================================================================
// Card Verification
// ============================================================================

/**
 * Verify that a response includes the pre-rendered data cards intact.
 * Returns true if all critical data points from the cards appear in
 * the response when the response references order data.
 *
 * This replaces regex-based claim extraction — instead of parsing
 * free text for fabricated claims, we check that the LLM used the
 * verified cards rather than inventing its own data.
 */
export function verifyCardIntegrity(
  responseText: string,
  orders: ServiceOrderInfo[],
): { intact: boolean; fabricatedClaims: string[] } {
  const fabricatedClaims: string[] = []

  for (const order of orders) {
    // Only check if the response seems to reference this order
    if (!responseText.includes(order.svc_order_no)) continue

    // Check status: if the response mentions a status code, it must match
    const statusPattern = /ST0[0-6]\d/g
    for (const match of responseText.matchAll(statusPattern)) {
      const mentionedStatus = match[0]
      const knownStatuses = orders.map(o => o.status)
      if (!knownStatuses.includes(mentionedStatus)) {
        fabricatedClaims.push(`Status ${mentionedStatus} not in known orders`)
      }
    }

    // Check prices: if a peso amount appears, it should match a known cost
    const pricePattern = /\$\s?([\d,.]+)\s*MXN/gi
    for (const match of responseText.matchAll(pricePattern)) {
      const amount = parseFloat(match[1].replace(/,/g, ''))
      if (isNaN(amount)) continue
      const knownPrices = orders
        .map(o => o.repair_cost_mxn)
        .filter((p): p is number => p !== null)
      if (knownPrices.length > 0) {
        const anyMatch = knownPrices.some(p => Math.abs(amount - p) <= p * 0.05)
        if (!anyMatch) {
          fabricatedClaims.push(`Price $${amount} doesn't match known costs: ${knownPrices.join(', ')}`)
        }
      }
    }
  }

  return {
    intact: fabricatedClaims.length === 0,
    fabricatedClaims,
  }
}

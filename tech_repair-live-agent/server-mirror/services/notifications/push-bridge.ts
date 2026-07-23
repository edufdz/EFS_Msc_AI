/**
 * Push Notification Bridge
 * ========================
 * Bridges TechRepair Connect (Supabase) to Pulpoo API (Prisma) for push notifications.
 * Connect doesn't have access to Prisma/push tokens, so it calls the internal API endpoint.
 *
 * Also dual-writes to dashboard_notifications table for in-app notification center.
 *
 * Fire-and-forget: failures are logged but never block operations.
 */

import type { SupabaseClient } from '@supabase/supabase-js'

// Read env at call time — ES module imports are hoisted before dotenvConfig() runs
function getPulpooApiUrl(): string {
    return process.env.PULPOO_API_URL || 'http://localhost:3000'
}

function getApiSecret(): string {
    return process.env.API_SECRET || process.env.TECH_REPAIR_PULPOO_API_KEY || ''
}

interface PushRequest {
  target_role?: string
  target_user_id?: string
  org_id: string
  title: string
  body: string
}

interface DashboardNotification {
  org_id: string
  target_user_id?: string | null
  target_role?: string | null
  type: string // 'escalation_assigned' | 'status_changed' | 'sla_warning' | 'task_update' | 'system'
  title: string
  message: string
  href?: string | null
}

/**
 * Insert a notification into dashboard_notifications table.
 * Fire-and-forget — never throws.
 */
export async function insertDashboardNotification(
  supabase: SupabaseClient,
  notification: DashboardNotification
): Promise<void> {
  try {
    const { error } = await supabase
      .from('dashboard_notifications')
      .insert({
        org_id: notification.org_id,
        target_user_id: notification.target_user_id ?? null,
        target_role: notification.target_role ?? null,
        type: notification.type,
        title: notification.title,
        message: notification.message,
        href: notification.href ?? null,
        read: false,
      })

    if (error) {
      console.error(`[Notification] Insert failed: ${error.message}`)
    }
  } catch (error) {
    console.error('[Notification] Insert error:', error)
  }
}

/**
 * Send escalation push notification via Pulpoo API internal endpoint.
 * Returns true if sent successfully, false otherwise.
 */
export async function sendEscalationPush(req: PushRequest): Promise<boolean> {
  const apiSecret = getApiSecret()
  if (!apiSecret) {
    console.warn('[Push Bridge] API_SECRET not configured, skipping push')
    return false
  }

  const apiUrl = getPulpooApiUrl()
  // Security: reject non-HTTPS remote URLs in production
  if (
      process.env.NODE_ENV === 'production' &&
      apiUrl.startsWith('http://') &&
      !apiUrl.includes('localhost') &&
      !apiUrl.includes('127.0.0.1')
  ) {
    console.error('[Push Bridge] HTTPS required for remote PULPOO_API_URL in production')
    return false
  }

  try {
    const res = await fetch(`${apiUrl}/v1/internal/push`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-API-Secret': apiSecret,
      },
      body: JSON.stringify(req),
    })

    if (!res.ok) {
      const text = await res.text()
      console.error(`[Push Bridge] Failed (${res.status}): ${text}`)
      return false
    }

    const data = await res.json()
    console.info(`[Push Bridge] Sent ${data.sent ?? 0} push notifications`)
    return true
  } catch (error) {
    console.error('[Push Bridge] Network error:', error)
    return false
  }
}

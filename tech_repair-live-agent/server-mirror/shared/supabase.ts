/**
 * Supabase Types & Contracts
 * ==========================
 * Type definitions for Supabase client dependency injection.
 *
 * CONNECT ARCHITECTURE:
 * - Core defines WHAT it needs (types/interfaces)
 * - App provides HOW (actual client instances)
 * - Core NEVER creates database connections
 */

import type { SupabaseClient } from '@supabase/supabase-js'

// =============================================================================
// RE-EXPORT TYPE FOR CONVENIENCE
// =============================================================================

export type { SupabaseClient }

// =============================================================================
// CONTEXT HOLDER (Injected by App at runtime)
// =============================================================================

/**
 * Runtime holder for the injected Supabase client.
 * Set by the App during initialization, used by Core services.
 */
let _injectedClient: SupabaseClient | null = null

/**
 * Set the Supabase client (called by App during bootstrap)
 */
export function setSupabaseClient(client: SupabaseClient): void {
  _injectedClient = client
}

/**
 * Get the injected Supabase client.
 * Returns null if not yet injected.
 */
export function getSupabaseClient(): SupabaseClient | null {
  return _injectedClient
}

/**
 * Get the injected Supabase client or throw.
 * Use in contexts where Supabase is required.
 */
export function requireSupabaseClient(): SupabaseClient {
  if (!_injectedClient) {
    throw new Error(
      'Supabase client not injected. App must call setSupabaseClient() during bootstrap.'
    )
  }
  return _injectedClient
}

/**
 * Reset the client (for testing)
 */
export function _resetClient(): void {
  _injectedClient = null
}

// =============================================================================
// APP ID HOLDER (Injected by App at runtime)
// =============================================================================

let _appId: string | null = null

export function setAppId(appId: string): void {
  _appId = appId
}

export function getAppId(): string | null {
  return _appId
}

export function requireAppId(): string {
  if (!_appId) {
    throw new Error(
      'App ID not injected. App must call setAppId() during bootstrap.'
    )
  }
  return _appId
}

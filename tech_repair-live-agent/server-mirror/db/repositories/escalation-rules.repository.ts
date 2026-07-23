/**
 * Escalation Rules Repository
 * ============================
 * CRUD for auto-escalation rules.
 */

import type { SupabaseClient } from '@supabase/supabase-js'

// ============================================================================
// Types
// ============================================================================

// [sim] type-only: 'repeat_issue_same_order' is evaluated by escalation-rules-engine but was missing from the upstream union
export type TriggerType = 'call_frequency' | 'sentiment_threshold' | 'gspn_status_duration' | 'repeat_issue_same_order'

export interface EscalationRule {
  id: string
  org_id: string
  name: string
  trigger_type: TriggerType
  trigger_config: Record<string, unknown>
  is_active: boolean
  created_by: string | null
  created_at: string
  updated_at: string
}

export interface CreateRuleDTO {
  org_id: string
  name: string
  trigger_type: TriggerType
  trigger_config: Record<string, unknown>
  created_by?: string
}

export interface UpdateRuleDTO {
  name?: string
  trigger_type?: TriggerType
  trigger_config?: Record<string, unknown>
  is_active?: boolean
}

// ============================================================================
// Repository
// ============================================================================

export class EscalationRulesRepository {
  constructor(private supabase: SupabaseClient) {}

  async findById(id: string): Promise<EscalationRule | null> {
    const { data, error } = await this.supabase
      .from('escalation_rules')
      .select('*')
      .eq('id', id)
      .single()

    if (error) return null
    return data as EscalationRule
  }

  async findAll(orgId: string): Promise<EscalationRule[]> {
    const { data, error } = await this.supabase
      .from('escalation_rules')
      .select('*')
      .eq('org_id', orgId)
      .order('created_at', { ascending: false })

    if (error) throw error
    return (data ?? []) as EscalationRule[]
  }

  async findActive(orgId: string): Promise<EscalationRule[]> {
    const { data, error } = await this.supabase
      .from('escalation_rules')
      .select('*')
      .eq('org_id', orgId)
      .eq('is_active', true)

    if (error) throw error
    return (data ?? []) as EscalationRule[]
  }

  async create(dto: CreateRuleDTO): Promise<EscalationRule> {
    const { data, error } = await this.supabase
      .from('escalation_rules')
      .insert({
        org_id: dto.org_id,
        name: dto.name,
        trigger_type: dto.trigger_type,
        trigger_config: dto.trigger_config,
        created_by: dto.created_by,
      })
      .select()
      .single()

    if (error) throw error
    return data as EscalationRule
  }

  async update(id: string, dto: UpdateRuleDTO): Promise<EscalationRule> {
    const updateData: Record<string, unknown> = { updated_at: new Date().toISOString() }
    if (dto.name !== undefined) updateData.name = dto.name
    if (dto.trigger_type !== undefined) updateData.trigger_type = dto.trigger_type
    if (dto.trigger_config !== undefined) updateData.trigger_config = dto.trigger_config
    if (dto.is_active !== undefined) updateData.is_active = dto.is_active

    const { data, error } = await this.supabase
      .from('escalation_rules')
      .update(updateData)
      .eq('id', id)
      .select()
      .single()

    if (error) throw error
    return data as EscalationRule
  }

  async delete(id: string): Promise<void> {
    const { error } = await this.supabase
      .from('escalation_rules')
      .delete()
      .eq('id', id)

    if (error) throw error
  }
}

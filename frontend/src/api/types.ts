// انواع مشترک قرارداد API — هم‌راستا با OpenAPI بک‌اند
export interface Person {
  id: string
  given_name: string
  family_name: string
  display_name: string
  status: string
  version: number
  merged_into_id: string | null
  created_at: string
  updated_at: string
}

export interface PersonDetail extends Person {
  identifiers: Identifier[]
  contacts: Contact[]
  account_links: AccountLink[]
  mappings: Mapping[]
}

export interface Identifier {
  id: string
  type: string
  issuer: string
  value_masked: string
  verification_status: string
  status: string
  created_at: string
}

export interface Contact {
  id: string
  type: string
  value: string
  verified_at: string | null
  status: string
}

export interface AccountLink {
  id: string
  issuer: string
  subject: string
  account_label: string | null
  status: string
  linked_at: string | null
}

export interface Mapping {
  id: string
  installation_id: string
  installation_code: string | null
  entity_type: string
  local_id: string
  entity_id: string
  status: string
  note?: string | null
}

export interface Organization {
  id: string
  parent_id: string | null
  type: string
  code: string
  name: string
  sort_order: number
  status: string
  version: number
}

export interface RefSet {
  id: string
  code: string
  title: string
  description: string | null
  version: number
  status: string
}

export interface RefItem {
  id: string
  set_id: string
  parent_id: string | null
  code: string
  title: string
  sort_order: number
  status: string
  valid_from: string | null
  valid_to: string | null
}

export interface OwnershipPolicy {
  id: string
  entity_type: string
  field_group: string
  owner_type: string
  owner_code: string
  version: number
  status: string
  updated_by: string | null
  updated_at: string
}

export interface ChangeRequest {
  id: string
  entity_type: string
  entity_id: string
  proposed_changes: Record<string, string>
  reason: string
  requested_by: string
  requested_by_name: string | null
  status: string
  decided_by: string | null
  decided_at: string | null
  decision_note: string | null
  applied_version: number | null
  created_at: string
}

export interface ResolutionCase {
  id: string
  candidate_ids: string[]
  evidence: {
    persons?: Array<{
      person_id: string
      display_name: string
      status: string
      version: number
      identifiers?: Array<{ type: string; issuer: string; value_masked: string; verification_status: string }>
    }>
    note?: string
    method?: string
  }
  status: string
  created_by: string | null
  decided_by: string | null
  decided_at: string | null
  decision: Record<string, unknown> | null
  merge_record_id: string | null
  created_at: string
}

export interface MergeRecord {
  id: string
  source_person_id: string
  target_person_id: string
  decided_by: string
  decision_note: string | null
  status: string
  alias_snapshot: Record<string, unknown> | null
  reversed_by: string | null
  reversed_at: string | null
  created_at: string
}

export interface Installation {
  id: string
  system_code: string
  installation_code: string
  title: string
  mode: string
  status: string
  base_url: string | null
  owner_scopes: string | null
  last_seen_at: string | null
}

export interface IntegrationsStatus {
  max_seq: number
  rabbitmq: { connected: boolean; detail: string }
  outbox: { pending: number; failed: number; oldest_pending_age_seconds: number | null }
  installations: Array<{
    installation_code: string
    title: string
    mode: string
    status: string
    last_seen_at: string | null
    checkpoint_cursor: number | null
    checkpoint_acknowledged_at: string | null
    lag: number | null
  }>
  recent_snapshots: Array<{ id: string; status: string; boundary_seq: number | null; created_at: string }>
}

export interface Stats {
  persons_total: number
  persons_active: number
  persons_inactive: number
  persons_merged: number
  open_change_requests: number
  open_quality_cases: number
}

export interface AuditLog {
  id: string
  actor_id: string
  actor_name: string | null
  operation: string
  entity_type: string
  entity_id: string | null
  before: string | null
  after: string | null
  ip: string | null
  correlation_id: string | null
  created_at: string
}

export interface HistoryEntry {
  seq: number
  operation: string
  version: number
  changed_fields: string[] | null
  data: Record<string, unknown>
  actor_id: string | null
  occurred_at: string
}

export interface Meta {
  app: string
  version: string
  env: string
  auth_mode: 'dev' | 'oidc'
  dev_mode: boolean
  oidc: {
    issuer: string
    client_id: string | null
    authorization_endpoint: string | null
    end_session_endpoint: string | null
    available: boolean
    error?: string
  }
}

export interface Me {
  kind: string
  subject?: string
  name?: string
  roles?: string[]
  tenant_codes?: string[]
  person?: { id: string; display_name: string; status: string; version: number } | null
  linked?: boolean
}

// Shapes returned by the Django API (kept in sync with the DRF serializers).

export type Role = "ADMIN" | "PLANNER" | "TECHNICIAN" | "VIEWER";
export type DueStatus = "OK" | "DUE_SOON" | "OVERDUE";
export type Airworthiness = "AIRWORTHY" | "ATTENTION" | "GROUNDED";
export type WOStatus = "OPEN" | "IN_PROGRESS" | "AWAITING_INSPECTION" | "CLOSED" | "CANCELLED";

export interface Paginated<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

export interface User {
  id: number;
  username: string;
  first_name: string;
  last_name: string;
  email: string;
  role: Role;
}

export interface Aircraft {
  id: number;
  tail_number: string;
  model: string;
  serial_number: string;
  status: "ACTIVE" | "STORED" | "RETIRED";
  in_service_date: string;
  total_hours: string;
  total_cycles: number;
}

export interface AirworthinessStatus {
  aircraft_id: number;
  tail_number: string;
  status: Airworthiness;
  reasons: string[];
  overdue: number;
  due_soon: number;
}

export interface Measure {
  unit: "hours" | "cycles" | "days";
  interval: string;
  used: string;
  remaining: string;
  status: DueStatus;
  projected_date: string | null;
}

export interface DueItem {
  key: string;
  kind: "RULE" | "LIFE_LIMIT";
  title: string;
  status: DueStatus;
  aircraft_id: number | null;
  tail_number: string | null;
  component_id: number | null;
  component_label: string | null;
  rule_id: number | null;
  last_done: string | null;
  projected_due_date: string | null;
  measures: Measure[];
}

export interface Installation {
  id: number;
  component: number;
  component_label: string;
  aircraft: number;
  aircraft_tail: string;
  position: string;
  installed_at: string;
  removed_at: string | null;
  removal_reason: string;
}

export interface Component {
  id: number;
  part_number: string;
  part_name: string;
  serial_number: string;
  status: string;
  hours_since_new: string;
  cycles_since_new: number;
  installed_on: { aircraft: number; tail_number: string; position: string } | null;
  life_remaining: { hours: string | null; cycles: number | null; days: number | null; expired: boolean };
}

export interface Flight {
  id: number;
  aircraft: number;
  aircraft_tail: string;
  takeoff_at: string;
  landing_at: string;
  cycles: number;
  duration_hours: string;
  mission: string;
  max_engine_temp_c: string | null;
  avg_vibration_g: string | null;
  fuel_used_l: string | null;
  logged_by: string | null;
}

export interface ChecklistItem {
  id: number;
  position: number;
  text: string;
  done: boolean;
  done_by: string | null;
  done_at: string | null;
  note: string;
}

export interface WorkOrder {
  id: number;
  number: string;
  title: string;
  description: string;
  aircraft: number;
  tail_number: string;
  component: number | null;
  rule: number | null;
  grounding: boolean;
  priority: "LOW" | "NORMAL" | "HIGH" | "AOG";
  status: WOStatus;
  due_date: string | null;
  assigned_to: number | null;
  assigned_to_name: string | null;
  created_by: string;
  created_at: string;
  tech_signed_by: string | null;
  tech_signed_at: string | null;
  tech_signature: string;
  inspector_signed_by: string | null;
  inspector_signed_at: string | null;
  inspector_signature: string;
  closed_at: string | null;
  cancel_reason: string;
  checklist: ChecklistItem[];
  progress: { done: number; total: number };
}

export interface AuditEntry {
  id: number;
  timestamp: string;
  actor: string | null;
  action: string;
  summary: string;
}

export interface SparePart {
  id: number;
  part_number: string;
  name: string;
  unit: string;
  location: string;
  quantity_on_hand: string;
  min_quantity: string;
  is_low: boolean;
}

export interface Alert {
  id: number;
  kind: "DUE_SOON" | "OVERDUE" | "LOW_STOCK" | "ANOMALY";
  severity: "INFO" | "WARNING" | "CRITICAL";
  title: string;
  message: string;
  aircraft: number | null;
  tail_number: string | null;
  created_at: string;
  resolved_at: string | null;
  acknowledged_at: string | null;
  acknowledged_by: string | null;
}

export interface Dashboard {
  generated_at: string;
  readiness: {
    active_aircraft: number;
    ready: number;
    readiness_pct: number | null;
    by_status: Record<Airworthiness, number>;
  };
  aircraft: AirworthinessStatus[];
  due_counts: Record<DueStatus, number>;
  timeline: {
    date: string;
    key: string;
    title: string;
    status: DueStatus;
    aircraft_id: number;
    tail_number: string;
    kind: string;
  }[];
  work_orders: Partial<Record<WOStatus, number>>;
  open_alerts: Partial<Record<Alert["severity"], number>>;
  low_stock: number;
  flight_hours_30d: { day: string; hours: string; flights: number }[];
}

export interface Citation {
  n: number;
  document_id: number;
  title: string;
  page: number;
  snippet: string;
}

export interface RagAnswer {
  answer: string;
  citations: Citation[];
  provider: string;
  model: string;
  degraded: boolean;
}

export interface QueryResult {
  question: string;
  spec: { entity: string; filters: Record<string, unknown>; limit: number; explanation: string };
  count: number;
  rows: Record<string, unknown>[];
  provider: string;
  degraded: boolean;
}

export interface Anomaly {
  key: string;
  aircraft_id: number;
  tail_number: string;
  metric: string;
  label: string;
  unit: string;
  baseline_median: number;
  recent_values: number[];
  recent_z: number[];
  flagged_flights: number;
  direction: "high" | "low";
}

export interface ManualDocument {
  id: number;
  title: string;
  aircraft_model: string;
  status: "PENDING" | "PROCESSING" | "READY" | "FAILED";
  page_count: number;
  chunk_count: number;
  error: string;
  uploaded_by: string;
  uploaded_at: string;
}

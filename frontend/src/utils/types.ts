// Shared TypeScript types derived from the JSON data files.

export interface RouteUtilisation {
  capacity: number
  assigned_students: number
  seats_available: number
  utilisation_pct: number
}

export interface Route {
  id: string
  name: string
  bus_id: string
  bus_license_plate: string
  bus_is_accessible: boolean
  bus_capacity_initial: number
  driver_id: string
  direction: string
  status: string
  pickup_window_start: string
  pickup_window_end: string
  is_feasible: boolean
  total_travel_minutes: number
  served_zone_ids: string[]
  effective_from: string | null
  utilisation: RouteUtilisation
}

export interface RouteStop {
  id: string
  route_id: string
  stop_id: string
  sequence: number
  travel_minutes_from_prev: number | null
  scheduled_time: string
}

export interface Assignment {
  id: string
  student_id: string
  route_id: string
  stop_id: string
  status: string
  effective_from: string | null
  effective_to: string | null
  academic_year: number | null
}

export interface Rejection {
  student_id: string
  attempted_route_id: string
  error_codes: string[]
  reason: string
}

export interface AttendanceSummary {
  date: string
  weekday: string
  total_events: number
  boarded: number
  absent: number
  no_show: number
  late_pickup: number
  attendance_rate: number
  disruptions_delay: number
  disruptions_cancelled: number
  has_disruption: boolean
}

export interface Disruption {
  disruption_id: string
  route_id: string
  date: string
  type: "DELAY" | "CANCELLED"
  reason: string
}

export interface NotifItem {
  id: string
  guardian_id: string
  guardian_masked_phone: string
  guardian_masked_email: string
  guardian_prefs: string[]
  student_id: string
  event_id: string
  event_collection: string
  channel: string
  status: string
  sent_at: string | null
  delivered_at: string | null
  failed_at: string | null
  failure_reason: string | null
  template_id: string | null
}

export interface SkippedItem {
  student_id: string
  event_id: string
  event_type: string
  date: string | null
  reason: string
}

export interface NotificationsData {
  sent: NotifItem[]
  skipped: SkippedItem[]
}

export interface CapacityHistoryItem {
  id: string
  bus_id: string
  capacity: number
  is_accessible: boolean
  reason: string
  effective_from: string | null
  effective_to: string | null
  changed_by: string
}

export interface StudentAssignment {
  assignment_id: string
  route_id: string
  stop_id: string
  status: string
}

export interface AttendanceEvent {
  event_id: string
  date: string
  event_type: string
  route_id: string
  stop_id: string
  notes: string | null
}

export interface NotifByStudent {
  notification_id: string
  event_id: string
  channel: string
  status: string
  sent_at: string | null
}

export interface Metrics {
  generated_at: string
  scale: string
  seed: number
  school_days: number
  students_total: number
  students_assigned: number
  students_rejected: number
  students_inactive_assignment: number
  routes_active: number
  buses_total: number
  stops_total: number
  attendance: {
    total_events: number
    boarded: number
    absent: number
    no_show: number
    late_pickup: number
    overall_rate: number
  }
  disruptions: {
    total: number
    cancelled: number
    delay: number
  }
  notifications: {
    sent: number
    delivered: number
    failed: number
    skipped: number
  }
}

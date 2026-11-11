export function pct(n: number): string {
  return (n * 100).toFixed(1) + "%"
}

export function fmt(n: number): string {
  return n.toLocaleString()
}

export function eventBadge(et: string): string {
  switch (et) {
    case "boarded":     return "badge badge-green"
    case "absent":      return "badge badge-red"
    case "no_show":     return "badge badge-yellow"
    case "late_pickup": return "badge badge-orange"
    default:            return "badge badge-gray"
  }
}

// Canonical label mapping documented in attendance_generator.py
export const EVENT_LABEL: Record<string, string> = {
  boarded:     "Present (boarded)",
  absent:      "Absent",
  no_show:     "Missed pickup (no_show)",
  late_pickup: "Capacity-reduced (late_pickup)",
  alighted:    "Alighted",
  emergency_exit: "Emergency exit",
}

export function statusBadge(s: string): string {
  switch (s) {
    case "active":    return "badge badge-green"
    case "delivered": return "badge badge-green"
    case "sent":      return "badge badge-blue"
    case "pending":   return "badge badge-blue"
    case "failed":    return "badge badge-red"
    case "cancelled": return "badge badge-gray"
    case "inactive":  return "badge badge-gray"
    default:          return "badge badge-gray"
  }
}

export function dotClass(et: string): string {
  if (et === "boarded")     return "tl-dot dot-boarded"
  if (et === "absent")      return "tl-dot dot-absent"
  if (et === "no_show")     return "tl-dot dot-no_show"
  if (et === "late_pickup") return "tl-dot dot-late_pickup"
  return "tl-dot dot-default"
}

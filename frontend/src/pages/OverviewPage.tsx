import { useJsonData } from "../hooks/useJsonData"
import LoadingWrapper from "../components/LoadingWrapper"
import { pct, fmt } from "../utils/format"
import type { Metrics } from "../utils/types"

function KpiCard({
  label, value, sub, tone,
}: {
  label: string
  value: string
  sub?: string
  tone?: "good" | "warn" | "danger"
}) {
  return (
    <div
      className={["kpi-card", tone ?? ""].join(" ").trim()}
      role="region"
      aria-label={`${label}: ${value}`}
    >
      <div className="kpi-label" aria-hidden="true">{label}</div>
      <div className="kpi-value" aria-hidden="true">{value}</div>
      {sub && <div className="kpi-sub" aria-hidden="true">{sub}</div>}
    </div>
  )
}

export default function OverviewPage() {
  const { data: m, status, error } = useJsonData<Metrics>("/data/metrics.json")

  return (
    <div>
      <h1>Overview</h1>
      <LoadingWrapper status={status} error={error}>
        {m && (
          <>
            <h2>Students</h2>
            <div className="kpi-grid">
              <KpiCard label="Total students"         value={fmt(m.students_total)} />
              <KpiCard label="Assigned"               value={fmt(m.students_assigned)} tone="good"
                sub={pct(m.students_assigned / m.students_total) + " of total"} />
              <KpiCard label="Rejected / waitlisted"  value={fmt(m.students_rejected)}
                tone={m.students_rejected > 0 ? "warn" : undefined} />
              <KpiCard label="Active routes"          value={fmt(m.routes_active)} />
              <KpiCard label="Buses"                  value={fmt(m.buses_total)} />
              <KpiCard label="Stops"                  value={fmt(m.stops_total)} />
            </div>

            <h2>Attendance ({m.school_days} school days)</h2>
            <div className="kpi-grid">
              <KpiCard label="Attendance rate"        value={pct(m.attendance.overall_rate)} tone="good" />
              <KpiCard label="Boarded (present)"      value={fmt(m.attendance.boarded)} />
              <KpiCard label="Absent"                 value={fmt(m.attendance.absent)} />
              <KpiCard label="Missed pickup"          value={fmt(m.attendance.no_show)}
                tone={m.attendance.no_show > 0 ? "warn" : undefined}
                sub="no_show events" />
              <KpiCard label="Capacity-reduced"       value={fmt(m.attendance.late_pickup)}
                tone={m.attendance.late_pickup > 0 ? "warn" : undefined}
                sub="late_pickup events" />
            </div>

            <h2>Disruptions</h2>
            <div className="kpi-grid">
              <KpiCard label="Total disruptions"      value={fmt(m.disruptions.total)}
                tone={m.disruptions.total > 0 ? "warn" : undefined} />
              <KpiCard label="Delays"                 value={fmt(m.disruptions.delay)} />
              <KpiCard label="Cancellations"          value={fmt(m.disruptions.cancelled)}
                tone={m.disruptions.cancelled > 0 ? "danger" : undefined} />
            </div>

            <h2>Notifications</h2>
            <div className="kpi-grid">
              <KpiCard label="Sent"                   value={fmt(m.notifications.sent)} />
              <KpiCard label="Delivered"              value={fmt(m.notifications.delivered)} tone="good"
                sub={m.notifications.sent > 0
                  ? pct(m.notifications.delivered / m.notifications.sent) + " of sent"
                  : ""} />
              <KpiCard label="Failed"                 value={fmt(m.notifications.failed)}
                tone={m.notifications.failed > 0 ? "warn" : undefined} />
              <KpiCard label="Skipped (no contact)"   value={fmt(m.notifications.skipped)}
                tone={m.notifications.skipped > 0 ? "warn" : undefined} />
            </div>

            <div className="card" style={{ fontSize: "12px", color: "#64748b" }} role="note" aria-label="Dataset provenance">
              Generated {m.generated_at} &bull; Scale: <strong>{m.scale}</strong> &bull; Seed: <strong>{m.seed}</strong>
            </div>
          </>
        )}
      </LoadingWrapper>
    </div>
  )
}
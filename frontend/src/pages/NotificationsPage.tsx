import {
  PieChart, Pie, Cell, Tooltip, BarChart, Bar, XAxis, YAxis,
  ResponsiveContainer,
} from "recharts"
import { useJsonData } from "../hooks/useJsonData"
import LoadingWrapper from "../components/LoadingWrapper"
import { fmt, statusBadge } from "../utils/format"
import { downloadCsv } from "../utils/csv"
import type { NotificationsData, NotifItem, SkippedItem } from "../utils/types"

const STATUS_COLORS: Record<string, string> = {
  delivered: "#166534",
  failed:    "#991b1b",
  sent:      "#1e40af",
  pending:   "#64748b",
  cancelled: "#374151",
}
const CHANNEL_COLORS: Record<string, string> = { sms: "#4338ca", email: "#0369a1", push: "#b45309" }

function countBy<T>(arr: T[], key: keyof T): Record<string, number> {
  const out: Record<string, number> = {}
  for (const item of arr) {
    const v = String(item[key])
    out[v] = (out[v] ?? 0) + 1
  }
  return out
}

function downloadSent(sent: NotifItem[]) {
  downloadCsv(
    sent.map((n) => ({
      id:                    n.id,
      student_id:            n.student_id,
      guardian_id:           n.guardian_id,
      guardian_masked_phone: n.guardian_masked_phone,
      guardian_masked_email: n.guardian_masked_email,
      channel:               n.channel,
      status:                n.status,
      sent_at:               n.sent_at ?? "",
      failure_reason:        n.failure_reason ?? "",
    })),
    "notifications_sent.csv",
  )
}

function downloadSkipped(skipped: SkippedItem[]) {
  downloadCsv(
    skipped.map((s) => ({
      student_id: s.student_id,
      event_id:   s.event_id,
      event_type: s.event_type,
      date:       s.date ?? "",
      reason:     s.reason,
    })),
    "notifications_skipped.csv",
  )
}

export default function NotificationsPage() {
  const { data, status, error } = useJsonData<NotificationsData>("/data/notifications.json")

  const sent    = data?.sent    ?? []
  const skipped = data?.skipped ?? []

  const byStatus    = countBy(sent, "status")
  const byChannel   = countBy(sent, "channel")
  const skipReasons = countBy(skipped, "reason")

  const statusPie  = Object.entries(byStatus).map(([name, value]) => ({ name, value }))
  const channelBar = Object.entries(byChannel).map(([name, value]) => ({ name, value }))
  const reasonBar  = Object.entries(skipReasons).map(([name, value]) => ({ name, value }))

  return (
    <div>
      <h1>Notifications</h1>
      <LoadingWrapper status={status} error={error}>
        {data && (
          <>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(220px,1fr))", gap: "1rem", marginBottom: "1rem" }}>

              {/* Status pie */}
              <div className="card">
                <h2 id="chart-status">By Status</h2>
                {statusPie.length === 0 ? (
                  <div className="empty-state"><div>No data.</div></div>
                ) : (
                  <figure aria-labelledby="chart-status">
                    <ResponsiveContainer width="100%" height={180}>
                      <PieChart>
                        <Pie
                          data={statusPie} dataKey="value" nameKey="name"
                          cx="50%" cy="50%" outerRadius={70}
                          label={({ name, percent }: { name: string; percent: number }) =>
                            `${name} ${(percent * 100).toFixed(0)}%`}
                          labelLine={false} fontSize={11}
                        >
                          {statusPie.map((entry, i) => (
                            <Cell key={i} fill={STATUS_COLORS[entry.name] ?? "#64748b"} />
                          ))}
                        </Pie>
                        <Tooltip formatter={(v: number) => fmt(v)} />
                      </PieChart>
                    </ResponsiveContainer>
                    <figcaption style={{ fontSize: 11, color: "#64748b", textAlign: "center", marginTop: 4 }}>
                      {statusPie.map((e) => `${e.name}: ${fmt(e.value)}`).join(" | ")}
                    </figcaption>
                  </figure>
                )}
              </div>

              {/* Channel bar */}
              <div className="card">
                <h2 id="chart-channel">By Channel</h2>
                {channelBar.length === 0 ? (
                  <div className="empty-state"><div>No data.</div></div>
                ) : (
                  <figure aria-labelledby="chart-channel">
                    <ResponsiveContainer width="100%" height={180}>
                      <BarChart data={channelBar} margin={{ top: 4, right: 8, bottom: 4, left: 0 }}>
                        <XAxis dataKey="name" tick={{ fontSize: 12 }} />
                        <YAxis tick={{ fontSize: 11 }} />
                        <Tooltip />
                        <Bar dataKey="value" name="Count" radius={[3, 3, 0, 0]}>
                          {channelBar.map((entry, i) => (
                            <Cell key={i} fill={CHANNEL_COLORS[entry.name] ?? "#64748b"} />
                          ))}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                    <figcaption style={{ fontSize: 11, color: "#64748b", textAlign: "center", marginTop: 4 }}>
                      {channelBar.map((e) => `${e.name}: ${fmt(e.value)}`).join(" | ")}
                    </figcaption>
                  </figure>
                )}
              </div>

              {/* Skip reasons bar */}
              <div className="card">
                <h2 id="chart-skip">Skip reasons</h2>
                {reasonBar.length === 0 ? (
                  <div className="empty-state"><div>No skipped notifications.</div></div>
                ) : (
                  <figure aria-labelledby="chart-skip">
                    <ResponsiveContainer width="100%" height={180}>
                      <BarChart data={reasonBar} layout="vertical" margin={{ top: 4, right: 8, bottom: 4, left: 110 }}>
                        <XAxis type="number" tick={{ fontSize: 11 }} />
                        <YAxis type="category" dataKey="name" tick={{ fontSize: 11 }} width={110} />
                        <Tooltip />
                        <Bar dataKey="value" name="Count" fill="#991b1b" radius={[0, 3, 3, 0]} />
                      </BarChart>
                    </ResponsiveContainer>
                    <figcaption style={{ fontSize: 11, color: "#64748b", textAlign: "center", marginTop: 4 }}>
                      {reasonBar.map((e) => `${e.name}: ${fmt(e.value)}`).join(" | ")}
                    </figcaption>
                  </figure>
                )}
              </div>
            </div>

            {/* Sent table */}
            <div className="card">
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: "0.5rem", marginBottom: "0.75rem" }}>
                <h2 style={{ margin: 0 }}>Sent ({fmt(sent.length)}) &mdash; masked contact info</h2>
                <button className="btn-csv" onClick={() => downloadSent(sent)} aria-label="Download sent notifications as CSV">
                  &#8595; Download CSV
                </button>
              </div>
              <p style={{ fontSize: 11, color: "#64748b", marginBottom: 8 }}>
                Phone and email are masked. No names are stored.
              </p>
              <div className="table-wrap">
                <table aria-label="Sent notifications">
                  <thead>
                    <tr>
                      <th scope="col">ID</th><th scope="col">Student</th><th scope="col">Guardian</th>
                      <th scope="col">Phone</th><th scope="col">Email</th>
                      <th scope="col">Channel</th><th scope="col">Status</th><th scope="col">Sent at</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sent.length === 0 && (
                      <tr><td colSpan={8} style={{ textAlign: "center", color: "#64748b" }}>No notifications sent.</td></tr>
                    )}
                    {sent.slice(0, 200).map((n) => (
                      <tr key={n.id}>
                        <td><code style={{ fontSize: 10 }}>{n.id}</code></td>
                        <td><code style={{ fontSize: 11 }}>{n.student_id}</code></td>
                        <td><code style={{ fontSize: 11 }}>{n.guardian_id}</code></td>
                        <td style={{ fontSize: 11 }}>{n.guardian_masked_phone}</td>
                        <td style={{ fontSize: 11 }}>{n.guardian_masked_email}</td>
                        <td><span className="badge badge-blue">{n.channel}</span></td>
                        <td><span className={statusBadge(n.status)}>{n.status}</span></td>
                        <td style={{ fontSize: 11 }}>{n.sent_at?.slice(0, 10) ?? "—"}</td>
                      </tr>
                    ))}
                    {sent.length > 200 && (
                      <tr>
                        <td colSpan={8} style={{ textAlign: "center", color: "#64748b", fontSize: 12 }}>
                          Showing first 200 of {fmt(sent.length)} &mdash; download CSV for full list
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Skipped table */}
            {skipped.length > 0 && (
              <div className="card">
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: "0.5rem", marginBottom: "0.75rem" }}>
                  <h2 style={{ margin: 0 }}>Skipped ({fmt(skipped.length)})</h2>
                  <button className="btn-csv" onClick={() => downloadSkipped(skipped)} aria-label="Download skipped notifications as CSV">
                    &#8595; Download CSV
                  </button>
                </div>
                <div className="table-wrap">
                  <table aria-label="Skipped notifications">
                    <thead>
                      <tr>
                        <th scope="col">Student</th><th scope="col">Event</th>
                        <th scope="col">Event type</th><th scope="col">Date</th><th scope="col">Reason</th>
                      </tr>
                    </thead>
                    <tbody>
                      {skipped.slice(0, 100).map((s, i) => (
                        <tr key={i}>
                          <td><code style={{ fontSize: 11 }}>{s.student_id}</code></td>
                          <td><code style={{ fontSize: 10 }}>{s.event_id.slice(0, 28)}&hellip;</code></td>
                          <td><span className="badge badge-gray">{s.event_type}</span></td>
                          <td style={{ fontSize: 11 }}>{s.date ?? "—"}</td>
                          <td><span className="badge badge-yellow">{s.reason}</span></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </>
        )}
      </LoadingWrapper>
    </div>
  )
}
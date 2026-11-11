import {
  LineChart, Line, BarChart, Bar, XAxis, YAxis, Tooltip,
  CartesianGrid, ResponsiveContainer, ReferenceLine,
} from "recharts"
import { useJsonData } from "../hooks/useJsonData"
import LoadingWrapper from "../components/LoadingWrapper"
import MappingNote from "../components/MappingNote"
import { pct, fmt } from "../utils/format"
import type { AttendanceSummary } from "../utils/types"

function weekdayAgg(rows: AttendanceSummary[]) {
  const order = ["Mon", "Tue", "Wed", "Thu", "Fri"]
  const acc: Record<string, { sum: number; count: number }> = {}
  for (const wd of order) acc[wd] = { sum: 0, count: 0 }
  for (const r of rows) {
    if (acc[r.weekday]) {
      acc[r.weekday].sum   += r.absent + r.no_show
      acc[r.weekday].count += r.total_events
    }
  }
  return order.map((wd) => ({
    weekday:     wd,
    absent_rate: acc[wd].count > 0 ? +(acc[wd].sum / acc[wd].count * 100).toFixed(2) : 0,
  }))
}

export default function AttendancePage() {
  const { data: summary, status, error } = useJsonData<AttendanceSummary[]>("/data/attendance_summary.json")

  const trendData = (summary ?? []).map((r) => ({
    date:    r.date.slice(5),
    rate:    +(r.attendance_rate * 100).toFixed(2),
    absent:  r.absent,
    no_show: r.no_show,
    disrupt: r.has_disruption,
  }))

  const wdData = summary ? weekdayAgg(summary) : []

  return (
    <div>
      <h1>Attendance</h1>
      <MappingNote />
      <LoadingWrapper status={status} error={error}>
        {summary && summary.length === 0 && (
          <div className="empty-state">
            <div className="es-icon" aria-hidden="true">&#128197;</div>
            <div>No attendance data.</div>
          </div>
        )}
        {summary && summary.length > 0 && (
          <>
            {/* daily trend line */}
            <div className="card">
              <h2 id="chart-trend">Daily attendance rate (boarded / active-assignment-days)</h2>
              <figure aria-labelledby="chart-trend">
                <ResponsiveContainer width="100%" height={260}>
                  <LineChart data={trendData} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                    <XAxis dataKey="date" tick={{ fontSize: 10 }} />
                    <YAxis tickFormatter={(v: number) => v + "%"} domain={[85, 100]} tick={{ fontSize: 11 }} />
                    <Tooltip formatter={(v: number) => v + "%"} />
                    <ReferenceLine y={92} stroke="#92400e" strokeDasharray="4 2"
                      label={{ value: "92% target", fontSize: 10, fill: "#92400e", position: "insideTopRight" }} />
                    <Line
                      type="monotone"
                      dataKey="rate"
                      stroke="#1e40af"
                      name="Attendance rate"
                      dot={(props: { cx?: number; cy?: number; payload?: { disrupt?: boolean } }) => {
                        const { cx = 0, cy = 0, payload } = props
                        if (payload?.disrupt) {
                          // triangle shape distinguishes disruption days without relying on colour alone
                          return (
                            <polygon
                              key={`${cx}-${cy}`}
                              points={`${cx},${cy - 7} ${cx - 5},${cy + 3} ${cx + 5},${cy + 3}`}
                              fill="#b45309"
                              aria-label="Disruption day"
                            />
                          )
                        }
                        return <circle key={`${cx}-${cy}`} cx={cx} cy={cy} r={2} fill="#1e40af" />
                      }}
                    />
                  </LineChart>
                </ResponsiveContainer>
                <figcaption style={{ fontSize: 11, color: "#64748b", marginTop: 4 }}>
                  Amber triangles (&#9650;) mark days with route disruptions.
                  Dashed line = 92% attendance target.
                </figcaption>
              </figure>
            </div>

            {/* weekday bar */}
            <div className="card">
              <h2 id="chart-weekday">Non-boarded rate by weekday (absent + missed-pickup)</h2>
              <figure aria-labelledby="chart-weekday">
                <ResponsiveContainer width="100%" height={200}>
                  <BarChart data={wdData} margin={{ top: 4, right: 16, bottom: 4, left: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                    <XAxis dataKey="weekday" tick={{ fontSize: 12 }} />
                    <YAxis tickFormatter={(v: number) => v + "%"} tick={{ fontSize: 11 }} />
                    <Tooltip formatter={(v: number) => v + "%"} />
                    <Bar dataKey="absent_rate" name="Non-boarded rate (%)" fill="#991b1b" radius={[3, 3, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
                <figcaption style={{ fontSize: 11, color: "#64748b", marginTop: 4 }}>
                  {wdData.map((d) => `${d.weekday}: ${d.absent_rate}%`).join(" | ")}
                </figcaption>
              </figure>
            </div>

            {/* daily detail table */}
            <div className="card">
              <h2>Daily detail</h2>
              <div className="table-wrap">
                <table aria-label="Attendance by school day">
                  <thead>
                    <tr>
                      <th scope="col">Date</th>
                      <th scope="col">Day</th>
                      <th scope="col">Boarded</th>
                      <th scope="col">Absent</th>
                      <th scope="col">No-show</th>
                      <th scope="col">Late pickup</th>
                      <th scope="col">Rate</th>
                      <th scope="col">Disruption</th>
                    </tr>
                  </thead>
                  <tbody>
                    {summary.map((r) => (
                      <tr
                        key={r.date}
                        className={r.has_disruption ? "disruption-row" : undefined}
                        aria-label={r.has_disruption ? `${r.date} disruption day` : undefined}
                      >
                        <td style={{ fontSize: 12 }}>{r.date}</td>
                        <td>{r.weekday}</td>
                        <td>{fmt(r.boarded)}</td>
                        <td>
                          {fmt(r.absent)}
                          {r.absent > 0 && <span aria-hidden="true" style={{ marginLeft: 3, fontSize: 10, color: "#991b1b" }}>!</span>}
                        </td>
                        <td>
                          {fmt(r.no_show)}
                          {r.no_show > 0 && <span aria-hidden="true" style={{ marginLeft: 3, fontSize: 10, color: "#92400e" }}>^</span>}
                        </td>
                        <td>{fmt(r.late_pickup)}</td>
                        <td>{pct(r.attendance_rate)}</td>
                        <td>
                          {r.disruptions_cancelled > 0 && (
                            <span className="badge badge-red">&#9733; Cancel x{r.disruptions_cancelled}</span>
                          )}
                          {r.disruptions_delay > 0 && (
                            <span className="badge badge-yellow" style={{ marginLeft: 4 }}>
                              &#9650; Delay x{r.disruptions_delay}
                            </span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </>
        )}
      </LoadingWrapper>
    </div>
  )
}
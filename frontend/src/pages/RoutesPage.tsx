import { useState } from "react"
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine, Cell,
} from "recharts"
import { useJsonData } from "../hooks/useJsonData"
import LoadingWrapper from "../components/LoadingWrapper"
import { fmt } from "../utils/format"
import type { Route, CapacityHistoryItem } from "../utils/types"

function routeTone(r: Route): "" | "warn" | "danger" {
  if (r.utilisation.utilisation_pct > 100) return "danger"
  if (r.utilisation.utilisation_pct >= 90) return "warn"
  return ""
}

function barColor(p: number): string {
  if (p > 100) return "#991b1b"
  if (p >= 90) return "#92400e"
  return "#1e40af"
}

function busesWithMultipleCapRows(capHist: CapacityHistoryItem[]): Set<string> {
  const counts: Record<string, number> = {}
  for (const c of capHist) counts[c.bus_id] = (counts[c.bus_id] ?? 0) + 1
  return new Set(Object.entries(counts).filter(([, n]) => n > 1).map(([id]) => id))
}

export default function RoutesPage() {
  const { data: routes,  status, error } = useJsonData<Route[]>("/data/routes.json")
  const { data: capHist }                = useJsonData<CapacityHistoryItem[]>("/data/capacity_history.json")
  const [filter, setFilter]              = useState<"all" | "active" | "issues">("active")

  const withReduction = busesWithMultipleCapRows(capHist ?? [])

  const visible = (routes ?? []).filter((r) => {
    if (filter === "active") return r.status === "active"
    if (filter === "issues") return r.utilisation.utilisation_pct >= 90 || withReduction.has(r.bus_id)
    return true
  })

  const chartData = visible.slice(0, 40).map((r) => ({
    name:     r.id.replace("ROUTE-2026-", ""),
    pct:      Math.round(r.utilisation.utilisation_pct),
    assigned: r.utilisation.assigned_students,
    capacity: r.utilisation.capacity,
  }))

  return (
    <div>
      <h1>Routes &amp; Capacity</h1>
      <LoadingWrapper status={status} error={error}>
        {routes && (
          <>
            {/* filter buttons */}
            <div className="search-row" role="group" aria-label="Filter routes">
              {(["all", "active", "issues"] as const).map((f) => (
                <button
                  key={f}
                  onClick={() => setFilter(f)}
                  aria-pressed={filter === f}
                  style={{
                    padding: "5px 14px", borderRadius: 6, border: "1px solid #94a3b8",
                    background: filter === f ? "#1a2233" : "#fff",
                    color:      filter === f ? "#fff"    : "#374151",
                    cursor: "pointer", fontSize: 13, fontWeight: 600,
                  }}
                >
                  {f === "issues" ? "Issues only" : f.charAt(0).toUpperCase() + f.slice(1)}
                </button>
              ))}
              <span style={{ color: "#64748b", fontSize: 12 }} aria-live="polite">
                {visible.length} routes shown
              </span>
            </div>

            {/* utilisation chart */}
            {chartData.length > 0 && (
              <div className="card">
                <h2 id="chart-util">Route utilisation (first {chartData.length})</h2>
                <figure aria-labelledby="chart-util">
                  <ResponsiveContainer width="100%" height={260}>
                    <BarChart data={chartData} margin={{ top: 8, right: 16, bottom: 28, left: 0 }}>
                      <XAxis dataKey="name" tick={{ fontSize: 10 }} angle={-45} textAnchor="end" interval={0} />
                      <YAxis tickFormatter={(v: number) => v + "%"} tick={{ fontSize: 11 }} />
                      <Tooltip
                        formatter={(v: number, _n: string, p: { payload?: { assigned?: number; capacity?: number } }) =>
                          [`${v}% (${p.payload?.assigned ?? 0}/${p.payload?.capacity ?? 0})`, "Utilisation"]}
                      />
                      <ReferenceLine y={100} stroke="#991b1b" strokeDasharray="4 2"
                        label={{ value: "100% (over)", fontSize: 10, fill: "#991b1b", position: "insideTopRight" }} />
                      <ReferenceLine y={90} stroke="#92400e" strokeDasharray="4 2"
                        label={{ value: "90%", fontSize: 10, fill: "#92400e", position: "insideTopRight" }} />
                      <Bar dataKey="pct" radius={[3, 3, 0, 0]}>
                        {chartData.map((d, i) => (
                          <Cell key={i} fill={barColor(d.pct)} />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                  <figcaption style={{ fontSize: 11, color: "#64748b", marginTop: 4 }}>
                    Dark red = over capacity (&gt;100%); amber = high load (90-100%); blue = normal.
                    Dashed lines mark 100% and 90% thresholds.
                  </figcaption>
                </figure>
              </div>
            )}

            {/* routes table */}
            <div className="card">
              <div className="table-wrap">
                <table aria-label="Route utilisation detail">
                  <thead>
                    <tr>
                      <th scope="col">Route ID</th>
                      <th scope="col">Status</th>
                      <th scope="col">Bus</th>
                      <th scope="col">Accessible</th>
                      <th scope="col">Cap (init)</th>
                      <th scope="col">Assigned</th>
                      <th scope="col">Utilisation</th>
                      <th scope="col">Cap reduced</th>
                      <th scope="col">Window</th>
                    </tr>
                  </thead>
                  <tbody>
                    {visible.length === 0 && (
                      <tr>
                        <td colSpan={9} style={{ textAlign: "center", color: "#64748b", padding: "1.5rem" }}>
                          No routes match filter.
                        </td>
                      </tr>
                    )}
                    {visible.map((r) => {
                      const tone = routeTone(r)
                      const isOver = tone === "danger"
                      return (
                        <tr
                          key={r.id}
                          className={isOver ? "row-over-capacity" : undefined}
                          aria-label={isOver ? `${r.id} OVER CAPACITY` : undefined}
                        >
                          <td><code style={{ fontSize: 11 }}>{r.id}</code></td>
                          <td>
                            <span className={r.status === "active" ? "badge badge-green" : "badge badge-gray"}>
                              {r.status}
                            </span>
                          </td>
                          <td style={{ fontSize: 11 }}>{r.bus_id}</td>
                          <td>
                            {r.bus_is_accessible
                              ? <span className="tag-accessible" aria-label="Accessible bus">ACC</span>
                              : <span aria-label="Not accessible" style={{ color: "#94a3b8", fontSize: 11 }}>—</span>}
                          </td>
                          <td>{fmt(r.bus_capacity_initial)}</td>
                          <td>
                            {fmt(r.utilisation.assigned_students)}
                            {tone === "danger" && <span aria-hidden="true" style={{ marginLeft: 4, color: "#991b1b" }}>!</span>}
                            {tone === "warn"   && <span aria-hidden="true" style={{ marginLeft: 4, color: "#92400e" }}>^</span>}
                          </td>
                          <td>
                            {r.utilisation.utilisation_pct.toFixed(1)}%
                          </td>
                          <td>
                            {withReduction.has(r.bus_id)
                              ? <span className="badge badge-orange" aria-label="Capacity was reduced mid-year">Yes</span>
                              : ""}
                          </td>
                          <td style={{ fontSize: 11 }}>
                            {r.pickup_window_start}&#8211;{r.pickup_window_end}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            </div>

            {/* capacity history */}
            {(capHist ?? []).length > 0 && (
              <div className="card">
                <h2>Capacity history (buses with mid-year reduction)</h2>
                <div className="table-wrap">
                  <table aria-label="Bus capacity history">
                    <thead>
                      <tr>
                        <th scope="col">Bus</th>
                        <th scope="col">Capacity</th>
                        <th scope="col">Accessible</th>
                        <th scope="col">Effective from</th>
                        <th scope="col">Effective to</th>
                        <th scope="col">Reason</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(capHist ?? [])
                        .filter((c) => withReduction.has(c.bus_id))
                        .map((c) => (
                          <tr key={c.id}>
                            <td><code style={{ fontSize: 11 }}>{c.bus_id}</code></td>
                            <td>{c.capacity}</td>
                            <td>
                              {c.is_accessible
                                ? <span className="tag-accessible" aria-label="Accessible">ACC</span>
                                : ""}
                            </td>
                            <td style={{ fontSize: 11 }}>{c.effective_from?.slice(0, 10)}</td>
                            <td style={{ fontSize: 11 }}>
                              {c.effective_to
                                ? c.effective_to.slice(0, 10)
                                : <span className="badge badge-green">current</span>}
                            </td>
                            <td style={{
                              fontSize: 11, maxWidth: 240,
                              overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                            }}>
                              {c.reason}
                            </td>
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
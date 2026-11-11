import { useJsonData } from "../hooks/useJsonData"
import LoadingWrapper from "../components/LoadingWrapper"
import MappingNote from "../components/MappingNote"
import { fmt } from "../utils/format"
import { downloadCsv } from "../utils/csv"
import type { Rejection } from "../utils/types"

export default function ExceptionsPage() {
  const { data: rejections, status, error } = useJsonData<Rejection[]>("/data/rejections.json")

  function handleDownload() {
    if (!rejections) return
    downloadCsv(
      rejections.map((r) => ({
        student_id:         r.student_id,
        attempted_route_id: r.attempted_route_id,
        error_codes:        r.error_codes.join("|"),
        reason:             r.reason,
      })),
      "rejections.csv",
    )
  }

  return (
    <div>
      <h1>Exceptions</h1>
      <MappingNote />
      <LoadingWrapper status={status} error={error}>
        {rejections && rejections.length === 0 && (
          <div className="empty-state">
            <div className="es-icon" aria-hidden="true">&#10003;</div>
            <div>No rejected or waitlisted assignments at starter scale.</div>
          </div>
        )}
        {rejections && rejections.length > 0 && (
          <div className="card">
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: "0.5rem", marginBottom: "0.75rem" }}>
              <h2 style={{ margin: 0 }}>Rejected / waitlisted students ({fmt(rejections.length)})</h2>
              <button className="btn-csv" onClick={handleDownload} aria-label="Download rejections as CSV">
                &#8595; Download CSV
              </button>
            </div>
            <div className="table-wrap">
              <table aria-label="Rejected and waitlisted student assignments">
                <thead>
                  <tr>
                    <th scope="col">Student ID</th>
                    <th scope="col">Attempted route</th>
                    <th scope="col">Error codes</th>
                    <th scope="col">Reason</th>
                  </tr>
                </thead>
                <tbody>
                  {rejections.map((r, i) => (
                    <tr key={i}>
                      <td><code style={{ fontSize: 11 }}>{r.student_id}</code></td>
                      <td><code style={{ fontSize: 11 }}>{r.attempted_route_id || "—"}</code></td>
                      <td>
                        {r.error_codes.map((c) => (
                          <span key={c} className="badge badge-red" style={{ marginRight: 4 }}>{c}</span>
                        ))}
                      </td>
                      <td style={{ fontSize: 12 }}>{r.reason}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </LoadingWrapper>
    </div>
  )
}
import { useState, useMemo } from "react"
import { useJsonData } from "../hooks/useJsonData"
import MappingNote from "../components/MappingNote"
import { EVENT_LABEL, eventBadge, dotClass, statusBadge } from "../utils/format"
import type {
  StudentAssignment, AttendanceEvent, NotifByStudent,
} from "../utils/types"

export default function StudentPage() {
  const [query, setQuery] = useState("")
  const [submitted, setSubmitted] = useState("")

  const { data: studentIndex, status: si } = useJsonData<Record<string, StudentAssignment>>("/data/student_index.json")
  const { data: attByStu,     status: ab } = useJsonData<Record<string, AttendanceEvent[]>>("/data/attendance_by_student.json")
  const { data: notifByStu,   status: nb } = useJsonData<Record<string, NotifByStudent[]>>("/data/notifications_by_student.json")

  const loading = si === "loading" || ab === "loading" || nb === "loading"
  const failed  = si === "error"   || ab === "error"   || nb === "error"

  const handleSearch = () => {
    const id = query.trim().toUpperCase()
    setSubmitted(id.startsWith("STU-") ? id : id ? "STU-" + id.padStart(6, "0") : "")
  }

  const asn    = submitted && studentIndex ? studentIndex[submitted] : null
  const events = submitted && attByStu     ? (attByStu[submitted] ?? [])  : []
  const notifs = submitted && notifByStu   ? (notifByStu[submitted] ?? []) : []

  const sortedEvents = useMemo(
    () => [...events].sort((a, b) => a.date.localeCompare(b.date)),
    [events],
  )

  return (
    <div>
      <h1>Student Lookup</h1>
      <MappingNote />

      {loading && <div className="loading-state">Loading student data...</div>}
      {failed  && <div className="error-state">Failed to load one or more data files.</div>}

      {!loading && !failed && (
        <>
          <div className="search-row">
            <input
              className="search-input"
              placeholder="Enter STU-000001 or just the number"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") handleSearch() }}
            />
            <button
              onClick={handleSearch}
              style={{ padding: "5px 16px", borderRadius: 6, background: "#1a2233", color: "#fff", border: "none", cursor: "pointer", fontSize: 13 }}>
              Search
            </button>
          </div>

          {submitted && !asn && (
            <div className="empty-state">
              <div className="es-icon">?</div>
              <div>No active assignment found for <strong>{submitted}</strong>.</div>
              <div style={{ fontSize: 12, marginTop: ".5rem", color: "#94a3b8" }}>
                Student may be waitlisted, rejected, or not exist at this scale.
              </div>
            </div>
          )}

          {asn && (
            <>
              <div className="card">
                <h2>Assignment</h2>
                <table>
                  <tbody>
                    <tr><th>Student ID</th><td><code>{submitted}</code></td></tr>
                    <tr><th>Assignment ID</th><td><code>{asn.assignment_id}</code></td></tr>
                    <tr><th>Route</th><td><code>{asn.route_id}</code></td></tr>
                    <tr><th>Stop</th><td><code>{asn.stop_id}</code></td></tr>
                    <tr><th>Status</th><td><span className={statusBadge(asn.status)}>{asn.status}</span></td></tr>
                  </tbody>
                </table>
              </div>

              <div className="card">
                <h2>Attendance timeline ({sortedEvents.length} events)</h2>
                {sortedEvents.length === 0 ? (
                  <div className="empty-state"><div>No attendance events.</div></div>
                ) : (
                  <ul className="timeline">
                    {sortedEvents.map((ev) => (
                      <li key={ev.event_id}>
                        <span className="tl-date">{ev.date}</span>
                        <span className={dotClass(ev.event_type)} />
                        <span className={eventBadge(ev.event_type)}>{EVENT_LABEL[ev.event_type] ?? ev.event_type}</span>
                        {ev.notes && <span style={{ fontSize: 11, color: "#94a3b8", marginLeft: 6 }}>{ev.notes}</span>}
                      </li>
                    ))}
                  </ul>
                )}
              </div>

              <div className="card">
                <h2>Notifications ({notifs.length})</h2>
                {notifs.length === 0 ? (
                  <div className="empty-state"><div>No notifications for this student.</div></div>
                ) : (
                  <div className="table-wrap">
                    <table>
                      <thead><tr><th>ID</th><th>Event</th><th>Channel</th><th>Status</th><th>Sent at</th></tr></thead>
                      <tbody>
                        {notifs.map((n) => (
                          <tr key={n.notification_id}>
                            <td><code style={{ fontSize: 10 }}>{n.notification_id}</code></td>
                            <td><code style={{ fontSize: 10 }}>{n.event_id.slice(0, 30)}...</code></td>
                            <td><span className="badge badge-blue">{n.channel}</span></td>
                            <td><span className={statusBadge(n.status)}>{n.status}</span></td>
                            <td style={{ fontSize: 11 }}>{n.sent_at?.slice(0, 16) ?? "—"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            </>
          )}

          {!submitted && (
            <div className="empty-state">
              <div className="es-icon">&#128100;</div>
              <div>Enter a student ID to look up their assignment, attendance timeline, and notifications.</div>
            </div>
          )}
        </>
      )}
    </div>
  )
}

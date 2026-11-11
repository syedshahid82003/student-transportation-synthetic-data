# Transport Dashboard

Read-only dashboard for the school bus routing synthetic dataset.

## Stack

- Vite 5 + React 18 + TypeScript
- Recharts for all charts
- react-router-dom v6 for client-side routing
- No external network calls; all data loaded from /public/data/

## Quick start

1. Install frontend dependencies
   cd frontend; npm install

2. Generate JSON data files (run from repo root, backend venv active)
   python scripts/export_frontend_data.py

3. Start the dev server
   cd frontend; npm run dev
   -> http://localhost:5173

4. Production build
   npm run build
   output in frontend/dist/

## Pages

| Route | Page | Roles |
|---|---|---|
| / | Overview | All |
| /routes | Routes and capacity | All |
| /students | Student lookup | Support, admin |
| /attendance | Attendance trends | All |
| /notifications | Notifications | Support, admin |
| /exceptions | Rejected assignments | All |
| /anomaly | Anomaly view | Admin only |

## Data files (frontend/public/data/)

| File | Contents |
|---|---|
| metrics.json | Top-level KPIs |
| routes.json | Routes with utilisation merged |
| route_stops.json | Stop sequence per route |
| assignments.json | All assignments (active + inactive) |
| rejections.json | Rejected/waitlisted students |
| attendance_summary.json | Per-day aggregated attendance |
| disruptions.json | Route disruption events |
| notifications.json | Sent and skipped notifications (masked PII) |
| capacity_history.json | Bus capacity changelog |
| student_index.json | student_id -> assignment lookup |
| attendance_by_student.json | Per-student event list |
| notifications_by_student.json | Per-student notification list |
| ground_truth/README.json | Placeholder; populated by anomaly injector |

## Event type mapping

The attendance_events validator constrains event_type to a fixed enum.

| Intent | validator event_type |
|---|---|
| Student present | boarded |
| Student absent | absent |
| Missed pickup (route cancelled) | no_show |
| Capacity-reduced ride (replaces boarded) | late_pickup |

The late_pickup mapping is a validator limitation: no CAPACITY_REDUCED type
exists in the schema. The notes field carries capacity_reduced to distinguish
it from a genuine late pickup caused by a DELAY disruption.

## Notes

- All data is fully synthetic. Seed 20261022. No real PII.
- Phone and email are masked in notifications.json (last 4 digits / domain only).
- The anomaly page loads from ground_truth/ kept separate from routing tables.
- The chunk-size warning from npm run build is expected: Recharts ~600 KB.
  Use build.rollupOptions.output.manualChunks if you need to split further.

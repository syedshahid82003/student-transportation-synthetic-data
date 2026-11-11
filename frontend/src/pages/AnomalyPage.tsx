import { useJsonData } from "../hooks/useJsonData"

interface GTReadme { status: string; note: string }
interface ReprodReport {
  generated_at: string
  seed: number
  scale: string
  row_counts: Record<string, number>
  checksums?: Record<string, string>
}

export default function AnomalyPage() {
  const { data: gt,     status: gs } = useJsonData<GTReadme>("/data/ground_truth/README.json")
  const { data: report, status: rs } = useJsonData<ReprodReport>("/data/reproducibility_report.json")

  const isEmpty = !gt || gt.status === "empty"

  return (
    <div>
      <h1>Anomaly view (admin only)</h1>

      <div
        style={{
          background: "#fef9c3", border: "1px solid #fde68a", borderRadius: 8,
          padding: "1rem", marginBottom: "1.2rem", fontSize: 13, color: "#78350f",
        }}
        role="note"
        aria-label="Admin-only page notice"
      >
        <strong>Admin-only page.</strong>{" "}
        This view loads data exclusively from{" "}
        <code>frontend/public/data/ground_truth/</code>,
        which is physically separate from all routing dataset tables.
        Labels from this view never mix with the input data.
      </div>

      {/* Reproducibility badge — shown once Phase 5 generates the report */}
      {rs === "ok" && report && (
        <div className="card" style={{ marginBottom: "1.2rem" }} role="region" aria-label="Reproducibility report">
          <h2>Reproducibility report</h2>
          <p style={{ fontSize: 12, color: "#64748b", marginBottom: "0.75rem" }}>
            Generated {report.generated_at} &bull; Scale: {report.scale} &bull; Seed: {report.seed}
          </p>
          <div className="table-wrap">
            <table aria-label="Row counts per collection">
              <thead>
                <tr>
                  <th scope="col">Collection</th>
                  <th scope="col">Row count</th>
                  {report.checksums && <th scope="col">SHA-256 (truncated)</th>}
                </tr>
              </thead>
              <tbody>
                {Object.entries(report.row_counts).map(([col, count]) => (
                  <tr key={col}>
                    <td><code style={{ fontSize: 11 }}>{col}</code></td>
                    <td>{count.toLocaleString()}</td>
                    {report.checksums && (
                      <td style={{ fontSize: 11, fontFamily: "monospace" }}>
                        {report.checksums[col]?.slice(0, 16) ?? "—"}&hellip;
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Empty state while report not yet generated */}
      {rs !== "ok" && (
        <div
          className="card"
          style={{ marginBottom: "1.2rem", fontSize: 12, color: "#64748b", fontStyle: "italic" }}
          role="note"
        >
          Reproducibility report (reproducibility_report.json) not yet generated.
          It will appear here once Phase 5 produces it.
        </div>
      )}

      {/* Ground-truth data */}
      {gs === "loading" && <div className="loading-state">Loading ground-truth index&hellip;</div>}

      {isEmpty && (
        <div className="empty-state" style={{ marginTop: "1.5rem" }}>
          <div className="es-icon" aria-hidden="true">&#128274;</div>
          <div style={{ fontWeight: 600, marginBottom: ".5rem" }}>No anomaly data available</div>
          <div style={{ fontSize: 12, color: "#64748b" }}>
            {gt?.note ?? "Run the anomaly injector pipeline first, then re-run export_frontend_data.py."}
          </div>
        </div>
      )}

      {!isEmpty && gt && (
        <div className="card">
          <pre style={{ fontSize: 12, whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
            {JSON.stringify(gt, null, 2)}
          </pre>
        </div>
      )}

      <div className="card" style={{ marginTop: "1.2rem", fontSize: 11, color: "#64748b" }} role="contentinfo">
        Fully synthetic data &mdash; no real students, addresses or personal information &mdash; no external sources.
      </div>
    </div>
  )
}
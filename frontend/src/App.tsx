import { BrowserRouter, Routes, Route, NavLink, useLocation } from "react-router-dom"
import OverviewPage      from "./pages/OverviewPage"
import RoutesPage        from "./pages/RoutesPage"
import StudentPage       from "./pages/StudentPage"
import AttendancePage    from "./pages/AttendancePage"
import NotificationsPage from "./pages/NotificationsPage"
import ExceptionsPage    from "./pages/ExceptionsPage"
import AnomalyPage       from "./pages/AnomalyPage"
import "./App.css"

const NAV_LINKS = [
  { to: "/",             label: "Overview"       },
  { to: "/routes",       label: "Routes"         },
  { to: "/students",     label: "Students"       },
  { to: "/attendance",   label: "Attendance"     },
  { to: "/notifications",label: "Notifications"  },
  { to: "/exceptions",   label: "Exceptions"     },
  { to: "/anomaly",      label: "Anomaly (admin)"},
]

const PAGE_TITLES: Record<string, string> = {
  "/":             "Overview",
  "/routes":       "Routes & Capacity",
  "/students":     "Student Lookup",
  "/attendance":   "Attendance",
  "/notifications":"Notifications",
  "/exceptions":   "Exceptions",
  "/anomaly":      "Anomaly View (admin)",
}

function PageHeader() {
  const loc   = useLocation()
  const title = PAGE_TITLES[loc.pathname] ?? "Transport Dashboard"
  return (
    <header className="page-header">
      <span className="page-header-title">{title}</span>
      <span className="scale-badge" aria-label="Dataset scale and seed">
        Starter scale &bull; seed&nbsp;20261022
      </span>
    </header>
  )
}

function PageFooter() {
  return (
    <footer className="page-footer">
      Fully synthetic data &mdash; no real students, addresses or personal information &mdash; no external sources.
      &nbsp;&bull;&nbsp;Seed&nbsp;20261022&nbsp;&bull;&nbsp;
      <a href="/data/metrics.json" target="_blank" rel="noopener noreferrer">metrics.json</a>
    </footer>
  )
}

export default function App() {
  return (
    <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <div className="app-layout">
        <nav className="sidebar" aria-label="Main navigation">
          <div className="sidebar-title">Transport<br />Dashboard</div>
          {NAV_LINKS.map(({ to, label }) => (
            <NavLink
              key={to}
              to={to}
              end={to === "/"}
              className={({ isActive }) => "nav-item" + (isActive ? " active" : "")}
            >
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="main-column">
          <PageHeader />
          <main className="main-content" id="main-content">
            <Routes>
              <Route path="/"              element={<OverviewPage />}      />
              <Route path="/routes"        element={<RoutesPage />}        />
              <Route path="/students"      element={<StudentPage />}       />
              <Route path="/attendance"    element={<AttendancePage />}    />
              <Route path="/notifications" element={<NotificationsPage />} />
              <Route path="/exceptions"    element={<ExceptionsPage />}    />
              <Route path="/anomaly"       element={<AnomalyPage />}       />
            </Routes>
          </main>
          <PageFooter />
        </div>
      </div>
    </BrowserRouter>
  )
}
interface Props {
  status: "idle" | "loading" | "ok" | "error"
  error?: string
  children: React.ReactNode
}

export default function LoadingWrapper({ status, error, children }: Props) {
  if (status === "idle" || status === "loading") {
    return <div className="loading-state">Loading...</div>
  }
  if (status === "error") {
    return <div className="error-state">Failed to load data: {error}</div>
  }
  return <>{children}</>
}

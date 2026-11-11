import { useState, useEffect } from "react"

type Status = "idle" | "loading" | "ok" | "error"

export function useJsonData<T>(url: string): { data: T | null; status: Status; error: string } {
  const [data, setData] = useState<T | null>(null)
  const [status, setStatus] = useState<Status>("idle")
  const [error, setError] = useState("")

  useEffect(() => {
    setStatus("loading")
    fetch(url)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}: ${url}`)
        return r.json() as Promise<T>
      })
      .then((d) => { setData(d); setStatus("ok") })
      .catch((e: unknown) => {
        setError(e instanceof Error ? e.message : String(e))
        setStatus("error")
      })
  }, [url])

  return { data, status, error }
}

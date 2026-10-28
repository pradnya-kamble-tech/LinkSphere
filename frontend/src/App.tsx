import { useState, useEffect } from 'react'

interface HealthResponse {
  status: string
  database: string
}

export function App() {
  const [loading, setLoading] = useState<boolean>(true)
  const [data, setData] = useState<HealthResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  const checkHealth = async () => {
    setLoading(true)
    setError(null)
    setData(null)

    try {
      const response = await fetch('/health')
      if (!response.ok) {
        const errorBody = await response.text()
        throw new Error(`HTTP ${response.status}: ${errorBody || response.statusText}`)
      }
      const json: HealthResponse = await response.json()
      setData(json)
    } catch (err: unknown) {
      if (err instanceof Error) {
        setError(err.message)
      } else {
        setError('Unknown error occurred')
      }
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    checkHealth()
  }, [])

  return (
    <div className="container">
      <h1>LinkSphere</h1>
      <p>Phase 1 Foundation Health Check</p>

      <div className="card">
        <h2>Backend Status</h2>

        {loading && (
          <div className="status-badge loading">
            Checking backend health...
          </div>
        )}

        {!loading && error && (
          <div>
            <div className="status-badge error">
              Unhealthy / Error
            </div>
            <p style={{ marginTop: '0.75rem', color: 'var(--status-error)' }}>
              {error}
            </p>
          </div>
        )}

        {!loading && data && (
          <div>
            <div className="status-badge ok">
              Healthy ({data.status})
            </div>
            <p style={{ marginTop: '0.75rem' }}>
              Database: <strong>{data.database}</strong>
            </p>
            <pre>{JSON.stringify(data, null, 2)}</pre>
          </div>
        )}
      </div>

      <button onClick={checkHealth} disabled={loading}>
        {loading ? 'Checking...' : 'Recheck Health'}
      </button>
    </div>
  )
}

export default App

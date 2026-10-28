import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'

interface HealthResponse {
  status: string
  database: string
}

export function Home() {
  const [loading, setLoading] = useState<boolean>(true)
  const [data, setData] = useState<HealthResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetch('/api/health')
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        return res.json()
      })
      .then((json: HealthResponse) => setData(json))
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false))
  }, [])

  return (
    <div className="container">
      <h1>LinkSphere</h1>
      <p>Modern URL shortener with verified account ownership, redirection, and real analytics.</p>

      <div className="card">
        <h2>Account Access</h2>
        <div style={{ display: 'flex', gap: '1rem', marginTop: '1rem' }}>
          <Link to="/login" className="btn btn-primary">
            Log In
          </Link>
          <Link to="/signup" className="btn btn-secondary">
            Sign Up
          </Link>
          <Link to="/dashboard" className="btn btn-outline">
            Dashboard
          </Link>
        </div>
      </div>

      <div className="card">
        <h3>System Health (/api/health)</h3>
        {loading && <div className="status-badge loading">Checking system health...</div>}
        {!loading && error && (
          <div className="status-badge error">Unhealthy: {error}</div>
        )}
        {!loading && data && (
          <div>
            <div className="status-badge ok">Healthy: {data.status}</div>
            <p style={{ marginTop: '0.5rem', marginBottom: 0 }}>
              Database connection: <strong>{data.database}</strong>
            </p>
          </div>
        )}
      </div>
    </div>
  )
}

import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { fetchMe, logoutUser, UserProfile } from '../api'

export function Dashboard() {
  const [loading, setLoading] = useState<boolean>(true)
  const [user, setUser] = useState<UserProfile | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loggingOut, setLoggingOut] = useState<boolean>(false)
  const navigate = useNavigate()

  useEffect(() => {
    fetchMe()
      .then((profile) => {
        if (!profile) {
          navigate('/login')
        } else {
          setUser(profile)
        }
      })
      .catch((err: Error) => {
        setError(err.message)
      })
      .finally(() => {
        setLoading(false)
      })
  }, [navigate])

  const handleSignOut = async () => {
    setLoggingOut(true)
    try {
      await logoutUser()
      navigate('/login')
    } catch (err: unknown) {
      if (err instanceof Error) {
        setError(err.message)
      } else {
        setError('Logout failed')
      }
      setLoggingOut(false)
    }
  }

  if (loading) {
    return (
      <div className="container">
        <h1>Dashboard</h1>
        <div className="card">
          <p>Loading your account...</p>
        </div>
      </div>
    )
  }

  if (error && !user) {
    return (
      <div className="container">
        <h1>Dashboard</h1>
        <div className="card alert-error">
          <p>Error loading account: {error}</p>
          <button onClick={() => window.location.reload()} className="btn btn-secondary">
            Retry
          </button>
        </div>
      </div>
    )
  }

  if (!user) {
    return null
  }

  return (
    <div className="container">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h1>Dashboard</h1>
        <button
          onClick={handleSignOut}
          disabled={loggingOut}
          className="btn btn-secondary"
        >
          {loggingOut ? 'Signing out...' : 'Sign out'}
        </button>
      </div>

      <div className="card">
        <h2>Your Profile</h2>
        <div style={{ display: 'flex', gap: '1rem', alignItems: 'center', marginTop: '1rem' }}>
          {user.avatar_url && (
            <img
              src={user.avatar_url}
              alt="Profile avatar"
              style={{ width: '64px', height: '64px', borderRadius: '50%', objectFit: 'cover' }}
            />
          )}
          <div>
            <p style={{ margin: 0, fontWeight: 600, fontSize: '1.125rem' }}>
              {user.name || '(No name provided)'}
            </p>
            <p style={{ margin: '0.25rem 0 0 0', color: 'var(--text-muted)' }}>
              {user.email}
            </p>
          </div>
        </div>

        <div style={{ marginTop: '1.25rem', borderTop: '1px solid var(--border-color)', paddingTop: '1rem' }}>
          <p style={{ fontSize: '0.875rem', margin: 0 }}>
            <strong>User ID:</strong> <code>{user.id}</code>
          </p>
          {user.created_at && (
            <p style={{ fontSize: '0.875rem', margin: '0.25rem 0 0 0' }}>
              <strong>Member since:</strong> {new Date(user.created_at).toLocaleDateString()}
            </p>
          )}
        </div>
      </div>
    </div>
  )
}

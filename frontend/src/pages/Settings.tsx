import { useState, useEffect } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import {
  fetchMe,
  logoutUser,
  logoutAllUser,
  fetchIdentities,
  fetchSessions,
  revokeSession,
  UserProfile,
  UserIdentity,
  UserSession,
} from '../api'

export function Settings() {
  const navigate = useNavigate()
  const [loading, setLoading] = useState<boolean>(true)
  const [error, setError] = useState<string | null>(null)

  const [user, setUser] = useState<UserProfile | null>(null)
  const [identities, setIdentities] = useState<UserIdentity[]>([])
  const [sessions, setSessions] = useState<UserSession[]>([])
  const [actionInProgress, setActionInProgress] = useState<boolean>(false)

  const loadData = async () => {
    try {
      setLoading(true)
      setError(null)
      const currentUser = await fetchMe()
      if (!currentUser) {
        navigate('/login')
        return
      }
      setUser(currentUser)

      const [idents, sessList] = await Promise.all([
        fetchIdentities(),
        fetchSessions(),
      ])
      setIdentities(idents)
      setSessions(sessList)
    } catch (err: any) {
      setError(err.message || 'Failed to load settings')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadData()
  }, [navigate])

  const handleSignOutCurrent = async () => {
    const confirmed = window.confirm('Are you sure you want to sign out?')
    if (!confirmed) return

    try {
      setActionInProgress(true)
      await logoutUser()
      navigate('/login')
    } catch (err: any) {
      setError(err.message || 'Logout failed')
      setActionInProgress(false)
    }
  }

  const handleSignOutEverywhere = async () => {
    const confirmed = window.confirm(
      'Are you sure you want to sign out everywhere? All your active sessions on all devices will be revoked.'
    )
    if (!confirmed) return

    try {
      setActionInProgress(true)
      await logoutAllUser()
      navigate('/login')
    } catch (err: any) {
      setError(err.message || 'Logout everywhere failed')
      setActionInProgress(false)
    }
  }

  const handleRevokeSession = async (session: UserSession) => {
    const confirmed = window.confirm('Revoke this session?')
    if (!confirmed) return

    try {
      setActionInProgress(true)
      await revokeSession(session.id)
      if (session.is_current) {
        navigate('/login')
      } else {
        await loadData()
      }
    } catch (err: any) {
      setError(err.message || 'Failed to revoke session')
    } finally {
      setActionInProgress(false)
    }
  }

  const formatApproxDate = (dateStr: string | null) => {
    if (!dateStr) return 'N/A'
    return `about ${new Date(dateStr).toLocaleString()}`
  }

  return (
    <div className="container" style={{ maxWidth: '680px', margin: '0 auto' }}>
      {/* Top Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.5rem', flexWrap: 'wrap', gap: '0.5rem' }}>
        <div>
          <h1>Settings</h1>
          <p style={{ margin: 0, color: 'var(--text-muted)', fontSize: '0.9rem' }}>
            Account management and session security
          </p>
        </div>
        <div style={{ display: 'flex', gap: '0.5rem' }}>
          <Link to="/dashboard" className="btn btn-secondary" style={{ padding: '0.4rem 0.8rem', textDecoration: 'none' }}>
            Dashboard
          </Link>
          <Link to="/analytics" className="btn btn-secondary" style={{ padding: '0.4rem 0.8rem', textDecoration: 'none' }}>
            Analytics
          </Link>
        </div>
      </div>

      {/* Error state */}
      {error && (
        <div className="alert-error" style={{ padding: '0.75rem', marginBottom: '1rem', borderRadius: '4px' }}>
          {error}
        </div>
      )}

      {/* Loading state */}
      {loading && (
        <div className="card" style={{ textAlign: 'center', padding: '2rem', color: 'var(--text-muted)' }}>
          Loading account settings...
        </div>
      )}

      {!loading && user && (
        <>
          {/* Profile Card */}
          <div className="card" style={{ marginBottom: '1.5rem' }}>
            <h2>Profile</h2>
            <div style={{ display: 'flex', gap: '1rem', alignItems: 'center', marginTop: '1rem' }}>
              {user.avatar_url && (
                <img
                  src={user.avatar_url}
                  alt="Profile avatar"
                  style={{ width: '56px', height: '56px', borderRadius: '50%', objectFit: 'cover' }}
                />
              )}
              <div>
                <p style={{ margin: 0, fontWeight: 600 }}>{user.name || '(No name provided)'}</p>
                <p style={{ margin: '0.2rem 0', color: 'var(--text-muted)', fontSize: '0.9rem' }}>{user.email}</p>
                <p style={{ margin: 0, color: 'var(--text-muted)', fontSize: '0.8rem' }}>
                  Member since: {user.created_at ? new Date(user.created_at).toLocaleDateString() : 'N/A'}
                </p>
              </div>
            </div>
          </div>

          {/* Linked Sign-in Methods Card */}
          <div className="card" style={{ marginBottom: '1.5rem' }}>
            <h2>Linked Sign-in Methods</h2>
            {identities.length === 0 ? (
              <p style={{ color: 'var(--text-muted)', fontSize: '0.9rem' }}>No sign-in methods found.</p>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem', marginTop: '1rem' }}>
                {identities.map((ident, idx) => (
                  <div
                    key={idx}
                    style={{
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                      padding: '0.5rem',
                      border: '1px solid var(--border-color)',
                      borderRadius: '4px',
                      background: '#fff',
                    }}
                  >
                    <div>
                      <span style={{ fontWeight: 600, textTransform: 'capitalize' }}>{ident.provider}</span>
                      <span
                        style={{
                          marginLeft: '0.5rem',
                          fontSize: '0.75rem',
                          padding: '0.1rem 0.4rem',
                          borderRadius: '3px',
                          background: ident.email_verified ? 'rgba(25, 135, 84, 0.15)' : 'rgba(220, 53, 69, 0.15)',
                          color: ident.email_verified ? 'var(--status-ok)' : 'var(--status-error)',
                          fontWeight: 500,
                        }}
                      >
                        {ident.email_verified ? 'Verified' : 'Unverified'}
                      </span>
                    </div>
                    <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                      Linked: {ident.created_at ? new Date(ident.created_at).toLocaleDateString() : 'N/A'}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Active Sessions Card */}
          <div className="card" style={{ marginBottom: '1.5rem' }}>
            <h2>Active Sessions</h2>
            <p style={{ fontSize: '0.85rem', color: 'var(--text-muted)', marginTop: 0 }}>
              Device details are not collected or stored. Last-seen times are approximate (updated at most once every 5 minutes).
            </p>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem', marginTop: '1rem' }}>
              {sessions.map((sess) => (
                <div
                  key={sess.id}
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    padding: '0.75rem',
                    border: '1px solid var(--border-color)',
                    borderRadius: '4px',
                    background: sess.is_current ? 'rgba(13, 110, 253, 0.05)' : '#fff',
                  }}
                >
                  <div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                      <span style={{ fontSize: '0.85rem', fontWeight: 600 }}>
                        Session: {sess.id.slice(0, 8)}...
                      </span>
                      {sess.is_current && (
                        <span
                          style={{
                            fontSize: '0.75rem',
                            padding: '0.1rem 0.4rem',
                            borderRadius: '3px',
                            background: 'var(--button-bg)',
                            color: '#fff',
                            fontWeight: 600,
                          }}
                        >
                          Current Session
                        </span>
                      )}
                    </div>
                    <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginTop: '0.25rem' }}>
                      Created: {sess.created_at ? new Date(sess.created_at).toLocaleDateString() : 'N/A'} • Last seen: {formatApproxDate(sess.last_seen_at)}
                    </div>
                  </div>

                  <div>
                    {!sess.is_current && (
                      <button
                        onClick={() => handleRevokeSession(sess)}
                        disabled={actionInProgress}
                        style={{
                          padding: '0.25rem 0.6rem',
                          fontSize: '0.8rem',
                          color: '#dc3545',
                          border: '1px solid #dc3545',
                          background: '#fff',
                          borderRadius: '4px',
                          cursor: 'pointer',
                        }}
                      >
                        Revoke
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Account Actions */}
          <div className="card" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '1rem' }}>
            <div>
              <h2 style={{ margin: 0, fontSize: '1.1rem' }}>Sign Out Options</h2>
              <p style={{ margin: '0.2rem 0 0 0', color: 'var(--text-muted)', fontSize: '0.85rem' }}>
                End your session on this browser or across all connected devices.
              </p>
            </div>
            <div style={{ display: 'flex', gap: '0.5rem' }}>
              <button
                onClick={handleSignOutCurrent}
                disabled={actionInProgress}
                className="btn btn-secondary"
                style={{ padding: '0.4rem 0.8rem', fontSize: '0.85rem', cursor: 'pointer' }}
              >
                Sign out
              </button>
              <button
                onClick={handleSignOutEverywhere}
                disabled={actionInProgress}
                style={{
                  padding: '0.4rem 0.8rem',
                  fontSize: '0.85rem',
                  color: '#dc3545',
                  border: '1px solid #dc3545',
                  background: '#fff',
                  borderRadius: '4px',
                  cursor: 'pointer',
                  fontWeight: 600,
                }}
              >
                Sign out everywhere
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  )
}

import React, { useState, useEffect } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import {
  fetchMe,
  logoutUser,
  fetchLinks,
  createLink,
  updateLink,
  deleteLink,
  UserProfile,
  LinkItem,
} from '../api'

export function Dashboard() {
  const [loading, setLoading] = useState<boolean>(true)
  const [user, setUser] = useState<UserProfile | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loggingOut, setLoggingOut] = useState<boolean>(false)

  // Links state
  const [links, setLinks] = useState<LinkItem[]>([])
  const [linksLoading, setLinksLoading] = useState<boolean>(true)
  const [linksError, setLinksError] = useState<string | null>(null)

  // Create form state
  const [originalUrl, setOriginalUrl] = useState<string>('')
  const [customCode, setCustomCode] = useState<string>('')
  const [expiresAt, setExpiresAt] = useState<string>('')
  const [creating, setCreating] = useState<boolean>(false)
  const [createError, setCreateError] = useState<string | null>(null)
  const [copiedId, setCopiedId] = useState<number | null>(null)

  const navigate = useNavigate()

  useEffect(() => {
    fetchMe()
      .then((profile) => {
        if (!profile) {
          navigate('/login')
        } else {
          setUser(profile)
          loadLinks()
        }
      })
      .catch((err: Error) => {
        setError(err.message)
      })
      .finally(() => {
        setLoading(false)
      })
  }, [navigate])

  const loadLinks = async () => {
    setLinksLoading(true)
    setLinksError(null)
    try {
      const res = await fetchLinks(50, 0)
      setLinks(res.items)
    } catch (err: unknown) {
      if (err instanceof Error) {
        setLinksError(err.message)
      } else {
        setLinksError('Failed to load links')
      }
    } finally {
      setLinksLoading(false)
    }
  }

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

  const handleCreateLink = async (e: React.FormEvent) => {
    e.preventDefault()
    setCreateError(null)
    setCreating(true)

    try {
      const payload: { original_url: string; custom_code?: string; expires_at?: string } = {
        original_url: originalUrl.trim(),
      }
      if (customCode.trim()) {
        payload.custom_code = customCode.trim()
      }
      if (expiresAt.trim()) {
        payload.expires_at = new Date(expiresAt).toISOString()
      }

      const newLink = await createLink(payload)
      setLinks((prev) => [newLink, ...prev])
      setOriginalUrl('')
      setCustomCode('')
      setExpiresAt('')
    } catch (err: unknown) {
      if (err instanceof Error) {
        setCreateError(err.message)
      } else {
        setCreateError('Failed to create link')
      }
    } finally {
      setCreating(false)
    }
  }

  const handleToggleActive = async (link: LinkItem) => {
    try {
      const updated = await updateLink(link.id, { is_active: !link.is_active })
      setLinks((prev) => prev.map((l) => (l.id === link.id ? updated : l)))
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : 'Failed to update link')
    }
  }

  const handleDelete = async (linkId: number) => {
    const confirmed = window.confirm(
      'Are you sure you want to delete this short link? This short code will remain permanently reserved.'
    )
    if (!confirmed) return

    try {
      await deleteLink(linkId)
      setLinks((prev) => prev.filter((l) => l.id !== linkId))
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : 'Failed to delete link')
    }
  }

  const handleCopy = (link: LinkItem) => {
    navigator.clipboard.writeText(link.short_url)
    setCopiedId(link.id)
    setTimeout(() => {
      setCopiedId((current) => (current === link.id ? null : current))
    }, 2000)
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
        <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
          <Link
            to="/analytics"
            className="btn btn-secondary"
            style={{ padding: '0.4rem 0.8rem', textDecoration: 'none' }}
          >
            Analytics
          </Link>
          <button
            onClick={handleSignOut}
            disabled={loggingOut}
            className="btn btn-secondary"
          >
            {loggingOut ? 'Signing out...' : 'Sign out'}
          </button>
        </div>
      </div>

      <div className="card" style={{ marginBottom: '2rem' }}>
        <h2>Your Profile</h2>
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
            <p style={{ margin: '0.25rem 0 0 0', color: 'var(--text-muted)' }}>{user.email}</p>
          </div>
        </div>
      </div>

      {/* Create Link Card */}
      <div className="card" style={{ marginBottom: '2rem' }}>
        <h2>Create Short Link</h2>
        {createError && (
          <div className="alert-error" style={{ padding: '0.75rem', marginBottom: '1rem', borderRadius: '4px' }}>
            {createError}
          </div>
        )}
        <form onSubmit={handleCreateLink} style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          <div>
            <label style={{ display: 'block', fontWeight: 500, marginBottom: '0.25rem' }}>
              Destination URL *
            </label>
            <input
              type="url"
              required
              placeholder="https://example.com/very/long/url"
              value={originalUrl}
              onChange={(e) => setOriginalUrl(e.target.value)}
              style={{ width: '100%', padding: '0.5rem', borderRadius: '4px', border: '1px solid var(--border)' }}
            />
          </div>

          <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap' }}>
            <div style={{ flex: 1, minWidth: '200px' }}>
              <label style={{ display: 'block', fontWeight: 500, marginBottom: '0.25rem' }}>
                Custom Short Code (optional)
              </label>
              <input
                type="text"
                placeholder="my-custom-code"
                value={customCode}
                onChange={(e) => setCustomCode(e.target.value)}
                style={{ width: '100%', padding: '0.5rem', borderRadius: '4px', border: '1px solid var(--border)' }}
              />
            </div>

            <div style={{ flex: 1, minWidth: '200px' }}>
              <label style={{ display: 'block', fontWeight: 500, marginBottom: '0.25rem' }}>
                Expires At (optional)
              </label>
              <input
                type="datetime-local"
                value={expiresAt}
                onChange={(e) => setExpiresAt(e.target.value)}
                style={{ width: '100%', padding: '0.5rem', borderRadius: '4px', border: '1px solid var(--border)' }}
              />
            </div>
          </div>

          <div>
            <button type="submit" disabled={creating} className="btn btn-primary">
              {creating ? 'Creating...' : 'Shorten Link'}
            </button>
          </div>
        </form>
      </div>

      {/* Links List Card */}
      <div className="card">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
          <h2>Your Links</h2>
          <button onClick={loadLinks} disabled={linksLoading} className="btn btn-secondary">
            Refresh
          </button>
        </div>

        {linksLoading && <p>Loading links...</p>}
        {linksError && <p className="alert-error">Error loading links: {linksError}</p>}

        {!linksLoading && !linksError && links.length === 0 && (
          <p style={{ color: 'var(--text-muted)' }}>You have not created any short links yet.</p>
        )}

        {!linksLoading && !linksError && links.length > 0 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
            {links.map((link) => {
              const isExpired = link.expires_at ? new Date(link.expires_at) <= new Date() : false
              const statusLabel = isExpired ? 'Expired' : link.is_active ? 'Active' : 'Disabled'
              const statusColor = isExpired ? '#f59e0b' : link.is_active ? '#22c55e' : '#ef4444'

              return (
                <div
                  key={link.id}
                  style={{
                    padding: '1rem',
                    borderRadius: '6px',
                    border: '1px solid var(--border)',
                    background: 'var(--bg-card)',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '0.5rem',
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '0.5rem' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                      <a
                        href={link.short_url}
                        target="_blank"
                        rel="noreferrer"
                        style={{ fontWeight: 600, fontSize: '1.05rem', color: 'var(--accent)' }}
                      >
                        {link.short_url}
                      </a>
                      <button
                        onClick={() => handleCopy(link)}
                        className="btn btn-secondary"
                        style={{ padding: '0.2rem 0.5rem', fontSize: '0.8rem' }}
                      >
                        {copiedId === link.id ? 'Copied!' : 'Copy'}
                      </button>
                    </div>

                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                      <span
                        style={{
                          fontSize: '0.8rem',
                          fontWeight: 600,
                          padding: '0.2rem 0.5rem',
                          borderRadius: '4px',
                          background: `${statusColor}22`,
                          color: statusColor,
                          border: `1px solid ${statusColor}44`,
                        }}
                      >
                        {statusLabel}
                      </span>
                      <span style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>
                        {link.click_count} {link.click_count === 1 ? 'click' : 'clicks'}
                      </span>
                    </div>
                  </div>

                  <div style={{ fontSize: '0.875rem', color: 'var(--text-muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    Destination: {link.original_url}
                  </div>

                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '0.25rem', fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                    <span>Created: {new Date(link.created_at).toLocaleDateString()}</span>
                    <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                      <Link
                        to={`/analytics?link_id=${link.id}`}
                        className="btn btn-secondary"
                        style={{ padding: '0.2rem 0.5rem', fontSize: '0.8rem', textDecoration: 'none' }}
                      >
                        View analytics
                      </Link>
                      <button
                        onClick={() => handleToggleActive(link)}
                        className="btn btn-secondary"
                        style={{ padding: '0.2rem 0.5rem', fontSize: '0.8rem' }}
                      >
                        {link.is_active ? 'Disable' : 'Enable'}
                      </button>
                      <button
                        onClick={() => handleDelete(link.id)}
                        className="btn btn-secondary"
                        style={{ padding: '0.2rem 0.5rem', fontSize: '0.8rem', color: '#ef4444' }}
                      >
                        Delete
                      </button>
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}

import { useState, useEffect } from 'react'
import { Link, useSearchParams, useNavigate } from 'react-router-dom'

interface SummaryData {
  current_clicks: number
  previous_clicks: number
  percent_change: number | null
  resolved_start_date: string
  resolved_end_date: string
  tz: string
  link_id: number | null
}

interface TimeseriesItem {
  date: string
  click_count: number
}

interface TimeseriesData {
  items: TimeseriesItem[]
  resolved_start_date: string
  resolved_end_date: string
  tz: string
  link_id: number | null
}

interface TopLinkItem {
  id: number
  short_code: string
  short_url: string
  original_url: string
  click_count: number
}

interface BreakdownItem {
  name: string
  click_count: number
  percentage: number
}

interface BreakdownData {
  referrers: BreakdownItem[]
  devices: BreakdownItem[]
  total_clicks: number
  resolved_start_date: string
  resolved_end_date: string
  tz: string
  link_id: number | null
}

export function Analytics() {
  const [searchParams, setSearchParams] = useSearchParams()
  const navigate = useNavigate()

  const linkIdParam = searchParams.get('link_id')
  const [range, setRange] = useState<number>(30)
  const [showTableFallback, setShowTableFallback] = useState<boolean>(false)
  const [copiedId, setCopiedId] = useState<number | null>(null)

  const [loading, setLoading] = useState<boolean>(true)
  const [error, setError] = useState<string | null>(null)
  const [notFound, setNotFound] = useState<boolean>(false)

  const [summary, setSummary] = useState<SummaryData | null>(null)
  const [timeseries, setTimeseries] = useState<TimeseriesData | null>(null)
  const [topLinks, setTopLinks] = useState<TopLinkItem[]>([])
  const [breakdown, setBreakdown] = useState<BreakdownData | null>(null)

  const userTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'

  useEffect(() => {
    let isCancelled = false
    setLoading(true)
    setError(null)
    setNotFound(false)

    const queryBase = `range=${range}&tz=${encodeURIComponent(userTimezone)}`
    const linkQuery = linkIdParam ? `&link_id=${encodeURIComponent(linkIdParam)}` : ''

    async function fetchData() {
      try {
        const [sumRes, timeRes, topRes, brkRes] = await Promise.all([
          fetch(`/api/analytics/summary?${queryBase}${linkQuery}`, { credentials: 'include' }),
          fetch(`/api/analytics/timeseries?${queryBase}${linkQuery}`, { credentials: 'include' }),
          fetch(`/api/analytics/top-links?${queryBase}&limit=10`, { credentials: 'include' }),
          fetch(`/api/analytics/breakdown?${queryBase}${linkQuery}`, { credentials: 'include' }),
        ])

        if (sumRes.status === 401 || timeRes.status === 401) {
          navigate('/login')
          return
        }

        if (sumRes.status === 404 || timeRes.status === 404 || brkRes.status === 404) {
          if (!isCancelled) {
            setNotFound(true)
            setLoading(false)
          }
          return
        }

        if (!sumRes.ok || !timeRes.ok || !topRes.ok || !brkRes.ok) {
          throw new Error('Failed to load analytics data')
        }

        const sumJson = await sumRes.json()
        const timeJson = await timeRes.json()
        const topJson = await topRes.json()
        const brkJson = await brkRes.json()

        if (!isCancelled) {
          setSummary(sumJson)
          setTimeseries(timeJson)
          setTopLinks(topJson.items || [])
          setBreakdown(brkJson)
          setLoading(false)
        }
      } catch (err: any) {
        if (!isCancelled) {
          setError(err.message || 'An error occurred')
          setLoading(false)
        }
      }
    }

    fetchData()

    return () => {
      isCancelled = true
    }
  }, [range, linkIdParam, userTimezone, navigate])

  const handleCopy = (link: TopLinkItem) => {
    navigator.clipboard.writeText(link.short_url)
    setCopiedId(link.id)
    setTimeout(() => setCopiedId(null), 2000)
  }

  const handleResetLink = () => {
    searchParams.delete('link_id')
    setSearchParams(searchParams)
  }

  const formatGrowth = (pct: number | null): string => {
    if (pct === null) return 'N/A (No previous clicks)'
    if (pct > 0) return `+${pct}%`
    if (pct < 0) return `${pct}%`
    return '0.0%'
  }

  // Render SVG timeseries chart
  const renderChart = () => {
    if (!timeseries || timeseries.items.length === 0) return null

    const items = timeseries.items
    const maxClicks = Math.max(...items.map((i) => i.click_count), 1)
    const svgWidth = 600
    const svgHeight = 200
    const padX = 40
    const padY = 25
    const chartW = svgWidth - padX * 2
    const chartH = svgHeight - padY * 2

    const points = items.map((item, index) => {
      const x = padX + (index / (items.length - 1 || 1)) * chartW
      const y = padY + chartH - (item.click_count / maxClicks) * chartH
      return { x, y, item }
    })

    const pathData = points.reduce((acc, p, i) => `${acc} ${i === 0 ? 'M' : 'L'} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`, '')
    const areaData = `${pathData} L ${points[points.length - 1].x.toFixed(1)} ${(padY + chartH).toFixed(1)} L ${points[0].x.toFixed(1)} ${(padY + chartH).toFixed(1)} Z`

    return (
      <svg
        viewBox={`0 0 ${svgWidth} ${svgHeight}`}
        style={{ width: '100%', height: 'auto', background: '#ffffff', borderRadius: '4px', border: '1px solid var(--border-color)' }}
        aria-label="Click timeseries chart"
      >
        {/* Y-axis baseline */}
        <line x1={padX} y1={padY + chartH} x2={padX + chartW} y2={padY + chartH} stroke="#cbd5e1" strokeWidth="1" />
        {/* Y-axis top line */}
        <line x1={padX} y1={padY} x2={padX + chartW} y2={padY} stroke="#e2e8f0" strokeDasharray="3 3" />
        <text x={padX - 8} y={padY + 4} textAnchor="end" fontSize="10" fill="#64748b">
          {maxClicks}
        </text>
        <text x={padX - 8} y={padY + chartH + 3} textAnchor="end" fontSize="10" fill="#64748b">
          0
        </text>

        {/* Shaded Area */}
        <path d={areaData} fill="rgba(13, 110, 253, 0.12)" />

        {/* Stroke Line */}
        <path d={pathData} fill="none" stroke="var(--button-bg)" strokeWidth="2" />

        {/* Data points */}
        {points.map((p, idx) => (
          <circle
            key={idx}
            cx={p.x}
            cy={p.y}
            r={items.length <= 14 ? '4' : '2'}
            fill="var(--button-bg)"
          >
            <title>{`${p.item.date}: ${p.item.click_count} clicks`}</title>
          </circle>
        ))}

        {/* Date labels on X axis: first and last */}
        <text x={padX} y={svgHeight - 6} fontSize="10" fill="#64748b" textAnchor="start">
          {items[0].date}
        </text>
        <text x={padX + chartW} y={svgHeight - 6} fontSize="10" fill="#64748b" textAnchor="end">
          {items[items.length - 1].date}
        </text>
      </svg>
    )
  }

  return (
    <div className="container" style={{ maxWidth: '800px', margin: '0 auto' }}>
      {/* Top Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.5rem', flexWrap: 'wrap', gap: '0.5rem' }}>
        <div>
          <h1>Analytics</h1>
          <p style={{ margin: 0, color: 'var(--text-muted)', fontSize: '0.9rem' }}>
            Timezone: {userTimezone}
          </p>
        </div>
        <div style={{ display: 'flex', gap: '0.5rem' }}>
          <Link to="/dashboard" className="btn btn-secondary" style={{ padding: '0.4rem 0.8rem', textDecoration: 'none' }}>
            Dashboard
          </Link>
        </div>
      </div>

      {/* Controls: Range selector & Link Filter reset */}
      <div className="card" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '1rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <span style={{ fontWeight: 600, fontSize: '0.9rem' }}>Range:</span>
          {[7, 30, 90].map((d) => (
            <button
              key={d}
              onClick={() => setRange(d)}
              style={{
                padding: '0.3rem 0.75rem',
                borderRadius: '4px',
                border: '1px solid var(--border-color)',
                background: range === d ? 'var(--button-bg)' : '#ffffff',
                color: range === d ? '#ffffff' : 'var(--text-color)',
                cursor: 'pointer',
                fontWeight: range === d ? 600 : 400,
              }}
            >
              {d} days
            </button>
          ))}
        </div>

        {linkIdParam && (
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <span style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>
              Filtering by Link ID: <strong>{linkIdParam}</strong>
            </span>
            <button
              onClick={handleResetLink}
              style={{
                padding: '0.25rem 0.5rem',
                fontSize: '0.8rem',
                border: '1px solid var(--border-color)',
                background: '#ffffff',
                cursor: 'pointer',
                borderRadius: '4px',
              }}
            >
              All links
            </button>
          </div>
        )}
      </div>

      {/* Not Found State */}
      {notFound && (
        <div className="card" style={{ textAlign: 'center', padding: '2rem' }}>
          <h2>Link Not Found</h2>
          <p style={{ color: 'var(--text-muted)' }}>
            The link you requested does not exist, has been deleted, or is not owned by your account.
          </p>
          <button onClick={handleResetLink} className="btn" style={{ background: 'var(--button-bg)', color: '#fff', border: 'none', padding: '0.5rem 1rem', borderRadius: '4px', cursor: 'pointer' }}>
            Reset to All Links
          </button>
        </div>
      )}

      {/* Error State */}
      {error && !notFound && (
        <div className="alert-error" style={{ padding: '1rem', marginBottom: '1rem', borderRadius: '4px' }}>
          {error}
        </div>
      )}

      {/* Loading State */}
      {loading && (
        <div className="card" style={{ textAlign: 'center', padding: '2rem', color: 'var(--text-muted)' }}>
          Loading analytics...
        </div>
      )}

      {/* Main Content */}
      {!loading && !notFound && summary && (
        <>
          {/* Summary Metric Cards */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '1rem', marginBottom: '1.5rem' }}>
            <div className="card" style={{ margin: 0 }}>
              <div style={{ fontSize: '0.85rem', color: 'var(--text-muted)', marginBottom: '0.25rem' }}>
                Total Clicks ({summary.resolved_start_date} to {summary.resolved_end_date})
              </div>
              <div style={{ fontSize: '2rem', fontWeight: 700 }}>
                {summary.current_clicks}
              </div>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '0.25rem' }}>
                includes today so far
              </div>
            </div>

            <div className="card" style={{ margin: 0 }}>
              <div style={{ fontSize: '0.85rem', color: 'var(--text-muted)', marginBottom: '0.25rem' }}>
                Previous Period ({range} days prior)
              </div>
              <div style={{ fontSize: '2rem', fontWeight: 700 }}>
                {summary.previous_clicks}
              </div>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '0.25rem' }}>
                comparison benchmark
              </div>
            </div>

            <div className="card" style={{ margin: 0 }}>
              <div style={{ fontSize: '0.85rem', color: 'var(--text-muted)', marginBottom: '0.25rem' }}>
                Period Growth
              </div>
              <div style={{ fontSize: '1.75rem', fontWeight: 700 }}>
                {formatGrowth(summary.percent_change)}
              </div>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '0.25rem' }}>
                {summary.percent_change !== null
                  ? summary.percent_change >= 0 ? '+ increased clicks' : '- decreased clicks'
                  : 'baseline not established'}
              </div>
            </div>
          </div>

          {/* Timeseries Section */}
          <div className="card" style={{ marginBottom: '1.5rem' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
              <h2>Clicks Over Time</h2>
              <button
                onClick={() => setShowTableFallback(!showTableFallback)}
                style={{
                  background: 'transparent',
                  border: '1px solid var(--border-color)',
                  padding: '0.25rem 0.5rem',
                  fontSize: '0.8rem',
                  borderRadius: '4px',
                  cursor: 'pointer',
                }}
              >
                {showTableFallback ? 'Show Chart' : 'Show Data Table'}
              </button>
            </div>

            {summary.current_clicks === 0 ? (
              <div style={{ textAlign: 'center', padding: '2rem', color: 'var(--text-muted)' }}>
                No clicks recorded for this period yet.
              </div>
            ) : showTableFallback ? (
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.9rem' }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid var(--border-color)', textAlign: 'left' }}>
                    <th style={{ padding: '0.5rem' }}>Date</th>
                    <th style={{ padding: '0.5rem', textAlign: 'right' }}>Clicks</th>
                  </tr>
                </thead>
                <tbody>
                  {timeseries?.items.map((it) => (
                    <tr key={it.date} style={{ borderBottom: '1px solid var(--border-color)' }}>
                      <td style={{ padding: '0.5rem' }}>{it.date}</td>
                      <td style={{ padding: '0.5rem', textAlign: 'right', fontWeight: 600 }}>{it.click_count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              renderChart()
            )}
          </div>

          {/* Top Links Section (shown in All Links view) */}
          {!linkIdParam && (
            <div className="card" style={{ marginBottom: '1.5rem' }}>
              <h2>Top Links</h2>
              {topLinks.length === 0 ? (
                <div style={{ textAlign: 'center', padding: '1.5rem', color: 'var(--text-muted)' }}>
                  No link clicks in this period.
                </div>
              ) : (
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.85rem' }}>
                  <thead>
                    <tr style={{ borderBottom: '1px solid var(--border-color)', textAlign: 'left' }}>
                      <th style={{ padding: '0.5rem' }}>Short Link</th>
                      <th style={{ padding: '0.5rem' }}>Destination</th>
                      <th style={{ padding: '0.5rem', textAlign: 'right' }}>Clicks</th>
                      <th style={{ padding: '0.5rem', textAlign: 'right' }}>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {topLinks.map((tl) => (
                      <tr key={tl.id} style={{ borderBottom: '1px solid var(--border-color)' }}>
                        <td style={{ padding: '0.5rem', fontWeight: 600 }}>
                          <a href={tl.short_url} target="_blank" rel="noreferrer">
                            {tl.short_code}
                          </a>
                        </td>
                        <td style={{ padding: '0.5rem', maxWidth: '250px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                          {tl.original_url}
                        </td>
                        <td style={{ padding: '0.5rem', textAlign: 'right', fontWeight: 600 }}>
                          {tl.click_count}
                        </td>
                        <td style={{ padding: '0.5rem', textAlign: 'right' }}>
                          <button
                            onClick={() => handleCopy(tl)}
                            style={{
                              marginRight: '0.4rem',
                              padding: '0.2rem 0.4rem',
                              fontSize: '0.75rem',
                              border: '1px solid var(--border-color)',
                              background: '#fff',
                              cursor: 'pointer',
                              borderRadius: '3px',
                            }}
                          >
                            {copiedId === tl.id ? 'Copied' : 'Copy'}
                          </button>
                          <Link
                            to={`/analytics?link_id=${tl.id}`}
                            style={{
                              padding: '0.2rem 0.4rem',
                              fontSize: '0.75rem',
                              border: '1px solid var(--border-color)',
                              background: 'var(--card-bg)',
                              borderRadius: '3px',
                              textDecoration: 'none',
                              color: 'var(--text-color)',
                            }}
                          >
                            Filter
                          </Link>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}

          {/* Breakdowns Grid */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: '1rem' }}>
            {/* Referrers Card */}
            <div className="card">
              <h2>Top Referrers</h2>
              {!breakdown || breakdown.referrers.length === 0 ? (
                <p style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>No referrer data.</p>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                  {breakdown.referrers.map((r, i) => (
                    <div key={i} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '0.85rem' }}>
                      <span style={{ fontWeight: 500 }}>{r.name}</span>
                      <span style={{ color: 'var(--text-muted)' }}>
                        {r.click_count} ({r.percentage}%)
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Devices Card */}
            <div className="card">
              <h2>Device Types</h2>
              {!breakdown || breakdown.devices.length === 0 ? (
                <p style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>No device data.</p>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                  {breakdown.devices.map((d, i) => (
                    <div key={i} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '0.85rem' }}>
                      <span style={{ textTransform: 'capitalize', fontWeight: 500 }}>{d.name}</span>
                      <span style={{ color: 'var(--text-muted)' }}>
                        {d.click_count} ({d.percentage}%)
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  )
}

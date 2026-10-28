import { useSearchParams, Link } from 'react-router-dom'
import { getAuthErrorMessage } from '../api'

export function Login() {
  const [searchParams] = useSearchParams()
  const errorCode = searchParams.get('error')
  const errorMessage = getAuthErrorMessage(errorCode)

  return (
    <div className="container">
      <h1>Log In</h1>
      <p>Welcome back to LinkSphere. Sign in with your OAuth provider.</p>

      {errorMessage && (
        <div className="card alert-error">
          <strong>Authentication Notice:</strong> {errorMessage}
        </div>
      )}

      <div className="card">
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
          <a
            href="/api/auth/google/login?next=/dashboard"
            className="btn btn-oauth"
          >
            Continue with Google
          </a>
          <a
            href="/api/auth/github/login?next=/dashboard"
            className="btn btn-oauth"
          >
            Continue with GitHub
          </a>
        </div>
      </div>

      <p style={{ marginTop: '1rem', fontSize: '0.875rem' }}>
        Don't have an account yet? <Link to="/signup">Create an account</Link>
      </p>
    </div>
  )
}

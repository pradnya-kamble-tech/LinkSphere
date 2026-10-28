import { Link } from 'react-router-dom'

export function Signup() {
  return (
    <div className="container">
      <h1>Create an Account</h1>
      <p>Start shortening URLs and tracking real click analytics today.</p>

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
        Already have an account? <Link to="/login">Log in here</Link>
      </p>
    </div>
  )
}

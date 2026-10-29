export interface UserProfile {
  id: string
  email: string
  name: string | null
  avatar_url: string | null
  created_at: string | null
}

export const AUTH_ERROR_MESSAGES: Record<string, string> = {
  access_denied: 'Sign-in was cancelled or access was denied.',
  invalid_state: 'Authentication session expired or security verification failed. Please try again.',
  invalid_nonce: 'Security token verification failed. Please try again.',
  email_not_verified: 'Your email address is not verified with the provider. Please verify your email first.',
  no_verified_email: 'Your GitHub account does not have a primary, verified email address.',
  provider_error: 'Unable to communicate with the OAuth provider. Please try again.',
  unknown: 'An unexpected error occurred during authentication. Please try again.',
}

export function getAuthErrorMessage(code: string | null): string | null {
  if (!code) return null
  return AUTH_ERROR_MESSAGES[code] || 'Authentication failed. Please try again.'
}

export async function fetchMe(): Promise<UserProfile | null> {
  const resp = await fetch('/api/me', {
    credentials: 'include',
  })
  if (resp.status === 401) {
    return null
  }
  if (!resp.ok) {
    throw new Error(`Failed to fetch profile: HTTP ${resp.status}`)
  }
  return resp.json()
}

export async function logoutUser(): Promise<void> {
  const resp = await fetch('/api/auth/logout', {
    method: 'POST',
    credentials: 'include',
    headers: {
      'Origin': window.location.origin,
    },
  })
  if (!resp.ok && resp.status !== 401) {
    throw new Error(`Logout failed: HTTP ${resp.status}`)
  }
}

export interface LinkItem {
  id: number
  short_code: string
  short_url: string
  original_url: string
  is_active: boolean
  expires_at: string | null
  created_at: string
  click_count: number
}

export interface LinkListResponse {
  items: LinkItem[]
  total: number
  limit: number
  offset: number
}

export async function fetchLinks(limit = 50, offset = 0): Promise<LinkListResponse> {
  const resp = await fetch(`/api/links?limit=${limit}&offset=${offset}`, {
    credentials: 'include',
  })
  if (!resp.ok) {
    throw new Error(`Failed to load links: HTTP ${resp.status}`)
  }
  return resp.json()
}

export async function createLink(data: {
  original_url: string
  custom_code?: string
  expires_at?: string
}): Promise<LinkItem> {
  const resp = await fetch('/api/links', {
    method: 'POST',
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      'Origin': window.location.origin,
    },
    body: JSON.stringify(data),
  })
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}))
    const msg = typeof err.detail === 'string' ? err.detail : Array.isArray(err.detail) ? err.detail[0]?.msg : null
    throw new Error(msg || `Failed to create link: HTTP ${resp.status}`)
  }
  return resp.json()
}

export async function updateLink(
  id: number,
  data: {
    is_active?: boolean
    expires_at?: string
  }
): Promise<LinkItem> {
  const resp = await fetch(`/api/links/${id}`, {
    method: 'PATCH',
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      'Origin': window.location.origin,
    },
    body: JSON.stringify(data),
  })
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}))
    const msg = typeof err.detail === 'string' ? err.detail : null
    throw new Error(msg || `Failed to update link: HTTP ${resp.status}`)
  }
  return resp.json()
}

export async function deleteLink(id: number): Promise<void> {
  const resp = await fetch(`/api/links/${id}`, {
    method: 'DELETE',
    credentials: 'include',
    headers: {
      'Origin': window.location.origin,
    },
  })
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}))
    const msg = typeof err.detail === 'string' ? err.detail : null
    throw new Error(msg || `Failed to delete link: HTTP ${resp.status}`)
  }
}

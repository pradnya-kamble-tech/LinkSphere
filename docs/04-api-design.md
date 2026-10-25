# LinkSphere - API Design

## 1. API Convention

Base path: /api/v1

The API uses HTTP methods and JSON request/response bodies.
The public redirect endpoint is /{short_code}.

## 2. Authentication

### POST /api/v1/auth/register

Purpose: Create a user account.

Example request:
{
  "email": "user@example.com",
  "password": "a-strong-password"
}

Expected success: 201 Created.

The response must never include the password or password hash.

### POST /api/v1/auth/login

Purpose: Authenticate an existing user.

Example request:
{
  "email": "user@example.com",
  "password": "a-strong-password"
}

Expected success: 200 OK.

Authentication tokens or secure session details will be returned
according to the authentication approach implemented later.

## 3. Create a Short Link

### POST /api/v1/links

Access: Authenticated users only.

Example request:
{
  "original_url": "https://example.com/articles/system-design",
  "custom_alias": null,
  "expires_at": null
}

The authenticated user's identity determines ownership.
The client must not be allowed to choose another user's ID.

Expected success: 201 Created.

Example response:
{
  "id": "generated-link-uuid",
  "short_code": "aB12cd",
  "original_url": "https://example.com/articles/system-design",
  "is_active": true,
  "expires_at": null
}

The final short URL will be built using the configured public base URL.

## 4. List Owned Links

### GET /api/v1/links

Access: Authenticated users only.

Returns links belonging to the authenticated user.
Pagination will be added to avoid returning unlimited records.

Expected success: 200 OK.

## 5. Get One Link

### GET /api/v1/links/{id}

Access: Authenticated users only.

Returns details for a link the authenticated user is authorized to view.

Expected success: 200 OK.

Unknown links return 404 Not Found.
Unauthorized access must not reveal another user's private link details.

## 6. Deactivate a Link

### DELETE /api/v1/links/{id}

Access: Authenticated users only.

Deactivates a link without permanently deleting its history.

Expected success: 204 No Content.

The deactivated short URL must no longer redirect to its destination.

## 7. Link Analytics

### GET /api/v1/links/{id}/analytics

Access: Authenticated users only.

Returns click counts and time-based summaries for a link the user owns.

Expected success: 200 OK.

Only authorized owners or permitted administrators may view analytics.

## 8. Public Redirect

### GET /{short_code}

Access: Public.

Behavior:
1. Find the link by short_code.
2. Return 404 if the code does not exist.
3. Reject inactive or expired links.
4. Record the click event.
5. Return HTTP 302 with the destination in the Location header.

A redirect response is not a normal JSON response.
The browser follows the Location header to navigate to the destination.

## 9. Error Handling

- 400 Bad Request: Invalid request data.
- 401 Unauthorized: Authentication is required or invalid.
- 403 Forbidden: The authenticated user lacks permission.
- 404 Not Found: The requested resource does not exist.
- 409 Conflict: A requested email or custom alias already exists.
- 422 Unprocessable Entity: Request validation failed.
- 429 Too Many Requests: A rate limit has been exceeded.
- 500 Internal Server Error: Unexpected server failure.

The implementation will use consistent, safe error response formats.

## 10. Security Rules

- Validate destination URLs and allow only HTTP and HTTPS schemes.
- Hash passwords with a suitable password-hashing algorithm.
- Protect private endpoints with authentication.
- Enforce link ownership on every private link operation.
- Never trust a user ID supplied by the client for authorization.
- Keep secrets out of source control.
- Apply rate limits to sensitive endpoints.
- Prevent open-redirect abuse by redirecting only to stored, validated destinations.

## 11. API Versioning

The /api/v1 prefix identifies the initial API version.
This makes future changes easier to manage without unexpectedly
breaking existing clients.

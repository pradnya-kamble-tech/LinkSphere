# LinkSphere — Database Design

## 1. Database

PostgreSQL is the initial source of truth for persistent application data.

## 2. Table: users

| Column | Type | Constraints | Purpose |
|---|---|---|---|
| id | UUID | Primary key | Unique account identifier |
| email | VARCHAR(255) | Not null, unique | Login email |
| password_hash | VARCHAR(255) | Not null | Hashed password |
| created_at | TIMESTAMPTZ | Not null | Account creation timestamp |

Passwords must never be stored in plaintext.

## 3. Table: links

| Column | Type | Constraints | Purpose |
|---|---|---|---|
| id | UUID | Primary key | Unique link identifier |
| user_id | UUID | Foreign key to users.id, not null | Link owner |
| short_code | VARCHAR(32) | Not null, unique | Short URL identifier |
| original_url | TEXT | Not null | Destination URL |
| created_at | TIMESTAMPTZ | Not null | Creation timestamp |
| expires_at | TIMESTAMPTZ | Nullable | Optional expiration |
| is_active | BOOLEAN | Not null, default true | Link status |

The short_code unique constraint prevents two links from using
the same code. PostgreSQL is the final authority for uniqueness.

## 4. Table: click_events

| Column | Type | Constraints | Purpose |
|---|---|---|---|
| id | UUID | Primary key | Unique click-event identifier |
| link_id | UUID | Foreign key to links.id, not null | Visited link |
| clicked_at | TIMESTAMPTZ | Not null | Visit timestamp |

We will add indexes to support common analytics queries.

We will avoid collecting IP addresses or other identifying visitor
metadata by default.

## 5. Relationships

- One user can own many links.
- Each link belongs to one user.
- One link can have many click events.
- Each click event refers to one link.

## 6. Initial Indexes

- Unique index on users.email.
- Unique index on links.short_code.
- Index on links.user_id for owner-specific link lists.
- Index on click_events.link_id and clicked_at for analytics queries.

Unique constraints create supporting indexes automatically where
appropriate. We will avoid adding redundant indexes.

## 7. Important Rules

- A user may manage only their own links unless an authorized
  administrator action applies.
- Short codes must be unique.
- Expired or inactive links must not redirect.
- Click events must reference existing links.
- Timestamps should use timezone-aware database types.
- Database migrations will track schema changes.

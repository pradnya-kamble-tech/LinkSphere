# LinkSphere - High-Level Architecture

## 1. Architecture Style

LinkSphere will start as a modular monolith.
The frontend and backend will be separate applications.
The backend will contain organized modules within one application.
We will avoid microservices until there is a clear reason to introduce them.

## 2. Main Components

### Frontend - React + TypeScript
- Display registration and login pages.
- Allow users to create and manage short links.
- Display click analytics.
- Send API requests to the backend.
- Display loading states and errors.

### Backend - Python + FastAPI
- Validate incoming requests.
- Register and authenticate users.
- Enforce user permissions.
- Generate unique short codes.
- Create and deactivate links.
- Redirect visitors to original URLs.
- Record clicks and provide analytics.

### Database - PostgreSQL
- Store user accounts.
- Store original URLs and short codes.
- Store link ownership and expiration.
- Store click events.
- Enforce data integrity with constraints and indexes.

## 3. Architecture Diagram

`mermaid
flowchart TD
    U[Browser and Visitor] --> F[React Frontend]
    F -->|API requests| B[FastAPI Backend]
    U -->|Open short link| B
    B --> A[Authentication and Permissions]
    B --> L[Link Management and Redirects]
    B --> C[Click Analytics]
    A --> D[(PostgreSQL)]
    L --> D
    C --> D

>>
>>
## 4. Link Creation Flow
1. A registered user enters a destination URL.
2. The frontend sends an authenticated request to the backend.
3. The backend validates the URL.
4. The backend generates a short code or checks a custom alias.
5. PostgreSQL stores the link and its owner.
6. The backend returns the short URL.
7. The frontend displays the result.

## 5. Redirect Flow
1. A visitor opens a short URL.
2. The backend looks up the short code.
3. It checks whether the link exists, is active, and has not expired.
4. The backend records a click event.
5. It returns HTTP 302 with a Location header containing the destination.
6. The browser navigates to the destination.

## 6. Backend Modules
- auth: registration and login.
- links: link creation and management.
- redirects: short-code lookup and redirects.
- analytics: click recording and reporting.
- admin: platform statistics and abuse management.

## 7. Initial Data Model
- users: account identity and password hash.
- links: short code, destination, owner, timestamps, and status.
- click_events: link reference and click timestamp.

## 8. Design Decisions
- PostgreSQL is the source of truth.
- Database constraints enforce short-code uniqueness.
- Private operations require authentication and ownership checks.
- Public redirects do not require login.
- Passwords are hashed, never stored in plaintext.
- We will measure performance before adding caching.
- Redis and asynchronous click processing are future improvements.

## 9. Request Paths
Create a link: Browser -> Frontend -> Backend -> PostgreSQL -> Frontend
Open a short link: Browser -> Backend -> PostgreSQL -> Backend -> Browser -> Destination

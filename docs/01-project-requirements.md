# LinkSphere — Project Requirements

## 1. Problem Statement

Long URLs can be difficult to share and manage. LinkSphere is a web
application that creates short, shareable links, redirects visitors
to the original destinations, and provides link owners with click
analytics.

## 2. Project Goals

- Build a working URL-shortening application.
- Learn System Design through practical implementation.
- Provide secure user accounts and private link management.
- Record link activity and display useful analytics.
- Deploy the application publicly.
- Measure performance and evolve the architecture responsibly.

## 3. User Roles

### Visitor
- Open a valid short URL without registering.
- Be redirected to the original destination.

### Registered User
- Register and log in.
- Create short URLs.
- Request a custom alias if it is available.
- View, copy, and deactivate their own links.
- View analytics for their links.

### Administrator
- Review platform-level statistics.
- Review reported or suspicious links.
- Deactivate links that violate platform rules.

## 4. Functional Requirements

FR-01: Users can register and log in securely.
FR-02: Authenticated users can create short URLs.
FR-03: The system generates unique short codes.
FR-04: Users can request available custom aliases.
FR-05: Short URLs redirect to their original destinations.
FR-06: The system records click events.
FR-07: Users can view and manage their own links.
FR-08: Users can view analytics for their links.
FR-09: Expired or deactivated links cannot redirect.
FR-10: The system validates URLs and handles errors.
FR-11: Administrators can review and deactivate abusive links.

## 5. Non-Functional Requirements

- Security: Hash passwords and protect private endpoints.
- Reliability: Enforce unique short codes in the database.
- Performance: Measure redirect latency and database lookup time.
- Maintainability: Keep application modules clearly separated.
- Testability: Add automated tests for core behavior.
- Scalability: Design for future caching and multiple backend instances.
- Portability: Use Docker for reproducible local development.
- Deployment: Provide a publicly accessible application.

## 6. Initial Technology Stack

Frontend: React + TypeScript
Backend: Python + FastAPI
Database: PostgreSQL
Testing: Pytest and frontend tests
Containerization: Docker and Docker Compose
Version Control: Git and GitHub

## 7. Initial Scope

The first version includes authentication, URL creation, redirects,
link management, click analytics, validation, and deployment.

Redis, asynchronous event queues, load balancing, and multiple
backend instances are planned as later learning milestones.

## 8. Success Criteria

- Users can create and open short links successfully.
- Short codes remain unique.
- Link data persists in PostgreSQL.
- Users cannot manage another user's private links.
- Click analytics reflect recorded events.
- Invalid, expired, and deactivated links are handled correctly.
- The deployed frontend and backend work together.
- Automated tests cover critical application behavior.

## 9. Important Design Decisions

- Start with a modular monolith rather than microservices.
- Use database constraints to enforce uniqueness.
- Keep secrets out of source control.
- Do not claim production-scale capacity without measurements.
- Document architectural changes and their trade-offs.

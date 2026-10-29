# LinkSphere v2

LinkSphere is a URL shortener featuring OAuth authentication (Google & GitHub with PKCE and state validation), user link management, reserved routing protections, fast 302 redirects, and background click event recording.

---

## Tech Stack

- **Backend**:
  - Python 3.11+
  - FastAPI (ASGI)
  - SQLAlchemy 2.0 + Alembic (PostgreSQL migrations)
  - psycopg 3 (native PostgreSQL driver)
  - Authlib (OAuth 2.0 with PKCE and OpenID Connect validation)
  - Pydantic v2
- **Frontend**:
  - React 18 + TypeScript
  - Vite
  - Tailwind CSS
  - React Router v6
- **Database**:
  - PostgreSQL 16
- **Testing**:
  - pytest, anyio, respx, httpx

---

## Project Structure

```text
LinkSphere_v2/
├── backend/
│   ├── alembic/              # Database migration versions
│   ├── app/
│   │   ├── analytics/        # Click logging and models
│   │   ├── auth/             # Session auth, cookies, OAuth (Google/GitHub)
│   │   ├── core/             # DB config, security, settings
│   │   ├── links/            # Link CRUD, slug generation, validation
│   │   ├── redirect/         # High-speed 302 redirect route
│   │   └── users/            # User model and management
│   ├── tests/                # Automated pytest suite & load verifiers
│   └── requirements.txt
├── frontend/
│   ├── src/                  # React components & pages
│   └── package.json
├── docker-compose.yml        # PostgreSQL 16 container definition
└── .env.example              # Sample environment configuration
```

---

## Setup & Running Locally

### 1. Prerequisites
- Docker Desktop
- Python 3.11+
- Node.js 18+

### 2. Environment Configuration
Copy `.env.example` to `.env`:
```powershell
Copy-Item .env.example .env
```
Ensure all required environment variables are filled in `.env` (OAuth credentials, session secrets). The local PostgreSQL service maps to port `5434`.

### 3. Start PostgreSQL
```powershell
docker compose up -d
```

### 4. Run Migrations & Start Backend
From the `backend/` directory:
```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --host localhost --port 8001 --reload
```

- API Docs: `http://localhost:8001/docs`
- Health check: `http://localhost:8001/health`

### 5. Start Frontend
From the `frontend/` directory:
```powershell
cd frontend
npm install
npm run dev
```

- Web App: `http://localhost:5173/`

---

## Testing

All tests run against a dedicated, isolated test database named `linksphere_test` (never the dev database).

### Run Test Suite
```powershell
cd backend
pytest -v
```

### Run Real-Server Click Verification
To verify exact click recording under concurrency against a running server:
```powershell
python backend/tests/load/verify_real_server_clicks.py
```

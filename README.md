# LinkSphere

URL shortener with user accounts, link management, redirects, and real click analytics.

## Phase 1: Foundation

### Prerequisites
- Docker Desktop running
- Python 3.11+
- Node.js 18+

### Setup and Running

#### 1. Environment Configuration
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```
*(On Windows PowerShell: `Copy-Item .env.example .env`)*

Configure environment variables if needed. The default mapped PostgreSQL port is `5434`.

#### 2. Start PostgreSQL
From the repository root:
```bash
docker compose up -d
```

#### 3. Backend Setup & Run
From inside the `backend/` directory:
```bash
cd backend
python -m venv .venv

# On Windows:
.venv\Scripts\activate
# On macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload --port 8001
```

*(Note: Port 8001 is used if port 8000 is occupied by an existing process. Vite dev server proxy is configured to target port 8001.)*

#### 4. Frontend Setup & Run
From inside the `frontend/` directory:
```bash
cd frontend
npm install
npm run dev
```

#### 5. Verify Health Check
- Open your browser to the URL displayed by Vite (e.g. `http://localhost:5173` or `http://localhost:5174`) to view the live health status.
- Alternatively, check the backend directly:
```bash
curl http://localhost:8001/health
```

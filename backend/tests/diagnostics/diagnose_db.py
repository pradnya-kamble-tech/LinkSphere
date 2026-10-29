import os
import sys
import time

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
import app.users.models
import app.auth.models
import app.links.models
import app.analytics.models
from app.users.models import User
from app.auth.service import create_user_session
from app.core.security import hash_session_token

TEST_DB_URL = "postgresql+psycopg://linksphere_user:linksphere_dev_password@localhost:5434/linksphere_test"
engine = create_engine(TEST_DB_URL)
SessionLocal = sessionmaker(bind=engine)
db = SessionLocal()

# 1. Check max_connections and superuser_reserved_connections
max_conn = db.execute(text("SHOW max_connections;")).scalar()
super_conn = db.execute(text("SHOW superuser_reserved_connections;")).scalar()
print(f"PostgreSQL max_connections: {max_conn}")
print(f"PostgreSQL superuser_reserved_connections: {super_conn}")

# 2. Ensure test user and session exist
user = db.query(User).filter_by(email="loadtest_valid@example.com").first()
if not user:
    user = User(email="loadtest_valid@example.com", name="Load User")
    db.add(user)
    db.commit()

token, session = create_user_session(db, user.id)
token_hash = session.token_hash

# 3. EXPLAIN (ANALYZE, BUFFERS) for session lookup
query_explain = text("""
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM sessions
WHERE token_hash = :token_hash AND revoked_at IS NULL;
""")

result = db.execute(query_explain, {"token_hash": token_hash}).fetchall()
print("\n--- EXPLAIN (ANALYZE, BUFFERS) for Session Lookup ---")
for row in result:
    print(row[0])

# 4. EXPLAIN (ANALYZE, BUFFERS) for user lookup by PK
user_explain = text("""
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM users
WHERE id = :user_id;
""")
user_res = db.execute(user_explain, {"user_id": user.id}).fetchall()
print("\n--- EXPLAIN (ANALYZE, BUFFERS) for User Lookup by PK ---")
for row in user_res:
    print(row[0])

db.close()

import uuid
from datetime import datetime, timezone, timedelta
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError, DataError
from alembic import command

from app.users.models import User
from app.auth.models import AuthIdentity, Session
from app.links.models import Link
from app.analytics.models import ClickEvent


def test_schema_columns_and_no_ip_address(test_engine):
    """Verify table structures, column definitions, and ensure no IP column exists."""
    inspector = inspect(test_engine)

    # 1. Verify click_events columns and NO IP column
    click_columns = {col["name"]: col for col in inspector.get_columns("click_events")}
    assert "id" in click_columns
    assert "link_id" in click_columns
    assert "clicked_at" in click_columns
    assert "referrer" in click_columns
    assert "device_type" in click_columns
    assert "country" in click_columns

    # Explicit check: No IP address column of any kind
    for col_name in click_columns:
        assert "ip" not in col_name.lower(), f"Forbidden IP column detected: {col_name}"

    # 2. Verify users columns
    user_columns = {col["name"]: col for col in inspector.get_columns("users")}
    expected_user_cols = {"id", "email", "name", "avatar_url", "created_at", "updated_at"}
    assert set(user_columns.keys()) == expected_user_cols

    # 3. Verify auth_identities columns
    ident_columns = {col["name"]: col for col in inspector.get_columns("auth_identities")}
    expected_ident_cols = {"id", "user_id", "provider", "provider_user_id", "email_verified", "created_at"}
    assert set(ident_columns.keys()) == expected_ident_cols

    # 4. Verify sessions columns
    session_columns = {col["name"]: col for col in inspector.get_columns("sessions")}
    expected_session_cols = {"id", "user_id", "token_hash", "created_at", "expires_at", "revoked_at", "last_seen_at"}
    assert set(session_columns.keys()) == expected_session_cols

    # 5. Verify links columns
    link_columns = {col["name"]: col for col in inspector.get_columns("links")}
    expected_link_cols = {"id", "user_id", "short_code", "original_url", "is_active", "expires_at", "created_at", "deleted_at"}
    assert set(link_columns.keys()) == expected_link_cols


def test_entity_creation_and_primary_key_types(db):
    """Verify entity creation and correct PK types (UUID for users/sessions/identities, BIGINT for links/events)."""
    # 1. User
    user = User(
        email="testuser@example.com",
        name="Test User",
        avatar_url="https://example.com/avatar.png"
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    assert isinstance(user.id, uuid.UUID)
    assert user.created_at.tzinfo is not None

    # 2. AuthIdentity
    identity = AuthIdentity(
        user_id=user.id,
        provider="google",
        provider_user_id="google-user-123",
        email_verified=True
    )
    db.add(identity)
    db.commit()
    db.refresh(identity)

    assert isinstance(identity.id, uuid.UUID)
    assert identity.email_verified is True

    # 3. Session
    session = Session(
        user_id=user.id,
        token_hash="a" * 64,
        expires_at=datetime.now(timezone.utc) + timedelta(days=7)
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    assert isinstance(session.id, uuid.UUID)
    assert session.expires_at.tzinfo is not None

    # 4. Link
    link = Link(
        user_id=user.id,
        short_code="myLink1",
        original_url="https://example.com/target"
    )
    db.add(link)
    db.commit()
    db.refresh(link)

    assert isinstance(link.id, int)
    assert link.id > 0
    assert link.is_active is True

    # 5. ClickEvent
    event = ClickEvent(
        link_id=link.id,
        referrer="https://twitter.com",
        device_type="mobile",
        country="US"
    )
    db.add(event)
    db.commit()
    db.refresh(event)

    assert isinstance(event.id, int)
    assert event.id > 0
    assert event.clicked_at.tzinfo is not None


def test_user_delete_cascade(db):
    """Deleting a user must cascade delete auth_identities, sessions, links, and click_events."""
    user = User(email="cascade@example.com")
    db.add(user)
    db.commit()

    identity = AuthIdentity(user_id=user.id, provider="github", provider_user_id="gh-123")
    session = Session(user_id=user.id, token_hash="b" * 64, expires_at=datetime.now(timezone.utc) + timedelta(days=1))
    link = Link(user_id=user.id, short_code="cascadelink", original_url="https://example.com")
    db.add_all([identity, session, link])
    db.commit()

    event = ClickEvent(link_id=link.id, referrer="https://google.com")
    db.add(event)
    db.commit()

    # Delete User
    db.delete(user)
    db.commit()

    # Verify everything cascaded
    assert db.query(AuthIdentity).filter_by(user_id=user.id).first() is None
    assert db.query(Session).filter_by(user_id=user.id).first() is None
    assert db.query(Link).filter_by(user_id=user.id).first() is None
    assert db.query(ClickEvent).filter_by(link_id=link.id).first() is None


def test_link_delete_cascade_to_click_events(db):
    """Deleting a link must cascade delete its click events."""
    user = User(email="linkcascade@example.com")
    db.add(user)
    db.commit()

    link = Link(user_id=user.id, short_code="linkonly", original_url="https://example.com")
    db.add(link)
    db.commit()

    e1 = ClickEvent(link_id=link.id, referrer="ref1")
    e2 = ClickEvent(link_id=link.id, referrer="ref2")
    db.add_all([e1, e2])
    db.commit()

    db.delete(link)
    db.commit()

    assert db.query(ClickEvent).filter_by(link_id=link.id).count() == 0


def test_email_check_constraint_lowercase(db):
    """Inserting an email with uppercase characters must be rejected by CHECK constraint."""
    user = User(email="A@B.com")
    db.add(user)
    with pytest.raises(IntegrityError) as exc_info:
        db.commit()
    assert "ck_users_email_lowercase" in str(exc_info.value).lower() or "check constraint" in str(exc_info.value).lower()
    db.rollback()


def test_email_unique_constraint(db):
    """Duplicate email must be rejected by unique constraint."""
    u1 = User(email="unique@example.com")
    db.add(u1)
    db.commit()

    u2 = User(email="unique@example.com")
    db.add(u2)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_auth_identities_provider_check_constraint(db):
    """Invalid provider name must be rejected by check constraint."""
    user = User(email="providertest@example.com")
    db.add(user)
    db.commit()

    # Invalid provider
    bad_ident = AuthIdentity(user_id=user.id, provider="facebook", provider_user_id="fb-123")
    db.add(bad_ident)
    with pytest.raises(IntegrityError) as exc_info:
        db.commit()
    assert "ck_auth_identities_provider" in str(exc_info.value).lower() or "check constraint" in str(exc_info.value).lower()
    db.rollback()

    # Allowed providers: google, github, password
    for allowed in ["google", "github", "password"]:
        ident = AuthIdentity(user_id=user.id, provider=allowed, provider_user_id=f"id-{allowed}")
        db.add(ident)
        db.commit()


def test_auth_identities_unique_provider_user(db):
    """(provider, provider_user_id) must be unique."""
    u1 = User(email="user1@example.com")
    u2 = User(email="user2@example.com")
    db.add_all([u1, u2])
    db.commit()

    ident1 = AuthIdentity(user_id=u1.id, provider="github", provider_user_id="gh-duplicate")
    db.add(ident1)
    db.commit()

    ident2 = AuthIdentity(user_id=u2.id, provider="github", provider_user_id="gh-duplicate")
    db.add(ident2)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_sessions_token_hash_unique(db):
    """token_hash must be unique."""
    u1 = User(email="session1@example.com")
    u2 = User(email="session2@example.com")
    db.add_all([u1, u2])
    db.commit()

    s1 = Session(user_id=u1.id, token_hash="c" * 64, expires_at=datetime.now(timezone.utc))
    db.add(s1)
    db.commit()

    s2 = Session(user_id=u2.id, token_hash="c" * 64, expires_at=datetime.now(timezone.utc))
    db.add(s2)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_short_code_case_sensitivity_and_uniqueness(db):
    """short_code is case-sensitive and unique."""
    user = User(email="casetest@example.com")
    db.add(user)
    db.commit()

    # Case sensitivity: 'CaseCode' and 'casecode' are distinct in PostgreSQL
    l1 = Link(user_id=user.id, short_code="CaseCode", original_url="https://example.com/1")
    l2 = Link(user_id=user.id, short_code="casecode", original_url="https://example.com/2")
    db.add_all([l1, l2])
    db.commit()

    assert db.query(Link).filter_by(short_code="CaseCode").one().id == l1.id
    assert db.query(Link).filter_by(short_code="casecode").one().id == l2.id

    # Duplicate exact short_code must fail
    l3 = Link(user_id=user.id, short_code="CaseCode", original_url="https://example.com/3")
    db.add(l3)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_concurrent_short_code_inserts(TestSessionLocal, db):
    """Concurrent inserts of the same short_code from two connections: exactly one succeeds, the other raises IntegrityError."""
    user = User(email="concurrent@example.com")
    db.add(user)
    db.commit()
    user_id = user.id

    results = []
    barrier = threading.Barrier(2)

    def attempt_insert(worker_id):
        session = TestSessionLocal()
        try:
            link = Link(
                user_id=user_id,
                short_code="race_code",
                original_url=f"https://example.com/{worker_id}"
            )
            session.add(link)
            # Synchronize both threads right before commit
            barrier.wait(timeout=5)
            session.commit()
            results.append(("SUCCESS", worker_id))
        except IntegrityError:
            session.rollback()
            results.append(("INTEGRITY_ERROR", worker_id))
        except Exception as e:
            session.rollback()
            results.append(("OTHER_ERROR", str(e)))
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(attempt_insert, 1)
        f2 = executor.submit(attempt_insert, 2)
        f1.result()
        f2.result()

    statuses = [r[0] for r in results]
    assert statuses.count("SUCCESS") == 1, f"Expected exactly 1 SUCCESS, got {results}"
    assert statuses.count("INTEGRITY_ERROR") == 1, f"Expected exactly 1 INTEGRITY_ERROR, got {results}"


def test_alembic_downgrade_and_upgrade_cycle(alembic_test_cfg, test_engine):
    """Alembic downgrade/upgrade cycle testing migration 0002 downgrade and base downgrade (runs ONLY on test DB)."""
    # 1. Downgrade from 0002 to 0001
    command.downgrade(alembic_test_cfg, "0001_initial_schema")
    inspector = inspect(test_engine)
    cols_0001 = {col["name"] for col in inspector.get_columns("links")}
    assert "deleted_at" not in cols_0001, "Column deleted_at was not removed after downgrade to 0001!"

    # 2. Upgrade back to head
    command.upgrade(alembic_test_cfg, "head")
    inspector = inspect(test_engine)
    cols_head = {col["name"] for col in inspector.get_columns("links")}
    assert "deleted_at" in cols_head, "Column deleted_at missing after upgrade to head!"

    # 3. Full downgrade to base
    command.downgrade(alembic_test_cfg, "base")

    # Verify tables are dropped
    inspector = inspect(test_engine)
    remaining_tables = inspector.get_table_names()
    assert len(remaining_tables) == 1 and remaining_tables[0] == "alembic_version" or len(remaining_tables) == 0, (
        f"Tables remained after downgrade: {remaining_tables}"
    )

    # 4. Upgrade back to head
    command.upgrade(alembic_test_cfg, "head")

    # Verify tables are restored
    inspector = inspect(test_engine)
    restored_tables = set(inspector.get_table_names())
    expected_tables = {"users", "auth_identities", "sessions", "links", "click_events", "alembic_version"}
    assert expected_tables.issubset(restored_tables), f"Missing tables after upgrade: {expected_tables - restored_tables}"


def test_adversarial_orphan_foreign_keys(db):
    """Attempt inserting records with non-existent foreign keys (must fail)."""
    fake_user_id = uuid.uuid4()

    # 1. Session with fake user_id
    bad_session = Session(user_id=fake_user_id, token_hash="x" * 64, expires_at=datetime.now(timezone.utc))
    db.add(bad_session)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()

    # 2. Link with fake user_id
    bad_link = Link(user_id=fake_user_id, short_code="orphanlink", original_url="https://example.com")
    db.add(bad_link)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()

    # 3. ClickEvent with fake link_id
    bad_event = ClickEvent(link_id=999999999)
    db.add(bad_event)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_adversarial_string_overflow(db):
    """Attempt inserting strings beyond declared column lengths."""
    user = User(email="overflow@example.com")
    db.add(user)
    db.commit()

    # 1. token_hash > 64 chars
    bad_session = Session(user_id=user.id, token_hash="a" * 65, expires_at=datetime.now(timezone.utc))
    db.add(bad_session)
    with pytest.raises(DataError):
        db.commit()
    db.rollback()

    # 2. short_code > 32 chars
    bad_link = Link(user_id=user.id, short_code="s" * 33, original_url="https://example.com")
    db.add(bad_link)
    with pytest.raises(DataError):
        db.commit()
    db.rollback()


def test_adversarial_sql_injection_values(db):
    """SQL injection strings must be safely escaped by SQLAlchemy/psycopg and not execute."""
    sqli_payload = "'; DROP TABLE users CASCADE; --"
    user = User(
        email="sqli_test@example.com",
        name=sqli_payload,
        avatar_url=sqli_payload
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    # Verify users table still exists and data was stored safely as literal text
    assert user.name == sqli_payload
    assert db.query(User).filter_by(id=user.id).one().name == sqli_payload

    # Link injection payload
    link = Link(
        user_id=user.id,
        short_code="sqli_code",
        original_url="https://example.com?q=" + sqli_payload
    )
    db.add(link)
    db.commit()
    db.refresh(link)

    assert link.original_url == "https://example.com?q=" + sqli_payload

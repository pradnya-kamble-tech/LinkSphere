"""create initial schema

Revision ID: 0001_initial_schema
Revises: 
Create Date: 2026-10-28 23:35:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0001_initial_schema'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. users
    op.create_table(
        'users',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=True),
        sa.Column('avatar_url', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint('email = lower(email)', name='ck_users_email_lowercase'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_users_email', 'users', ['email'], unique=True)

    # 2. auth_identities
    op.create_table(
        'auth_identities',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('provider', sa.String(length=50), nullable=False),
        sa.Column('provider_user_id', sa.String(length=255), nullable=False),
        sa.Column('email_verified', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("provider IN ('google', 'github', 'password')", name='ck_auth_identities_provider'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('provider', 'provider_user_id', name='uq_auth_identities_provider_user')
    )
    op.create_index('ix_auth_identities_user_id', 'auth_identities', ['user_id'], unique=False)

    # 3. sessions
    op.create_table(
        'sessions',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_sessions_token_hash', 'sessions', ['token_hash'], unique=True)
    op.create_index('ix_sessions_user_id', 'sessions', ['user_id'], unique=False)

    # 4. links
    op.create_table(
        'links',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('short_code', sa.String(length=32), nullable=False),
        sa.Column('original_url', sa.Text(), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_links_short_code', 'links', ['short_code'], unique=True)
    op.create_index('ix_links_user_id', 'links', ['user_id'], unique=False)

    # 5. click_events
    op.create_table(
        'click_events',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column('link_id', sa.BigInteger(), nullable=False),
        sa.Column('clicked_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('referrer', sa.Text(), nullable=True),
        sa.Column('device_type', sa.String(length=50), nullable=True),
        sa.Column('country', sa.String(length=10), nullable=True),
        sa.ForeignKeyConstraint(['link_id'], ['links.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_click_events_link_id_clicked_at', 'click_events', ['link_id', sa.text('clicked_at DESC')], unique=False)


def downgrade() -> None:
    op.drop_index('ix_click_events_link_id_clicked_at', table_name='click_events')
    op.drop_table('click_events')

    op.drop_index('ix_links_user_id', table_name='links')
    op.drop_index('ix_links_short_code', table_name='links')
    op.drop_table('links')

    op.drop_index('ix_sessions_user_id', table_name='sessions')
    op.drop_index('ix_sessions_token_hash', table_name='sessions')
    op.drop_table('sessions')

    op.drop_index('ix_auth_identities_user_id', table_name='auth_identities')
    op.drop_table('auth_identities')

    op.drop_index('ix_users_email', table_name='users')
    op.drop_table('users')

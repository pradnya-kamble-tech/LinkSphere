
"""Add passwordless authentication models.

Revision ID: 77b0d317e65a
Revises: a0344b180c0e
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "77b0d317e65a"
down_revision: Union[str, Sequence[str], None] = "a0344b180c0e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create passwordless authentication tables and update users."""

    op.create_table(
        "auth_identities",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("provider_user_id", sa.String(length=255), nullable=False),
        sa.Column("provider_email", sa.String(length=255), nullable=True),
        sa.Column(
            "provider_email_verified",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider",
            "provider_user_id",
            name="uq_auth_identities_provider_user",
        ),
    )

    op.create_index(
        "ix_auth_identities_user_id",
        "auth_identities",
        ["user_id"],
        unique=False,
    )

    op.create_table(
        "email_login_tokens",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_email_login_tokens_token_hash",
        "email_login_tokens",
        ["token_hash"],
        unique=True,
    )

    op.create_index(
        "ix_email_login_tokens_user_id",
        "email_login_tokens",
        ["user_id"],
        unique=False,
    )

    op.add_column(
        "users",
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.drop_column("users", "password_hash")


def downgrade() -> None:
    """Reverse the schema changes.

    Existing password hashes cannot be recovered after upgrade.
    The restored column is nullable to avoid inventing password hashes.
    """

    op.add_column(
        "users",
        sa.Column("password_hash", sa.String(length=255), nullable=True),
    )

    op.drop_column("users", "email_verified_at")

    op.drop_index(
        "ix_email_login_tokens_user_id",
        table_name="email_login_tokens",
    )
    op.drop_index(
        "ix_email_login_tokens_token_hash",
        table_name="email_login_tokens",
    )
    op.drop_table("email_login_tokens")

    op.drop_index(
        "ix_auth_identities_user_id",
        table_name="auth_identities",
    )
    op.drop_table("auth_identities")

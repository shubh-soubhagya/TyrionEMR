"""refresh_tokens.revoked_reason accepts 'password_changed'

Revision ID: 0003
Revises: 0002
"""
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

_OLD = "('rotated', 'logout', 'reuse_detected', 'user_inactive')"
_NEW = "('rotated', 'logout', 'reuse_detected', 'user_inactive', 'password_changed')"


def upgrade() -> None:
    op.execute("ALTER TABLE refresh_tokens DROP CONSTRAINT ck_rt_revoked_reason")
    op.execute(
        "ALTER TABLE refresh_tokens ADD CONSTRAINT ck_rt_revoked_reason "
        f"CHECK (revoked_reason IS NULL OR revoked_reason IN {_NEW})"
    )


def downgrade() -> None:
    op.execute("UPDATE refresh_tokens SET revoked_reason = 'logout' WHERE revoked_reason = 'password_changed'")
    op.execute("ALTER TABLE refresh_tokens DROP CONSTRAINT ck_rt_revoked_reason")
    op.execute(
        "ALTER TABLE refresh_tokens ADD CONSTRAINT ck_rt_revoked_reason "
        f"CHECK (revoked_reason IS NULL OR revoked_reason IN {_OLD})"
    )

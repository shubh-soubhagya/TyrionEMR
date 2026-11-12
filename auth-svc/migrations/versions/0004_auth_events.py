"""auth_events: durable audit trail of authentication events (no email, password or token columns)

Revision ID: 0004
Revises: 0003
"""
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE auth_events (
        id          uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
        at          timestamptz NOT NULL,
        event       text        NOT NULL,
        outcome     text        NOT NULL,
        user_id     uuid        NULL,
        family_id   uuid        NULL,
        request_id  text        NULL,
        ip          inet        NULL,
        user_agent  text        NULL,
        CONSTRAINT ck_auth_events_user_agent_len CHECK (user_agent IS NULL OR char_length(user_agent) <= 256)
    )""")
    op.execute("CREATE INDEX ix_auth_events_user_at ON auth_events (user_id, at DESC)")
    op.execute("CREATE INDEX ix_auth_events_at ON auth_events (at)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS auth_events")

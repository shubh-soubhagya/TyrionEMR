"""initial: users and refresh_tokens (LLD §15.2)

Revision ID: 0001
Revises:
"""
import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    has_citext = op.get_bind().execute(sa.text("SELECT 1 FROM pg_extension WHERE extname = 'citext'")).scalar()
    if not has_citext:
        raise RuntimeError("citext is missing in this database. Run setup/init-auth-db.sh first.")

    op.execute("""
    CREATE TABLE users (
        id                  uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
        email               citext      NOT NULL,
        password_hash       text        NOT NULL,
        full_name           text        NOT NULL,
        role                text        NOT NULL DEFAULT 'clinician',
        is_active           boolean     NOT NULL DEFAULT true,
        failed_login_count  integer     NOT NULL DEFAULT 0,
        locked_until        timestamptz NULL,
        last_login_at       timestamptz NULL,
        created_at          timestamptz NOT NULL DEFAULT now(),
        updated_at          timestamptz NOT NULL DEFAULT now(),

        CONSTRAINT uq_users_email            UNIQUE (email),
        CONSTRAINT ck_users_email_len        CHECK (char_length(email) BETWEEN 3 AND 254),
        CONSTRAINT ck_users_full_name_len    CHECK (char_length(full_name) BETWEEN 2 AND 120),
        CONSTRAINT ck_users_role             CHECK (role IN ('clinician')),
        CONSTRAINT ck_users_failed_count     CHECK (failed_login_count >= 0),
        CONSTRAINT ck_users_hash_format      CHECK (password_hash LIKE '$argon2id$%')
    )""")
    op.execute("""
    CREATE TABLE refresh_tokens (
        id                 uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id            uuid        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        family_id          uuid        NOT NULL,
        token_hash         text        NOT NULL,
        expires_at         timestamptz NOT NULL,
        family_expires_at  timestamptz NOT NULL,
        revoked_at         timestamptz NULL,
        revoked_reason     text        NULL,
        replaced_by_id     uuid        NULL REFERENCES refresh_tokens(id) ON DELETE SET NULL,
        user_agent         text        NULL,
        created_at         timestamptz NOT NULL DEFAULT now(),

        CONSTRAINT uq_refresh_tokens_hash      UNIQUE (token_hash),
        CONSTRAINT ck_rt_hash_len              CHECK (char_length(token_hash) = 64),
        CONSTRAINT ck_rt_expiry_order          CHECK (expires_at <= family_expires_at),
        CONSTRAINT ck_rt_revoked_reason        CHECK (
            revoked_reason IS NULL
            OR revoked_reason IN ('rotated', 'logout', 'reuse_detected', 'user_inactive')
        ),
        CONSTRAINT ck_rt_revoked_consistency   CHECK ((revoked_at IS NULL) = (revoked_reason IS NULL)),
        CONSTRAINT ck_rt_user_agent_len        CHECK (user_agent IS NULL OR char_length(user_agent) <= 256)
    )""")
    op.execute("CREATE INDEX ix_rt_family_active ON refresh_tokens (family_id) WHERE revoked_at IS NULL")
    op.execute("CREATE INDEX ix_rt_user_id ON refresh_tokens (user_id)")
    op.execute("CREATE INDEX ix_rt_expires_at ON refresh_tokens (expires_at)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS refresh_tokens")
    op.execute("DROP TABLE IF EXISTS users")

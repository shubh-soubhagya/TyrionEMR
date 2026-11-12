"""Item 7: AUTH_DB_SSLMODE / AUTH_DB_SSLROOTCERT reach asyncpg."""
import ssl

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.x509.oid import NameOID

from app.db import session as db_session
from app.db.session import build_ssl, create_engine
from tests.conftest import make_settings


@pytest.fixture
def ca_file(tmp_path, rsa_key):
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test-ca")])
    import datetime
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(rsa_key.public_key())
            .serial_number(1).not_valid_before(datetime.datetime(2026, 1, 1))
            .not_valid_after(datetime.datetime(2036, 1, 1))
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .sign(rsa_key, hashes.SHA256()))
    path = tmp_path / "ca.pem"
    path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return str(path)


def test_disable_means_no_ssl_argument():
    assert build_ssl("disable", None) is None


def test_require_without_a_root_cert_encrypts_without_verifying():
    assert build_ssl("require", None) == "require"


def test_require_with_a_root_cert_verifies_the_chain_but_not_the_host_name(ca_file):
    ctx = build_ssl("require", ca_file)
    assert isinstance(ctx, ssl.SSLContext)
    assert ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname is False


def test_verify_full_verifies_chain_and_host_name(ca_file):
    ctx = build_ssl("verify-full", ca_file)
    assert isinstance(ctx, ssl.SSLContext)
    assert ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname is True


def test_unknown_mode_is_rejected():
    with pytest.raises(ValueError):
        build_ssl("prefer", None)


def test_engine_passes_ssl_and_timeouts_to_asyncpg(monkeypatch, ca_file):
    captured = {}
    monkeypatch.setattr(db_session, "create_async_engine", lambda url, **kw: captured.update(kw))
    create_engine(make_settings(auth_db_sslmode="verify-full", auth_db_sslrootcert=ca_file))
    args = captured["connect_args"]
    assert isinstance(args["ssl"], ssl.SSLContext) and args["ssl"].check_hostname is True
    assert args["server_settings"]["statement_timeout"] == "5000"
    assert args["server_settings"]["lock_timeout"] == "2000"
    assert args["server_settings"]["idle_in_transaction_session_timeout"] == "10000"


def test_engine_has_no_ssl_argument_when_disabled(monkeypatch):
    captured = {}
    monkeypatch.setattr(db_session, "create_async_engine", lambda url, **kw: captured.update(kw))
    create_engine(make_settings())
    assert "ssl" not in captured["connect_args"]

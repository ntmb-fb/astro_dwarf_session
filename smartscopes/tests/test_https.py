import asyncio
import datetime as dt
import ssl

import pytest
from cryptography import x509

from smartscopes import https


@pytest.fixture
def cert_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(https, "CERT_DIR", tmp_path)
    monkeypatch.setattr(https, "local_ips", lambda: ["192.168.1.23"])
    return tmp_path


def test_not_enabled_without_opt_in(cert_dir):
    assert https.ensure_certificates() is False
    assert not (cert_dir / "ca.crt").exists()


def test_chain_verifies_for_ip_and_mdns_name(cert_dir):
    assert https.ensure_certificates(create_ca=True)
    ctx = ssl.create_default_context(cafile=str(cert_dir / "ca.crt"))
    server_ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    server_ctx.load_cert_chain(cert_dir / "server.crt", cert_dir / "server.key")

    for name in ("192.168.1.23", https._dns_names()[1], "localhost"):
        a, b = ssl.MemoryBIO(), ssl.MemoryBIO()
        c, s = ssl.MemoryBIO(), ssl.MemoryBIO()
        client = ctx.wrap_bio(a, b, server_hostname=name)
        server = server_ctx.wrap_bio(c, s, server_side=True)
        for _ in range(10):  # pump the handshake between the two in-memory ends
            for obj in (client, server):
                try:
                    obj.do_handshake()
                except ssl.SSLWantReadError:
                    pass
            c.write(b.read())
            a.write(s.read())
        assert client.getpeercert()["subjectAltName"]


def test_ca_is_name_constrained(cert_dir):
    https.ensure_certificates(create_ca=True)
    ca = x509.load_pem_x509_certificate((cert_dir / "ca.crt").read_bytes())
    nc = ca.extensions.get_extension_for_class(x509.NameConstraints).value
    assert x509.DNSName("local") in nc.permitted_subtrees


def test_server_cert_reissued_when_ip_changes(cert_dir, monkeypatch):
    https.ensure_certificates(create_ca=True)
    first = (cert_dir / "server.crt").read_bytes()
    ca_first = (cert_dir / "ca.crt").read_bytes()
    https.ensure_certificates()
    assert (cert_dir / "server.crt").read_bytes() == first  # still valid -> kept

    monkeypatch.setattr(https, "local_ips", lambda: ["10.0.0.7"])
    https.ensure_certificates()
    cert = x509.load_pem_x509_certificate((cert_dir / "server.crt").read_bytes())
    ips = [str(i) for i in cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
           .value.get_values_for_type(x509.IPAddress)]
    assert "10.0.0.7" in ips
    assert (cert_dir / "ca.crt").read_bytes() == ca_first  # phones keep trusting
    assert cert.not_valid_after_utc - dt.datetime.now(dt.timezone.utc) < dt.timedelta(days=398)


def test_relay_forwards_bytes(cert_dir, monkeypatch):
    https.ensure_certificates(create_ca=True)
    monkeypatch.setattr(https, "HTTPS_PORT", 0)

    async def scenario():
        async def echo(r, w):
            w.write(b"pong:" + await r.readline())
            await w.drain()
            w.close()

        backend = await asyncio.start_server(echo, "127.0.0.1", 0)
        await https.start_relay(backend.sockets[0].getsockname()[1])
        port = https._server.sockets[0].getsockname()[1]
        ctx = ssl.create_default_context(cafile=str(cert_dir / "ca.crt"))
        r, w = await asyncio.open_connection("127.0.0.1", port, ssl=ctx, server_hostname="localhost")
        w.write(b"ping\n")
        await w.drain()
        reply = await r.read()
        w.close()
        await https.stop_relay()
        backend.close()
        return reply

    assert asyncio.run(scenario()) == b"pong:ping\n"

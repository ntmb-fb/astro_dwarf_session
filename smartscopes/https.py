"""Optional HTTPS for phones (installable PWA on Android needs HTTPS).

How it works:
  * A private certificate authority (CA) is created once. The user
    installs its certificate (ca.crt) on each phone/tablet, once.
  * A server certificate for this computer's LAN IP(s) and <hostname>.local
    is signed by that CA - and re-signed automatically at startup whenever
    the IP changes or it nears expiry, so phones never need re-setup.
  * A small in-process TLS relay listens on HTTPS_PORT (default 8443) and
    forwards raw bytes to the normal HTTP server, so plain HTTP (and the
    native desktop window) keep working unchanged, and websockets just
    pass through.

The CA is name-constrained to private IP ranges, localhost and *.local,
so even a leaked CA key cannot be used to impersonate public websites
on a phone that trusts it.

Files live in ~/.smartscope_session/https/ (override with the
SMARTSCOPE_CERT_DIR environment variable), outside the git checkout.
HTTPS is active only once the CA exists (see enable()).
"""
from __future__ import annotations

import asyncio
import datetime as dt
import ipaddress
import logging
import os
import socket
import ssl
from pathlib import Path

log = logging.getLogger("smartscopes.https")

def _default_cert_dir() -> Path:
    new, old = Path.home() / ".smartscope_session" / "https", Path.home() / ".astro_dwarf_session" / "https"
    # Keep using a CA created before the rename, so phones that trust it keep working.
    return old if (old / "ca.crt").exists() and not new.exists() else new


CERT_DIR = Path(os.environ.get("SMARTSCOPE_CERT_DIR") or _default_cert_dir())
HTTPS_PORT = int(os.environ.get("SMARTSCOPE_HTTPS_PORT", "8443"))

_CA_DAYS = 3650
_SERVER_DAYS = 397          # Chrome's limit for server certificates
_RENEW_BEFORE_DAYS = 30
_PRIVATE_NETS = ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8", "169.254.0.0/16")

_server: asyncio.base_events.Server | None = None


def ca_cert_path() -> Path:
    return CERT_DIR / "ca.crt"


def is_enabled() -> bool:
    return ca_cert_path().exists()


def is_running() -> bool:
    return _server is not None and _server.is_serving()


def local_ips() -> list[str]:
    """Private IPv4 addresses of this machine, primary one first."""
    ips: list[str] = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))  # no packet is sent for UDP connect
            ips.append(s.getsockname()[0])
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.append(info[4][0])
    except OSError:
        pass
    private = [ip for ip in dict.fromkeys(ips)
               if any(ipaddress.ip_address(ip) in ipaddress.ip_network(n) for n in _PRIVATE_NETS)
               and not ip.startswith("127.")]
    return private


def _dns_names() -> list[str]:
    host = socket.gethostname().split(".")[0].lower()
    return ["localhost", f"{host}.local"]


# --- certificates ----------------------------------------------------------------

def _write_private(path: Path, data: bytes) -> None:
    path.write_bytes(data)
    try:
        path.chmod(0o600)
    except OSError:
        pass


def _create_ca() -> None:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    host = socket.gethostname().split(".")[0]
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"Smartscope Session local CA ({host})")])
    now = dt.datetime.now(dt.timezone.utc)
    permitted = [x509.IPAddress(ipaddress.ip_network(n)) for n in _PRIVATE_NETS]
    permitted += [x509.DNSName("localhost"), x509.DNSName("local")]
    cert = (
        x509.CertificateBuilder()
        .subject_name(name).issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=_CA_DAYS))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True,
                                     content_commitment=False, key_encipherment=False,
                                     data_encipherment=False, key_agreement=False,
                                     encipher_only=False, decipher_only=False), critical=True)
        # Non-critical for compatibility; verifiers that support it (Android,
        # Chrome) still enforce it.
        .add_extension(x509.NameConstraints(permitted_subtrees=permitted, excluded_subtrees=None),
                       critical=False)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .sign(key, hashes.SHA256())
    )
    CERT_DIR.mkdir(parents=True, exist_ok=True)
    _write_private(CERT_DIR / "ca.key", key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    ca_cert_path().write_bytes(cert.public_bytes(serialization.Encoding.PEM))


def _server_cert_ok(ips: list[str]) -> bool:
    from cryptography import x509

    path = CERT_DIR / "server.crt"
    if not path.exists() or not (CERT_DIR / "server.key").exists():
        return False
    cert = x509.load_pem_x509_certificate(path.read_bytes())
    if cert.not_valid_after_utc - dt.datetime.now(dt.timezone.utc) < dt.timedelta(days=_RENEW_BEFORE_DAYS):
        return False
    san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    have = {str(ip) for ip in san.get_values_for_type(x509.IPAddress)}
    return set(ips) <= have and set(_dns_names()) <= set(san.get_values_for_type(x509.DNSName))


def _issue_server_cert(ips: list[str]) -> None:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    ca_key = serialization.load_pem_private_key((CERT_DIR / "ca.key").read_bytes(), password=None)
    ca_cert = x509.load_pem_x509_certificate(ca_cert_path().read_bytes())
    key = ec.generate_private_key(ec.SECP256R1())
    now = dt.datetime.now(dt.timezone.utc)
    sans = [x509.DNSName(n) for n in _dns_names()]
    sans += [x509.IPAddress(ipaddress.ip_address(ip)) for ip in ["127.0.0.1", *ips]]
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, _dns_names()[1])]))
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=_SERVER_DAYS))
        .add_extension(x509.SubjectAlternativeName(sans), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    _write_private(CERT_DIR / "server.key", key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    (CERT_DIR / "server.crt").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    log.info("HTTPS: issued server certificate for %s", ", ".join(ips + _dns_names()))


def ensure_certificates(*, create_ca: bool = False) -> bool:
    """Makes sure a valid server certificate exists for the current IPs.
    Creates the CA only when create_ca=True (explicit opt-in)."""
    if not is_enabled():
        if not create_ca:
            return False
        _create_ca()
    ips = local_ips()
    if not _server_cert_ok(ips):
        _issue_server_cert(ips)
    return True


# --- TLS relay ---------------------------------------------------------------------

async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    except (ConnectionError, OSError, asyncio.IncompleteReadError, ssl.SSLError):
        pass
    finally:
        try:
            writer.close()
        except Exception:
            pass


async def start_relay(target_port: int, target_host: str = "127.0.0.1") -> None:
    """Starts the HTTPS relay (no-op if already running or not enabled)."""
    global _server
    if is_running() or not ensure_certificates():
        return
    ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ctx.load_cert_chain(CERT_DIR / "server.crt", CERT_DIR / "server.key")

    async def handle(client_r: asyncio.StreamReader, client_w: asyncio.StreamWriter) -> None:
        try:
            upstream_r, upstream_w = await asyncio.open_connection(target_host, target_port)
        except OSError:
            client_w.close()
            return
        await asyncio.gather(_pipe(client_r, upstream_w), _pipe(upstream_r, client_w))

    try:
        _server = await asyncio.start_server(handle, "0.0.0.0", HTTPS_PORT, ssl=ctx)
    except OSError as exc:
        log.warning("HTTPS: cannot listen on port %s (%s)", HTTPS_PORT, exc)
        return
    log.info("HTTPS: https://%s:%s/ -> http://%s:%s/",
             (local_ips() or ["localhost"])[0], HTTPS_PORT, target_host, target_port)


async def stop_relay() -> None:
    global _server
    if _server is not None:
        _server.close()
        await _server.wait_closed()
        _server = None


def https_urls() -> list[str]:
    return [f"https://{ip}:{HTTPS_PORT}/" for ip in local_ips()] + [f"https://{_dns_names()[1]}:{HTTPS_PORT}/"]

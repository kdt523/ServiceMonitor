"""
Health checker — supports HTTP, HTTPS, SSL, TCP, Ping, DNS, SSH, FTP, SMTP.

Status mapping:
  HTTP/HTTPS: 200–399 → 'healthy', non-200 → 'problem', error → 'problem'
  SSL cert:   >30 days → 'healthy', 7–30 days → 'warning', <7 days → 'problem'
  TCP/SSH/FTP: port open → 'healthy', refused/timeout → 'problem'
  Ping:       reply received → 'healthy', timeout/unreachable → 'problem'
  DNS:        resolves → 'healthy', failure → 'problem'
  SMTP:       220 banner → 'healthy', no banner → 'problem'
"""
import asyncio
import platform
import ssl
import socket
import time
from datetime import datetime, timezone
from typing import Optional


# ---------------------------------------------------------------------------
# HTTP check
# ---------------------------------------------------------------------------

async def check_http(url: str, keyword: str | None = None, headers: dict | None = None) -> dict:
    """Plain HTTP health check — requires status 200–399.
    Optionally asserts a keyword exists in the response body.
    Optionally merges custom headers into the request.
    """
    import httpx
    start = time.monotonic()
    try:
        default_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 (Gonitor/2.0; +https://github.com/user/gonitor; user@example.com)"
        }
        merged_headers = {**default_headers, **(headers or {})}
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True, verify=False, headers=merged_headers) as client:
            response = await client.get(url)
        elapsed_ms = int((time.monotonic() - start) * 1000)

        if 200 <= response.status_code < 400:
            # Keyword check (only if status is OK)
            if keyword:
                body = response.text
                if keyword not in body:
                    return {
                        "status": "problem",
                        "response_time_ms": elapsed_ms,
                        "error_message": f"Keyword '{keyword}' not found in response body",
                    }
            return {"status": "healthy", "response_time_ms": elapsed_ms, "error_message": None}
        else:
            return {
                "status": "problem",
                "response_time_ms": elapsed_ms,
                "error_message": f"HTTP {response.status_code}",
            }
    except httpx.TimeoutException:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return {"status": "problem", "response_time_ms": elapsed_ms, "error_message": "Connection timed out"}
    except Exception as exc:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return {"status": "problem", "response_time_ms": elapsed_ms, "error_message": str(exc)}


# ---------------------------------------------------------------------------
# HTTPS check
# ---------------------------------------------------------------------------

async def check_https(url: str, keyword: str | None = None, headers: dict | None = None) -> dict:
    """HTTPS health check — enforces TLS and requires status 200–399.
    Optionally asserts a keyword exists in the response body.
    Optionally merges custom headers into the request.
    """
    import httpx
    if not url.startswith("https://"):
        url = "https://" + url.split("://", 1)[-1]
    start = time.monotonic()
    try:
        default_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 (Gonitor/2.0; +https://github.com/user/gonitor; user@example.com)"
        }
        merged_headers = {**default_headers, **(headers or {})}
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True, verify=True, headers=merged_headers) as client:
            response = await client.get(url)
        elapsed_ms = int((time.monotonic() - start) * 1000)

        if 200 <= response.status_code < 400:
            # Keyword check (only if status is OK)
            if keyword:
                body = response.text
                if keyword not in body:
                    return {
                        "status": "problem",
                        "response_time_ms": elapsed_ms,
                        "error_message": f"Keyword '{keyword}' not found in response body",
                    }
            return {"status": "healthy", "response_time_ms": elapsed_ms, "error_message": None}
        else:
            return {
                "status": "problem",
                "response_time_ms": elapsed_ms,
                "error_message": f"HTTPS {response.status_code}",
            }
    except httpx.TimeoutException:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return {"status": "problem", "response_time_ms": elapsed_ms, "error_message": "Connection timed out"}
    except Exception as exc:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return {"status": "problem", "response_time_ms": elapsed_ms, "error_message": str(exc)}


# ---------------------------------------------------------------------------
# SSL certificate expiry check
# ---------------------------------------------------------------------------

def _get_ssl_cert_details(hostname: str, port: int = 443) -> dict:
    """
    Connect to hostname:port, retrieve the TLS certificate, and return
    a rich dict of certificate fields plus days_remaining.
    Raises on connection/verification error.
    """
    ctx = ssl.create_default_context()
    with socket.create_connection((hostname, port), timeout=10) as sock:
        with ctx.wrap_socket(sock, server_hostname=hostname) as ssock:
            cert = ssock.getpeercert()
            # Also grab the cipher for extra info
            cipher_info = ssock.cipher()  # (name, protocol, bits)

    # ── Expiry / validity ──────────────────────────────────────────────
    not_after_str  = cert.get("notAfter", "")
    not_before_str = cert.get("notBefore", "")
    fmt = "%b %d %H:%M:%S %Y %Z"

    expiry_dt  = datetime.strptime(not_after_str,  fmt).replace(tzinfo=timezone.utc)
    issued_dt  = datetime.strptime(not_before_str, fmt).replace(tzinfo=timezone.utc)
    now        = datetime.now(timezone.utc)
    days_left  = max(0, (expiry_dt - now).days)

    # ── Common Name ────────────────────────────────────────────────────
    subject_dict = dict(x[0] for x in cert.get("subject", []))
    common_name  = subject_dict.get("commonName", hostname)

    # ── Issuer ─────────────────────────────────────────────────────────
    issuer_dict  = dict(x[0] for x in cert.get("issuer", []))
    issuer_cn    = issuer_dict.get("commonName") or issuer_dict.get("organizationName", "Unknown")
    issuer_org   = issuer_dict.get("organizationName", "")
    issuer_country = issuer_dict.get("countryName", "")

    # ── Subject Alternative Names (SANs) ──────────────────────────────
    sans = [
        value
        for kind, value in cert.get("subjectAltName", [])
        if kind == "DNS"
    ]

    # ── Serial number (hex) ────────────────────────────────────────────
    serial_number = format(cert.get("serialNumber", 0), "x") if isinstance(cert.get("serialNumber"), int) else cert.get("serialNumber", "N/A")

    # ── Signature / key algorithm ──────────────────────────────────────
    # Python's ssl exposes limited DER info; use cipher suite as proxy
    cipher_name     = cipher_info[0] if cipher_info else "Unknown"
    tls_version     = cipher_info[1] if cipher_info else "Unknown"

    return {
        "common_name":    common_name,
        "sans":           sans,
        "valid_from":     issued_dt.strftime("%b %d, %Y"),
        "valid_to":       expiry_dt.strftime("%b %d, %Y"),
        "days_remaining": days_left,
        "serial_number":  serial_number,
        "issuer_cn":      issuer_cn,
        "issuer_org":     issuer_org,
        "issuer_country": issuer_country,
        "tls_version":    tls_version,
        "cipher":         cipher_name,
    }


async def check_ssl(hostname: str) -> dict:
    """
    SSL certificate expiry check (runs blocking SSL I/O in a thread pool).

    Returns:
        status           : 'healthy' (>30d), 'warning' (7–30d), 'problem' (<7d or error)
        ssl_days_remaining: int or None
        ssl_cert_details : dict with rich cert metadata, or None on error
    """
    # Strip scheme/path — we only need the hostname
    hostname = hostname.split("://")[-1].split("/")[0].split(":")[0]
    start = time.monotonic()
    try:
        details = await asyncio.get_event_loop().run_in_executor(
            None, _get_ssl_cert_details, hostname
        )
        elapsed_ms = int((time.monotonic() - start) * 1000)
        days = details["days_remaining"]
        if days > 30:
            status = "healthy"
        elif days >= 7:
            status = "warning"
        else:
            status = "problem"
        return {
            "status": status,
            "response_time_ms": elapsed_ms,
            "ssl_days_remaining": days,
            "ssl_cert_details": details,
            "error_message": None,
        }
    except Exception as exc:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return {
            "status": "problem",
            "response_time_ms": elapsed_ms,
            "ssl_days_remaining": None,
            "ssl_cert_details": None,
            "error_message": str(exc),
        }


# ---------------------------------------------------------------------------
# TCP check
# ---------------------------------------------------------------------------

async def check_tcp(host: str, port: int, timeout: float = 10.0) -> dict:
    """TCP connectivity check."""
    start = time.monotonic()
    writer: Optional[asyncio.StreamWriter] = None
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=timeout
        )
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return {"status": "healthy", "response_time_ms": elapsed_ms, "error_message": None}
    except asyncio.TimeoutError:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return {"status": "problem", "response_time_ms": elapsed_ms, "error_message": "TCP connection timed out"}
    except ConnectionRefusedError:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return {"status": "problem", "response_time_ms": elapsed_ms, "error_message": "Connection refused"}
    except Exception as exc:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return {"status": "problem", "response_time_ms": elapsed_ms, "error_message": str(exc)}
    finally:
        if writer is not None:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# ICMP Ping check
# ---------------------------------------------------------------------------

async def check_ping(host: str, timeout: int = 5) -> dict:
    """
    Run system ping via asyncio subprocess.
    Uses platform detection for Linux vs Windows ping flags.
    Returns: {"status": "healthy"|"problem", "response_time_ms": int, "error_message": str|None}
    """
    start = time.monotonic()
    try:
        # Platform-specific ping command
        if platform.system().lower() == "windows":
            cmd = ["ping", "-n", "1", "-w", str(timeout * 1000), host]
        else:
            cmd = ["ping", "-c", "1", "-W", str(timeout), host]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout + 2)
        elapsed_ms = int((time.monotonic() - start) * 1000)

        if proc.returncode == 0:
            return {"status": "healthy", "response_time_ms": elapsed_ms, "error_message": None}
        else:
            return {"status": "problem", "response_time_ms": elapsed_ms, "error_message": "Ping failed — host unreachable"}
    except asyncio.TimeoutError:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return {"status": "problem", "response_time_ms": elapsed_ms, "error_message": "Ping timed out"}
    except Exception as exc:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return {"status": "problem", "response_time_ms": elapsed_ms, "error_message": str(exc)}


# ---------------------------------------------------------------------------
# DNS Resolution check
# ---------------------------------------------------------------------------

async def check_dns(hostname: str, timeout: int = 5) -> dict:
    """
    Resolve hostname via getaddrinfo in a thread pool (blocking call).
    Returns: {"status": "healthy"|"problem", "response_time_ms": int, "resolved_ip": str|None, "error_message": str|None}
    """
    loop = asyncio.get_event_loop()
    start = time.monotonic()
    try:
        result = await asyncio.wait_for(
            loop.run_in_executor(None, socket.getaddrinfo, hostname, None),
            timeout=timeout,
        )
        elapsed_ms = int((time.monotonic() - start) * 1000)
        resolved_ip = result[0][4][0] if result else None
        return {"status": "healthy", "response_time_ms": elapsed_ms, "resolved_ip": resolved_ip, "error_message": None}
    except asyncio.TimeoutError:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return {"status": "problem", "response_time_ms": elapsed_ms, "resolved_ip": None, "error_message": "DNS resolution timed out"}
    except socket.gaierror as exc:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return {"status": "problem", "response_time_ms": elapsed_ms, "resolved_ip": None, "error_message": f"DNS failed: {exc}"}
    except Exception as exc:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return {"status": "problem", "response_time_ms": elapsed_ms, "resolved_ip": None, "error_message": str(exc)}


# ---------------------------------------------------------------------------
# SSH Port check (TCP to port 22)
# ---------------------------------------------------------------------------

async def check_ssh(hostname: str, port: int = 22, timeout: float = 5.0) -> dict:
    """Reuses TCP check logic with default port 22."""
    return await check_tcp(hostname, port, timeout)


# ---------------------------------------------------------------------------
# FTP Port check (TCP to port 21)
# ---------------------------------------------------------------------------

async def check_ftp(hostname: str, port: int = 21, timeout: float = 5.0) -> dict:
    """Reuses TCP check logic with default port 21."""
    return await check_tcp(hostname, port, timeout)


# ---------------------------------------------------------------------------
# SMTP check with banner grab
# ---------------------------------------------------------------------------

async def check_smtp(hostname: str, port: int = 587, timeout: int = 5) -> dict:
    """
    Connect to SMTP port and read the 220 greeting banner.
    A 220 response confirms it's a real SMTP server, not just an open port.
    """
    start = time.monotonic()
    writer: Optional[asyncio.StreamWriter] = None
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(hostname, port),
            timeout=timeout,
        )
        banner = await asyncio.wait_for(reader.readline(), timeout=timeout)
        elapsed_ms = int((time.monotonic() - start) * 1000)

        banner_str = banner.decode(errors="ignore").strip()
        if banner_str.startswith("220"):
            return {"status": "healthy", "response_time_ms": elapsed_ms, "error_message": None, "banner": banner_str}
        else:
            return {"status": "problem", "response_time_ms": elapsed_ms, "error_message": f"Unexpected SMTP banner: {banner_str}"}
    except asyncio.TimeoutError:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return {"status": "problem", "response_time_ms": elapsed_ms, "error_message": "SMTP connection timed out"}
    except ConnectionRefusedError:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return {"status": "problem", "response_time_ms": elapsed_ms, "error_message": f"Connection refused on port {port}"}
    except Exception as exc:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return {"status": "problem", "response_time_ms": elapsed_ms, "error_message": str(exc)}
    finally:
        if writer is not None:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

def _extract_hostname(url: str) -> str:
    """Extract bare hostname from a URL string."""
    host = url.split("://")[-1].split("/")[0].split(":")[0]
    return host


async def run_health_check(
    service_type: str,
    url: str,
    port: int | None = None,
    keyword: str | None = None,
    headers: dict | None = None,
    canonical_name: str | None = None,
) -> dict:
    """Dispatch to the correct checker based on service_type."""
    hostname = canonical_name or _extract_hostname(url)

    if service_type == "http":
        return await check_http(url, keyword=keyword, headers=headers)
    elif service_type == "https":
        return await check_https(url, keyword=keyword, headers=headers)
    elif service_type == "ssl":
        return await check_ssl(url)
    elif service_type == "tcp":
        tcp_port = port or 80
        # Support tcp:// URL format: tcp://host:port
        if url.startswith("tcp://"):
            stripped = url.removeprefix("tcp://")
            host, _, port_str = stripped.rpartition(":")
            if host and port_str.isdigit():
                hostname = host
                tcp_port = int(port_str)
        return await check_tcp(hostname, tcp_port)
    elif service_type == "ping":
        return await check_ping(hostname)
    elif service_type == "dns":
        return await check_dns(hostname)
    elif service_type == "ssh":
        return await check_ssh(hostname, port or 22)
    elif service_type == "ftp":
        return await check_ftp(hostname, port or 21)
    elif service_type == "smtp":
        return await check_smtp(hostname, port or 587)
    else:
        raise ValueError(f"Unknown service type: {service_type!r}")

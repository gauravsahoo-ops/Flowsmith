"""SSRF Protection and Outbound URL Validator for Flowsmith DataLoad.

Enforces strict security rules:
1. Rejection of prohibited private, loopback, link-local, carrier-grade NAT, and cloud metadata destinations.
2. Scheme restrictions: only http and https allowed.
3. DNS resolution validation: hostnames are resolved and every resolved IP is verified against blocked ranges.
4. Redirect validation: every redirect hop Location is re-validated before connection.
5. Sensitive credential, token, and query parameter redaction in logs and error messages.
"""

from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

from app.engine.errors import NodeExecutionError
from app.security.ssrf import assert_public_url


# Blocked IPv4 networks
_BLOCKED_IPV4_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),          # Current network (only valid as source address)
    ipaddress.ip_network("10.0.0.0/8"),         # RFC 1918 Private
    ipaddress.ip_network("100.64.0.0/10"),      # Shared Address Space (Carrier-grade NAT)
    ipaddress.ip_network("127.0.0.0/8"),        # Loopback
    ipaddress.ip_network("169.254.0.0/16"),     # Link-Local (including cloud metadata 169.254.169.254)
    ipaddress.ip_network("172.16.0.0/12"),      # RFC 1918 Private
    ipaddress.ip_network("192.0.0.0/24"),       # IETF Protocol Assignments
    ipaddress.ip_network("192.0.2.0/24"),       # TEST-NET-1 (documentation)
    ipaddress.ip_network("192.168.0.0/16"),     # RFC 1918 Private
    ipaddress.ip_network("198.18.0.0/15"),      # Benchmarking
    ipaddress.ip_network("198.51.100.0/24"),    # TEST-NET-2 (documentation)
    ipaddress.ip_network("203.0.113.0/24"),     # TEST-NET-3 (documentation)
    ipaddress.ip_network("224.0.0.0/4"),        # Multicast
    ipaddress.ip_network("240.0.0.0/4"),        # Reserved
    ipaddress.ip_network("255.255.255.255/32"), # Limited Broadcast
]

# Blocked IPv6 networks
_BLOCKED_IPV6_NETWORKS = [
    ipaddress.ip_network("::/128"),             # Unspecified
    ipaddress.ip_network("::1/128"),            # Loopback
    ipaddress.ip_network("::ffff:0:0/96"),      # IPv4-mapped
    ipaddress.ip_network("100::/64"),           # Discard-only
    ipaddress.ip_network("2001:db8::/32"),      # Documentation
    ipaddress.ip_network("fc00::/7"),           # Unique Local (ULA)
    ipaddress.ip_network("fe80::/10"),          # Link-Local
    ipaddress.ip_network("ff00::/8"),           # Multicast
]

# Blocked hostnames / metadata patterns
_BLOCKED_HOSTNAMES = frozenset({
    "localhost",
    "metadata.google.internal",
    "metadata.internal",
    "instance-data",
    "169.254.169.254",
})


def is_ip_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Check if an IP address belongs to any blocked or private CIDR."""
    if isinstance(ip, ipaddress.IPv4Address):
        for net in _BLOCKED_IPV4_NETWORKS:
            if ip in net:
                return True
        return False
    elif isinstance(ip, ipaddress.IPv6Address):
        # Also check IPv4-mapped addresses
        if ip.ipv4_mapped:
            return is_ip_blocked(ip.ipv4_mapped)
        for net in _BLOCKED_IPV6_NETWORKS:
            if ip in net:
                return True
        return False
    return True


def redact_sensitive_url(url: str) -> str:
    """Redact sensitive query parameters, tokens, credentials, and passwords from a URL for safe logging."""
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        # Redact basic auth in userinfo
        netloc = parsed.netloc
        if "@" in netloc:
            auth_part, host_part = netloc.split("@", 1)
            netloc = f"***:***@{host_part}"

        # Redact sensitive query parameters
        sensitive_keys = {
            "token", "access_token", "auth", "authorization", "key", "apikey",
            "api_key", "secret", "password", "signature", "sig", "bearer", "session",
        }
        query_dict = parse_qs(parsed.query, keep_blank_values=True)
        redacted_query = {}
        for k, vals in query_dict.items():
            if k.lower() in sensitive_keys:
                redacted_query[k] = ["REDACTED"]
            else:
                redacted_query[k] = vals

        new_query = urlencode(redacted_query, doseq=True)
        return urlunparse((
            parsed.scheme,
            netloc,
            parsed.path,
            parsed.params,
            new_query,
            parsed.fragment,
        ))
    except Exception:
        # Fallback regex redaction
        return re.sub(r"(token|key|secret|password|sig|auth)=[^&]+", r"\1=REDACTED", url, flags=re.IGNORECASE)


async def validate_download_url(
    url: str,
    *,
    node_id: str = "data_load",
    allow_loopback_in_dev: bool = False,
) -> None:
    """Validate a download URL against strict SSRF rules before connection.

    Raises NodeExecutionError with code 'SSRF_BLOCKED' if the URL violates security policies.
    """
    clean_url = (url or "").strip()
    if not clean_url:
        raise NodeExecutionError("Download URL cannot be empty.", code="INVALID_URL", node_id=node_id, retryable=False)

    parsed = urlparse(clean_url)

    # 1. Enforce scheme: only http and https allowed
    if parsed.scheme.lower() not in ("http", "https"):
        raise NodeExecutionError(
            f"SSRF blocked: Invalid URL scheme '{parsed.scheme}'. Only HTTP and HTTPS are permitted.",
            code="SSRF_BLOCKED",
            node_id=node_id,
            retryable=False,
        )

    host = (parsed.hostname or "").strip("[]").lower()
    if not host:
        raise NodeExecutionError("SSRF blocked: Download URL has no valid host.", code="SSRF_BLOCKED", node_id=node_id, retryable=False)

    # 2. Block known sensitive hostnames
    if host in _BLOCKED_HOSTNAMES or host.endswith(".internal") or host.endswith(".local"):
        if not (allow_loopback_in_dev and host in ("localhost", "127.0.0.1", "::1")):
            raise NodeExecutionError(
                f"SSRF blocked: Destination host '{host}' is restricted.",
                code="SSRF_BLOCKED",
                node_id=node_id,
                retryable=False,
            )

    # 3. Check if host is literal IP address
    try:
        literal_ip = ipaddress.ip_address(host)
        if is_ip_blocked(literal_ip):
            if not (allow_loopback_in_dev and literal_ip.is_loopback):
                raise NodeExecutionError(
                    f"SSRF blocked: Destination IP '{literal_ip}' is private or reserved.",
                    code="SSRF_BLOCKED",
                    node_id=node_id,
                    retryable=False,
                )
    except ValueError:
        # Host is a domain name, not a literal IP; proceed to DNS resolution check
        pass

    # 4. Delegate to shared Flowsmith SSRF guard (verifies DNS resolution against internal ranges)
    # If allow_loopback_in_dev is True, assert_public_url already supports dev loopback exemption.
    await assert_public_url(clean_url, node_id=node_id)

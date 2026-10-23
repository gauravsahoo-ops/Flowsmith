"""Trusted-proxy aware client IP extraction.

``request.client.host`` is the proxy's address when the app sits behind a
reverse proxy. Blindly trusting ``X-Forwarded-For`` is worse: a direct client
can spoof it. Only honour forwarding headers when the immediate peer is in
``TRUSTED_PROXIES``; walk the forwarded chain from the right and return the
first untrusted hop.
"""

from __future__ import annotations

import ipaddress
from functools import lru_cache

from fastapi import Request

from app.config import get_settings


@lru_cache(maxsize=32)
def _trusted_networks(raw: str) -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    networks = []
    for item in (raw or "").split(","):
        item = item.strip()
        if not item:
            continue
        try:
            networks.append(ipaddress.ip_network(item, strict=False))
        except ValueError:
            continue
    return tuple(networks)


def _is_trusted(addr: ipaddress.IPv4Address | ipaddress.IPv6Address,
                networks: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]) -> bool:
    return any(addr.version == net.version and addr in net for net in networks)


def client_ip(request: Request) -> str:
    """Best available client address without trusting spoofable input."""
    peer = request.client.host if request.client is not None else "unknown"
    if peer == "unknown":
        return peer

    networks = _trusted_networks(get_settings().trusted_proxies)
    try:
        peer_addr = ipaddress.ip_address(peer)
    except ValueError:
        return peer
    if not networks or not _is_trusted(peer_addr, networks):
        return peer

    forwarded = request.headers.get("x-forwarded-for", "")
    hops = [h.strip() for h in forwarded.split(",") if h.strip()]
    real_ip = (request.headers.get("x-real-ip") or "").strip()
    if not hops and real_ip:
        hops = [real_ip]

    # X-Forwarded-For is ordered client-first. Append the immediate peer and
    # walk right-to-left, skipping proxies we trust; the first address that is
    # not a trusted proxy is the effective client.
    for raw in reversed(hops):
        try:
            addr = ipaddress.ip_address(raw)
        except ValueError:
            continue
        if not _is_trusted(addr, networks):
            return str(addr)
    return peer

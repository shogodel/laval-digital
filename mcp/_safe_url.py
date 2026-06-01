import ipaddress
import socket
from urllib.parse import urlparse


def resolve_host(hostname: str) -> list[tuple[str, int]]:
    """Resolve a hostname to (ip, family) pairs, handling both IPv4 and IPv6."""
    try:
        result: list[tuple[str, int]] = []
        for family, _, _, _, sockaddr in socket.getaddrinfo(hostname, None):
            ip = sockaddr[0]
            if isinstance(ip, str):
                result.append((ip, family))
        return result
    except socket.gaierror:
        return []


def _ipv4_is_private(ip: str) -> bool:
    parts = [int(x) for x in ip.split(".")]
    if parts[0] in (127, 10, 0):
        return True
    if parts[0] == 169 and parts[1] == 254:
        return True
    if parts[0] == 192 and parts[1] == 168:
        return True
    if parts[0] == 172 and 16 <= parts[1] <= 31:
        return True
    return parts[0] == 100 and 64 <= parts[1] <= 127


def _ipv6_is_private(ip: str) -> bool:
    try:
        addr = ipaddress.IPv6Address(ip)
    except ipaddress.AddressValueError:
        return False
    return (
        addr.is_loopback
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_private
        or ip.startswith("2001:db8:")
    )


def is_safe_url(url: str) -> bool:
    """Block requests to private/reserved IPs (SSRF protection).

    Covers:
      - IPv4: loopback, RFC 1918, link-local, CGNAT
      - IPv6: loopback, link-local, multicast, unique-local (ULA),
              documentation prefix (2001:db8::/32)
      - Unresolvable hostnames are treated as unsafe.
    """
    hostname = urlparse(url).hostname or ""
    if not hostname:
        return False
    addrs = resolve_host(hostname)
    if not addrs:
        return False
    for ip, _ in addrs:
        if ":" in ip:
            if _ipv6_is_private(ip):
                return False
        else:
            if _ipv4_is_private(ip):
                return False
    return True


# Legacy alias for MCP server imports — do not use in new code.
_is_safe_url = is_safe_url


def is_safe_host(hostname: str) -> bool:
    """Check a bare hostname (without URL scheme) for SSRF safety."""
    if not hostname:
        return False
    addrs = resolve_host(hostname)
    if not addrs:
        return False
    for ip, _ in addrs:
        if ":" in ip:
            if _ipv6_is_private(ip):
                return False
        else:
            if _ipv4_is_private(ip):
                return False
    return True

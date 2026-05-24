import socket
from urllib.parse import urlparse


def _is_safe_url(url: str) -> bool:
    """Block requests to private/reserved IPs (SSRF protection)."""
    hostname = urlparse(url).hostname or ""
    try:
        addrs = socket.getaddrinfo(hostname, None)
        for _, _, _, _, sockaddr in addrs:
            ip = sockaddr[0]
            if ":" not in ip:
                parts = [int(x) for x in ip.split(".")]
                if parts[0] == 127 or parts[0] == 10 or parts[0] == 0:
                    return False
                if parts[0] == 169 and parts[1] == 254:
                    return False
                if parts[0] == 192 and parts[1] == 168:
                    return False
                if parts[0] == 172 and 16 <= parts[1] <= 31:
                    return False
            else:
                if ip.startswith("::1") or ip.startswith("fc") or ip.startswith("fd") or ip.startswith("fe80"):
                    return False
        return True
    except socket.gaierror:
        return False

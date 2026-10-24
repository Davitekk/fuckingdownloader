"""Keep random people on the public page from using the server to poke at
your LAN / docker network (SSRF)."""
import asyncio
import ipaddress
import socket
from urllib.parse import urlparse


class BlockedURL(ValueError):
    pass


def _is_private(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    return (
        addr.is_private or addr.is_loopback or addr.is_link_local
        or addr.is_multicast or addr.is_reserved or addr.is_unspecified
    )


async def check_url(url: str, allow_private: bool) -> str:
    url = url.strip()
    p = urlparse(url)
    if p.scheme not in ("http", "https"):
        raise BlockedURL("Only http(s) links, buddy.")
    if not p.hostname:
        raise BlockedURL("That's not a link.")
    if allow_private:
        return url
    host = p.hostname
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise BlockedURL(f"Can't resolve {host}.")
    for info in infos:
        if _is_private(info[4][0]):
            raise BlockedURL("Private/internal addresses are blocked.")
    return url

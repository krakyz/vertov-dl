"""A SOCKS5 gateway: public IPs only, ports 80/443, pinned DNS resolution.

Every target, including extractor redirects and CDN requests, passes this gate.
The upstream receives an IP address, so it cannot re-resolve a public name to LAN.
This is an application boundary, not a container/kernel sandbox.
"""

import asyncio
import ipaddress
import socket
import struct
from urllib.parse import urlsplit


def public_ip(value: str) -> bool:
    address = ipaddress.ip_address(value)
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        return public_ip(str(address.ipv4_mapped))
    if isinstance(address, ipaddress.IPv6Address) and (
        address.sixtofour or address.teredo or address not in ipaddress.ip_network("2000::/3")
    ):
        return False
    return address.is_global and not address.is_multicast and not address.is_reserved


async def public_addresses(host: str) -> list[str]:
    try:
        ipaddress.ip_address(host)
        addresses = [host]
    except ValueError:
        records = await asyncio.wait_for(
            asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM), 8
        )
        addresses = list(dict.fromkeys(record[4][0] for record in records))
    # Reject mixed public/private answers rather than picking just a safe member.
    if not addresses or not all(public_ip(address) for address in addresses):
        raise ValueError("Private/reserved target blocked")
    return sorted(addresses, key=lambda address: ":" in address)


async def read_address(reader):
    kind = (await reader.readexactly(1))[0]
    if kind == 1:
        return socket.inet_ntop(socket.AF_INET, await reader.readexactly(4))
    if kind == 4:
        return socket.inet_ntop(socket.AF_INET6, await reader.readexactly(16))
    if kind == 3:
        length = (await reader.readexactly(1))[0]
        return (await reader.readexactly(length)).decode("ascii")
    raise ValueError("Unsupported address")


class Gateway:
    def __init__(self, upstream: str):
        self.upstream = urlsplit(upstream)
        self.server = None
        self.tasks = set()
        self.limit = asyncio.Semaphore(32)

    async def start(self, port=0):
        self.server = await asyncio.start_server(self.accept, "127.0.0.1", port)
        return self.server.sockets[0].getsockname()[1]

    async def stop(self):
        self.server.close()
        await self.server.wait_closed()
        tasks = list(self.tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def accept(self, reader, writer):
        current = asyncio.current_task()
        self.tasks.add(current)
        peer = None
        try:
            async with self.limit:
                upstream_reader, peer = await asyncio.wait_for(self.connect(reader, writer), 20)

                async def pump(source, destination):
                    while chunk := await asyncio.wait_for(source.read(65536), 90):
                        destination.write(chunk)
                        await destination.drain()

                pumps = [
                    asyncio.create_task(pump(reader, peer)),
                    asyncio.create_task(pump(upstream_reader, writer)),
                ]
                try:
                    await asyncio.wait(pumps, return_when=asyncio.FIRST_COMPLETED)
                finally:
                    for task in pumps:
                        task.cancel()
                    await asyncio.gather(*pumps, return_exceptions=True)
        except (TimeoutError, OSError, ValueError, UnicodeError, asyncio.IncompleteReadError):
            # No raw hostnames/URLs or upstream errors in application logs.
            writer.write(b"\x05\x02\x00\x01" + b"\x00" * 6)
        finally:
            writer.close()
            if peer:
                peer.close()
            self.tasks.discard(current)

    async def connect(self, reader, writer):
        version, count = await reader.readexactly(2)
        methods = await reader.readexactly(count)
        if version != 5 or 0 not in methods:
            raise ValueError("SOCKS5 no-auth required")
        writer.write(b"\x05\x00")
        await writer.drain()
        if await reader.readexactly(3) != b"\x05\x01\x00":
            raise ValueError("CONNECT only")
        host = await read_address(reader)
        port = struct.unpack("!H", await reader.readexactly(2))[0]
        if port not in (80, 443):
            raise ValueError("Target port blocked")
        addresses = await public_addresses(host)
        for address in addresses[:4]:
            peer = None
            try:
                upstream_reader, peer = await asyncio.wait_for(
                    asyncio.open_connection(self.upstream.hostname, self.upstream.port), 5
                )
                peer.write(b"\x05\x01\x00")
                await peer.drain()
                if await upstream_reader.readexactly(2) != b"\x05\x00":
                    raise ValueError("Upstream SOCKS5 unavailable")
                ip = ipaddress.ip_address(address)
                peer.write(
                    b"\x05\x01\x00"
                    + bytes([1 if ip.version == 4 else 4])
                    + ip.packed
                    + struct.pack("!H", port)
                )
                await peer.drain()
                reply = await asyncio.wait_for(upstream_reader.readexactly(3), 8)
                if reply != b"\x05\x00\x00":
                    raise OSError("Upstream rejected target")
                await read_address(upstream_reader)
                await upstream_reader.readexactly(2)
                writer.write(b"\x05\x00\x00\x01" + b"\x00" * 6)
                await writer.drain()
                return upstream_reader, peer
            except asyncio.CancelledError:
                if peer:
                    peer.close()
                raise
            except (TimeoutError, OSError, ValueError, asyncio.IncompleteReadError):
                if peer:
                    peer.close()
        raise OSError("No reachable public target")

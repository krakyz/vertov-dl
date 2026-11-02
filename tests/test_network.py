import asyncio
import socket
import struct

import pytest
from media_loader import network


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.1",
        "192.168.31.1",
        "169.254.169.254",
        "100.64.0.1",
        "0.0.0.0",
        "::1",
        "fc00::1",
        "::ffff:127.0.0.1",
        "224.0.0.1",
    ],
)
def test_reserved_targets(address):
    assert not network.public_ip(address)


async def test_rejects_mixed_dns_answers(monkeypatch):
    loop = asyncio.get_running_loop()

    async def resolve(*args, **kwargs):
        return [
            (socket.AF_INET, 1, 6, "", ("1.1.1.1", 0)),
            (socket.AF_INET, 1, 6, "", ("127.0.0.1", 0)),
        ]

    monkeypatch.setattr(loop, "getaddrinfo", resolve)
    with pytest.raises(ValueError):
        await network.public_addresses("mixed.example")


async def test_gateway_pins_public_ip_and_relays(monkeypatch):
    captured = []

    async def upstream(reader, writer):
        assert await reader.readexactly(3) == b"\x05\x01\x00"
        writer.write(b"\x05\x00")
        await writer.drain()
        assert await reader.readexactly(3) == b"\x05\x01\x00"
        captured.append(await network.read_address(reader))
        assert struct.unpack("!H", await reader.readexactly(2))[0] == 443
        writer.write(b"\x05\x00\x00\x01" + b"\x00" * 6)
        await writer.drain()
        writer.write(await reader.readexactly(4))
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(upstream, "127.0.0.1", 0)

    async def resolve(host):
        return ["1.1.1.1"]

    monkeypatch.setattr(network, "public_addresses", resolve)
    gateway = network.Gateway(f"socks5h://127.0.0.1:{server.sockets[0].getsockname()[1]}")
    port = await gateway.start()
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(b"\x05\x01\x00")
        await writer.drain()
        assert await reader.readexactly(2) == b"\x05\x00"
        name = b"public.example"
        writer.write(b"\x05\x01\x00\x03" + bytes([len(name)]) + name + struct.pack("!H", 443))
        await writer.drain()
        assert await reader.readexactly(10) == b"\x05\x00\x00\x01" + b"\x00" * 6
        writer.write(b"test")
        await writer.drain()
        assert await reader.readexactly(4) == b"test"
        assert captured == ["1.1.1.1"]
        writer.close()
    finally:
        await gateway.stop()
        server.close()
        await server.wait_closed()


async def test_private_target_is_blocked_before_upstream():
    gateway = network.Gateway("socks5h://127.0.0.1:1")
    port = await gateway.start()
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(b"\x05\x01\x00")
        await writer.drain()
        await reader.readexactly(2)
        writer.write(b"\x05\x01\x00\x01\x7f\x00\x00\x01\x00\x50")
        await writer.drain()
        assert (await reader.readexactly(10))[1] == 2
        writer.close()
    finally:
        await gateway.stop()

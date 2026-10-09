"""
Asyncio UDP transport for the LIFX LAN protocol.

A single datagram endpoint is shared by discovery, state queries and colour streaming.
Requests are matched to replies by ``(serial, sequence)``; fire-and-forget sends (the
streaming path) never wait and never block the event loop.
"""

from __future__ import annotations

import asyncio
import logging
import random
import socket
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field

from .constants import LIFX_PORT, MessageType
from .protocol import BROADCAST_TARGET, Header, decode_header, encode_message

LOGGER = logging.getLogger(__name__)

DEFAULT_TIMEOUT_S = 0.5
DEFAULT_RETRIES = 3

# Called for every received packet: (header, payload, (host, port)).
PacketListener = Callable[[Header, bytes, tuple[str, int]], None]


@dataclass
class _PendingRequest:
    """An in-flight request waiting for replies."""

    response_types: frozenset[int]
    future: asyncio.Future[list[tuple[Header, bytes]]]
    # Number of replies to collect before resolving (multi-packet responses).
    expected: int = 1
    replies: list[tuple[Header, bytes]] = field(default_factory=list)


class _Protocol(asyncio.DatagramProtocol):
    """Forwards datagrams to the owning transport."""

    def __init__(self, owner: LifxTransport) -> None:
        self._owner = owner

    def datagram_received(self, data: bytes, addr: tuple[str | int, int]) -> None:
        self._owner._on_datagram(data, (str(addr[0]), int(addr[1])))  # noqa: SLF001

    def error_received(self, exc: Exception) -> None:
        LOGGER.debug("LIFX UDP error: %s", exc)


class LifxTransport:
    """Shared UDP endpoint for talking to LIFX devices."""

    def __init__(self, source: int | None = None) -> None:
        """
        Initialize the transport (no socket is opened until :meth:`open`).

        :param source: Client identifier stamped on every packet; random when omitted.
        """
        # 0 and 1 make devices broadcast their replies, so keep the source above that.
        self.source = source if source is not None else random.randint(2, 0xFFFFFFFF)  # noqa: S311
        self._transport: asyncio.DatagramTransport | None = None
        self._sequence = 0
        self._pending: dict[tuple[str, int], _PendingRequest] = {}
        self._listeners: list[PacketListener] = []

    @property
    def is_open(self) -> bool:
        """Return True while the UDP socket is open."""
        return self._transport is not None and not self._transport.is_closing()

    async def open(self, local_addr: tuple[str, int] = ("0.0.0.0", 0)) -> None:  # noqa: S104
        """
        Open the UDP socket (idempotent).

        :param local_addr: Local address to bind; an ephemeral port by default.
        """
        if self.is_open:
            return
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.setblocking(False)  # noqa: FBT003
        sock.bind(local_addr)
        loop = asyncio.get_running_loop()
        transport, _ = await loop.create_datagram_endpoint(lambda: _Protocol(self), sock=sock)
        self._transport = transport

    def close(self) -> None:
        """Close the socket and fail every pending request."""
        if self._transport is not None:
            self._transport.close()
            self._transport = None
        for pending in self._pending.values():
            if not pending.future.done():
                pending.future.cancel()
        self._pending.clear()

    def add_listener(self, listener: PacketListener) -> Callable[[], None]:
        """
        Register a callback for every received packet (used by discovery).

        :param listener: Callback receiving ``(header, payload, addr)``.
        :return: A function that removes the listener again.
        """
        self._listeners.append(listener)

        def _remove() -> None:
            with suppress(ValueError):
                self._listeners.remove(listener)

        return _remove

    def send(
        self,
        host: str,
        msg_type: int,
        payload: bytes = b"",
        *,
        target: bytes = BROADCAST_TARGET,
        port: int = LIFX_PORT,
        res_required: bool = False,
        ack_required: bool = False,
    ) -> int:
        """
        Send a packet without waiting for anything (non-blocking).

        :param host: Device IP or broadcast address.
        :param msg_type: Message type number.
        :param payload: Encoded payload.
        :param target: 8-byte device target.
        :param port: Destination UDP port.
        :param res_required: Ask for a State reply.
        :param ack_required: Ask for an Acknowledgement.
        :return: The sequence number used.
        """
        if self._transport is None:
            msg = "LIFX transport is not open"
            raise RuntimeError(msg)
        sequence = self._next_sequence()
        packet = encode_message(
            msg_type,
            payload,
            source=self.source,
            sequence=sequence,
            target=target,
            res_required=res_required,
            ack_required=ack_required,
        )
        self._transport.sendto(packet, (host, port))
        return sequence

    async def request(
        self,
        host: str,
        target: bytes,
        msg_type: int,
        payload: bytes = b"",
        *,
        response_types: tuple[int, ...],
        port: int = LIFX_PORT,
        expected: int = 1,
        timeout: float = DEFAULT_TIMEOUT_S,
        retries: int = DEFAULT_RETRIES,
    ) -> list[tuple[Header, bytes]]:
        """
        Send a request to one device and wait for its reply (with retries).

        :param host: Device IP.
        :param target: 8-byte device target.
        :param msg_type: Request message type.
        :param payload: Encoded payload.
        :param response_types: Message types accepted as a reply.
        :param port: Device UDP port.
        :param expected: Number of reply packets to collect (multi-packet responses).
        :param timeout: Seconds to wait per attempt.
        :param retries: Number of attempts before giving up.
        :raises TimeoutError: When no (complete) reply arrived in any attempt.
        """
        serial = target[:6].hex()
        ack_only = response_types == (MessageType.ACKNOWLEDGEMENT,)
        loop = asyncio.get_running_loop()
        for _attempt in range(max(1, retries)):
            future: asyncio.Future[list[tuple[Header, bytes]]] = loop.create_future()
            sequence = self.send(
                host,
                msg_type,
                payload,
                target=target,
                port=port,
                res_required=not ack_only,
                ack_required=ack_only,
            )
            key = (serial, sequence)
            self._pending[key] = _PendingRequest(
                response_types=frozenset(response_types), future=future, expected=expected
            )
            try:
                return await asyncio.wait_for(future, timeout)
            except TimeoutError:
                pending = self._pending.get(key)
                # A partial multi-packet reply is still useful (e.g. fewer zones than asked).
                if pending is not None and pending.replies and expected > 1:
                    return list(pending.replies)
            finally:
                self._pending.pop(key, None)
        msg = f"No reply from LIFX device {serial} at {host} to message {msg_type}"
        raise TimeoutError(msg)

    def _next_sequence(self) -> int:
        self._sequence = (self._sequence + 1) & 0xFF
        return self._sequence

    def _on_datagram(self, data: bytes, addr: tuple[str, int]) -> None:
        try:
            header = decode_header(data)
        except ValueError:
            return
        if header.source != self.source:
            return
        payload = data[36 : header.size] if header.size <= len(data) else data[36:]
        for listener in list(self._listeners):
            try:
                listener(header, payload, addr)
            except Exception:
                LOGGER.exception("LIFX packet listener failed")
        pending = self._pending.get((header.serial, header.sequence))
        if pending is None or pending.future.done():
            return
        if header.type == MessageType.STATE_UNHANDLED:
            pending.future.set_exception(
                NotImplementedError(f"Device {header.serial} does not support this message")
            )
            return
        if header.type not in pending.response_types:
            return
        pending.replies.append((header, payload))
        if len(pending.replies) >= pending.expected:
            pending.future.set_result(list(pending.replies))

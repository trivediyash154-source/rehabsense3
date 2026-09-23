"""Per-leg connection and stream-health tracking.

A leg is only ever reported CONNECTED while a socket is genuinely open. The
backend never infers a connection from the presence of data alone, and a
disconnect is a normal event that pauses analytics for that leg rather than
ending the session.
"""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field


class ConnectionState(str, enum.Enum):
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    DEGRADED = "DEGRADED"
    DISCONNECTED = "DISCONNECTED"


@dataclass
class LegConnection:
    """Health of one leg's stream within one session."""

    leg: str
    state: ConnectionState = ConnectionState.DISCONNECTED
    device_id: str | None = None
    device_pk: int | None = None
    firmware_version: str | None = None
    protocol_version: int | None = None
    simulated: bool = False
    capabilities: list[str] = field(default_factory=list)

    packets_received: int = 0
    packets_dropped: int = 0
    samples_dropped: int = 0
    sequence_gaps: int = 0
    samples_received: int = 0
    last_seq: int | None = None
    last_packet_at: float | None = None
    first_connected_at: float | None = None
    connected_seconds: float = 0.0
    latency_ms: float | None = None

    _connected_since: float | None = field(default=None, init=False)

    # A stream that has not delivered a packet in this long is degraded,
    # even though the socket may still be nominally open.
    stale_after_s: float = 2.0

    @property
    def fsr_available(self) -> bool:
        return "fsr" in self.capabilities

    def connect(self, *, device_id: str, firmware: str, protocol: int,
                capabilities: list[str], simulated: bool, now: float | None = None) -> None:
        now = now if now is not None else time.time()
        self.device_id = device_id
        self.firmware_version = firmware
        self.protocol_version = protocol
        self.capabilities = capabilities
        self.simulated = simulated
        self.state = ConnectionState.CONNECTED
        self._connected_since = now
        if self.first_connected_at is None:
            self.first_connected_at = now
        # A reconnect resumes the same leg; sequence numbering restarts.
        self.last_seq = None

    def disconnect(self, now: float | None = None) -> None:
        now = now if now is not None else time.time()
        if self._connected_since is not None:
            self.connected_seconds += max(0.0, now - self._connected_since)
            self._connected_since = None
        self.state = ConnectionState.DISCONNECTED

    def observe_packet(
        self,
        first_seq: int | None,
        last_seq: int | None,
        sample_count: int,
        now: float | None = None,
    ) -> None:
        """Record a delivered packet and detect loss.

        `seq` is a per-*sample* counter (see the packet schema), so a packet
        carrying N samples advances it by N. Loss is therefore a gap between
        the previous packet's last sample and this packet's first sample —
        comparing packet-to-packet would report every batch of N as N-1
        losses.
        """
        now = now if now is not None else time.time()
        self.packets_received += 1
        self.samples_received += sample_count
        self.last_packet_at = now
        if self.state is not ConnectionState.CONNECTED:
            self.state = ConnectionState.CONNECTED
            if self._connected_since is None:
                self._connected_since = now

        if first_seq is None or last_seq is None:
            return
        if self.last_seq is not None and first_seq > self.last_seq + 1:
            missing = first_seq - self.last_seq - 1
            self.samples_dropped += missing
            self.sequence_gaps += 1
            # Report loss in packet-equivalents so the ratio stays meaningful.
            self.packets_dropped += max(1, round(missing / max(1, sample_count)))
        self.last_seq = last_seq

    def tick(self, now: float | None = None) -> None:
        """Mark a silent-but-open stream as degraded."""
        now = now if now is not None else time.time()
        if self.state is ConnectionState.CONNECTED and self.last_packet_at is not None:
            if now - self.last_packet_at > self.stale_after_s:
                self.state = ConnectionState.DEGRADED

    def live_connected_seconds(self, now: float | None = None) -> float:
        now = now if now is not None else time.time()
        total = self.connected_seconds
        if self._connected_since is not None:
            total += max(0.0, now - self._connected_since)
        return total

    @property
    def delivery_ratio(self) -> float:
        total = self.packets_received + self.packets_dropped
        return 1.0 if total == 0 else self.packets_received / total

    def as_dict(self, now: float | None = None) -> dict:
        return {
            "leg": self.leg,
            "state": self.state.value,
            "device_id": self.device_id,
            "simulated": self.simulated,
            "firmware_version": self.firmware_version,
            "protocol_version": self.protocol_version,
            "capabilities": list(self.capabilities),
            "fsr_available": self.fsr_available,
            "packets_received": self.packets_received,
            "packets_dropped": self.packets_dropped,
            "samples_dropped": self.samples_dropped,
            "sequence_gaps": self.sequence_gaps,
            "samples_received": self.samples_received,
            "delivery_ratio": round(self.delivery_ratio, 4),
            "connected_seconds": round(self.live_connected_seconds(now), 2),
            "last_packet_at": self.last_packet_at,
        }

"""Minimal streaming pcap reader + L2/L3 address extraction. No dependencies.

Handles the classic libpcap global header (any endianness / µs or ns, incl. the
``a1 b2 cd 34`` variant the FRITZ!Box emits) and per-record headers. Only the
first ~40 bytes of each frame are inspected, so a small capture snaplen is fine.
"""
from __future__ import annotations

import ipaddress
import struct
from typing import Iterator, List, Tuple, Union

Net = Union[ipaddress.IPv4Network, ipaddress.IPv6Network]


class PcapError(Exception):
    pass


# magic (any endianness) -> (struct endianness, per-record header size).
# 0xa1b2c3d4 / 0xa1b23c4d = classic pcap, 16-byte record header.
# 0xa1b2cd34 = "modified" pcap (patched tcpdump; what FRITZ!OS emits), which
# inserts ifindex/protocol/pkt_type/pad after the 16 standard bytes -> 24.
_MAGICS = {
    b"\xa1\xb2\xc3\xd4": (">", 16),
    b"\xd4\xc3\xb2\xa1": ("<", 16),
    b"\xa1\xb2\x3c\x4d": (">", 16),
    b"\x4d\x3c\xb2\xa1": ("<", 16),
    b"\xa1\xb2\xcd\x34": (">", 24),
    b"\x34\xcd\xb2\xa1": ("<", 24),
}


def _hdr(magic: bytes) -> Tuple[str, int]:
    try:
        return _MAGICS[magic]
    except KeyError:
        raise PcapError(f"not a pcap stream (magic {magic.hex()})") from None


class PcapStream:
    """Feed bytes with :meth:`feed`; iterate ``(orig_len, frame)`` tuples."""

    def __init__(self) -> None:
        self._buf = bytearray()
        self._endian = ""
        self._rec_hdr = 16

    def feed(self, data: bytes) -> Iterator[Tuple[int, bytes]]:
        self._buf.extend(data)
        if not self._endian:
            if len(self._buf) < 24:
                return
            self._endian, self._rec_hdr = _hdr(bytes(self._buf[:4]))
            del self._buf[:24]  # drop global header
        rec = struct.Struct(self._endian + "IIII")
        hdr = self._rec_hdr
        while len(self._buf) >= hdr:
            _ts, _tf, incl_len, orig_len = rec.unpack_from(self._buf, 0)
            if incl_len > 262144 or orig_len > 262144:  # sanity: desync
                raise PcapError("record length out of range — stream desync")
            if len(self._buf) < hdr + incl_len:
                return
            frame = bytes(self._buf[hdr : hdr + incl_len])
            del self._buf[: hdr + incl_len]
            yield orig_len, frame


_VLAN = 0x8100
_IPV4 = 0x0800
_IPV6 = 0x86DD


def frame_endpoints(frame: bytes) -> Tuple[str, str]:
    """Return (src_ip, dst_ip) as strings, or ("","") for non-IP frames."""
    if len(frame) < 14:
        return "", ""
    etype = int.from_bytes(frame[12:14], "big")
    off = 14
    if etype == _VLAN:
        if len(frame) < 18:
            return "", ""
        etype = int.from_bytes(frame[16:18], "big")
        off = 18
    if etype == _IPV4:
        if len(frame) < off + 20:
            return "", ""
        return (
            str(ipaddress.IPv4Address(frame[off + 12 : off + 16])),
            str(ipaddress.IPv4Address(frame[off + 16 : off + 20])),
        )
    if etype == _IPV6:
        if len(frame) < off + 40:
            return "", ""
        return (
            str(ipaddress.IPv6Address(frame[off + 8 : off + 24])),
            str(ipaddress.IPv6Address(frame[off + 24 : off + 40])),
        )
    return "", ""


def classify(
    frame: bytes, orig_len: int, nets: List[Net]
) -> List[Tuple[str, str, int]]:
    """Return [(local_ip, "tx"|"rx", bytes), ...] for the local hosts in `frame`.

    tx = local host is the source (upload), rx = local host is the destination.
    """
    src, dst = frame_endpoints(frame)
    if not src:
        return []
    out: List[Tuple[str, str, int]] = []
    try:
        src_a = ipaddress.ip_address(src)
        dst_a = ipaddress.ip_address(dst)
    except ValueError:
        return []
    if any(src_a in n for n in nets):
        out.append((src, "tx", orig_len))
    if any(dst_a in n for n in nets):
        out.append((dst, "rx", orig_len))
    return out


# --- L4 / traffic category (heuristic — everything is 443 these days) -----
def frame_l4(frame: bytes) -> Tuple[int, int, int]:
    """Return (ip_proto, src_port, dst_port). Ports 0 for non-TCP/UDP."""
    if len(frame) < 14:
        return 0, 0, 0
    etype = int.from_bytes(frame[12:14], "big")
    off = 14
    if etype == _VLAN and len(frame) >= 18:
        etype = int.from_bytes(frame[16:18], "big")
        off = 18
    if etype == _IPV4:
        if len(frame) < off + 20:
            return 0, 0, 0
        ihl = (frame[off] & 0x0F) * 4
        proto = frame[off + 9]
        l4 = off + ihl
    elif etype == _IPV6:
        if len(frame) < off + 40:
            return 0, 0, 0
        proto = frame[off + 6]
        l4 = off + 40
    else:
        return 0, 0, 0
    if proto in (6, 17) and len(frame) >= l4 + 4:
        return (
            proto,
            int.from_bytes(frame[l4 : l4 + 2], "big"),
            int.from_bytes(frame[l4 + 2 : l4 + 4], "big"),
        )
    return proto, 0, 0


_PORT_CAT = {
    53: "dns",
    853: "dns",
    80: "web",
    443: "web",
    25: "mail",
    465: "mail",
    587: "mail",
    993: "mail",
    995: "mail",
    110: "mail",
    143: "mail",
    22: "remote",
    3389: "remote",
    5900: "remote",
    1194: "vpn",
    51820: "vpn",
    500: "vpn",
    4500: "vpn",
    1701: "vpn",
    123: "ntp",
    5228: "push",
    5223: "push",
}
_GAME_RANGES = (
    (27000, 27100),
    (3074, 3075),
    (3478, 3480),
    (6672, 6672),
    (9000, 9010),
    (3658, 3658),
    (30000, 45000),
)


def category(proto: int, sport: int, dport: int) -> str:
    port = min((p for p in (sport, dport) if 0 < p < 1024), default=0) or dport or sport
    if proto == 17 and 443 in (sport, dport):
        return "quic"  # UDP/443 — mostly video / Google / Meta
    if port in _PORT_CAT:
        return _PORT_CAT[port]
    if any(lo <= port <= hi for lo, hi in _GAME_RANGES) and proto == 17:
        return "gaming"
    if proto == 17 and sport > 1024 and dport > 1024:
        return "p2p/rtc"
    return "other"


def classify_flows(
    frame: bytes, orig_len: int, nets: List[Net]
) -> List[Tuple[str, str, str, int]]:
    """Like :func:`classify` but adds a traffic category:
    [(local_ip, "tx"|"rx", category, bytes), ...]."""
    base = classify(frame, orig_len, nets)
    if not base:
        return []
    cat = category(*frame_l4(frame))
    return [(ip, direction, cat, n) for ip, direction, n in base]

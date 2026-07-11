import hashlib
import os
import socket
import struct
import time

import boto3
from botocore.config import Config

MAGIC = b"\xf9\xbe\xb4\xd9"  # Bitcoin mainnet magic bytes

cloudwatch = boto3.client(
    "cloudwatch", config=Config(connect_timeout=5, read_timeout=10)
)

_NAMESPACE = "BitcoinNode"
_NODE_ID = os.environ["NODE_ID"]
_HOSTNAME = os.environ["IP_PROVIDER_HOSTNAME"]
_PORT = int(os.environ.get("BITCOIN_PORT", "8333"))

type Response = dict[str, int | str]


def lambda_handler(event: dict, _context: object) -> Response:
    reachable = _check(_HOSTNAME, _PORT)
    _put_metric(reachable)
    return {"reachable": reachable}


def _check(hostname: str, port: int) -> bool:
    try:
        ip = socket.gethostbyname(hostname)
        with socket.create_connection((ip, port), timeout=10) as sock:
            sock.sendall(_version_message(ip, port))
            return _wait_for_verack(sock)
    except Exception as e:
        print(f"Reachability check failed: {e}")
        return False


def _version_message(ip: str, port: int) -> bytes:
    version = 70015
    services = 1
    timestamp = int(time.time())
    addr_recv = _net_addr(ip, port)
    addr_from = _net_addr("0.0.0.0", 0)
    nonce = struct.pack("<Q", int.from_bytes(os.urandom(8), "little"))
    user_agent_str = b"/Satoshi:30.2.0/"
    user_agent = bytes([len(user_agent_str)]) + user_agent_str
    start_height = struct.pack("<i", 0)

    payload = (
        struct.pack("<i", version)
        + struct.pack("<Q", services)
        + struct.pack("<q", timestamp)
        + addr_recv
        + addr_from
        + nonce
        + user_agent
        + start_height
    )
    return _message(b"version", payload)


def _net_addr(ip: str, port: int) -> bytes:
    services = struct.pack("<Q", 1)
    ip_bytes = b"\x00" * 10 + b"\xff\xff" + socket.inet_aton(ip)
    port_bytes = struct.pack(">H", port)
    return services + ip_bytes + port_bytes


def _message(command: bytes, payload: bytes) -> bytes:
    cmd = command.ljust(12, b"\x00")
    length = struct.pack("<I", len(payload))
    checksum = hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
    return MAGIC + cmd + length + checksum + payload


def _wait_for_verack(sock: socket.socket) -> bool:
    buf = b""
    # Read until we find a verack/version header or give up after 4096 bytes or
    # 10 seconds of wall-clock time. The deadline shrinks the per-recv timeout so
    # a peer dribbling one byte per recv cannot hold the loop open until the
    # Lambda timeout kills the function before the metric is emitted.
    # Note: this is a substring scan, not a framed parse — the header bytes could
    # in theory appear inside another message's payload. Acceptable for a liveness
    # probe; a hostile peer forging such a payload still proves the port is open.
    verack_cmd = MAGIC + b"verack\x00\x00\x00\x00\x00\x00"
    version_cmd = MAGIC + b"version\x00\x00\x00\x00\x00"
    deadline = time.monotonic() + 10
    while len(buf) < 4096:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        sock.settimeout(remaining)
        chunk = sock.recv(256)
        if not chunk:
            break
        buf += chunk
        if verack_cmd in buf or version_cmd in buf:
            return True
    return False


def _emit_metric(metric_name: str, value: float, node_id: str) -> None:
    cloudwatch.put_metric_data(
        Namespace=_NAMESPACE,
        MetricData=[
            {
                "MetricName": metric_name,
                "Dimensions": [{"Name": "NodeId", "Value": node_id}],
                "Value": value,
                "Unit": "Count",
            }
        ],
    )


def _put_metric(reachable: bool) -> None:
    _emit_metric("NodeReachable", 1.0 if reachable else 0.0, _NODE_ID)

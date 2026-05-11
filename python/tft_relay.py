#!/usr/bin/env python3
"""
TCP fan-out relay for ESP8266 TFT terminals.

Your display program connects to this relay as if it were one TFT terminal.
The relay forwards each newline-delimited JSON command to every configured
ESP8266 terminal running the firmware in src/main.ino.

Protocol:
  client -> relay: {"cmd":"text",...}\n
  relay -> client: {"ok":true,"targets":{...}}\n

Edit TARGETS below, then run:
  python tft_relay.py
"""

from __future__ import annotations

import argparse
import json
import socket
import threading
import time
from dataclasses import dataclass
from typing import Any


LISTEN_HOST = "0.0.0.0"
LISTEN_PORT = 9999

# Change these to the IP addresses of your ESP8266 TFT terminals.
TARGETS = {
    "left": ("192.168.1.41", 8888),
    "center": ("192.168.1.42", 8888),
    "right": ("192.168.1.43", 8888),
}

CONNECT_TIMEOUT_SEC = 3.0
RESPONSE_TIMEOUT_SEC = 5.0
RECONNECT_DELAY_SEC = 1.0
MAX_LINE_BYTES = 4096


@dataclass
class TargetResult:
    ok: bool
    response: Any | None = None
    error: str | None = None

    def as_json(self) -> dict[str, Any]:
        if self.ok:
            return {"ok": True, "response": self.response}
        return {"ok": False, "error": self.error or "unknown error"}


class TftTarget:
    def __init__(self, name: str, host: str, port: int):
        self.name = name
        self.host = host
        self.port = port
        self.sock: socket.socket | None = None
        self.reader = None
        self.lock = threading.Lock()
        self.last_connect_attempt = 0.0

    def close(self) -> None:
        if self.reader:
            try:
                self.reader.close()
            except OSError:
                pass
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass
        self.reader = None
        self.sock = None

    def connect(self) -> None:
        now = time.monotonic()
        if now - self.last_connect_attempt < RECONNECT_DELAY_SEC:
            raise ConnectionError("reconnect delay active")

        self.close()
        self.last_connect_attempt = now

        sock = socket.create_connection(
            (self.host, self.port),
            timeout=CONNECT_TIMEOUT_SEC,
        )
        sock.settimeout(RESPONSE_TIMEOUT_SEC)
        reader = sock.makefile("r", encoding="utf-8", newline="\n")

        # Firmware sends an initial info line after connect.
        greeting = reader.readline()
        if not greeting:
            raise ConnectionError("connected but received no greeting")

        self.sock = sock
        self.reader = reader
        print(f"[{self.name}] connected to {self.host}:{self.port}: {greeting.strip()}")

    def send_line(self, line: bytes) -> TargetResult:
        with self.lock:
            try:
                if self.sock is None or self.reader is None:
                    self.connect()

                assert self.sock is not None
                assert self.reader is not None

                self.sock.sendall(line)
                raw_response = self.reader.readline()
                if not raw_response:
                    raise ConnectionError("connection closed before response")

                try:
                    response = json.loads(raw_response)
                except json.JSONDecodeError:
                    response = raw_response.strip()

                target_ok = isinstance(response, dict) and response.get("ok") is True
                if not target_ok:
                    return TargetResult(ok=False, response=response, error="target returned error")
                return TargetResult(ok=True, response=response)

            except Exception as exc:
                self.close()
                return TargetResult(ok=False, error=str(exc))


class RelayServer:
    def __init__(self, listen_host: str, listen_port: int, targets: dict[str, tuple[str, int]]):
        self.listen_host = listen_host
        self.listen_port = listen_port
        self.targets = {
            name: TftTarget(name, host, port)
            for name, (host, port) in targets.items()
        }

    def serve_forever(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind((self.listen_host, self.listen_port))
            server.listen()
            print(f"Relay listening on {self.listen_host}:{self.listen_port}")
            print("Targets:")
            for name, target in self.targets.items():
                print(f"  {name}: {target.host}:{target.port}")

            while True:
                conn, addr = server.accept()
                thread = threading.Thread(
                    target=self.handle_client,
                    args=(conn, addr),
                    daemon=True,
                )
                thread.start()

    def handle_client(self, conn: socket.socket, addr: tuple[str, int]) -> None:
        print(f"[client] connected from {addr[0]}:{addr[1]}")
        with conn:
            conn.settimeout(None)
            reader = conn.makefile("rb")
            writer = conn.makefile("wb")

            self.write_json(writer, {
                "info": "ESP8266 TFT relay ready",
                "targets": list(self.targets.keys()),
            })

            while True:
                line = reader.readline(MAX_LINE_BYTES + 1)
                if not line:
                    break
                if len(line) > MAX_LINE_BYTES:
                    self.write_json(writer, {
                        "ok": False,
                        "error": f"command line too long > {MAX_LINE_BYTES} bytes",
                    })
                    continue
                if line in (b"\n", b"\r\n"):
                    continue

                result = self.forward_to_targets(line)
                self.write_json(writer, result)

        print(f"[client] disconnected from {addr[0]}:{addr[1]}")

    def forward_to_targets(self, line: bytes) -> dict[str, Any]:
        try:
            json.loads(line)
        except json.JSONDecodeError as exc:
            return {"ok": False, "error": f"JSON parse error before relay: {exc}"}

        results: dict[str, TargetResult] = {}
        threads: list[threading.Thread] = []

        def send_one(target: TftTarget) -> None:
            results[target.name] = target.send_line(line)

        for target in self.targets.values():
            thread = threading.Thread(target=send_one, args=(target,))
            thread.start()
            threads.append(thread)

        for thread in threads:
            thread.join()

        target_json = {
            name: result.as_json()
            for name, result in results.items()
        }
        return {
            "ok": all(result.ok for result in results.values()),
            "targets": target_json,
        }

    @staticmethod
    def write_json(writer, obj: dict[str, Any]) -> None:
        writer.write(json.dumps(obj, separators=(",", ":")).encode("utf-8") + b"\n")
        writer.flush()


def parse_target(value: str) -> tuple[str, tuple[str, int]]:
    try:
        name, address = value.split("=", 1)
        host, port_text = address.rsplit(":", 1)
        port = int(port_text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected NAME=HOST:PORT") from exc

    if not name:
        raise argparse.ArgumentTypeError("target name must not be empty")
    return name, (host, port)


def main() -> None:
    parser = argparse.ArgumentParser(description="TCP fan-out relay for ESP8266 TFT terminals")
    parser.add_argument("--host", default=LISTEN_HOST, help="listen host, default: %(default)s")
    parser.add_argument("--port", type=int, default=LISTEN_PORT, help="listen port, default: %(default)s")
    parser.add_argument(
        "--target",
        action="append",
        type=parse_target,
        help="target as NAME=HOST:PORT; can be used more than once",
    )
    args = parser.parse_args()

    targets = dict(args.target) if args.target else TARGETS
    if not targets:
        raise SystemExit("configure at least one target")

    RelayServer(args.host, args.port, targets).serve_forever()


if __name__ == "__main__":
    main()

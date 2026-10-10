"""Thin anvil-fork client: cached reads/traces, snapshots, impersonation, storage writes.

Every eth_call / debug_traceCall result is cached on disk keyed by (fork block, setup id, request),
so the demo replays offline if the RPC dies.
"""
from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from eth_abi import decode, encode
from eth_utils import keccak, to_checksum_address
from web3 import Web3

from core.schemas import stable_hash

load_dotenv()
ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "cache"


class DiskCache:
    def __init__(self, name: str):
        self.dir = CACHE / name
        self.dir.mkdir(parents=True, exist_ok=True)

    def get(self, key: str):
        p = self.dir / f"{key}.json"
        return json.loads(p.read_text()) if p.exists() else None

    def put(self, key: str, value):
        (self.dir / f"{key}.json").write_text(json.dumps(value))
        return value


def selector(sig: str) -> bytes:
    return keccak(text=sig)[:4]


class Fork:
    def __init__(self, url: str | None = None, offline: bool = False):
        self.url = url or os.getenv("ANVIL_URL", "http://127.0.0.1:8545")
        self.w3 = Web3(Web3.HTTPProvider(self.url, request_kwargs={"timeout": 300}))
        self.offline = offline or not self._alive()
        self.fork_block = None if self.offline else self.w3.eth.block_number
        self.setup_id = "base"                # changes when we mutate state (approve, storage writes)
        self.calls = DiskCache("calls")
        self.traces = DiskCache("traces")

    def _alive(self) -> bool:
        try:
            return self.w3.is_connected()
        except Exception:
            return False

    # ---------- raw RPC ----------
    def rpc(self, method: str, params: list):
        for attempt in range(6):         # the fork's upstream (Alchemy free tier) rate-limits bursts with HTTP 429
            r = self.w3.provider.make_request(method, params)
            if "error" in r and "429" in str(r["error"]) and attempt < 5:
                time.sleep(3 * (attempt + 1))
                continue
            break
        if "error" in r:
            raise RuntimeError(f"{method}: {r['error']}")
        return r["result"]

    # ---------- cached reads ----------
    def eth_call(self, to: str, data: bytes | str, sender: str | None = None) -> bytes | None:
        """Returns raw return bytes, or None on revert / no code. Cached."""
        data_hex = data if isinstance(data, str) else "0x" + data.hex()
        tx = {"to": to_checksum_address(to), "data": data_hex}
        if sender:
            tx["from"] = to_checksum_address(sender)
        key = stable_hash([self.fork_block, self.setup_id, tx])
        hit = self.calls.get(key)
        if hit is not None:
            return bytes.fromhex(hit["out"][2:]) if hit["ok"] else None
        if self.offline:
            return None
        try:
            out = self.rpc("eth_call", [tx, "latest"])
            self.calls.put(key, {"ok": True, "out": out})
            return bytes.fromhex(out[2:])
        except RuntimeError:
            self.calls.put(key, {"ok": False, "out": "0x"})
            return None

    def call(self, to: str, sig: str, args_types: list[str] | None = None, args: list | None = None,
             out_types: list[str] | None = None):
        """call('0x..', 'balanceOf(address)', ['address'], [x], ['uint256']) -> decoded tuple or None."""
        data = selector(sig) + (encode(args_types, args) if args_types else b"")
        raw = self.eth_call(to, data)
        if raw is None or (out_types and len(raw) < 32 * len(out_types)):
            return None
        if not out_types:
            return raw
        try:
            return decode(out_types, raw)
        except Exception:
            return None

    def call1(self, to: str, sig: str, out_type: str, args_types=None, args=None):
        r = self.call(to, sig, args_types, args, [out_type])
        return r[0] if r else None

    def block_timestamp(self) -> int:
        key = stable_hash(["block_ts", self.fork_block])
        hit = self.calls.get(key)
        if hit is not None:
            return hit
        return self.calls.put(key, self.w3.eth.get_block(self.fork_block)["timestamp"])

    def code_size(self, addr: str) -> int:
        key = stable_hash(["code", self.fork_block, addr.lower()])
        hit = self.calls.get(key)
        if hit is not None:
            return hit
        if self.offline:
            return 0
        code = self.w3.eth.get_code(to_checksum_address(addr))
        return self.calls.put(key, len(code))

    def storage(self, addr: str, slot: int | bytes) -> bytes:
        slot_hex = hex(slot) if isinstance(slot, int) else "0x" + slot.hex()
        key = stable_hash(["sload", self.fork_block, self.setup_id, addr.lower(), slot_hex])
        hit = self.calls.get(key)
        if hit is not None:
            return bytes.fromhex(hit[2:])
        if self.offline:
            return b"\x00" * 32
        v = self.rpc("eth_getStorageAt", [to_checksum_address(addr), slot_hex, "latest"])
        self.calls.put(key, v)
        return bytes.fromhex(v[2:].rjust(64, "0"))

    # ---------- traces ----------
    def trace_call(self, tx: dict, tracer: str, label: str) -> dict:
        tx = {k: v for k, v in tx.items() if v is not None}
        key = stable_hash([self.fork_block, self.setup_id, tx, tracer])
        hit = self.traces.get(key)
        if hit is not None:
            return hit["result"]
        if self.offline:
            raise RuntimeError(f"offline and no cached trace for {label}")
        cfg = {"tracer": tracer}
        if tracer == "prestateTracer":
            cfg["tracerConfig"] = {"diffMode": False}
        res = self.rpc("debug_traceCall", [tx, "latest", cfg])
        self.traces.put(key, {"label": label, "tracer": tracer, "fork_block": self.fork_block, "result": res})
        return res

    # ---------- state mutation (always inside snapshot()) ----------
    @contextmanager
    def snapshot(self):
        if self.offline:
            prev = self.setup_id
            yield
            self.setup_id = prev
            return
        snap = self.rpc("evm_snapshot", [])
        prev = self.setup_id
        try:
            yield
        finally:
            self.rpc("evm_revert", [snap])
            self.setup_id = prev

    def mark_setup(self, tag: str):
        self.setup_id = stable_hash([self.setup_id, tag])

    def send(self, sender: str, to: str, data: bytes | str, gas: int = 3_000_000) -> dict:
        data_hex = data if isinstance(data, str) else "0x" + data.hex()
        tag = f"send{sender.lower()}{to.lower()}{data_hex}"
        # the outcome is cached so an offline replay takes the same branch (a reverted tx leaves the setup unchanged)
        okey = stable_hash(["send", self.fork_block, self.setup_id, tag])
        if self.offline:
            hit = self.calls.get(okey)
            if hit is not None and not hit["ok"]:
                raise RuntimeError(f"setup tx reverted (cached): {sender}->{to} {data_hex[:10]}")
            self.mark_setup(tag)
            return {}
        sender = to_checksum_address(sender)
        self.rpc("anvil_impersonateAccount", [sender])
        self.rpc("anvil_setBalance", [sender, hex(10**20)])
        h = self.rpc("eth_sendTransaction", [{"from": sender, "to": to_checksum_address(to), "data": data_hex,
                                              "gas": hex(gas)}])
        for attempt in range(6):         # only the receipt poll is retried: the tx itself is never re-sent
            try:
                rcpt = self.w3.eth.wait_for_transaction_receipt(h)
                break
            except Exception as e:
                if "429" not in str(e) or attempt == 5:
                    raise
                time.sleep(3 * (attempt + 1))
        self.calls.put(okey, {"ok": rcpt["status"] == 1})
        if rcpt["status"] != 1:
            raise RuntimeError(f"setup tx reverted: {sender}->{to} {data_hex[:10]}")
        self.mark_setup(tag)
        return rcpt

    def set_storage(self, addr: str, slot: int | bytes, value: int):
        slot_hex = "0x" + (slot.to_bytes(32, "big") if isinstance(slot, int) else slot).hex()
        if not self.offline:
            self.rpc("anvil_setStorageAt", [to_checksum_address(addr), slot_hex, "0x" + value.to_bytes(32, "big").hex()])
        self.mark_setup(f"sstore{addr}{slot_hex}{value}")

    def set_code(self, addr: str, code_hex: str):
        if not self.offline:
            self.rpc("anvil_setCode", [to_checksum_address(addr), code_hex])
        self.mark_setup(f"code{addr.lower()}{code_hex}")

    def pin_price(self, oracle: str, price: int):
        """Replace a Morpho oracle with code that returns `price` for any call (PUSH32 p; MSTORE; RETURN 32)."""
        self.set_code(oracle, "0x7f" + price.to_bytes(32, "big").hex() + "60005260206000f3")

    def fund_erc20(self, token: str, holder: str, amount: int, max_slot: int = 80) -> int:
        """Set balanceOf(holder)=amount by brute-forcing the balances mapping slot. Returns the slot."""
        holder_b = bytes.fromhex(holder[2:].lower().rjust(64, "0"))
        if self.offline:
            self.mark_setup(f"fund{token}{holder}{amount}")
            return -1
        for s in range(max_slot):
            for layout in ("sol", "vy"):
                sb = s.to_bytes(32, "big")
                slot = keccak(holder_b + sb) if layout == "sol" else keccak(sb + holder_b)
                orig = int.from_bytes(self.storage(token, slot), "big")
                self.rpc("anvil_setStorageAt", [to_checksum_address(token), "0x" + slot.hex(),
                                                "0x" + amount.to_bytes(32, "big").hex()])
                bal = self.w3.eth.call({"to": to_checksum_address(token),
                                        "data": "0x" + (selector("balanceOf(address)") + holder_b).hex()})
                if int.from_bytes(bal, "big") == amount:
                    self.mark_setup(f"fund{token}{holder}{amount}")
                    return s
                self.rpc("anvil_setStorageAt", [to_checksum_address(token), "0x" + slot.hex(),
                                                "0x" + orig.to_bytes(32, "big").hex()])
        raise RuntimeError(f"balance slot not found for {token}")

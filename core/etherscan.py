"""Etherscan v2 source/ABI lookup (names + ABI for getter enumeration). Cached forever on disk."""
from __future__ import annotations

import json
import os
import time

import requests

from core.fork import DiskCache

_cache = DiskCache("etherscan")
_last = [0.0]


def contract_info(address: str, chain_id: int = 1) -> dict:
    """{'name': str|None, 'abi': list|None, 'proxy': bool, 'implementation': str|None}"""
    addr = address.lower()
    hit = _cache.get(f"{chain_id}_{addr}")
    if hit is not None:
        return hit
    key = os.getenv("ETHERSCAN_API_KEY")
    if not key:
        return {"name": None, "abi": None, "proxy": False, "implementation": None}
    wait = 0.22 - (time.time() - _last[0])   # free tier: 5 req/s
    if wait > 0:
        time.sleep(wait)
    _last[0] = time.time()
    try:
        r = requests.get("https://api.etherscan.io/v2/api", timeout=30, params={
            "chainid": chain_id, "module": "contract", "action": "getsourcecode",
            "address": addr, "apikey": key}).json()
        res = r["result"][0] if isinstance(r.get("result"), list) else None
    except Exception:
        return {"name": None, "abi": None, "proxy": False, "implementation": None}
    if res is None:   # rate limited or error: do not cache
        return {"name": None, "abi": None, "proxy": False, "implementation": None}
    abi = None
    if res.get("ABI") and not res["ABI"].startswith("Contract source code not verified"):
        try:
            abi = json.loads(res["ABI"])
        except Exception:
            abi = None
    info = {"name": res.get("ContractName") or None, "abi": abi,
            "proxy": res.get("Proxy") == "1", "implementation": (res.get("Implementation") or None)}
    return _cache.put(f"{chain_id}_{addr}", info)


def get_logs(address: str, topic0: str, from_block: int, to_block: int, chain_id: int = 1) -> list[dict]:
    """Event history via Etherscan (Alchemy free tier caps eth_getLogs at 10 blocks). Cached, paginated."""
    ck = f"logs_{chain_id}_{address.lower()}_{topic0[:10]}_{from_block}_{to_block}"
    hit = _cache.get(ck)
    if hit is not None:
        return hit
    key = os.getenv("ETHERSCAN_API_KEY")
    out, page = [], 1
    while key:
        wait = 0.22 - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
        r = requests.get("https://api.etherscan.io/v2/api", timeout=60, params={
            "chainid": chain_id, "module": "logs", "action": "getLogs", "address": address,
            "topic0": topic0, "fromBlock": from_block, "toBlock": to_block, "page": page,
            "offset": 1000, "apikey": key}).json()
        res = r.get("result")
        if not isinstance(res, list):
            if r.get("message") == "No records found":
                break
            return out            # error / rate limit: do not cache a partial answer
        out += res
        if len(res) < 1000:
            break
        page += 1
    return _cache.put(ck, out)

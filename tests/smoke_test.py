"""Smoke test: is the fork alive, can we read an oracle, can we trace a call?"""
import json, os
from dotenv import load_dotenv
from web3 import Web3

load_dotenv()
w3 = Web3(Web3.HTTPProvider(os.getenv("ANVIL_URL", "http://127.0.0.1:8545")))
assert w3.is_connected(), "Anvil is not running: start it in the other terminal"
print("✅ Connected to fork. Block:", w3.eth.block_number)

# Chainlink ETH/USD price feed (mainnet)
FEED = Web3.to_checksum_address("0x5f4eC3Df9cbd43714FE2740f5E3616155c5b8419")
call = {"to": FEED, "data": "0xfeaf968c"}  # selector of latestRoundData()

raw = w3.eth.call(call)
answer = int.from_bytes(raw[32:64], "big", signed=True)
print(f"✅ Oracle read: ETH/USD = {answer / 1e8:,.2f}")

# 1) callTracer: which contracts does this call touch?
r = w3.provider.make_request("debug_traceCall", [call, "latest", {"tracer": "callTracer"}])
if "error" in r:
    print("❌ callTracer error:", r["error"])
else:
    def walk(node, depth=0):
        print("   " * depth + f"→ {node.get('to')}  ({node.get('type')})")
        for child in node.get("calls", []):
            walk(child, depth + 1)
    print("✅ callTracer (dependency tree):")
    walk(r["result"])

# 2) prestateTracer: which storage slots are read?
r = w3.provider.make_request("debug_traceCall", [call, "latest", {"tracer": "prestateTracer"}])
if "error" in r:
    print("⚠️ prestateTracer not supported by anvil:", r["error"]["message"])
    print("   → fallback: call debug_traceCall directly on ETH_RPC_URL (Alchemy)")
else:
    print(f"✅ prestateTracer: {len(r['result'])} contracts with state read")
    print(json.dumps(r["result"], indent=1)[:800])
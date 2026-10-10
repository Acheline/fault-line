"""Interface probing: classify an address by which well-known selectors it answers."""
from __future__ import annotations

from eth_utils import keccak

from core.etherscan import contract_info
from core.fork import Fork
from core.schemas import NodeType

EIP1967_IMPL = int.from_bytes(keccak(text="eip1967.proxy.implementation"), "big") - 1
EIP1967_ADMIN = int.from_bytes(keccak(text="eip1967.proxy.admin"), "big") - 1
EIP1967_BEACON = int.from_bytes(keccak(text="eip1967.proxy.beacon"), "big") - 1
EIP1822_PROXIABLE = int.from_bytes(keccak(text="PROXIABLE"), "big")
OZ_LEGACY_IMPL = int.from_bytes(keccak(text="org.zeppelinos.proxy.implementation"), "big")


def _addr(word: bytes) -> str | None:
    a = "0x" + word[-20:].hex()
    return None if int(a, 16) == 0 else a


def canonical_type(inp: dict) -> str:
    t = inp["type"]
    if t.startswith("tuple"):
        return "(" + ",".join(canonical_type(c) for c in inp["components"]) + ")" + t[5:]
    return t


def abi_selectors(abi: list | None) -> dict[str, str]:
    out = {}
    for f in abi or []:
        if f.get("type") == "function":
            sig = f"{f['name']}({','.join(canonical_type(i) for i in f.get('inputs', []))})"
            out["0x" + keccak(text=sig)[:4].hex()] = f["name"]
    return out


def proxy_info(fork: Fork, addr: str) -> dict:
    impl = _addr(fork.storage(addr, EIP1967_IMPL)) or _addr(fork.storage(addr, EIP1822_PROXIABLE)) \
        or _addr(fork.storage(addr, OZ_LEGACY_IMPL))
    beacon = _addr(fork.storage(addr, EIP1967_BEACON))
    if not impl and beacon:
        impl = fork.call1(beacon, "implementation()", "address")
    admin = _addr(fork.storage(addr, EIP1967_ADMIN))
    return {"implementation": impl.lower() if impl else None, "admin": admin, "beacon": beacon}


def probe(fork: Fork, addr: str) -> dict:
    """Returns {'type', 'label', 'tags', 'props', 'abi', 'impl_abi'}."""
    tags: set[str] = set()
    props: dict = {}
    if fork.code_size(addr) == 0:
        return {"type": NodeType.GOVERNANCE, "label": f"EOA {addr[:8]}", "tags": {"eoa"}, "props": {},
                "abi": None, "selectors": {}}

    info = contract_info(addr)
    px = proxy_info(fork, addr)
    impl_info = contract_info(px["implementation"]) if px["implementation"] else None
    if px["implementation"]:
        tags.add("proxy")
        props["implementation"] = px["implementation"]
        if px["admin"]:
            props["proxy_admin"] = px["admin"]
    abi = (impl_info or {}).get("abi") or info.get("abi")
    name = ((impl_info or {}).get("name") or info.get("name")) or None
    if info.get("name") and impl_info and impl_info.get("name"):
        name = f"{impl_info['name']}" if info["name"] in ("TransparentUpgradeableProxy", "ERC1967Proxy",
                                                           "BeaconProxy", "InitializableImmutableAdminUpgradeabilityProxy") \
            else info["name"]
    props["contract_name"] = name
    sels = abi_selectors(abi)
    sels.update(abi_selectors(info.get("abi")))

    c = fork.call1
    symbol = c(addr, "symbol()", "string")
    decimals = c(addr, "decimals()", "uint8")
    is_erc20 = symbol is not None and decimals is not None and c(addr, "totalSupply()", "uint256") is not None
    if is_erc20:
        props.update(symbol=symbol, decimals=decimals)
    label = symbol or name or addr[:10]
    lname = (name or "").lower()

    threshold = c(addr, "getThreshold()", "uint256")
    owners = fork.call(addr, "getOwners()", out_types=["address[]"])
    min_delay = c(addr, "getMinDelay()", "uint256")
    if min_delay is None:
        min_delay = c(addr, "delay()", "uint256") if "timelock" in lname else None

    rd = fork.call(addr, "latestRoundData()", out_types=["uint80", "int256", "uint256", "uint256", "uint80"])
    morpho_price = c(addr, "price()", "uint256")
    pendle_tokens = fork.call(addr, "readTokens()", out_types=["address", "address", "address"])

    if threshold is not None and owners is not None:
        t = NodeType.GOVERNANCE
        tags.add("safe")
        props.update(threshold=threshold, owners=[o.lower() for o in owners[0]], n_owners=len(owners[0]))
        label = f"Safe {threshold}/{len(owners[0])} {addr[:8]}"
    elif min_delay is not None:
        t = NodeType.GOVERNANCE
        tags.add("timelock")
        props["min_delay_s"] = min_delay
        label = f"{name or 'Timelock'} ({min_delay/3600:.1f}h)"
    elif pendle_tokens is not None:
        t = NodeType.LIQUIDITY_VENUE
        tags.add("pendle_market")
        props.update(sy=pendle_tokens[0].lower(), pt=pendle_tokens[1].lower(), yt=pendle_tokens[2].lower())
        label = f"Pendle market {symbol or ''}".strip() if not name else f"{name} {addr[:8]}"
    elif not is_erc20 and (rd is not None or morpho_price is not None or "oracle" in lname or "aggregator" in lname):
        t = NodeType.ORACLE
        if rd is not None:
            tags.add("chainlink_interface")
            props.update(answer=rd[1], updated_at=rd[3])
            desc = c(addr, "description()", "string")
            if desc:
                props["description"] = desc
                label = f"{desc} ({name or 'feed'})"
            if rd[3] == 0:
                tags.add("no_update_timestamp")
        if morpho_price is not None:
            tags.add("morpho_oracle_interface")
            props["price"] = morpho_price
        if "lineardiscount" in lname:
            tags.add("fixed_schedule")
        if "dummy" in lname or "dummy" in (props.get("description") or "").lower():
            tags.add("fixed_price")
        label = label if label != addr[:10] else (name or "oracle")
    elif any(len(fork.call(addr, s) or b"") >= 64 for s in ("slot0()", "getReserves()")) \
            or c(addr, "coins(uint256)", "address", ["uint256"], [0]) is not None \
            or any(k in lname for k in ("pool", "pair", "poolmanager", "balancervault")):
        t = NodeType.LIQUIDITY_VENUE
        label = f"{name or 'pool'} {symbol or addr[:8]}"
    elif c(addr, "adaptersLength()", "uint256") is not None or (c(addr, "MORPHO()", "address") and c(addr, "curator()", "address")):
        t = NodeType.VAULT
        tags.add("morpho_vault_v2" if c(addr, "adaptersLength()", "uint256") is not None else "metamorpho")
    elif c(addr, "idToMarketParams(bytes32)", "address", ["bytes32"], [b"\x00" * 32]) is not None:
        t = NodeType.CONTRACT
        tags.add("morpho_blue")
        label = "Morpho Blue"
    elif is_erc20:
        t = NodeType.ASSET
        under = c(addr, "asset()", "address")
        if under and c(addr, "convertToAssets(uint256)", "uint256", ["uint256"], [10**18]) is not None:
            tags.add("erc4626")
            props["underlying"] = under.lower()
        if c(addr, "SY()", "address") and c(addr, "expiry()", "uint256"):
            tags.add("pendle_pt")
            props["expiry"] = c(addr, "expiry()", "uint256")
        if c(addr, "yieldToken()", "address") and c(addr, "exchangeRate()", "uint256"):
            tags.add("pendle_sy")
            props["exchange_rate"] = c(addr, "exchangeRate()", "uint256")
    else:
        t = NodeType.CONTRACT
        label = name or addr[:10]
    return {"type": t, "label": label, "tags": tags, "props": props, "abi": abi, "selectors": sels}

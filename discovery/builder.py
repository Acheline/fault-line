"""Turn executed critical-path traces into a typed dependency graph, then resolve every touched
address recursively (proxy -> implementation/admin -> owner -> Safe/timelock; stored address getters)."""
from __future__ import annotations

import re
from collections import defaultdict

from core.fork import Fork
from core.schemas import (PATH_EDGE, CriticalPath, DependencyGraph, Edge, EdgeType, Node, NodeType,
                          Provenance)
from discovery.classify import probe

PRECOMPILE_MAX = 0x1_0000

GOV_GETTERS = re.compile(r"^(owner|admin|getAdmin|governance|gov|guardian|curator|timelock|pauser|"
                         r"blacklister|masterMinter|rescuer|sentinel|emergencyAdmin|DEFAULT_ADMIN)$", re.I)
PRICE_GETTERS = re.compile(r"(oracle|feed|aggregator|priceSource|source|primary|backup)", re.I)
WRAP_GETTERS = re.compile(r"^(SY|yieldToken|asset|underlying|UNDERLYING|UNDERLYING_ASSET|token|PT|stakedToken)$")
ISSUE_GETTERS = re.compile(r"^(minter|MINTER|issuer|mintingContract)$")
SKIP_GETTERS = re.compile(r"(^WETH|^weth|^wNative|permit2|PERMIT2|^factory$|^YT$|feeRecipient|treasury)", re.I)


def mark_implementation(node: Node):
    """Logic contract behind a proxy / library: code, not an economic layer."""
    node.tags.add("implementation")
    node.props["probed_type"] = node.type.value
    node.type = NodeType.CONTRACT


def _is_precompile(a: str) -> bool:
    return int(a, 16) < PRECOMPILE_MAX


class GraphBuilder:
    def __init__(self, fork: Fork, position_id: str, root_label: str):
        self.fork = fork
        self.g = DependencyGraph(position_id=position_id, fork_block=fork.fork_block or 0)
        self.root = f"position:{position_id}"
        self.g.add_node(Node(id=self.root, type=NodeType.POSITION, label=root_label))
        self.probed: dict[str, dict] = {}
        self.storage_reads: dict[str, dict[str, int]] = defaultdict(dict)   # addr -> path -> n slots
        self.selectors: dict[str, dict[str, str]] = {}
        self.touched: dict[str, set[str]] = defaultdict(set)    # call_id -> addresses executed

    # ------------------------------------------------------------------ nodes
    def ensure(self, addr: str, prov: Provenance, path: CriticalPath | None = None) -> Node:
        addr = addr.lower()
        if addr not in self.probed:
            self.probed[addr] = probe(self.fork, addr)
            self.selectors[addr] = self.probed[addr]["selectors"]
        p = self.probed[addr]
        node = Node(id=addr, type=p["type"], label=p["label"], address=addr, tags=set(p["tags"]),
                    props=dict(p["props"]), provenance=[prov], paths={path} if path else set())
        return self.g.add_node(node)

    def fn_name(self, addr: str, sel: str) -> str:
        return self.selectors.get(addr.lower(), {}).get(sel, sel)

    # ------------------------------------------------------------------ traces
    def ingest_trace(self, call_trace: dict, prestate: dict, path: CriticalPath, call_id: str,
                     entry_src: str | None = None):
        """entry_src: graph node that 'owns' the top-level call (defaults to the position root)."""
        blk = self.fork.fork_block
        etype = PATH_EDGE[path]
        top_from = call_trace["from"].lower()

        def walk(fr: dict, parent: str):
            to = (fr.get("to") or "").lower()
            if not to or _is_precompile(to) or to == top_from:
                return
            prov = Provenance(source="trace", block=blk, call=call_id,
                              detail=f"{fr['type']} {fr.get('input', '0x')[:10]}")
            node = self.ensure(to, prov, path)
            self.touched[call_id].add(to)
            if fr["type"] == "DELEGATECALL":
                mark_implementation(node)
            src = parent
            sel = fr.get("input", "0x")[:10]
            et = EdgeType.DELEGATES_TO if fr["type"] == "DELEGATECALL" else etype
            if src != to:
                e = self.g.add_edge(Edge(src=src, dst=to, type=et, path=path, provenance=[prov]))
                fns = set(e.props.get("functions", []))
                fns.add(self.fn_name(to, sel))
                e.props["functions"] = sorted(fns)
                if fr.get("error"):
                    e.props["reverted"] = fr["error"]
            # delegatecall children execute in the caller's context; attribute them to the proxy
            next_parent = parent if fr["type"] == "DELEGATECALL" else to
            for ch in fr.get("calls", []) or []:
                walk(ch, next_parent)

        start = entry_src or self.root
        # the top-level frame's sender is our harness account: attach to the position root
        walk(call_trace, start)
        for addr, st in (prestate or {}).items():
            a = addr.lower()
            if _is_precompile(a) or a == top_from:
                continue
            n_slots = len((st or {}).get("storage", {}) or {})
            self.storage_reads[a][path.value] = n_slots
            if a in self.g.nodes:
                self.g.nodes[a].props.setdefault("storage_slots_read", {})[path.value] = n_slots
            elif (st or {}).get("code"):
                # touched only as state (balance/extcode/storage), never as a call target
                n = self.ensure(a, Provenance(source="storage", block=blk, call=call_id,
                                              detail=f"prestate: {n_slots} slots"), path)
                n.tags.add("state_only")
                n.props.setdefault("storage_slots_read", {})[path.value] = n_slots

    # ------------------------------------------------------------------ resolver
    def resolve(self, budget_by_path: dict[CriticalPath, int], max_nodes: int = 400):
        """Recursive resolution. Budget = how many getter hops to follow from a traced node.
        Governance chains (proxy admin -> owner -> Safe/timelock) are always followed to the end."""
        blk = self.fork.fork_block
        queue: list[tuple[str, int]] = []
        for nid, n in list(self.g.nodes.items()):
            if n.address:
                b = max([budget_by_path.get(p, 0) for p in n.paths] or [0])
                queue.append((nid, b))
        seen: set[str] = set()
        while queue and len(self.g.nodes) < max_nodes:
            nid, budget = queue.pop(0)
            if nid in seen:
                continue
            seen.add(nid)
            node = self.g.nodes[nid]
            if "eoa" in node.tags:
                continue
            # 1. proxy -> implementation, proxy -> admin
            impl = node.props.get("implementation")
            if impl:
                self.ensure(impl, Provenance(source="storage", block=blk, detail="EIP-1967/1822 implementation slot"))
                mark_implementation(self.g.nodes[impl])
                self.g.add_edge(Edge(src=nid, dst=impl, type=EdgeType.DELEGATES_TO,
                                     provenance=[Provenance(source="storage", block=blk, detail="EIP-1967 impl slot")]))
            admin = node.props.get("proxy_admin")
            if admin:
                self._gov_edge(nid, admin, "EIP-1967 admin slot", "storage")
                queue.append((admin.lower(), max(budget, 1)))
            # 2. Safe owners stay as props (count/threshold), timelock delay as props.
            # 3. zero-arg address getters from the verified ABI
            for fname in self._address_getters(nid):
                val = self.fork.call1(nid, f"{fname}()", "address")
                if not val or int(val, 16) == 0 or val.lower() == nid:
                    continue
                v = val.lower()
                if GOV_GETTERS.match(fname):
                    self._gov_edge(nid, v, f"{fname}()", "onchain_read")
                    queue.append((v, max(budget, 1)))       # governance chain: always follow
                    continue
                if budget <= 0 or SKIP_GETTERS.search(fname):
                    continue
                if ISSUE_GETTERS.match(fname):
                    et = EdgeType.ISSUED_BY
                elif WRAP_GETTERS.match(fname) and node.type != NodeType.ORACLE:
                    et = EdgeType.WRAPS
                elif PRICE_GETTERS.search(fname):
                    et = EdgeType.PRICES
                else:
                    et = EdgeType.REFERENCES
                if self.fork.code_size(v) == 0:
                    continue
                prov = Provenance(source="onchain_read", block=blk, detail=f"{fname}()")
                self.ensure(v, prov)
                self.g.add_edge(Edge(src=nid, dst=v, type=et, props={"getter": fname}, provenance=[prov]))
                queue.append((v, budget - 1))

    def read_params(self, nid: str, max_n: int = 40) -> dict:
        """All zero-arg uint/int/bool view getters of a contract (oracle thresholds, timelocks, discounts)."""
        abi = self.probed.get(nid, {}).get("abi") or []
        out = {}
        for f in abi:
            if f.get("type") != "function" or f.get("inputs") or f.get("stateMutability") not in ("view", "pure"):
                continue
            outs = f.get("outputs") or []
            if len(outs) == 1 and outs[0]["type"].rstrip("0123456789") in ("uint", "int", "bool"):
                v = self.fork.call1(nid, f"{f['name']}()", outs[0]["type"])
                if v is not None:
                    out[f["name"]] = v
            if len(out) >= max_n:
                break
        self.g.nodes[nid].props["params"] = out
        return out

    def _gov_edge(self, nid: str, gov: str, detail: str, source: str):
        prov = Provenance(source=source, block=self.fork.fork_block, detail=detail)
        gnode = self.ensure(gov, prov)
        if gnode.type not in (NodeType.GOVERNANCE,):
            gnode.tags.add("governance_role")
            if gnode.type == NodeType.CONTRACT:
                gnode.type = NodeType.GOVERNANCE
        e = self.g.add_edge(Edge(src=nid, dst=gov.lower(), type=EdgeType.GOVERNS, provenance=[prov]))
        roles = set(e.props.get("roles", []))
        roles.add(detail)
        e.props["roles"] = sorted(roles)

    def _address_getters(self, addr: str) -> list[str]:
        abi = self.probed.get(addr, {}).get("abi") or []
        out = []
        for f in abi:
            if f.get("type") != "function" or f.get("inputs") or f.get("stateMutability") not in ("view", "pure"):
                continue
            outs = f.get("outputs") or []
            if len(outs) == 1 and outs[0]["type"] == "address":
                out.append(f["name"])
        if not abi:   # unverified: probe a fixed list of common getters
            out = ["owner", "admin", "governance", "guardian", "asset", "underlying", "oracle", "aggregator"]
        return sorted(set(out))[:40]

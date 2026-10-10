"""Fault Line data model.

Edge direction convention (everywhere): src = the DEPENDENT, dst = the DEPENDENCY.
  PT --wraps--> SY            "PT wraps SY"
  proxy --governs--> Safe     "proxy is governed by Safe"
  USDe --backs--> CEX hedge   "USDe is backed by CEX hedge"
  market --prices--> oracle   "market is priced by oracle"
So "what does X depend on" = descendants(X), and depth = distance from the position root.
"""
from __future__ import annotations

import hashlib
import json
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class NodeType(str, Enum):
    CHAIN = "CHAIN"
    CONTRACT = "CONTRACT"
    ASSET = "ASSET"
    ORACLE = "ORACLE"
    LIQUIDITY_VENUE = "LIQUIDITY_VENUE"
    LENDING_MARKET = "LENDING_MARKET"
    VAULT = "VAULT"
    GOVERNANCE = "GOVERNANCE"
    ISSUER = "ISSUER"
    OFFCHAIN = "OFFCHAIN"
    POSITION = "POSITION"


class EdgeType(str, Enum):
    # critical-path edges (from execution traces)
    PRICES = "prices"
    EXIT_ROUTE = "exit_route"
    LIQUIDATION_ROUTE = "liquidation_route"
    # structural edges (from storage / interface reads / disclosures)
    GOVERNS = "governs"
    WRAPS = "wraps"
    BACKS = "backs"
    ALLOCATES_TO = "allocates_to"
    ISSUED_BY = "issued_by"
    DELEGATES_TO = "delegates_to"      # proxy -> implementation
    HOLDS = "holds"                    # position -> asset / market
    USES_COLLATERAL = "uses_collateral"
    LENDS = "lends"                    # lending market -> loan asset
    REFERENCES = "references"          # address stored in a contract, not on a traced path


class CriticalPath(str, Enum):
    VALUE = "value"
    EXIT = "exit"
    LIQUIDATION = "liquidation"


PATH_EDGE = {
    CriticalPath.VALUE: EdgeType.PRICES,
    CriticalPath.EXIT: EdgeType.EXIT_ROUTE,
    CriticalPath.LIQUIDATION: EdgeType.LIQUIDATION_ROUTE,
}

Source = Literal["trace", "storage", "onchain_read", "api", "dune", "disclosure", "assumption"]


class Provenance(BaseModel):
    source: Source
    block: int | None = None
    call: str | None = None          # critical-path call id, e.g. "exit:pendle_router.swap"
    detail: str | None = None        # selector, slot, getter name, query...
    url: str | None = None           # disclosure / API link
    confidence: float = 1.0          # 1.0 = read from executed code; lower for disclosures/assumptions


class Node(BaseModel):
    id: str                          # lowercased address, or "<kind>:<key>" for logical nodes
    type: NodeType
    label: str
    chain: str = "ethereum"
    address: str | None = None
    tags: set[str] = Field(default_factory=set)       # proxy, issuer_reported, fixed_schedule, offchain_disclosed, critical...
    paths: set[CriticalPath] = Field(default_factory=set)
    props: dict[str, Any] = Field(default_factory=dict)
    provenance: list[Provenance] = Field(default_factory=list)

    @property
    def is_critical(self) -> bool:
        return len(self.paths) >= 2


class Edge(BaseModel):
    src: str
    dst: str
    type: EdgeType
    path: CriticalPath | None = None
    props: dict[str, Any] = Field(default_factory=dict)
    provenance: list[Provenance] = Field(default_factory=list)

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.src, self.dst, self.type.value)


class IncidentFamily(str, Enum):
    """The brief's three incident families. Every shock carries one."""
    SECURITY_INCIDENT = "security_incident"
    MARKET_DISRUPTION = "market_disruption"
    TECHNICAL_FAILURE = "technical_failure"


class BelemKPI(str, Enum):
    """Belem's own track-record KPIs: results are reported under these labels."""
    SECURITY_INCIDENT = "security_incidents"
    COUNTERPARTY_DEFAULT = "counterparty_defaults"
    LIQUIDATION = "liquidations"


class ShockKind(str, Enum):
    ORACLE_BUMP = "oracle_bump"            # answer x (1+m)
    ORACLE_STALE = "oracle_stale"          # time advanced beyond heartbeat
    ORACLE_FROZEN = "oracle_frozen"        # answer pinned while underlying moves
    DEPEG = "depeg"                        # correlated pool + oracle move
    LIQUIDITY_REMOVAL = "liquidity_removal"
    NAV_MARKDOWN = "nav_markdown"
    REDEMPTION_GATE = "redemption_gate"
    ISSUER_DEFAULT = "issuer_default"
    UTILIZATION = "utilization"
    GOVERNANCE = "governance"
    VENUE_FAILURE = "venue_failure"        # parametric, off-chain


class Shock(BaseModel):
    id: str
    node_id: str
    kind: ShockKind
    magnitude: float                       # signed fraction (-0.05 = -5%) or kind-specific
    family: IncidentFamily
    kpi: BelemKPI | None = None            # which Belem KPI this shock would show up under
    params: dict[str, Any] = Field(default_factory=dict)
    correlated_with: list[str] = Field(default_factory=list)   # other shock ids applied together
    provenance: Provenance = Provenance(source="assumption")


class Result(BaseModel):
    shock_id: str
    position_id: str
    fork_block: int
    family: IncidentFamily | None = None
    kpi: BelemKPI | None = None
    mtm_change_usd: float | None = None
    exit_proceeds_usd: float | None = None
    withdrawable_usd: float | None = None
    liquidated: bool | None = None
    liquidation_penalty_usd: float | None = None
    bad_debt_usd: float | None = None
    loss_per_share: float | None = None
    time_to_impact_s: float | None = None
    raw: dict[str, Any] = Field(default_factory=dict)
    provenance: list[Provenance] = Field(default_factory=list)


class Action(str, Enum):
    STAY = "STAY"
    REDUCE = "REDUCE"
    EXIT = "EXIT"


class Headline(BaseModel):
    """The ONE number a PM acts on. net value of exiting now =
    (risk-adjusted expected loss avoided) - (measured exit cost). Positive = exit, negative = stay."""
    scope: str                              # position id, or "book"
    fork_block: int
    net_value_exit_usd: float
    net_value_exit_bps_book: float
    action: Action
    exit_fraction: float = 0.0              # x in "REDUCE x%" (1.0 = EXIT)
    expected_loss_avoided_usd: float        # E[L_stay] + lambda * (CVaR95 - E[L]) on the exited slice
    exit_cost_usd: float                    # C_exit(x, t=now), measured on the fork
    time_to_impact_s: float | None = None
    breakeven_belief: dict[str, Any] = Field(default_factory=dict)  # {"event": "full USDe depeg", "p_breakeven": .14, "p_est": .09}
    driver: str | None = None               # #1 dependency path by share of E[L]
    reason: list[str] = Field(default_factory=list)                # 3 plain-English lines naming the path
    exit_cost_curve: dict[str, float] = Field(default_factory=dict)  # {"0m": .., "15m": .., "1h": .., "6h": .., "24h": ..}
    provenance: list[Provenance] = Field(default_factory=list)


class DependencyGraph(BaseModel):
    position_id: str
    fork_block: int
    nodes: dict[str, Node] = Field(default_factory=dict)
    edges: dict[str, Edge] = Field(default_factory=dict)
    meta: dict[str, Any] = Field(default_factory=dict)

    def add_node(self, node: Node) -> Node:
        cur = self.nodes.get(node.id)
        if cur is None:
            self.nodes[node.id] = node
            return node
        # merge: keep the more specific type, union everything else
        if cur.type == NodeType.CONTRACT and node.type != NodeType.CONTRACT and "implementation" not in cur.tags:
            cur.type = node.type
        if cur.label.startswith("0x") and not node.label.startswith("0x"):
            cur.label = node.label
        cur.tags |= node.tags
        cur.paths |= node.paths
        cur.props.update({k: v for k, v in node.props.items() if k not in cur.props})
        cur.provenance += [p for p in node.provenance if p not in cur.provenance]
        return cur

    def add_edge(self, edge: Edge) -> Edge:
        k = "|".join(edge.key) + (f"|{edge.path.value}" if edge.path else "")
        cur = self.edges.get(k)
        if cur is None:
            self.edges[k] = edge
            return edge
        cur.props.update(edge.props)
        cur.provenance += [p for p in edge.provenance if p not in cur.provenance]
        return cur

    def to_json(self) -> str:
        return self.model_dump_json(indent=1)


def stable_hash(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:16]

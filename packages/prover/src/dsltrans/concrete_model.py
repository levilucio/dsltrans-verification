from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class ConcreteNode:
    """Concrete model node."""

    id: str
    class_name: str
    attrs: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ConcreteEdge:
    """Concrete typed edge (association instance)."""

    assoc_name: str
    source_id: str
    target_id: str


@dataclass(frozen=True)
class TraceLink:
    """Trace link from source node to target node."""

    source_id: str
    target_id: str


@dataclass
class ConcreteModel:
    """In-memory concrete model for runtime DSLTrans execution."""

    nodes: dict[str, ConcreteNode] = field(default_factory=dict)
    edges: set[ConcreteEdge] = field(default_factory=set)
    traces: set[TraceLink] = field(default_factory=set)
    _next_id: int = 1

    def generate_node_id(self, hint: str) -> str:
        node_id = f"{hint}_{self._next_id}"
        self._next_id += 1
        return node_id

    def ensure_node(self, node_id: str, class_name: str) -> ConcreteNode:
        existing = self.nodes.get(node_id)
        if existing is not None:
            if existing.class_name != class_name:
                raise ValueError(
                    f"Node {node_id} already exists as {existing.class_name}, cannot reuse as {class_name}"
                )
            return existing
        node = ConcreteNode(id=node_id, class_name=class_name, attrs={})
        self.nodes[node_id] = node
        return node

    def set_attr(self, node_id: str, attr_name: str, value: object) -> bool:
        node = self.nodes[node_id]
        old = node.attrs.get(attr_name)
        if old == value:
            return False
        node.attrs[attr_name] = value
        return True

    def add_edge(self, assoc_name: str, source_id: str, target_id: str) -> bool:
        edge = ConcreteEdge(assoc_name=assoc_name, source_id=source_id, target_id=target_id)
        if edge in self.edges:
            return False
        self.edges.add(edge)
        return True

    def has_edge(self, assoc_name: str, source_id: str, target_id: str) -> bool:
        return ConcreteEdge(assoc_name=assoc_name, source_id=source_id, target_id=target_id) in self.edges

    def add_trace(self, source_id: str, target_id: str) -> bool:
        trace = TraceLink(source_id=source_id, target_id=target_id)
        if trace in self.traces:
            return False
        self.traces.add(trace)
        return True

    def get_traced_targets(self, source_id: str, target_class: Optional[str] = None) -> list[str]:
        out: list[str] = []
        for tr in self.traces:
            if tr.source_id != source_id:
                continue
            if target_class is None:
                out.append(tr.target_id)
                continue
            node = self.nodes.get(tr.target_id)
            if node is not None and node.class_name == target_class:
                out.append(tr.target_id)
        out.sort()
        return out

    def snapshot(self) -> ConcreteModel:
        """Read-only copy of this model (e.g. target at layer start for backward-link resolution)."""
        other = ConcreteModel()
        other.nodes = dict(self.nodes)
        other.edges = set(self.edges)
        other.traces = set(self.traces)
        other._next_id = self._next_id
        return other

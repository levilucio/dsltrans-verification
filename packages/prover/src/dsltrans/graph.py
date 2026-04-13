"""
DSLTrans Path Condition Graph

Visualization support for path condition exploration results.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .model import Transformation, RuleId
from .path_condition import PathCondition


@dataclass
class PCNode:
    """Node in the path condition graph."""
    id: int
    pc: PathCondition
    rule_set_str: str
    vertex_count: int
    edge_count: int
    trace_count: int


@dataclass
class PCEdge:
    """Edge in the path condition graph (derivation step)."""
    source: int
    target: int
    label: str  # Rule(s) applied


@dataclass
class PathConditionGraph:
    """
    Path condition exploration graph.
    
    Nodes are path conditions; edges represent derivation steps
    (rule combinations).
    """
    nodes: dict[int, PCNode] = field(default_factory=dict)
    edges: list[PCEdge] = field(default_factory=list)
    transformation_name: str = ""
    
    @staticmethod
    def from_path_conditions(
        transformation: Transformation,
        path_conditions: tuple[PathCondition, ...],
    ) -> PathConditionGraph:
        """
        Build graph from final path conditions.
        
        Note: This creates a flat graph (all PCs as nodes) since we don't
        track the derivation history. A more sophisticated implementation
        would build the graph during exploration.
        """
        graph = PathConditionGraph(transformation_name=transformation.name)
        
        for i, pc in enumerate(path_conditions):
            rules_str = ", ".join(sorted(str(r) for r in pc.rule_copies))
            graph.nodes[i] = PCNode(
                id=i,
                pc=pc,
                rule_set_str=rules_str if rules_str else "∅",
                vertex_count=len(pc.vertices),
                edge_count=len(pc.edges),
                trace_count=len(pc.trace_links),
            )
        
        # Build edges based on rule set inclusion (approximation of derivation)
        for i, pc_i in enumerate(path_conditions):
            for j, pc_j in enumerate(path_conditions):
                if i >= j:
                    continue
                # Check if one is derived from the other
                if pc_i.rule_copies < pc_j.rule_copies:
                    # pc_j has more rules - could be derived from pc_i
                    diff = pc_j.rule_copies - pc_i.rule_copies
                    if len(diff) <= 2:  # Reasonable derivation step
                        graph.edges.append(PCEdge(
                            source=i,
                            target=j,
                            label=", ".join(sorted(str(r) for r in diff)),
                        ))
        
        return graph
    
    def to_dot(self) -> str:
        """Export graph to DOT format for visualization."""
        lines = [
            "digraph PathConditions {",
            '  rankdir=TB;',
            '  node [shape=box, fontname="monospace"];',
            '',
        ]
        
        # Nodes
        for node in sorted(self.nodes.values(), key=lambda n: n.id):
            label = f"PC{node.id}\\n{node.rule_set_str}\\nV:{node.vertex_count} E:{node.edge_count} T:{node.trace_count}"
            style = "filled" if node.vertex_count > 0 else ""
            fillcolor = "lightblue" if node.vertex_count > 0 else "white"
            lines.append(f'  n{node.id} [label="{label}", style="{style}", fillcolor="{fillcolor}"];')
        
        lines.append('')
        
        # Edges
        for edge in self.edges:
            label = edge.label if edge.label else ""
            lines.append(f'  n{edge.source} -> n{edge.target} [label="{label}"];')
        
        lines.append('}')
        return '\n'.join(lines)
    
    def to_json(self) -> dict:
        """Export graph to JSON format."""
        return {
            "transformation": self.transformation_name,
            "nodes": [
                {
                    "id": n.id,
                    "rules": n.rule_set_str,
                    "vertices": n.vertex_count,
                    "edges": n.edge_count,
                    "traces": n.trace_count,
                }
                for n in sorted(self.nodes.values(), key=lambda n: n.id)
            ],
            "edges": [
                {"source": e.source, "target": e.target, "label": e.label}
                for e in self.edges
            ],
        }


def pretty_path_condition(pc: PathCondition) -> str:
    """Pretty-print a path condition for debugging."""
    lines = []
    lines.append(f"PathCondition (layer {pc.layer_index}):")
    lines.append(f"  Rules: {sorted(str(r) for r in pc.rule_copies)}")
    
    if pc.match_vertices:
        lines.append("  Match vertices:")
        for v in sorted(pc.match_vertices, key=lambda x: x.id):
            lines.append(f"    {v.id}: {v.class_type}")
    
    if pc.apply_vertices:
        lines.append("  Apply vertices:")
        for v in sorted(pc.apply_vertices, key=lambda x: x.id):
            lines.append(f"    {v.id}: {v.class_type}")
    
    if pc.match_edges:
        lines.append("  Match edges:")
        for e in sorted(pc.match_edges, key=lambda x: x.id):
            lines.append(f"    {e.id}: {e.source} --{e.assoc_type}--> {e.target}")
    
    if pc.apply_edges:
        lines.append("  Apply edges:")
        for e in sorted(pc.apply_edges, key=lambda x: x.id):
            lines.append(f"    {e.id}: {e.source} --{e.assoc_type}--> {e.target}")
    
    if pc.trace_links:
        lines.append("  Trace links:")
        for t in sorted(pc.trace_links, key=lambda x: x.id):
            lines.append(f"    {t.apply_vertex} <--trace-- {t.match_vertex}")
    
    return '\n'.join(lines)

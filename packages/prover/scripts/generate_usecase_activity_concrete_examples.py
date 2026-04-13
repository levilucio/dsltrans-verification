"""
Generate graded concrete UseCase models for usecase2activity_concrete.dslt.

Writes to:
  examples/models/usecase2activity_concrete/usecase2activity_concrete_<size>_input.xmi
"""
from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape


MM = "UseCaseConcrete"


def xmi_object(oid: str, cls: str, **attrs: object) -> str:
    parts = [f'  <objects xmi:id="{oid}" xsi:type="{MM}:{cls}"']
    for k, v in attrs.items():
        parts.append(f' {k}="{escape(str(v), {chr(34): "&quot;"})}"')
    parts.append(" />")
    return "".join(parts)


def xmi_link(assoc: str, src: str, tgt: str) -> str:
    return f'  <links xsi:type="{MM}:{assoc}" source="{src}" target="{tgt}" />'


def build_doc(objects: list[str], links: list[str]) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<model xmlns:xmi="http://www.omg.org/XMI" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">\n'
        + "\n".join(objects)
        + "\n\n"
        + "\n".join(links)
        + "\n</model>\n"
    )


def write_case(out_dir: Path, size_name: str, nodes: list[dict[str, object]], edges: list[dict[str, object]]) -> None:
    objects = [
        xmi_object(
            "sm",
            "UseCaseModel",
            systemName="RetailCheckout",
            domain="Retail",
            release=3 if size_name in ("very_small", "small") else 4,
        )
    ]
    for idx, n in enumerate(nodes):
        objects.append(
            xmi_object(
                f"n{idx}",
                "UseCaseNode",
                name=n["name"],
                actor=n["actor"],
                goal=n["goal"],
                priority=n["priority"],
                complexity=n["complexity"],
            )
        )
    for idx, e in enumerate(edges):
        objects.append(
            xmi_object(
                f"e{idx}",
                "Include",
                relationKind=e["relationKind"],
                rationale=e["rationale"],
                priority=e["priority"],
            )
        )

    links: list[str] = []
    for idx in range(len(nodes)):
        links.append(xmi_link("nodes", "sm", f"n{idx}"))
    for idx, e in enumerate(edges):
        links.append(xmi_link("edges", "sm", f"e{idx}"))
        links.append(xmi_link("src", f"e{idx}", f"n{e['src']}"))
        links.append(xmi_link("dst", f"e{idx}", f"n{e['dst']}"))

    out = out_dir / f"usecase2activity_concrete_{size_name}_input.xmi"
    out.write_text(build_doc(objects, links), encoding="utf-8")


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    out_dir = root / "examples" / "models" / "usecase2activity_concrete"
    out_dir.mkdir(parents=True, exist_ok=True)

    write_case(
        out_dir,
        "very_small",
        nodes=[
            {
                "name": "BrowseCatalog",
                "actor": "Customer",
                "goal": "Find relevant items quickly",
                "priority": 4,
                "complexity": 2,
            }
        ],
        edges=[],
    )

    write_case(
        out_dir,
        "small",
        nodes=[
            {
                "name": "SubmitPayment",
                "actor": "Customer",
                "goal": "Collect payment securely",
                "priority": 9,
                "complexity": 3,
            },
            {
                "name": "AuthenticateUser",
                "actor": "System",
                "goal": "Authenticate the user before checkout",
                "priority": 8,
                "complexity": 2,
            },
        ],
        edges=[
            {
                "src": 0,
                "dst": 1,
                "relationKind": "include",
                "rationale": "Shared authentication requirement",
                "priority": 9,
            }
        ],
    )

    base_nodes = [
        ("BrowseCatalog", "Customer", "Find relevant items quickly", 4, 2),
        ("CreateOrder", "Customer", "Create a persistent order record", 8, 4),
        ("AuthenticateUser", "System", "Authenticate the user before checkout", 8, 2),
        ("SubmitPayment", "Customer", "Collect payment securely", 9, 3),
        ("NotifyCustomer", "System", "Send customer notification", 6, 2),
    ]
    write_case(
        out_dir,
        "medium",
        nodes=[
            {"name": n, "actor": a, "goal": g, "priority": p, "complexity": c}
            for n, a, g, p, c in base_nodes
        ],
        edges=[
            {"src": 1, "dst": 2, "relationKind": "include", "rationale": "Shared authentication requirement", "priority": 8},
            {"src": 1, "dst": 3, "relationKind": "include", "rationale": "Payment requires prior validation", "priority": 9},
            {"src": 1, "dst": 4, "relationKind": "extend", "rationale": "Notification follows order submission", "priority": 6},
            {"src": 3, "dst": 2, "relationKind": "dependsOn", "rationale": "Audit trail requires persistent record", "priority": 7},
        ],
    )

    large_nodes: list[dict[str, object]] = []
    for i in range(14):
        large_nodes.append(
            {
                "name": f"CheckoutStep{i}",
                "actor": "Customer" if i % 3 != 0 else "System",
                "goal": f"Execute checkout step {i}",
                "priority": 3 + (i % 8),
                "complexity": 1 + (i % 5),
            }
        )
    large_edges: list[dict[str, object]] = []
    for i in range(13):
        large_edges.append(
            {
                "src": i,
                "dst": i + 1,
                "relationKind": "include",
                "rationale": f"Step {i} enables step {i + 1}",
                "priority": 3 + (i % 8),
            }
        )
    for i in range(0, 10, 2):
        large_edges.append(
            {
                "src": i,
                "dst": i + 2,
                "relationKind": "precedes",
                "rationale": f"Fast path from step {i} to {i + 2}",
                "priority": 5 + (i % 4),
            }
        )
    write_case(out_dir, "large", large_nodes, large_edges)

    very_large_nodes: list[dict[str, object]] = []
    for i in range(32):
        very_large_nodes.append(
            {
                "name": f"OrderFlowStep{i}",
                "actor": "Customer" if i % 4 in (1, 2) else ("SupportAgent" if i % 7 == 0 else "System"),
                "goal": f"Handle order flow step {i}",
                "priority": 1 + (i % 10),
                "complexity": 1 + (i % 5),
            }
        )
    very_large_edges: list[dict[str, object]] = []
    for i in range(31):
        very_large_edges.append(
            {
                "src": i,
                "dst": i + 1,
                "relationKind": "include",
                "rationale": f"Order flow dependency {i}->{i + 1}",
                "priority": 1 + (i % 10),
            }
        )
    for i in range(0, 28, 3):
        very_large_edges.append(
            {
                "src": i,
                "dst": i + 3,
                "relationKind": "dependsOn",
                "rationale": f"Cross-step dependency {i}->{i + 3}",
                "priority": 2 + (i % 8),
            }
        )
    write_case(out_dir, "very_large", very_large_nodes, very_large_edges)
    print(f"Wrote concrete graded inputs under {out_dir}")


if __name__ == "__main__":
    main()

"""
Generate graded UseCase compact XMI examples for usecase2activity_concrete.dslt.

Writes to examples/models/usecase2activity/usecase2activity_<size>_input.xmi
Run from dsltrans-prover repo root:

  python scripts/generate_usecase_activity_examples.py
"""
from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape


MM = "UseCase"


def xmi_object(oid: str, cls: str, **attrs: str) -> str:
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


def write_very_small(out_dir: Path) -> None:
    objs = [
        xmi_object("sm", "UseCaseModel"),
        xmi_object("n0", "UseCaseNode", name="U0"),
    ]
    links = [
        xmi_link("nodes", "sm", "n0"),
    ]
    (out_dir / "usecase2activity_very_small_input.xmi").write_text(build_doc(objs, links), encoding="utf-8")


def write_small(out_dir: Path) -> None:
    objs = [
        xmi_object("sm", "UseCaseModel"),
        xmi_object("n0", "UseCaseNode", name="A"),
        xmi_object("n1", "UseCaseNode", name="B"),
        xmi_object("e0", "Include"),
    ]
    links = [
        xmi_link("nodes", "sm", "n0"),
        xmi_link("nodes", "sm", "n1"),
        xmi_link("edges", "sm", "e0"),
        xmi_link("src", "e0", "n0"),
        xmi_link("dst", "e0", "n1"),
    ]
    (out_dir / "usecase2activity_small_input.xmi").write_text(build_doc(objs, links), encoding="utf-8")


def write_medium(out_dir: Path) -> None:
    # sm --5 nodes-- chain n0->n1->n2, fork n2->n3, n2->n4
    nodes = [("n0", "N0"), ("n1", "N1"), ("n2", "N2"), ("n3", "N3"), ("n4", "N4")]
    objs = [xmi_object("sm", "UseCaseModel")]
    objs += [xmi_object(oid, "UseCaseNode", name=name) for oid, name in nodes]
    edges = [("e0", "n0", "n1"), ("e1", "n1", "n2"), ("e2", "n2", "n3"), ("e3", "n2", "n4")]
    objs += [xmi_object(eid, "Include") for eid, _, _ in edges]
    links = [xmi_link("nodes", "sm", oid) for oid, _ in nodes]
    links += [xmi_link("edges", "sm", eid) for eid, _, _ in edges]
    for eid, s, t in edges:
        links.append(xmi_link("src", eid, s))
        links.append(xmi_link("dst", eid, t))
    (out_dir / "usecase2activity_medium_input.xmi").write_text(build_doc(objs, links), encoding="utf-8")


def write_linear_chain(out_dir: Path, name: str, n_nodes: int, n_extra_edges: int) -> None:
    """n_nodes nodes in a chain n0->...->n_{k-1}, plus n_extra_edges random forward jumps."""
    objs = [xmi_object("sm", "UseCaseModel")]
    for i in range(n_nodes):
        objs.append(xmi_object(f"n{i}", "UseCaseNode", name=f"U{i}"))
    links = [xmi_link("nodes", "sm", f"n{i}") for i in range(n_nodes)]
    eidx = 0
    for i in range(n_nodes - 1):
        eid = f"e{eidx}"
        eidx += 1
        objs.append(xmi_object(eid, "Include"))
        links.append(xmi_link("edges", "sm", eid))
        links.append(xmi_link("src", eid, f"n{i}"))
        links.append(xmi_link("dst", eid, f"n{i + 1}"))
    # extra edges: connect n_i to n_{i+2} when possible
    i = 0
    while n_extra_edges > 0 and i + 2 < n_nodes:
        eid = f"e{eidx}"
        eidx += 1
        objs.append(xmi_object(eid, "Include"))
        links.append(xmi_link("edges", "sm", eid))
        links.append(xmi_link("src", eid, f"n{i}"))
        links.append(xmi_link("dst", eid, f"n{i + 2}"))
        i += 3
        n_extra_edges -= 1
    (out_dir / name).write_text(build_doc(objs, links), encoding="utf-8")


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    out_dir = root / "examples" / "models" / "usecase2activity"
    out_dir.mkdir(parents=True, exist_ok=True)
    write_very_small(out_dir)
    write_small(out_dir)
    write_medium(out_dir)
    write_linear_chain(out_dir, "usecase2activity_large_input.xmi", n_nodes=14, n_extra_edges=6)
    write_linear_chain(out_dir, "usecase2activity_very_large_input.xmi", n_nodes=32, n_extra_edges=10)
    print(f"Wrote graded inputs under {out_dir}")


if __name__ == "__main__":
    main()

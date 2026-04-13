"""
Generate graded Statechart compact XMI examples for statechart2flow_concrete.dslt.

Writes to examples/models/statechart2flow/statechart2flow_<size>_input.xmi
Run from dsltrans-prover repo root:

  python scripts/generate_statechart_flow_examples.py
"""
from __future__ import annotations

from pathlib import Path


MM = "Statechart"


def xmi_object(oid: str, cls: str) -> str:
    return f'  <objects xmi:id="{oid}" xsi:type="{MM}:{cls}" />'


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
        xmi_object("sm", "StatechartModel"),
        xmi_object("s0", "State"),
    ]
    links = [
        xmi_link("nodes", "sm", "s0"),
    ]
    (out_dir / "statechart2flow_very_small_input.xmi").write_text(build_doc(objs, links), encoding="utf-8")


def write_small(out_dir: Path) -> None:
    objs = [
        xmi_object("sm", "StatechartModel"),
        xmi_object("s0", "State"),
        xmi_object("s1", "State"),
        xmi_object("t0", "Trigger"),
    ]
    links = [
        xmi_link("nodes", "sm", "s0"),
        xmi_link("nodes", "sm", "s1"),
        xmi_link("edges", "sm", "t0"),
        xmi_link("src", "t0", "s0"),
        xmi_link("dst", "t0", "s1"),
    ]
    (out_dir / "statechart2flow_small_input.xmi").write_text(build_doc(objs, links), encoding="utf-8")


def write_medium(out_dir: Path) -> None:
    # 5 states and a branching transition structure.
    states = ["s0", "s1", "s2", "s3", "s4"]
    transitions = [
        ("t0", "s0", "s1"),
        ("t1", "s1", "s2"),
        ("t2", "s2", "s3"),
        ("t3", "s2", "s4"),
    ]
    objs = [xmi_object("sm", "StatechartModel")]
    objs += [xmi_object(sid, "State") for sid in states]
    objs += [xmi_object(tid, "Trigger") for tid, _, _ in transitions]
    links = [xmi_link("nodes", "sm", sid) for sid in states]
    links += [xmi_link("edges", "sm", tid) for tid, _, _ in transitions]
    for tid, src, dst in transitions:
        links.append(xmi_link("src", tid, src))
        links.append(xmi_link("dst", tid, dst))
    (out_dir / "statechart2flow_medium_input.xmi").write_text(build_doc(objs, links), encoding="utf-8")


def write_linear_chain(out_dir: Path, name: str, n_states: int, n_extra_triggers: int) -> None:
    objs = [xmi_object("sm", "StatechartModel")]
    for i in range(n_states):
        objs.append(xmi_object(f"s{i}", "State"))
    links = [xmi_link("nodes", "sm", f"s{i}") for i in range(n_states)]

    tidx = 0
    for i in range(n_states - 1):
        tid = f"t{tidx}"
        tidx += 1
        objs.append(xmi_object(tid, "Trigger"))
        links.append(xmi_link("edges", "sm", tid))
        links.append(xmi_link("src", tid, f"s{i}"))
        links.append(xmi_link("dst", tid, f"s{i + 1}"))

    i = 0
    while n_extra_triggers > 0 and i + 2 < n_states:
        tid = f"t{tidx}"
        tidx += 1
        objs.append(xmi_object(tid, "Trigger"))
        links.append(xmi_link("edges", "sm", tid))
        links.append(xmi_link("src", tid, f"s{i}"))
        links.append(xmi_link("dst", tid, f"s{i + 2}"))
        i += 3
        n_extra_triggers -= 1

    (out_dir / name).write_text(build_doc(objs, links), encoding="utf-8")


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    out_dir = root / "examples" / "models" / "statechart2flow"
    out_dir.mkdir(parents=True, exist_ok=True)
    write_very_small(out_dir)
    write_small(out_dir)
    write_medium(out_dir)
    write_linear_chain(out_dir, "statechart2flow_large_input.xmi", n_states=14, n_extra_triggers=6)
    write_linear_chain(out_dir, "statechart2flow_very_large_input.xmi", n_states=32, n_extra_triggers=10)
    print(f"Wrote graded inputs under {out_dir}")


if __name__ == "__main__":
    main()

"""
Generate graded ClassDiagram compact XMI inputs for class2relational_concrete.dslt.

Writes to:
  examples/models/class2relational/class2relational_<size>_input.xmi
"""
from __future__ import annotations

from pathlib import Path


MM = "ClassDiagram"


def xmi_object(oid: str, cls: str, **attrs: object) -> str:
    parts = [f'  <objects xmi:id="{oid}" xsi:type="{MM}:{cls}"']
    for key, value in attrs.items():
        parts.append(f' {key}="{value}"')
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


def _base_model() -> tuple[list[str], list[str]]:
    objects = [
        xmi_object("m0", "Model"),
        xmi_object("pkg0", "Package", name="Pkg1"),
        xmi_object("dt_int", "DataType", name="T1"),
        xmi_object("dt_str", "DataType", name="T2"),
    ]
    links = [
        xmi_link("root", "m0", "pkg0"),
        xmi_link("packagedElement", "pkg0", "dt_int"),
        xmi_link("packagedElement", "pkg0", "dt_str"),
    ]
    return objects, links


def _add_class(
    objects: list[str],
    links: list[str],
    cid: str,
    *,
    name: str,
    is_abstract: bool,
) -> None:
    objects.append(xmi_object(cid, "Class", name=name, isAbstract=str(is_abstract).lower()))
    links.append(xmi_link("packagedElement", "pkg0", cid))


def _add_attribute(
    objects: list[str],
    links: list[str],
    aid: str,
    owner: str,
    *,
    name: str,
    is_multivalued: bool,
    target: str | None = None,
) -> None:
    objects.append(xmi_object(aid, "Attribute", name=name, isMultivalued=str(is_multivalued).lower()))
    links.append(xmi_link("ownedAttribute", owner, aid))
    if target:
        links.append(xmi_link("type", aid, target))


def _add_association(
    objects: list[str],
    links: list[str],
    assoc_id: str,
    ab_id: str,
    src_cls: str,
    tgt_cls: str,
    *,
    assoc_name: str,
    src_upper: int,
    tgt_upper: int,
) -> None:
    e1 = f"{assoc_id}_e1"
    e2 = f"{assoc_id}_e2"
    objects.extend(
        [
            xmi_object(assoc_id, "Association", name=assoc_name),
            xmi_object(e1, "AssociationEnd", name="end1", isNavigable="true", lowerBound="0", upperBound=str(src_upper)),
            xmi_object(e2, "AssociationEnd", name="end2", isNavigable="true", lowerBound="0", upperBound=str(tgt_upper)),
            xmi_object(ab_id, "AssocBetween", srcLower="0", srcUpper=str(src_upper), tgtLower="0", tgtUpper=str(tgt_upper)),
        ]
    )
    links.extend(
        [
            xmi_link("rootAssociations", "m0", assoc_id),
            xmi_link("memberEnd", assoc_id, e1),
            xmi_link("memberEnd", assoc_id, e2),
            xmi_link("endType", e1, src_cls),
            xmi_link("endType", e2, tgt_cls),
            xmi_link("association", ab_id, assoc_id),
            xmi_link("sourceClass", ab_id, src_cls),
            xmi_link("targetClass", ab_id, tgt_cls),
        ]
    )


def _add_generalization(
    objects: list[str],
    links: list[str],
    gid: str,
    parent: str,
    child: str,
) -> None:
    objects.append(xmi_object(gid, "Generalization"))
    links.extend(
        [
            xmi_link("rootGeneralizations", "m0", gid),
            xmi_link("general", gid, parent),
            xmi_link("specific", gid, child),
        ]
    )


def write_very_small(out_dir: Path) -> None:
    objects, links = _base_model()
    _add_class(objects, links, "c0", name="C", is_abstract=False)
    _add_attribute(objects, links, "a0", "c0", name="a", is_multivalued=False, target="dt_str")
    (out_dir / "class2relational_very_small_input.xmi").write_text(build_doc(objects, links), encoding="utf-8")


def write_small(out_dir: Path) -> None:
    objects, links = _base_model()
    _add_class(objects, links, "c0", name="C", is_abstract=False)
    _add_class(objects, links, "c1", name="D", is_abstract=False)
    _add_attribute(objects, links, "a0", "c0", name="id", is_multivalued=False, target="dt_int")
    _add_attribute(objects, links, "a1", "c1", name="ref", is_multivalued=False, target="c0")
    _add_attribute(objects, links, "a2", "c1", name="val", is_multivalued=False, target="dt_str")
    _add_association(objects, links, "as0", "ab0", "c0", "c1", assoc_name="A1", src_upper=1, tgt_upper=16)
    (out_dir / "class2relational_small_input.xmi").write_text(build_doc(objects, links), encoding="utf-8")


def write_medium(out_dir: Path) -> None:
    objects, links = _base_model()
    _add_class(objects, links, "parent", name="C", is_abstract=True)
    _add_class(objects, links, "child", name="D", is_abstract=False)
    _add_class(objects, links, "helper", name="T1", is_abstract=False)
    _add_class(objects, links, "target", name="T2", is_abstract=False)

    _add_attribute(objects, links, "a0", "parent", name="val", is_multivalued=False, target="dt_str")
    _add_attribute(objects, links, "a1", "child", name="ref", is_multivalued=False, target="target")
    _add_attribute(objects, links, "a2", "child", name="a", is_multivalued=True, target=None)
    _add_attribute(objects, links, "a3", "target", name="id", is_multivalued=False, target="dt_int")

    _add_generalization(objects, links, "g0", "parent", "child")
    _add_association(objects, links, "as0", "ab0", "child", "target", assoc_name="A1", src_upper=1, tgt_upper=1)
    _add_association(objects, links, "as1", "ab1", "helper", "target", assoc_name="A2", src_upper=16, tgt_upper=16)
    (out_dir / "class2relational_medium_input.xmi").write_text(build_doc(objects, links), encoding="utf-8")


def write_large(out_dir: Path) -> None:
    objects, links = _base_model()
    class_ids: list[str] = []
    names = ["C", "D", "T1", "T2"]
    for i in range(16):
        cid = f"c{i}"
        _add_class(objects, links, cid, name=names[i % len(names)], is_abstract=(i in {0, 8}))
        class_ids.append(cid)

    for i, cid in enumerate(class_ids):
        target = "dt_int" if i % 3 == 0 else ("dt_str" if i % 3 == 1 else class_ids[(i + 1) % len(class_ids)])
        _add_attribute(
            objects,
            links,
            f"a{i}",
            cid,
            name=["a", "id", "val", "ref"][i % 4],
            is_multivalued=(i % 5 == 0),
            target=None if i % 5 == 0 else target,
        )

    _add_generalization(objects, links, "g0", class_ids[0], class_ids[1])
    _add_generalization(objects, links, "g1", class_ids[8], class_ids[9])

    bounds = [(1, 16), (16, 1), (1, 1), (16, 16), (16, 16), (1, 16)]
    for i, (src_u, tgt_u) in enumerate(bounds):
        _add_association(
            objects,
            links,
            f"as{i}",
            f"ab{i}",
            class_ids[(2 * i + 1) % len(class_ids)],
            class_ids[(2 * i + 2) % len(class_ids)],
            assoc_name="A1" if i % 2 == 0 else "A2",
            src_upper=src_u,
            tgt_upper=tgt_u,
        )

    (out_dir / "class2relational_large_input.xmi").write_text(build_doc(objects, links), encoding="utf-8")


def write_very_large(out_dir: Path) -> None:
    objects, links = _base_model()
    class_ids: list[str] = []
    names = ["C", "D", "T1", "T2"]
    for i in range(32):
        cid = f"c{i}"
        _add_class(objects, links, cid, name=names[i % len(names)], is_abstract=(i % 9 == 0))
        class_ids.append(cid)

    for i, cid in enumerate(class_ids):
        target = "dt_int" if i % 4 == 0 else ("dt_str" if i % 4 == 1 else class_ids[(i + 3) % len(class_ids)])
        _add_attribute(
            objects,
            links,
            f"a{i}",
            cid,
            name=["a", "id", "val", "ref"][i % 4],
            is_multivalued=(i % 6 == 0),
            target=None if i % 6 == 0 else target,
        )

    for i in range(4):
        _add_generalization(objects, links, f"g{i}", class_ids[i * 9], class_ids[(i * 9 + 1) % len(class_ids)])

    patterns = [(1, 16), (16, 1), (1, 1), (16, 16)]
    for i in range(12):
        src_u, tgt_u = patterns[i % len(patterns)]
        _add_association(
            objects,
            links,
            f"as{i}",
            f"ab{i}",
            class_ids[(3 * i + 2) % len(class_ids)],
            class_ids[(3 * i + 5) % len(class_ids)],
            assoc_name="A1" if i % 2 == 0 else "A2",
            src_upper=src_u,
            tgt_upper=tgt_u,
        )

    (out_dir / "class2relational_very_large_input.xmi").write_text(build_doc(objects, links), encoding="utf-8")


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    out_dir = root / "examples" / "models" / "class2relational"
    out_dir.mkdir(parents=True, exist_ok=True)
    write_very_small(out_dir)
    write_small(out_dir)
    write_medium(out_dir)
    write_large(out_dir)
    write_very_large(out_dir)
    print(f"Wrote graded inputs under {out_dir}")


if __name__ == "__main__":
    main()

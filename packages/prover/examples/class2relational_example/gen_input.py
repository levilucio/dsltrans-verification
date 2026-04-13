"""Generate a semantically meaningful class diagram XMI for class2relational_example.

Domain: document/catalog schema
- Package Pkg1
- DataTypes: T1 (int-like), T2 (string-like)
- Classes: C (Category) 50, D (Document) 80, T1 (Tag1) 40, T2 (Tag2) 40 = 210 classes
- Attributes: C has id->int; D has id->int or ref->C; T1/T2 have val/a->string
"""
from pathlib import Path

def main():
    out_path = Path(__file__).parent / "classdiagram_input.xmi"
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<model xmlns:xmi="http://www.omg.org/XMI" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">',
        '  <!-- Root containment: Model -> Package -->',
        '  <objects xmi:id="model1" xsi:type="ClassDiagram:Model"/>',
        '  <objects xmi:id="pkg1" xsi:type="ClassDiagram:Package" name="Pkg1"/>',
        '  <links xsi:type="ClassDiagram:root" source="model1" target="pkg1"/>',
        '  <!-- DataTypes: T1 (int-like), T2 (string-like) -->',
        '  <objects xmi:id="dt_int" xsi:type="ClassDiagram:DataType" name="T1"/>',
        '  <objects xmi:id="dt_str" xsi:type="ClassDiagram:DataType" name="T2"/>',
    ]

    n_c, n_d, n_t1, n_t2 = 50, 80, 40, 40
    class_ids = []
    for i in range(1, n_c + 1):
        class_ids.append((f"c_{i}", "ClassDiagram:Class", "C"))
    for i in range(1, n_d + 1):
        class_ids.append((f"d_{i}", "ClassDiagram:Class", "D"))
    for i in range(1, n_t1 + 1):
        class_ids.append((f"t1_{i}", "ClassDiagram:Class", "T1"))
    for i in range(1, n_t2 + 1):
        class_ids.append((f"t2_{i}", "ClassDiagram:Class", "T2"))

    lines.append("  <!-- Classes: C (Category) 50, D (Document) 80, T1 (Tag1) 40, T2 (Tag2) 40 -->")
    for oid, xtype, cname in class_ids:
        lines.append(f'  <objects xmi:id="{oid}" xsi:type="{xtype}" name="{cname}" isAbstract="false"/>')

    attr_links = []
    for i, (cid, _, cname) in enumerate(class_ids):
        if cname == "C":
            aid = f"attr_c_{i+1}"
            lines.append(f'  <objects xmi:id="{aid}" xsi:type="ClassDiagram:Attribute" name="id" isMultivalued="false"/>')
            attr_links.append((aid, cid, "dt_int"))
        elif cname == "D":
            aid = f"attr_d_{i+1}"
            if i < 65:
                lines.append(f'  <objects xmi:id="{aid}" xsi:type="ClassDiagram:Attribute" name="id" isMultivalued="false"/>')
                attr_links.append((aid, cid, "dt_int"))
            else:
                lines.append(f'  <objects xmi:id="{aid}" xsi:type="ClassDiagram:Attribute" name="ref" isMultivalued="false"/>')
                attr_links.append((aid, cid, "c_1"))
        elif cname == "T1":
            aid = f"attr_t1_{i+1}"
            lines.append(f'  <objects xmi:id="{aid}" xsi:type="ClassDiagram:Attribute" name="val" isMultivalued="false"/>')
            attr_links.append((aid, cid, "dt_str"))
        else:
            aid = f"attr_t2_{i+1}"
            lines.append(f'  <objects xmi:id="{aid}" xsi:type="ClassDiagram:Attribute" name="a" isMultivalued="false"/>')
            attr_links.append((aid, cid, "dt_str"))

    lines.append("  <!-- packagedElement: pkg1 -> each classifier -->")
    for oid, _, _ in class_ids:
        lines.append(f'  <links xsi:type="ClassDiagram:packagedElement" source="pkg1" target="{oid}"/>')
    lines.append('  <links xsi:type="ClassDiagram:packagedElement" source="pkg1" target="dt_int"/>')
    lines.append('  <links xsi:type="ClassDiagram:packagedElement" source="pkg1" target="dt_str"/>')

    lines.append("  <!-- ownedAttribute and type -->")
    for aid, cid, tid in attr_links:
        lines.append(f'  <links xsi:type="ClassDiagram:ownedAttribute" source="{cid}" target="{aid}"/>')
        lines.append(f'  <links xsi:type="ClassDiagram:type" source="{aid}" target="{tid}"/>')

    lines.append("</model>")
    out_path.write_text("\n".join(lines), encoding="utf-8")
    n_class = n_c + n_d + n_t1 + n_t2
    n_attr = n_class
    n_obj = 1 + 2 + n_class + n_attr
    n_links = n_class + 2 + n_attr * 2
    print(f"Wrote {out_path} ({n_obj} objects, {n_links} links)")


if __name__ == "__main__":
    main()

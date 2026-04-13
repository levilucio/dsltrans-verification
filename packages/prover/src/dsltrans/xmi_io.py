from __future__ import annotations

from pathlib import Path
import xml.etree.ElementTree as ET

from .concrete_model import ConcreteModel, ConcreteNode, TraceLink
from .model import Metamodel

XMI_NS = "http://www.omg.org/XMI"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"


def _attr_xmi_id() -> str:
    return f"{{{XMI_NS}}}id"


def _attr_xsi_type() -> str:
    return f"{{{XSI_NS}}}type"


def _split_type(xmi_type: str) -> str:
    if ":" in xmi_type:
        return xmi_type.split(":", 1)[1]
    return xmi_type


def _parse_value(raw: str) -> object:
    low = raw.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    try:
        return int(raw)
    except ValueError:
        return raw


def load_xmi_model(path: str | Path, mm: Metamodel) -> ConcreteModel:
    """
    Load a compact EMF-compatible XMI model.

    Supported canonical structure:
      <model>
        <objects xmi:id="..." xmi:type="MM:ClassName" ...attrs... />
        <links xmi:type="MM:assocName" source="objId" target="objId" />
      </model>
    """
    root = ET.parse(path).getroot()
    model = ConcreteModel()

    for child in root:
        tag = child.tag.split("}", 1)[-1]
        if tag != "objects":
            continue
        node_id = child.attrib.get(_attr_xmi_id()) or child.attrib.get("id")
        xmi_type = child.attrib.get(_attr_xsi_type(), "")
        class_name = _split_type(xmi_type)
        if not node_id or not class_name:
            raise ValueError(f"Invalid object entry in XMI: missing id/type in {path}")
        if class_name not in mm.class_by_name:
            raise ValueError(f"Class {class_name!r} in XMI not present in metamodel {mm.name}")
        attrs: dict[str, object] = {}
        for k, v in child.attrib.items():
            if k in (_attr_xmi_id(), _attr_xsi_type(), "id", "source", "target"):
                continue
            if k.startswith("{"):
                continue
            attrs[k] = _parse_value(v)
        model.nodes[node_id] = ConcreteNode(id=node_id, class_name=class_name, attrs=attrs)

    for child in root:
        tag = child.tag.split("}", 1)[-1]
        if tag != "links":
            continue
        assoc_name = _split_type(child.attrib.get(_attr_xsi_type(), ""))
        src = child.attrib.get("source")
        tgt = child.attrib.get("target")
        if not assoc_name or src is None or tgt is None:
            raise ValueError(f"Invalid link entry in XMI: {ET.tostring(child, encoding='unicode')}")
        if assoc_name not in mm.assoc_by_name:
            raise ValueError(f"Association {assoc_name!r} in XMI not present in metamodel {mm.name}")
        if src not in model.nodes or tgt not in model.nodes:
            raise ValueError(f"Association endpoint missing in XMI link {assoc_name}: {src}->{tgt}")
        model.add_edge(assoc_name, src, tgt)

    return model


def load_traces_from_xmi(path: str | Path) -> list[TraceLink]:
    """
    Load trace links from a compact XMI model.

    Traces are expected as:
      <traces source="srcId" target="tgtId" />
    """
    root = ET.parse(path).getroot()
    traces: list[TraceLink] = []
    for child in root:
        tag = child.tag.split("}", 1)[-1]
        if tag != "traces":
            continue
        src = child.attrib.get("source")
        tgt = child.attrib.get("target")
        if src is None or tgt is None:
            raise ValueError(f"Invalid trace entry in XMI: {ET.tostring(child, encoding='unicode')}")
        traces.append(TraceLink(source_id=src, target_id=tgt))
    traces.sort(key=lambda t: (t.source_id, t.target_id))
    return traces


def save_xmi_model(path: str | Path, model: ConcreteModel, mm_name: str) -> None:
    """
    Save model in compact EMF-compatible XMI format.
    """
    ET.register_namespace("xmi", XMI_NS)
    ET.register_namespace("xsi", XSI_NS)
    root = ET.Element("model")
    for node_id in sorted(model.nodes):
        node = model.nodes[node_id]
        attrs = {
            _attr_xmi_id(): node.id,
            _attr_xsi_type(): f"{mm_name}:{node.class_name}",
        }
        for k in sorted(node.attrs):
            val = node.attrs[k]
            attrs[k] = str(val).lower() if isinstance(val, bool) else str(val)
        ET.SubElement(root, "objects", attrs)

    for edge in sorted(model.edges, key=lambda e: (e.assoc_name, e.source_id, e.target_id)):
        ET.SubElement(
            root,
            "links",
            {
                _attr_xsi_type(): f"{mm_name}:{edge.assoc_name}",
                "source": edge.source_id,
                "target": edge.target_id,
            },
        )

    for tr in sorted(model.traces, key=lambda t: (t.source_id, t.target_id)):
        ET.SubElement(root, "traces", {"source": tr.source_id, "target": tr.target_id})

    tree = ET.ElementTree(root)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    tree.write(path, encoding="utf-8", xml_declaration=True)

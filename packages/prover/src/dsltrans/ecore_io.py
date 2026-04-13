from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import xml.etree.ElementTree as ET

from .model import Metamodel


@dataclass(frozen=True)
class EcoreReference:
    name: str
    source_class: str
    target_class: str
    containment: bool


@dataclass(frozen=True)
class EcoreModel:
    name: str
    classes: tuple[str, ...]
    references: tuple[EcoreReference, ...]


def _local(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def load_ecore_model(path: str | Path) -> EcoreModel:
    """
    Parse a subset of Ecore needed for runtime consistency checks.
    """
    root = ET.parse(path).getroot()
    if _local(root.tag) != "EPackage":
        raise ValueError(f"Expected EPackage root in {path}")
    pkg_name = root.attrib.get("name", "EPackage")

    classes: list[str] = []
    refs: list[EcoreReference] = []

    for child in root:
        if _local(child.tag) != "eClassifiers":
            continue
        xsi_type = child.attrib.get("{http://www.w3.org/2001/XMLSchema-instance}type", "")
        if not xsi_type.endswith("EClass"):
            continue
        cls_name = child.attrib.get("name")
        if not cls_name:
            continue
        classes.append(cls_name)
        for feat in child:
            if _local(feat.tag) != "eStructuralFeatures":
                continue
            feat_type = feat.attrib.get("{http://www.w3.org/2001/XMLSchema-instance}type", "")
            if not feat_type.endswith("EReference"):
                continue
            ref_name = feat.attrib.get("name")
            raw_e_type = feat.attrib.get("eType", "")
            tgt = raw_e_type.split("/")[-1].replace("#", "")
            if tgt.startswith("/"):
                tgt = tgt[1:]
            if tgt.startswith("/"):
                tgt = tgt[1:]
            if tgt.startswith("//"):
                tgt = tgt[2:]
            if ref_name and tgt:
                refs.append(
                    EcoreReference(
                        name=ref_name,
                        source_class=cls_name,
                        target_class=tgt,
                        containment=feat.attrib.get("containment", "false") == "true",
                    )
                )

    return EcoreModel(name=pkg_name, classes=tuple(classes), references=tuple(refs))


def check_metamodel_consistency(dslt_mm: Metamodel, ecore_mm: EcoreModel) -> list[str]:
    """Return human-readable consistency mismatches."""
    issues: list[str] = []
    dslt_classes = {c.name for c in dslt_mm.classes}
    ecore_classes = set(ecore_mm.classes)

    for c in sorted(dslt_classes - ecore_classes):
        issues.append(f"Class {c!r} exists in DSLT metamodel but not in Ecore")
    for c in sorted(ecore_classes - dslt_classes):
        issues.append(f"Class {c!r} exists in Ecore but not in DSLT metamodel")

    ecore_refs = {(r.name, r.source_class, r.target_class) for r in ecore_mm.references}
    for assoc in dslt_mm.associations:
        triple = (assoc.name, str(assoc.source_class), str(assoc.target_class))
        if triple not in ecore_refs:
            issues.append(
                f"Association {assoc.name!r} ({assoc.source_class}->{assoc.target_class})"
                " missing in Ecore or has different endpoints"
            )
    return issues

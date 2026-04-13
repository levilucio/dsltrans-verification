import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Callable, NamedTuple

ROOT = Path(__file__).resolve().parent.parent
DSLT_EXAMPLES = ROOT / "examples"
GEN_DIR = ROOT / "cross_validation_tmp"
GEN_DIR.mkdir(parents=True, exist_ok=True)


class ConcreteInputCase(NamedTuple):
    label: str
    source: Path | Callable[[], Path]


def _write_generated_input(file_name: str, xml: str) -> Path:
    path = GEN_DIR / file_name
    path.write_text(xml, encoding="utf-8")
    return path


def _resolve_input_path(source: Path | Callable[[], Path]) -> Path:
    return source() if callable(source) else source

def generate_bpmn_input():
    xml = '''<?xml version="1.0" encoding="UTF-8"?>
<model xmlns:xmi="http://www.omg.org/XMI" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <objects xmi:id="def1" xsi:type="BPMN:Definitions"/>
  <objects xmi:id="proc1" xsi:type="BPMN:Process"/>
  <links xsi:type="BPMN:processes" source="def1" target="proc1"/>
  
  <objects xmi:id="se1" xsi:type="BPMN:StartEvent"/>
  <objects xmi:id="task1" xsi:type="BPMN:Task"/>
  <objects xmi:id="sf1" xsi:type="BPMN:SequenceFlow"/>
  
  <links xsi:type="BPMN:flowNodes" source="proc1" target="se1"/>
  <links xsi:type="BPMN:flowNodes" source="proc1" target="task1"/>
  <links xsi:type="BPMN:sequenceFlows" source="proc1" target="sf1"/>
  
  <links xsi:type="BPMN:sourceRef" source="sf1" target="se1"/>
  <links xsi:type="BPMN:targetRef" source="sf1" target="task1"/>
</model>
'''
    return _write_generated_input("bpmn_input.xmi", xml)


def generate_bpmn_featureful_input():
    xml = '''<?xml version="1.0" encoding="UTF-8"?>
<model xmlns:xmi="http://www.omg.org/XMI" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <objects xmi:id="def1" xsi:type="BPMN:Definitions"/>
  <objects xmi:id="proc1" xsi:type="BPMN:Process"/>
  <objects xmi:id="proc2" xsi:type="BPMN:Process"/>
  <links xsi:type="BPMN:processes" source="def1" target="proc1"/>
  <links xsi:type="BPMN:processes" source="def1" target="proc2"/>

  <objects xmi:id="start1" xsi:type="BPMN:StartEvent"/>
  <objects xmi:id="task1" xsi:type="BPMN:Task"/>
  <objects xmi:id="end1" xsi:type="BPMN:EndEvent"/>
  <objects xmi:id="sub1" xsi:type="BPMN:SubProcess"/>
  <objects xmi:id="gw1" xsi:type="BPMN:ParallelGateway"/>
  <objects xmi:id="gw2" xsi:type="BPMN:ParallelGateway"/>
  <objects xmi:id="bnd1" xsi:type="BPMN:BoundaryEvent" cancelActivity="false"/>
  <objects xmi:id="bnd2" xsi:type="BPMN:BoundaryEvent" cancelActivity="true"/>
  <objects xmi:id="task2" xsi:type="BPMN:Task"/>

  <links xsi:type="BPMN:flowNodes" source="proc1" target="start1"/>
  <links xsi:type="BPMN:flowNodes" source="proc1" target="task1"/>
  <links xsi:type="BPMN:flowNodes" source="proc1" target="end1"/>
  <links xsi:type="BPMN:flowNodes" source="proc1" target="sub1"/>
  <links xsi:type="BPMN:flowNodes" source="proc1" target="gw1"/>
  <links xsi:type="BPMN:flowNodes" source="proc1" target="gw2"/>
  <links xsi:type="BPMN:flowNodes" source="proc1" target="bnd1"/>
  <links xsi:type="BPMN:flowNodes" source="proc1" target="bnd2"/>
  <links xsi:type="BPMN:flowNodes" source="proc2" target="task2"/>

  <objects xmi:id="sf1" xsi:type="BPMN:SequenceFlow"/>
  <objects xmi:id="sf2" xsi:type="BPMN:SequenceFlow"/>
  <links xsi:type="BPMN:sequenceFlows" source="proc1" target="sf1"/>
  <links xsi:type="BPMN:sequenceFlows" source="proc1" target="sf2"/>
  <links xsi:type="BPMN:sourceRef" source="sf1" target="start1"/>
  <links xsi:type="BPMN:targetRef" source="sf1" target="task1"/>
  <links xsi:type="BPMN:sourceRef" source="sf2" target="task1"/>
  <links xsi:type="BPMN:targetRef" source="sf2" target="end1"/>

  <links xsi:type="BPMN:attachedTo" source="bnd1" target="task1"/>
  <links xsi:type="BPMN:attachedTo" source="bnd2" target="task1"/>

  <objects xmi:id="msg1" xsi:type="BPMN:MessageFlow"/>
  <links xsi:type="BPMN:messageFlows" source="def1" target="msg1"/>
  <links xsi:type="BPMN:msgSource" source="msg1" target="task1"/>
  <links xsi:type="BPMN:msgTarget" source="msg1" target="task2"/>
</model>
'''
    return _write_generated_input("bpmn_featureful_input.xmi", xml)

def generate_family_input():
    xml = '''<?xml version="1.0" encoding="UTF-8"?>
<model xmlns:xmi="http://www.omg.org/XMI" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <objects xmi:id="fm1" xsi:type="Family:FamilyModel"/>
  <objects xmi:id="m1" xsi:type="Family:Member"/>
  <objects xmi:id="m2" xsi:type="Family:Member"/>
  <objects xmi:id="k1" xsi:type="Family:Kinship"/>
  
  <links xsi:type="Family:nodes" source="fm1" target="m1"/>
  <links xsi:type="Family:nodes" source="fm1" target="m2"/>
  <links xsi:type="Family:edges" source="fm1" target="k1"/>
  
  <links xsi:type="Family:src" source="k1" target="m1"/>
  <links xsi:type="Family:dst" source="k1" target="m2"/>
</model>
'''
    return _write_generated_input("family_input.xmi", xml)

def generate_fsm_input():
    xml = '''<?xml version="1.0" encoding="UTF-8"?>
<model xmlns:xmi="http://www.omg.org/XMI" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <objects xmi:id="sm1" xsi:type="FSM:StateMachine" name="sm1"/>
  <objects xmi:id="s1" xsi:type="FSM:State" name="s1"/>
  <objects xmi:id="s2" xsi:type="FSM:State" name="s1"/>
  <objects xmi:id="t1" xsi:type="FSM:Transition" name="t1"/>
  
  <links xsi:type="FSM:states" source="sm1" target="s1"/>
  <links xsi:type="FSM:states" source="sm1" target="s2"/>
  <links xsi:type="FSM:transitions" source="sm1" target="t1"/>
  
  <links xsi:type="FSM:src" source="t1" target="s1"/>
  <links xsi:type="FSM:dst" source="t1" target="s2"/>
</model>
'''
    return _write_generated_input("fsm_input.xmi", xml)

def generate_tree_input():
    xml = '''<?xml version="1.0" encoding="UTF-8"?>
<model xmlns:xmi="http://www.omg.org/XMI" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <objects xmi:id="n1" xsi:type="Tree:Node" name="n1"/>
  <objects xmi:id="n2" xsi:type="Tree:Node" name="n1"/>
  <objects xmi:id="e1" xsi:type="Tree:Edge"/>
  
  <links xsi:type="Tree:root" source="n1" target="n1"/>
  <links xsi:type="Tree:children" source="n1" target="n2"/>
  <links xsi:type="Tree:edges" source="n1" target="e1"/>
  
  <links xsi:type="Tree:target" source="e1" target="n2"/>
</model>
'''
    return _write_generated_input("tree_input.xmi", xml)


def generate_class2relational_class_typed_attr_input():
    xml = '''<?xml version="1.0" encoding="UTF-8"?>
<model xmlns:xmi="http://www.omg.org/XMI" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <objects xmi:id="model1" xsi:type="ClassDiagram:Model"/>
  <objects xmi:id="pkg1" xsi:type="ClassDiagram:Package" name="Pkg1"/>
  <objects xmi:id="cls1" xsi:type="ClassDiagram:Class" name="C" isAbstract="false"/>
  <objects xmi:id="cls2" xsi:type="ClassDiagram:Class" name="D" isAbstract="false"/>
  <objects xmi:id="attr1" xsi:type="ClassDiagram:Attribute" name="ref" isMultivalued="false"/>

  <links xsi:type="ClassDiagram:root" source="model1" target="pkg1"/>
  <links xsi:type="ClassDiagram:packagedElement" source="pkg1" target="cls1"/>
  <links xsi:type="ClassDiagram:packagedElement" source="pkg1" target="cls2"/>
  <links xsi:type="ClassDiagram:ownedAttribute" source="cls1" target="attr1"/>
  <links xsi:type="ClassDiagram:type" source="attr1" target="cls2"/>
</model>
'''
    return _write_generated_input("class2relational_class_typed_attr_input.xmi", xml)


def generate_class2relational_one_to_many_input():
    xml = '''<?xml version="1.0" encoding="UTF-8"?>
<model xmlns:xmi="http://www.omg.org/XMI" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <objects xmi:id="model1" xsi:type="ClassDiagram:Model"/>
  <objects xmi:id="pkg1" xsi:type="ClassDiagram:Package" name="Pkg1"/>
  <objects xmi:id="src1" xsi:type="ClassDiagram:Class" name="C" isAbstract="false"/>
  <objects xmi:id="tgt1" xsi:type="ClassDiagram:Class" name="D" isAbstract="false"/>
  <objects xmi:id="ab1" xsi:type="ClassDiagram:AssocBetween" srcLower="0" srcUpper="1" tgtLower="0" tgtUpper="16"/>

  <links xsi:type="ClassDiagram:root" source="model1" target="pkg1"/>
  <links xsi:type="ClassDiagram:packagedElement" source="pkg1" target="src1"/>
  <links xsi:type="ClassDiagram:packagedElement" source="pkg1" target="tgt1"/>
  <links xsi:type="ClassDiagram:sourceClass" source="ab1" target="src1"/>
  <links xsi:type="ClassDiagram:targetClass" source="ab1" target="tgt1"/>
</model>
'''
    return _write_generated_input("class2relational_one_to_many_input.xmi", xml)


def generate_class2relational_abstract_assoc_input():
    xml = '''<?xml version="1.0" encoding="UTF-8"?>
<model xmlns:xmi="http://www.omg.org/XMI" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <objects xmi:id="model1" xsi:type="ClassDiagram:Model"/>
  <objects xmi:id="pkg1" xsi:type="ClassDiagram:Package" name="Pkg1"/>
  <objects xmi:id="src1" xsi:type="ClassDiagram:Class" name="C" isAbstract="true"/>
  <objects xmi:id="tgt1" xsi:type="ClassDiagram:Class" name="D" isAbstract="true"/>
  <objects xmi:id="ab1" xsi:type="ClassDiagram:AssocBetween" srcLower="0" srcUpper="1" tgtLower="0" tgtUpper="1"/>

  <links xsi:type="ClassDiagram:root" source="model1" target="pkg1"/>
  <links xsi:type="ClassDiagram:packagedElement" source="pkg1" target="src1"/>
  <links xsi:type="ClassDiagram:packagedElement" source="pkg1" target="tgt1"/>
  <links xsi:type="ClassDiagram:sourceClass" source="ab1" target="src1"/>
  <links xsi:type="ClassDiagram:targetClass" source="ab1" target="tgt1"/>
</model>
'''
    return _write_generated_input("class2relational_abstract_assoc_input.xmi", xml)


def generate_class2relational_multivalued_attr_input():
    xml = '''<?xml version="1.0" encoding="UTF-8"?>
<model xmlns:xmi="http://www.omg.org/XMI" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <objects xmi:id="model1" xsi:type="ClassDiagram:Model"/>
  <objects xmi:id="pkg1" xsi:type="ClassDiagram:Package" name="Pkg1"/>
  <objects xmi:id="cls1" xsi:type="ClassDiagram:Class" name="C" isAbstract="false"/>
  <objects xmi:id="attr1" xsi:type="ClassDiagram:Attribute" name="val" isMultivalued="true"/>

  <links xsi:type="ClassDiagram:root" source="model1" target="pkg1"/>
  <links xsi:type="ClassDiagram:packagedElement" source="pkg1" target="cls1"/>
  <links xsi:type="ClassDiagram:ownedAttribute" source="cls1" target="attr1"/>
</model>
'''
    return _write_generated_input("class2relational_multivalued_attr_input.xmi", xml)


def generate_uml_featureful_input():
    xml = '''<?xml version="1.0" encoding="UTF-8"?>
<model xmlns:xmi="http://www.omg.org/XMI" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <objects xmi:id="model1" xsi:type="UML:Model" name="M1"/>
  <objects xmi:id="pkg1" xsi:type="UML:Package" name="Pkg1"/>
  <links xsi:type="UML:rootPackages" source="model1" target="pkg1"/>

  <objects xmi:id="abs1" xsi:type="UML:Class" name="N1" isAbstract="true" isFinal="false" priority="4" layerTag="Core" kind="Entity"/>
  <objects xmi:id="cls1" xsi:type="UML:Class" name="C" isAbstract="false" isFinal="false" priority="1" layerTag="Core" kind="Entity"/>
  <objects xmi:id="cls2" xsi:type="UML:Class" name="N2" isAbstract="false" isFinal="true" priority="3" layerTag="Domain" kind="Service"/>
  <objects xmi:id="iface1" xsi:type="UML:Interface" name="I"/>
  <objects xmi:id="enm1" xsi:type="UML:Enumeration" name="E"/>
  <objects xmi:id="prim1" xsi:type="UML:PrimitiveType" name="N1"/>
  <objects xmi:id="assocCls1" xsi:type="UML:AssociationClass" name="N3" isAbstract="false" isFinal="false" priority="1" layerTag="Core" kind="Entity"/>
  <objects xmi:id="assoc1" xsi:type="UML:Association" name="A1" isDerived="false"/>

  <links xsi:type="UML:packagedElement" source="pkg1" target="abs1"/>
  <links xsi:type="UML:packagedElement" source="pkg1" target="cls1"/>
  <links xsi:type="UML:packagedElement" source="pkg1" target="cls2"/>
  <links xsi:type="UML:packagedElement" source="pkg1" target="iface1"/>
  <links xsi:type="UML:packagedElement" source="pkg1" target="enm1"/>
  <links xsi:type="UML:packagedElement" source="pkg1" target="prim1"/>
  <links xsi:type="UML:packagedElement" source="pkg1" target="assocCls1"/>

  <objects xmi:id="prop1" xsi:type="UML:Property" name="f" visibility="private" isStatic="false" isDerived="false" isReadOnly="false" isOrdered="false" isUnique="true" lower="0" upper="1" defaultValue=""/>
  <objects xmi:id="propRead" xsi:type="UML:Property" name="f" visibility="private" isStatic="false" isDerived="false" isReadOnly="true" isOrdered="false" isUnique="true" lower="0" upper="1" defaultValue=""/>
  <objects xmi:id="propStatic" xsi:type="UML:Property" name="f" visibility="public" isStatic="true" isDerived="false" isReadOnly="false" isOrdered="false" isUnique="true" lower="0" upper="1" defaultValue=""/>
  <objects xmi:id="propAB" xsi:type="UML:Property" name="f" visibility="private" isStatic="false" isDerived="false" isReadOnly="false" isOrdered="false" isUnique="true" lower="0" upper="1" defaultValue=""/>
  <objects xmi:id="propBA" xsi:type="UML:Property" name="f" visibility="private" isStatic="false" isDerived="false" isReadOnly="false" isOrdered="false" isUnique="true" lower="0" upper="1" defaultValue=""/>

  <links xsi:type="UML:ownedAttribute" source="cls1" target="prop1"/>
  <links xsi:type="UML:ownedAttribute" source="cls1" target="propRead"/>
  <links xsi:type="UML:ownedAttribute" source="cls1" target="propStatic"/>
  <links xsi:type="UML:ownedAttribute" source="cls1" target="propAB"/>
  <links xsi:type="UML:ownedAttribute" source="cls2" target="propBA"/>
  <links xsi:type="UML:type" source="prop1" target="prim1"/>
  <links xsi:type="UML:type" source="propRead" target="prim1"/>
  <links xsi:type="UML:type" source="propStatic" target="prim1"/>
  <links xsi:type="UML:type" source="propAB" target="cls2"/>
  <links xsi:type="UML:type" source="propBA" target="cls1"/>

  <objects xmi:id="op1" xsi:type="UML:Operation" name="op" visibility="public" isStatic="false" isAbstract="false" isQuery="false"/>
  <objects xmi:id="opAbs" xsi:type="UML:Operation" name="op" visibility="public" isStatic="false" isAbstract="true" isQuery="false"/>
  <objects xmi:id="ifaceOp" xsi:type="UML:Operation" name="op" visibility="public" isStatic="false" isAbstract="false" isQuery="false"/>
  <links xsi:type="UML:ownedOperation" source="cls1" target="op1"/>
  <links xsi:type="UML:ownedOperation" source="abs1" target="opAbs"/>
  <links xsi:type="UML:interfaceOperation" source="iface1" target="ifaceOp"/>

  <objects xmi:id="param1" xsi:type="UML:Parameter" name="p" direction="in"/>
  <links xsi:type="UML:ownedParameter" source="op1" target="param1"/>
  <links xsi:type="UML:paramType" source="param1" target="cls2"/>
  <links xsi:type="UML:returnType" source="op1" target="cls2"/>

  <objects xmi:id="lit1" xsi:type="UML:EnumerationLiteral" name="LIT1"/>
  <links xsi:type="UML:ownedLiteral" source="enm1" target="lit1"/>

  <objects xmi:id="gen1" xsi:type="UML:Generalization" isSubstitutable="true"/>
  <links xsi:type="UML:general" source="gen1" target="abs1"/>
  <links xsi:type="UML:specific" source="gen1" target="cls1"/>

  <objects xmi:id="real1" xsi:type="UML:InterfaceRealization"/>
  <links xsi:type="UML:contract" source="real1" target="iface1"/>
  <links xsi:type="UML:implementingClass" source="real1" target="cls1"/>

  <objects xmi:id="comment1" xsi:type="UML:Comment" body="javadoc"/>
  <links xsi:type="UML:ownedComment" source="cls1" target="comment1"/>

  <objects xmi:id="dep1" xsi:type="UML:Dependency" name="D1"/>
  <links xsi:type="UML:client" source="dep1" target="cls1"/>
  <links xsi:type="UML:supplier" source="dep1" target="cls2"/>
</model>
'''
    return _write_generated_input("uml2java_featureful_input.xmi", xml)


def generate_uml_inherited_property_input():
    xml = '''<?xml version="1.0" encoding="UTF-8"?>
<model xmlns:xmi="http://www.omg.org/XMI" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <objects xmi:id="model1" xsi:type="UML:Model" name="M1"/>
  <objects xmi:id="pkg1" xsi:type="UML:Package" name="Pkg1"/>
  <objects xmi:id="parent1" xsi:type="UML:Class" name="N1" isAbstract="true" isFinal="false" priority="4" layerTag="Core" kind="Entity"/>
  <objects xmi:id="child1" xsi:type="UML:Class" name="C" isAbstract="false" isFinal="false" priority="1" layerTag="Core" kind="Entity"/>
  <objects xmi:id="prop1" xsi:type="UML:Property" name="f" visibility="private" isStatic="false" isDerived="false" isReadOnly="false" isOrdered="false" isUnique="true" lower="0" upper="1" defaultValue=""/>
  <objects xmi:id="prim1" xsi:type="UML:PrimitiveType" name="N1"/>
  <objects xmi:id="gen1" xsi:type="UML:Generalization" isSubstitutable="true"/>

  <links xsi:type="UML:rootPackages" source="model1" target="pkg1"/>
  <links xsi:type="UML:packagedElement" source="pkg1" target="parent1"/>
  <links xsi:type="UML:packagedElement" source="pkg1" target="child1"/>
  <links xsi:type="UML:packagedElement" source="pkg1" target="prim1"/>
  <links xsi:type="UML:ownedAttribute" source="parent1" target="prop1"/>
  <links xsi:type="UML:type" source="prop1" target="prim1"/>
  <links xsi:type="UML:general" source="gen1" target="parent1"/>
  <links xsi:type="UML:specific" source="gen1" target="child1"/>
</model>
'''
    return _write_generated_input("uml2java_inherited_property_input.xmi", xml)

def generate_mindmap_input(num_nodes=2, num_edges=2997):
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<model xmlns:xmi="http://www.omg.org/XMI" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">',
             '  <objects xmi:id="mm1" xsi:type="MindMap:MindMapModel"/>']
    for i in range(num_nodes):
        lines.append(f'  <objects xmi:id="t{i}" xsi:type="MindMap:Topic"/>')
        lines.append(f'  <links xsi:type="MindMap:nodes" source="mm1" target="t{i}"/>')
    for i in range(num_edges):
        lines.append(f'  <objects xmi:id="b{i}" xsi:type="MindMap:Branch"/>')
        lines.append(f'  <links xsi:type="MindMap:edges" source="mm1" target="b{i}"/>')
        src = f"t{i % num_nodes}"
        dst = f"t{(i+1) % num_nodes}"
        lines.append(f'  <links xsi:type="MindMap:src" source="b{i}" target="{src}"/>')
        lines.append(f'  <links xsi:type="MindMap:dst" source="b{i}" target="{dst}"/>')
    lines.append('</model>')
    return _write_generated_input("mindmap_input.xmi", "\n".join(lines))

def generate_statechart_input(num_nodes=2, num_edges=2997):
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<model xmlns:xmi="http://www.omg.org/XMI" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">',
             '  <objects xmi:id="mm1" xsi:type="Statechart:StatechartModel"/>']
    for i in range(num_nodes):
        lines.append(f'  <objects xmi:id="t{i}" xsi:type="Statechart:State"/>')
        lines.append(f'  <links xsi:type="Statechart:nodes" source="mm1" target="t{i}"/>')
    for i in range(num_edges):
        lines.append(f'  <objects xmi:id="b{i}" xsi:type="Statechart:Trigger"/>')
        lines.append(f'  <links xsi:type="Statechart:edges" source="mm1" target="b{i}"/>')
        src = f"t{i % num_nodes}"
        dst = f"t{(i+1) % num_nodes}"
        lines.append(f'  <links xsi:type="Statechart:src" source="b{i}" target="{src}"/>')
        lines.append(f'  <links xsi:type="Statechart:dst" source="b{i}" target="{dst}"/>')
    lines.append('</model>')
    return _write_generated_input("statechart_input.xmi", "\n".join(lines))

def generate_org_input(num_nodes=2, num_edges=2997):
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<model xmlns:xmi="http://www.omg.org/XMI" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">',
             '  <objects xmi:id="mm1" xsi:type="Organization:OrgModel"/>']
    for i in range(num_nodes):
        lines.append(f'  <objects xmi:id="t{i}" xsi:type="Organization:Role"/>')
        lines.append(f'  <links xsi:type="Organization:nodes" source="mm1" target="t{i}"/>')
    for i in range(num_edges):
        lines.append(f'  <objects xmi:id="b{i}" xsi:type="Organization:Delegation"/>')
        lines.append(f'  <links xsi:type="Organization:edges" source="mm1" target="b{i}"/>')
        src = f"t{i % num_nodes}"
        dst = f"t{(i+1) % num_nodes}"
        lines.append(f'  <links xsi:type="Organization:src" source="b{i}" target="{src}"/>')
        lines.append(f'  <links xsi:type="Organization:dst" source="b{i}" target="{dst}"/>')
    lines.append('</model>')
    return _write_generated_input("org_input.xmi", "\n".join(lines))

def generate_component_input(num_nodes=2, num_edges=2997):
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<model xmlns:xmi="http://www.omg.org/XMI" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">',
             '  <objects xmi:id="mm1" xsi:type="Component:ComponentModel"/>']
    for i in range(num_nodes):
        lines.append(f'  <objects xmi:id="t{i}" xsi:type="Component:ComponentNode"/>')
        lines.append(f'  <links xsi:type="Component:nodes" source="mm1" target="t{i}"/>')
    for i in range(num_edges):
        lines.append(f'  <objects xmi:id="b{i}" xsi:type="Component:Dependency"/>')
        lines.append(f'  <links xsi:type="Component:edges" source="mm1" target="b{i}"/>')
        src = f"t{i % num_nodes}"
        dst = f"t{(i+1) % num_nodes}"
        lines.append(f'  <links xsi:type="Component:src" source="b{i}" target="{src}"/>')
        lines.append(f'  <links xsi:type="Component:dst" source="b{i}" target="{dst}"/>')
    lines.append('</model>')
    return _write_generated_input("comp_input.xmi", "\n".join(lines))

def generate_usecase_input(num_nodes=2, num_edges=2997):
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<model xmlns:xmi="http://www.omg.org/XMI" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">',
             '  <objects xmi:id="mm1" xsi:type="UseCase:UseCaseModel"/>']
    for i in range(num_nodes):
        lines.append(f'  <objects xmi:id="t{i}" xsi:type="UseCase:UseCaseNode"/>')
        lines.append(f'  <links xsi:type="UseCase:nodes" source="mm1" target="t{i}"/>')
    for i in range(num_edges):
        lines.append(f'  <objects xmi:id="b{i}" xsi:type="UseCase:Include"/>')
        lines.append(f'  <links xsi:type="UseCase:edges" source="mm1" target="b{i}"/>')
        src = f"t{i % num_nodes}"
        dst = f"t{(i+1) % num_nodes}"
        lines.append(f'  <links xsi:type="UseCase:src" source="b{i}" target="{src}"/>')
        lines.append(f'  <links xsi:type="UseCase:dst" source="b{i}" target="{dst}"/>')
    lines.append('</model>')
    return _write_generated_input("usecase_input.xmi", "\n".join(lines))


def build_targets():
    class2rel_example = DSLT_EXAMPLES / "class2relational_example"
    return [
        {
            "spec": DSLT_EXAMPLES / "persons_concrete.dslt",
            "inputs": [
                ConcreteInputCase("baseline", DSLT_EXAMPLES / "persons_example" / "input" / "household_input.xmi"),
            ],
        },
        {
            "spec": DSLT_EXAMPLES / "class2relational_concrete.dslt",
            "inputs": [
                ConcreteInputCase("minimal", DSLT_EXAMPLES / "models" / "class2relational_minimal_input.xmi"),
                ConcreteInputCase("association_example", class2rel_example / "with_association_input.xmi"),
                ConcreteInputCase("generalization_example", class2rel_example / "with_generalization_input.xmi"),
                ConcreteInputCase("many_to_many_example", class2rel_example / "with_many_to_many_input.xmi"),
            ],
        },
        {
            "spec": DSLT_EXAMPLES / "uml2java_concrete_canonical.dslt",
            "inputs": [
                ConcreteInputCase("minimal", DSLT_EXAMPLES / "models" / "uml2java_minimal_input.xmi"),
                ConcreteInputCase("featureful", generate_uml_featureful_input),
            ],
        },
        {
            "spec": DSLT_EXAMPLES / "bpmn2petri_concrete.dslt",
            "inputs": [
                ConcreteInputCase("baseline", generate_bpmn_input),
                ConcreteInputCase("featureful", generate_bpmn_featureful_input),
            ],
        },
        {
            "spec": DSLT_EXAMPLES / "family2socialnetwork_concrete.dslt",
            "inputs": [ConcreteInputCase("baseline", generate_family_input)],
        },
        {
            "spec": DSLT_EXAMPLES / "fsm2petrinet_concrete.dslt",
            "inputs": [ConcreteInputCase("baseline", generate_fsm_input)],
        },
        {
            "spec": DSLT_EXAMPLES / "tree2graph_concrete.dslt",
            "inputs": [ConcreteInputCase("baseline", generate_tree_input)],
        },
        {
            "spec": DSLT_EXAMPLES / "mindmap2graph_concrete.dslt",
            "inputs": [ConcreteInputCase("baseline", generate_mindmap_input)],
        },
        {
            "spec": DSLT_EXAMPLES / "statechart2flow_concrete.dslt",
            "inputs": [ConcreteInputCase("baseline", generate_statechart_input)],
        },
        {
            "spec": DSLT_EXAMPLES / "organization2accesscontrol_concrete.dslt",
            "inputs": [ConcreteInputCase("baseline", generate_org_input)],
        },
        {
            "spec": DSLT_EXAMPLES / "component2deployment_concrete.dslt",
            "inputs": [ConcreteInputCase("baseline", generate_component_input)],
        },
        {
            "spec": DSLT_EXAMPLES / "usecase2activity_concrete.dslt",
            "inputs": [ConcreteInputCase("baseline", generate_usecase_input)],
        },
    ]


def cross_validation_probe_inputs(spec_name: str, prop_name: str):
    probes: list[ConcreteInputCase] = []
    if spec_name == "class2relational_concrete.dslt":
        if prop_name == "AssociationCreatesForeignKey":
            probes.append(ConcreteInputCase("one_to_many_probe", generate_class2relational_one_to_many_input))
        if prop_name == "OneToManyAssociationCreatesForeignKey":
            probes.append(ConcreteInputCase("one_to_many_probe", generate_class2relational_one_to_many_input))
            probes.append(ConcreteInputCase("abstract_assoc_probe", generate_class2relational_abstract_assoc_input))
        if prop_name == "ClassTypedAttributeBecomesFKColumn":
            probes.append(ConcreteInputCase("class_typed_attr_probe", generate_class2relational_class_typed_attr_input))
        if prop_name in {
            "MultiValuedAttributeCreatesTable",
            "Diag_MultiValuedAttrCreatesSeparateTable",
        }:
            probes.append(ConcreteInputCase("multivalued_attr_probe", generate_class2relational_multivalued_attr_input))
    if spec_name == "uml2java_concrete_canonical.dslt" and prop_name == "InheritedPropertyAccessibility":
        probes.append(ConcreteInputCase("inherited_property_probe", generate_uml_inherited_property_input))
    return probes


def _collect_concrete_evidence(spec_path: Path, input_cases: list[ConcreteInputCase]) -> dict[str, list[tuple[str, str]]]:
    evidence: dict[str, list[tuple[str, str]]] = defaultdict(list)
    seen_labels: set[str] = set()
    for case in input_cases:
        if case.label in seen_labels:
            continue
        seen_labels.add(case.label)
        input_path = _resolve_input_path(case.source)
        concrete_props = run_concrete(spec_path, input_path)
        if not concrete_props:
            continue
        for prop_name, status in concrete_props.items():
            evidence[prop_name].append((case.label, status))
    return evidence


def _summarize_concrete_evidence(rows: list[tuple[str, str]]) -> tuple[str, Counter]:
    counts = Counter(status for _, status in rows)
    total = len(rows)
    if total == 0:
        return "no concrete evidence", counts
    parts = [f"hit={total - counts.get('PRECONDITION_NEVER_MATCHED', 0)}/{total}"]
    for status in ("HOLDS", "VIOLATED", "UNEXPECTEDLY_HOLDS", "PRECONDITION_NEVER_MATCHED", "NOT_RUN"):
        if counts.get(status, 0):
            parts.append(f"{status}={counts[status]}")
    return "; ".join(parts), counts


def _classify_cross_validation(prover_status: str, evidence_rows: list[tuple[str, str]]) -> tuple[str, str, str]:
    evidence_summary, counts = _summarize_concrete_evidence(evidence_rows)
    hit_count = len(evidence_rows) - counts.get("PRECONDITION_NEVER_MATCHED", 0)
    if prover_status == "HOLDS":
        if counts.get("VIOLATED", 0) or counts.get("UNEXPECTEDLY_HOLDS", 0):
            return evidence_summary, "❌ No", "CRITICAL: proved HOLDS but concrete evidence shows a violation"
        if hit_count == 0:
            return evidence_summary, "⚠️ Vacuous", "All concrete inputs missed the precondition"
        if counts.get("HOLDS", 0):
            if counts.get("PRECONDITION_NEVER_MATCHED", 0):
                return evidence_summary, "✅ Yes", "Matched on at least one concrete input; remaining inputs are vacuous"
            return evidence_summary, "✅ Yes", "Matched on concrete inputs that hit the precondition"
    elif prover_status == "VIOLATED":
        if counts.get("VIOLATED", 0) or counts.get("UNEXPECTEDLY_HOLDS", 0):
            return evidence_summary, "✅ Yes", "Concrete evidence witnesses the symbolic violation"
        if hit_count == 0:
            return evidence_summary, "⚠️ Vacuous", "All concrete inputs missed the precondition"
        if counts.get("HOLDS", 0):
            return evidence_summary, "⚠️ Expected", "Symbolic result is existential; current concrete inputs do not witness the violation"
    elif prover_status == "UNKNOWN":
        if hit_count == 0:
            return evidence_summary, "⚠️ Vacuous", "Symbolic run was inconclusive and all concrete inputs missed the precondition"
        if counts.get("VIOLATED", 0) or counts.get("UNEXPECTEDLY_HOLDS", 0):
            return evidence_summary, "⚠️ Inconclusive", "Concrete evidence found violations while the symbolic run remained inconclusive"
        if counts.get("HOLDS", 0):
            return evidence_summary, "⚠️ Inconclusive", "Symbolic run was inconclusive (for example an unconfirmed minimal-fragment violation), while sampled concrete inputs held"
    return evidence_summary, "N/A", f"Prover returned {prover_status}"

def run_prover(spec_name):
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "run_hybrid_cegar_stress.py"),
        "--specs", spec_name
    ]
    print(f"Running prover on {spec_name}...", flush=True)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    result = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, env=env)
    
    props = {}
    for line in result.stdout.splitlines():
        m = re.search(r'\.dslt\s*/\s*(\w+).*?(HOLDS|VIOLATED|UNKNOWN|ERROR|Exception|Not in fragment)', line)
        if m:
            prop_name = m.group(1)
            statuses = re.findall(r'(HOLDS|VIOLATED|UNKNOWN|ERROR|Exception|Not in fragment)', line)
            if statuses:
                props[prop_name] = statuses[-1]
    return props

def run_concrete(spec_path, input_path):
    out_xmi = GEN_DIR / f"{spec_path.stem}_out.xmi"
    out_json = GEN_DIR / f"{spec_path.stem}_props.json"
    
    cmd = [
        sys.executable,
        "-m", "dsltrans.run",
        "--spec", str(spec_path),
        "--in", str(input_path),
        "--out", str(out_xmi),
        "--check-concrete-properties",
        "--property-report", str(out_json)
    ]
    print(f"Running concrete engine on {spec_path.name} with {input_path.name}...", flush=True)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    
    res = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, env=env)
    
    if res.returncode != 0:
        print(f"Concrete execution failed for {spec_path.name}:\n{res.stderr}", flush=True)
        return None
    
    if not out_json.exists():
        print(f"Concrete execution did not produce JSON report for {spec_path.name}", flush=True)
        return None
    
    try:
        data = json.loads(out_json.read_text(encoding="utf-8"))
        props = {}
        for row in data:
            props[row["name"]] = str(row["status"]).upper()
        return props
    except Exception as e:
        print(f"Error reading JSON for {spec_path.name}: {e}", flush=True)
        return None

def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=str, default=None, help="Output markdown path. Default: docs/evaluation/large_scale_cross_validation_results.md")
    ap.add_argument("--specs", nargs="*", default=None, help="Restrict to these spec file names.")
    args = ap.parse_args()
    default_report = ROOT / "docs" / "evaluation" / "large_scale_cross_validation_results.md"
    report_path = Path(args.out) if args.out else default_report
    targets = build_targets()
    if args.specs:
        allowed = set(args.specs)
        targets = [target for target in targets if target["spec"].name in allowed]

    report_lines = [
        "# Large Scale Cross-Validation Results: Symbolic vs Concrete Property Execution",
        "",
        "This report compares the property verdicts from the symbolic execution prover against the concrete DSLTrans engine.",
        "Concrete validation now uses input portfolios per transformation plus a first batch of property-targeted probe inputs for previously vacuous cases.",
        "The `Concrete Evidence` column summarizes how many concrete inputs actually hit each property precondition and how the resulting statuses split across those inputs.",
        "",
        "| Transformation | Property | Prover Status | Concrete Evidence | Match? | Notes |",
        "| --- | --- | --- | --- | --- | --- |"
    ]

    for target in targets:
        spec_path = target["spec"]
        print(f"=== Processing {spec_path.name} ===", flush=True)
        prover_props = run_prover(spec_path.name)
        concrete_evidence = _collect_concrete_evidence(spec_path, target["inputs"])

        if not concrete_evidence:
            print(f"Warning: No concrete properties for {spec_path.name}", flush=True)
            report_lines.append(f"| {spec_path.name} | ALL | - | no concrete evidence | ❌ No | Concrete execution failed |")
            continue

        all_prop_names = set(prover_props.keys()).union(concrete_evidence.keys())

        for prop_name in sorted(all_prop_names):
            pr_stat = prover_props.get(prop_name, "NOT_RUN")
            evidence_rows = list(concrete_evidence.get(prop_name, []))
            probe_cases = cross_validation_probe_inputs(spec_path.name, prop_name)
            if probe_cases:
                for extra_prop_name, rows in _collect_concrete_evidence(spec_path, probe_cases).items():
                    if extra_prop_name == prop_name:
                        evidence_rows.extend(rows)
            evidence_summary, match, notes = _classify_cross_validation(pr_stat, evidence_rows)
            report_lines.append(
                f"| {spec_path.name} | {prop_name} | {pr_stat} | {evidence_summary} | {match} | {notes} |"
            )

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(report_lines), encoding="utf-8")
    print(f"\nDone! Report written to {report_path}", flush=True)

if __name__ == "__main__":
    main()

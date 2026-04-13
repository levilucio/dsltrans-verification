import {
  getMetamodelNameFromXmi,
  getMermaidForModel,
  isActivityMetamodel,
  isUmlMetamodel,
  parseXmiToActivityFlowStructure,
  parseXmiToGraph,
  parseXmiToUmlStructure,
  stringifyActivityFlowToMermaid,
  stringifyGraphToMermaid,
  stringifyGraphToXmi,
  stringifyUmlToMermaidClassDiagram,
  validateInputModelForTransformation,
} from "@/utils/xmiUtils";

describe("xmi utils", () => {
  test("parse and stringify basic graph", () => {
    const xmi = `<?xml version="1.0" encoding="UTF-8"?>
<model xmlns:xmi="http://www.omg.org/XMI" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <objects xmi:id="n1" xsi:type="MM:A" />
  <objects xmi:id="n2" xsi:type="MM:B" />
  <links xsi:type="MM:ab" source="n1" target="n2" />
</model>`;
    const graph = parseXmiToGraph(xmi);
    expect(graph.nodes).toHaveLength(2);
    expect(graph.edges).toHaveLength(1);
    const out = stringifyGraphToXmi(graph, "MM");
    expect(out).toContain("<objects");
    expect(out).toContain("<links");
  });

  test("getMetamodelNameFromXmi extracts prefix from first object", () => {
    const xmi = `<?xml version="1.0"?>
<model xmlns:xmi="http://www.omg.org/XMI" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <objects xmi:id="n1" xsi:type="Package:Package" />
</model>`;
    expect(getMetamodelNameFromXmi(xmi)).toBe("Package");
  });

  test("getMetamodelNameFromXmi returns null when no objects", () => {
    const xmi = `<?xml version="1.0"?>
<model xmlns:xmi="http://www.omg.org/XMI"><objects /></model>`;
    expect(getMetamodelNameFromXmi(xmi)).toBeNull();
  });

  test("getMetamodelNameFromXmi returns null when xsi:type has no colon", () => {
    const xmi = `<?xml version="1.0"?>
<model xmlns:xmi="http://www.omg.org/XMI" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <objects xmi:id="n1" xsi:type="JustType" />
</model>`;
    expect(getMetamodelNameFromXmi(xmi)).toBeNull();
  });

  test("getMetamodelNameFromXmi returns null when xsi:type is missing", () => {
    const xmi = `<?xml version="1.0"?>
<model xmlns:xmi="http://www.omg.org/XMI" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <objects xmi:id="n1" />
</model>`;
    expect(getMetamodelNameFromXmi(xmi)).toBeNull();
  });

  test("stringifyGraphToMermaid emits nodes and labeled edges", () => {
    const graph = {
      nodes: [
        { id: "start-1", className: "StartEvent" },
        { id: "p1", className: "Place" },
      ],
      edges: [
        { id: "e1", sourceId: "start-1", targetId: "p1", assocName: "flowNodes", edgeType: "association" },
        { id: "e2", sourceId: "start-1", targetId: "p1", assocName: "trace", edgeType: "trace" },
      ],
    };
    const text = stringifyGraphToMermaid(graph, "Input Model");
    expect(text).toContain("flowchart LR");
    expect(text).toContain("start_1");
    expect(text).toContain('["StartEvent\\nstart-1"]');
    expect(text).toContain('(("Place\\np1"))');
    expect(text).toContain("-->|flowNodes|");
    expect(text).toContain("-.->|trace|");
  });
});

describe("validateInputModelForTransformation", () => {
  const xmiWithPackage = `<?xml version="1.0"?>
<model xmlns:xmi="http://www.omg.org/XMI" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <objects xmi:id="c1" xsi:type="Package:Class" />
</model>`;

  const xmiWithClass = `<?xml version="1.0"?>
<model xmlns:xmi="http://www.omg.org/XMI" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <objects xmi:id="c1" xsi:type="Class:Class" />
</model>`;

  test("rejects when no transformation is loaded (source metamodel null)", () => {
    const result = validateInputModelForTransformation(xmiWithPackage, null);
    expect(result.ok).toBe(false);
    expect(result.error).toContain("Load a transformation first");
  });

  test("rejects when no transformation is loaded (source metamodel undefined)", () => {
    const result = validateInputModelForTransformation(xmiWithPackage, undefined);
    expect(result.ok).toBe(false);
    expect(result.error).toContain("Load a transformation first");
  });

  test("rejects when source metamodel is empty string", () => {
    const result = validateInputModelForTransformation(xmiWithPackage, "");
    expect(result.ok).toBe(false);
    expect(result.error).toContain("Load a transformation first");
  });

  test("rejects when model metamodel cannot be determined", () => {
    const xmiNoType = `<?xml version="1.0"?>
<model xmlns:xmi="http://www.omg.org/XMI"><objects /></model>`;
    const result = validateInputModelForTransformation(xmiNoType, "Package");
    expect(result.ok).toBe(false);
    expect(result.error).toContain("Could not determine metamodel");
  });

  test("rejects when model metamodel does not match transformation source metamodel", () => {
    const result = validateInputModelForTransformation(xmiWithClass, "Package");
    expect(result.ok).toBe(false);
    expect(result.error).toContain("Class");
    expect(result.error).toContain("Package");
    expect(result.error).toContain("does not match");
  });

  test("accepts when model metamodel matches transformation source metamodel", () => {
    const result = validateInputModelForTransformation(xmiWithPackage, "Package");
    expect(result.ok).toBe(true);
  });

  test("accepts when both use same metamodel name (Class)", () => {
    const result = validateInputModelForTransformation(xmiWithClass, "Class");
    expect(result.ok).toBe(true);
  });
});

describe("UML Mermaid", () => {
  test("isUmlMetamodel recognizes UML and UMLConcrete", () => {
    expect(isUmlMetamodel("UML")).toBe(true);
    expect(isUmlMetamodel("UMLConcrete")).toBe(true);
    expect(isUmlMetamodel("uml")).toBe(true);
    expect(isUmlMetamodel("UML2")).toBe(true);
    expect(isUmlMetamodel("Class")).toBe(false);
    expect(isUmlMetamodel(null)).toBe(false);
    expect(isUmlMetamodel("")).toBe(false);
  });

  test("parseXmiToUmlStructure extracts classifiers and relations", () => {
    const xmi = `<?xml version="1.0" encoding="UTF-8"?>
<model xmlns:xmi="http://www.omg.org/XMI" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <objects xmi:id="cls_entity" xsi:type="UMLConcrete:Class" name="EntityBase" isAbstract="true"/>
  <objects xmi:id="cls_customer" xsi:type="UMLConcrete:Class" name="Customer"/>
  <objects xmi:id="prop_name" xsi:type="UMLConcrete:Property" name="name"/>
  <objects xmi:id="prim_string" xsi:type="UMLConcrete:PrimitiveType" name="String"/>
  <objects xmi:id="gen_1" xsi:type="UMLConcrete:Generalization"/>
  <links xsi:type="UMLConcrete:ownedAttribute" source="cls_customer" target="prop_name"/>
  <links xsi:type="UMLConcrete:type" source="prop_name" target="prim_string"/>
  <links xsi:type="UMLConcrete:general" source="gen_1" target="cls_entity"/>
  <links xsi:type="UMLConcrete:specific" source="gen_1" target="cls_customer"/>
</model>`;
    const uml = parseXmiToUmlStructure(xmi);
    expect(uml.classifiers).toHaveLength(2);
    expect(uml.classifiers.map((c) => c.name)).toEqual(expect.arrayContaining(["EntityBase", "Customer"]));
    expect(uml.classifiers.find((c) => c.name === "Customer").attributes).toEqual([{ name: "name", typeName: "String" }]);
    expect(uml.generalizations).toHaveLength(1);
    expect(uml.generalizations[0]).toEqual({ parentId: "cls_entity", childId: "cls_customer" });
  });

  test("stringifyUmlToMermaidClassDiagram emits classDiagram with relations", () => {
    const uml = {
      classifiers: [
        { id: "c1", name: "Parent", kind: "Class", attributes: [], operations: [], literals: [] },
        { id: "c2", name: "Child", kind: "Class", attributes: [], operations: [], literals: [] },
      ],
      generalizations: [{ parentId: "c1", childId: "c2" }],
      realizations: [],
      dependencies: [],
      objects: {},
    };
    const out = stringifyUmlToMermaidClassDiagram(uml, "Test");
    expect(out).toContain("classDiagram");
    expect(out).toContain("class Parent");
    expect(out).toContain("class Child");
    expect(out).toContain("Parent <|-- Child");
  });

  test("getMermaidForModel returns class diagram when source is UML", () => {
    const xmi = `<?xml version="1.0"?>
<model xmlns:xmi="http://www.omg.org/XMI" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <objects xmi:id="a" xsi:type="UMLConcrete:Class" name="Service"/>
</model>`;
    const graph = parseXmiToGraph(xmi);
    const mermaid = getMermaidForModel(graph, xmi, "Input", "UMLConcrete");
    expect(mermaid).toContain("classDiagram");
    expect(mermaid).toContain("Service");
  });

  test("getMermaidForModel returns flowchart when source is not UML", () => {
    const xmi = `<?xml version="1.0"?>
<model xmlns:xmi="http://www.omg.org/XMI" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <objects xmi:id="a" xsi:type="Class:Class" />
</model>`;
    const graph = parseXmiToGraph(xmi);
    const mermaid = getMermaidForModel(graph, xmi, "Input", "Class");
    expect(mermaid).toContain("flowchart LR");
    expect(mermaid).not.toContain("classDiagram");
  });
});

describe("Activity Mermaid", () => {
  test("isActivityMetamodel", () => {
    expect(isActivityMetamodel("Activity")).toBe(true);
    expect(isActivityMetamodel(" UseCase ")).toBe(false);
    expect(isActivityMetamodel(null)).toBe(false);
  });

  test("parseXmiToActivityFlowStructure reads actions and flows", () => {
    const xmi = `<?xml version="1.0" encoding="UTF-8"?>
<model xmlns:xmi="http://www.omg.org/XMI" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <objects xmi:id="am" xsi:type="Activity:ActivityModel" />
  <objects xmi:id="a1" xsi:type="Activity:Action" name="Left" />
  <objects xmi:id="a2" xsi:type="Activity:Action" name="Right" />
  <objects xmi:id="f1" xsi:type="Activity:Flow" />
  <links xsi:type="Activity:nodes" source="am" target="a1" />
  <links xsi:type="Activity:nodes" source="am" target="a2" />
  <links xsi:type="Activity:edges" source="am" target="f1" />
  <links xsi:type="Activity:src" source="f1" target="a1" />
  <links xsi:type="Activity:dst" source="f1" target="a2" />
</model>`;
    const s = parseXmiToActivityFlowStructure(xmi);
    expect(s.actions.map((x) => x.id).sort()).toEqual(["a1", "a2"]);
    expect(s.transitions).toEqual([{ fromId: "a1", toId: "a2", flowId: "f1" }]);
  });

  test("getMermaidForModel returns flowchart TD for Activity target", () => {
    const xmi = `<?xml version="1.0" encoding="UTF-8"?>
<model xmlns:xmi="http://www.omg.org/XMI" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <objects xmi:id="am" xsi:type="Activity:ActivityModel" />
  <objects xmi:id="a1" xsi:type="Activity:Action" name="A" />
  <objects xmi:id="f1" xsi:type="Activity:Flow" />
  <links xsi:type="Activity:nodes" source="am" target="a1" />
  <links xsi:type="Activity:edges" source="am" target="f1" />
  <links xsi:type="Activity:src" source="f1" target="a1" />
  <links xsi:type="Activity:dst" source="f1" target="a1" />
</model>`;
    const graph = parseXmiToGraph(xmi);
    const m = getMermaidForModel(graph, xmi, "Out", "Activity");
    expect(m).toContain("flowchart TD");
    expect(m).toContain("A");
    expect(stringifyActivityFlowToMermaid(parseXmiToActivityFlowStructure(xmi), "T")).toContain("flowchart TD");
  });
});

import {
  parseDsltrans,
  parseDsltransToGraph,
  parsePropertyToGraph,
  parsePropertiesFromSpec,
  serializeDsltrans,
} from "@/utils/dsltransSerializer";

describe("dsltransSerializer", () => {
  test("serializes visual model into DSLTrans-like text", () => {
    const text = serializeDsltrans({
      layers: [{ id: "l1", name: "Layer1", index: 0 }],
      nodes: [
        { id: "r1", kind: "RULE", label: "Rule1", layerId: "l1" },
        { id: "m1", kind: "MATCH", label: "a : A", parentRuleId: "r1" },
        { id: "a1", kind: "APPLY", label: "b : B", parentRuleId: "r1" },
      ],
    });
    expect(text).toContain("dsltransformation");
    expect(text).toContain("layer Layer1");
    expect(text).toContain("rule Rule1");
  });

  test("parses DSLTrans-like text", () => {
    const parsed = parseDsltrans(`dsltransformation
layer L1 {
  rule R1 {
    match {
      a : A
    }
    apply {
      b : B
    }
  }
}`);
    expect(parsed.layers).toHaveLength(1);
    expect(parsed.rules).toHaveLength(1);
    expect(parsed.rules[0].label).toBe("R1");
  });

  test("parses transformation syntax from fragment spec", () => {
    const parsed = parseDsltransToGraph(`transformation T : A -> B {
  layer L1 {
    rule R1 {
      match {
        any x : X
      }
      apply {
        y : Y
      }
    }
  }
}`);
    expect(parsed.layers).toHaveLength(1);
    expect(parsed.nodes.some((n) => n.kind === "RULE" && n.label === "R1")).toBe(true);
  });

  test("parses single-line match and apply (HouseholdsToCommunity style)", () => {
    const parsed = parseDsltransToGraph(`transformation Persons_frag : Household -> Community {
  layer TopLevel {
    rule HouseholdsToCommunity {
      match { any h : Households }
      apply { c : Community }
    }
  }
}`);
    const rules = parsed.nodes.filter((n) => n.kind === "RULE");
    expect(rules).toHaveLength(1);
    expect(rules[0].label).toBe("HouseholdsToCommunity");
    const matchNodes = parsed.nodes.filter(
      (n) => n.kind === "MATCH" && n.parentRuleId === rules[0].id,
    );
    const applyNodes = parsed.nodes.filter(
      (n) => n.kind === "APPLY" && n.parentRuleId === rules[0].id,
    );
    expect(matchNodes).toHaveLength(1);
    expect(matchNodes[0].label).toBe("any h : Households");
    expect(applyNodes).toHaveLength(1);
    expect(applyNodes[0].label).toBe("c : Community");
  });

  test("parses backward block and creates trace edges", () => {
    const parsed = parseDsltransToGraph(`transformation T : A -> B {
  layer L1 {
    rule R1 {
      match { any a : X }
      apply { x : Y }
      backward { x <--trace-- a }
    }
  }
}`);
    expect(parsed.edges).toHaveLength(1);
    expect(parsed.edges[0].edgeType).toBe("trace");
    const rule = parsed.nodes.find((n) => n.kind === "RULE" && n.label === "R1");
    const matchNode = parsed.nodes.find(
      (n) => n.kind === "MATCH" && n.parentRuleId === rule?.id,
    );
    const applyNode = parsed.nodes.find(
      (n) => n.kind === "APPLY" && n.parentRuleId === rule?.id,
    );
    expect(parsed.edges[0].sourceId).toBe(matchNode?.id);
    expect(parsed.edges[0].targetId).toBe(applyNode?.id);
  });

  test("parses apply elements with inline braces and backward links", () => {
    const parsed = parseDsltransToGraph(`transformation T : A -> B {
  layer L1 {
    rule R1 {
      match {
        any cls : Class
        any prop : Property
      }
      apply {
        classDecl : ClassDeclaration { name = cls.name }
        field : FieldDeclaration { name = prop.name }
      }
      backward {
        classDecl <--trace-- cls
        field <--trace-- prop
      }
    }
  }
}`);
    const rule = parsed.nodes.find((n) => n.kind === "RULE" && n.label === "R1");
    const applyNodes = parsed.nodes.filter(
      (n) => n.kind === "APPLY" && n.parentRuleId === rule?.id,
    );
    expect(applyNodes).toHaveLength(2);
    expect(applyNodes.map((n) => n.varName)).toContain("classDecl");
    expect(applyNodes.map((n) => n.varName)).toContain("field");
    const classDeclApply = applyNodes.find((n) => n.varName === "classDecl");
    const fieldApply = applyNodes.find((n) => n.varName === "field");
    expect(classDeclApply?.attributeBindings).toEqual([{ attr: "name", expr: "cls.name" }]);
    expect(fieldApply?.attributeBindings).toEqual([{ attr: "name", expr: "prop.name" }]);
    expect(parsed.edges).toHaveLength(2);
    const matchCls = parsed.nodes.find(
      (n) => n.kind === "MATCH" && n.parentRuleId === rule?.id && n.label?.includes("cls"),
    );
    const matchProp = parsed.nodes.find(
      (n) => n.kind === "MATCH" && n.parentRuleId === rule?.id && n.label?.includes("prop"),
    );
    expect(parsed.edges.some((e) => e.sourceId === matchCls?.id && e.targetId === classDeclApply?.id)).toBe(true);
    expect(parsed.edges.some((e) => e.sourceId === matchProp?.id && e.targetId === fieldApply?.id)).toBe(true);
  });

  test("parses direct match/apply relation declarations as labeled edges, not nodes", () => {
    const parsed = parseDsltransToGraph(`transformation T : A -> B {
  layer L1 {
    rule R1 {
      match {
        any f : Family
        any m : Member
        direct motherLink : mother -- f.m
      }
      apply {
        c : Community
        woman : Woman
        hasLink : has -- c.woman
      }
    }
  }
}`);
    const rule = parsed.nodes.find((n) => n.kind === "RULE" && n.label === "R1");
    const matchNodes = parsed.nodes.filter(
      (n) => n.kind === "MATCH" && n.parentRuleId === rule?.id,
    );
    const applyNodes = parsed.nodes.filter(
      (n) => n.kind === "APPLY" && n.parentRuleId === rule?.id,
    );
    expect(matchNodes.map((n) => n.label)).toEqual(
      expect.arrayContaining(["any f : Family", "any m : Member"]),
    );
    expect(applyNodes.map((n) => n.label)).toEqual(
      expect.arrayContaining(["c : Community", "woman : Woman"]),
    );
    expect(matchNodes.some((n) => n.label.includes("motherLink"))).toBe(false);
    expect(applyNodes.some((n) => n.label.includes("hasLink"))).toBe(false);
    const directEdges = parsed.edges.filter((e) => e.edgeType === "direct");
    expect(directEdges).toHaveLength(2);
    expect(directEdges.map((e) => e.label)).toEqual(
      expect.arrayContaining(["mother", "has"]),
    );
  });

  test("parses compact one-line property blocks into graph elements", () => {
    const props = parsePropertiesFromSpec(`
property NavigationCallHasGet {
  precondition { any op : Operation any c : NavigationCall where c.isStatic == false && c.isSuper == false direct owns : exprs -- op.c }
  postcondition { e_op : Operation e_op <--trace-- op i : Get i <--trace-- c outL : e_instrs -- e_op.i }
}`);
    expect(props).toHaveLength(1);
    expect(props[0].description).toBe("");
    const graph = parsePropertyToGraph(props[0].precondition, props[0].postcondition);

    expect(graph.preNodes.map((n) => n.varName)).toEqual(expect.arrayContaining(["op", "c"]));
    expect(graph.preRelations).toHaveLength(1);
    expect(graph.preRelations[0].assocName).toBe("exprs");

    expect(graph.postNodes.map((n) => n.varName)).toEqual(expect.arrayContaining(["e_op", "i"]));
    expect(graph.postRelations).toHaveLength(1);
    expect(graph.postRelations[0].assocName).toBe("e_instrs");
    expect(graph.traceEdges).toEqual(
      expect.arrayContaining([
        { sourceVar: "op", targetVar: "e_op" },
        { sourceVar: "c", targetVar: "i" },
      ]),
    );
  });

  test("parses optional property description in header", () => {
    const props = parsePropertiesFromSpec(`
property FieldOwnedByTracedExecEnv "Field is owned by the traced execution environment." {
  precondition { any mod : Module any f : Field direct l : fields -- mod.f }
  postcondition { env : ExecEnv env <--trace-- mod e_f : Field e_f <--trace-- f outL : e_fields -- env.e_f }
}`);
    expect(props).toHaveLength(1);
    expect(props[0].name).toBe("FieldOwnedByTracedExecEnv");
    expect(props[0].description).toBe("Field is owned by the traced execution environment.");
    expect(props[0].precondition).toContain("any mod : Module");
    expect(props[0].postcondition).toContain("env : ExecEnv");
  });

  test("parses consecutive direct relations in precondition", () => {
    const props = parsePropertiesFromSpec(`
property DependencyYieldsImport "A UML dependency from client to supplier yields an import." {
  precondition {
    any dep : Dependency
    any clientCls : Classifier
    any supplierCls : Classifier
    direct depClient : client -- dep.clientCls
    direct depSupplier : supplier -- dep.supplierCls
  }
  postcondition {
    cu : CompilationUnit
    importDecl : ImportDeclaration
    cu <--trace-- clientCls
    importDecl <--trace-- supplierCls
  }
}`);
    expect(props).toHaveLength(1);
    const graph = parsePropertyToGraph(props[0].precondition, props[0].postcondition);
    expect(graph.preNodes.map((n) => n.varName)).toEqual(
      expect.arrayContaining(["dep", "clientCls", "supplierCls"]),
    );
    expect(graph.preRelations).toHaveLength(2);
    expect(graph.preRelations.map((r) => r.assocName)).toEqual(
      expect.arrayContaining(["client", "supplier"]),
    );
  });
});

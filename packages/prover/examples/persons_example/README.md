# Persons Example: DSLTrans Transformation

This folder contains a complete example of running a DSLTrans transformation from Household to Community models using `persons_concrete.dslt`.

## Artifacts

| File | Description |
|------|-------------|
| `household_input.xmi` | Source XMI model (20 objects: 1 Households, 3 Families, 16 Members) |
| `community_output.xmi` | Target XMI model produced by the transformation |
| `README.md` | This file |

## Input Model Structure

- **1** `Households` root
- **3** `Family` objects (contained via `have`)
- **16** `Member` objects with roles:
  - Family 1: 1 father, 1 mother, 2 sons, 2 daughters
  - Family 2: 1 father, 1 mother, 1 son, 2 daughters
  - Family 3: 1 father, 1 mother, 2 sons, 1 daughter

Each `Member` has attributes: `isActive` (true), `roleTag`, `role` (Father/Mother/Son/Daughter).

## Transformation Result

The transformation `Persons_frag` maps:
- Households → Community
- Fathers → Man
- Mothers → Woman
- Sons → Man
- Daughters → Woman

**Output stats** (last run):
- Created nodes: 34
- Created edges: 16 (`has` links Community → Person)
- Created traces: 17 (source Member/Households → target Person/Community)

## How to Run

From the `symbolic-execution-engine` root:

```bash
python -m symex_engine.dsltrans.run \
  --spec dsltrans_examples/persons_concrete.dslt \
  --in dsltrans_examples/persons_example/household_input.xmi \
  --out dsltrans_examples/persons_example/community_output.xmi \
  --transformation Persons_frag
```

Use `--property-report path.json` to choose the property results file path. Add `--source-ecore` and `--target-ecore` for metamodel consistency checks.

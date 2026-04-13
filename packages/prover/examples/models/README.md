# Example XMI models (by transformation)

This folder holds sample **input/output** compact XMI models, **visualization** text dumps, and **property result** JSON files used in docs and manual runs.

Files are grouped **by transformation / case study** (not by metamodel alone):

| Subfolder | Transformation / use |
|-----------|----------------------|
| `uml2java/` | UML → Java (concrete spec examples: very_small … very_large) |
| `oclcompiler/` | OCL AST → EMFTVM-style target examples |
| `bibtex2docbook/` | BibTeX → DocBook examples; generic `out.xmi` sample lives here |
| `class2relational/` | Class diagram → relational graded inputs/outputs (`very_small` … `very_large`) |
| `usecase2activity/` | Use case → Activity graded inputs/outputs (`very_small` … `very_large`) |
| `usecase2activity_concrete/` | Concrete Use case → Activity examples with meaningful text/metadata |
| `statechart2flow/` | Statechart → Flow graded inputs/outputs (`very_small` … `very_large`) |

**Paths in commands:** use the subfolder, e.g.  
`examples/models/uml2java/uml2java_medium_input.xmi`.

Visualization `.txt` files that reference an XMI path use repo-relative paths like  
`dsltrans-prover/examples/models/<subfolder>/<file>.xmi`.

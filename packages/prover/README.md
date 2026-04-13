# DSLTrans Symbolic Execution Prover

This repository contains the essential artifacts for the symbolic and concrete execution of DSLTrans model transformations. It is a self-contained extraction of the core formal verification engine, focusing on the mathematically grounded bounded model checking approach (the "Cutoff Theorem").

## Directory Structure

- **`docs/`**: Documentation and formal theory.
  - **`theory/`**: Mathematical foundations, including the Cutoff Theorem explanation (`cutoff_explanation.tex`), fragment monotonicity, and limitations.
  - **`evaluation/`**: Results from cross-validation, stress testing, mutation testing, and correctness assessments.
- **`src/dsltrans/`**: The core implementation of the DSLTrans engine.
  - `smt_direct.py`: The direct SMT-based property prover.
  - `cutoff.py`: Implementation of the cutoff bound computation and fragment selection.
  - `runtime_engine.py`: The concrete execution engine for DSLTrans.
  - `parser.py`, `lexer.py`, `model.py`: Front-end for parsing `.dslt` files.
- **`tests/`**: Unit and integration tests for the engine.
- **`scripts/`**: Runners for stress tests, cross-validation, and CEGAR loops.
- **`examples/`**: Canonical DSLTrans specifications used for evaluation (e.g., `class2relational`, `persons`, `uml2java`).

## Key Concepts

The prover verifies properties of the form `Precondition => Postcondition` over model transformations. For the supported positive existence/traceability fragment, it uses a **Cutoff Theorem** to guarantee completeness: if no counterexample is found within the theorem-valid bound `K`, the property holds for all possible input models of any size.

The verification targets a specific fragment of DSLTrans (F-LNR) and bounded positive/traceability properties (G-BPP) to ensure decidability and tractability. Heuristic runs that use capped cutoffs, per-class type bounds, or stress/evaluation scripts should be read as bounded empirical evidence unless they explicitly report theorem-complete status.

## Running the Prover

You can use the provided scripts to run the evaluation campaigns:

```bash
# Run cross-validation (symbolic vs concrete execution)
PYTHONPATH=src python scripts/run_cross_validation.py

# Run stress tests
PYTHONPATH=src python scripts/run_all_stress_report.py
```

## Running Tests

To run the test suite:

```bash
PYTHONPATH=src pytest tests/
```

## Current Focus

The current focus is on keeping the theory, implementation, and evaluation artifacts aligned: theorem-backed claims should be stated only for theorem-valid runs in the positive/traceability fragment, while heuristic or capped runs should be reported explicitly as incomplete evidence.

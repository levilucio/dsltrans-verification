# BPMN to Petri Net test inputs

Small BPMN inputs for visual testing of `bpmn2petri_concrete.dslt`.

All models follow the same minimal XMI structure and use the BPMN metamodel links already used in `cross_validation_tmp/bpmn_featureful_input.xmi`.

## Files

- `01_start_only.xmi`: Minimal `Definitions -> Process` with one `StartEvent`.
- `02_linear_start_task_end.xmi`: Simple linear flow `StartEvent -> Task -> EndEvent`.
- `03_parallel_split_join.xmi`: Two parallel gateways with one task in between.
- `04_boundary_events.xmi`: One task with interrupting and non-interrupting boundary events.
- `05_message_cross_process.xmi`: Message flow from a task in one process to a task in another process.

## Suggested quick checks

- Run each input through `bpmn2petri_concrete.dslt`.
- In the UI, use **Copy Mermaid** on Input and Output panels and paste into a Mermaid viewer.
- Confirm expected structures:
  - Start and end events become places/pattern nodes.
  - Tasks produce execution/input/output pattern pieces.
  - Parallel gateway split/join yields balanced branching pattern.
  - Boundary events produce exception/cancel handling structures.
  - Message flow creates async communication pattern.

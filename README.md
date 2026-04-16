# DSLTrans Verification

DSLTrans Verification is a public monorepo for a visual DSLTrans transformation environment, a concrete transformation runner, and an SMT-backed symbolic verification engine.

It is designed for two audiences:
- people who already know model transformations and want a usable verification toolchain
- people who are new to model transformation and want runnable examples, screenshots, and a guided entry point

## What this project does

This project supports two complementary ways of working with DSLTrans:

1. **Concrete transformation execution**
   - load a DSLTrans transformation and an input model
   - run the transformation concretely
   - inspect the produced target model

2. **Symbolic verification**
   - define structural properties over source and target models
   - run SMT-based bounded verification
   - inspect proofs, counterexamples, and unknown cases

In practice, this makes the repository useful both as:
- a browser studio for authoring and exploring DSLTrans transformations
- a verification tool for checking whether transformations satisfy formal properties

## Repository layout

- `packages/web-app/` — browser studio and HTTP bridge used for concrete execution and verification
- `packages/prover/` — Python prover, abstraction pipeline, scripts, and examples
- `screenshots/` — public screenshots used in documentation
- `docs/` — public-facing supporting documentation

## User manual

For a feature-by-feature walkthrough of the web app, including a running UML2Java example, see:

- [`docs/USER_MANUAL.md`](./docs/USER_MANUAL.md)

## Quick start

### Local development

Requirements:
- Node.js 20+
- Python 3.11+

Run the web app and bridge locally:

```bash
cd packages/web-app
npm install
npm start
```

The server calls into the prover code in `packages/prover`.

## Public examples

The browser studio ships with built-in examples from the prover corpus. You can load them directly from the UI:
- built-in DSLTrans examples
- built-in input models
- local browser persistence for your current work
- local file import/export

Examples currently include transformations such as:
- UML2Java
- BPMN2PetriNet
- Families2Persons
- Class2Relational
- BibTeX2DocBook
- PetriNet2PathExp

## Screenshots

### Browser studio

![DSLTrans browser studio](./screenshots/uml_java_transformation.png)

### Model loading and execution

![UML to Java example model panel](./screenshots/uml_java_model_panel.png)

### Verification output

![UML to Java proof result](./screenshots/uml_java_proof_result.png)

## Project story

Model transformations are often tested locally but not verified systematically. This project aims to narrow that gap by combining:
- a visual transformation language
- concrete execution for fast feedback
- property-based symbolic verification for stronger assurance

The result is a workflow where engineers can author, run, inspect, and formally analyze transformations in one place.

## Deployment

The live application is intended to run as a single Render web service that serves:
- the browser frontend
- the Node/Express bridge
- the Python prover backend invoked by the bridge

Deployment configuration is included in this repository.

## License

MIT

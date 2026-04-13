# Concrete-to-Proof Abstraction Report

- Concrete spec: `C:\Users\Levi\CascadeProjects\symbolic-execution\dsltrans-prover\examples\oclcompiler_concrete.dslt`
- Generated proof spec: `C:\Users\Levi\CascadeProjects\symbolic-execution\dsltrans-prover\examples\generated\oclcompiler_proof_generated.dslt`

## Mappings

| Concrete | Proof |
|---|---|
| metamodel `OCLASTConcrete` | `OCLASTProof` |
| metamodel `EMFTVMASTConcrete` | `EMFTVMASTProof` |
| transformation `OCLCompiler_concrete` | `OCLCompiler_proof` |

## Attribute Decisions

| Metamodel | Class | Attribute | Concrete Type | Abstract Type | Decision | Reason |
|---|---|---|---|---|---|---|
| `OCLASTProof` | `Module` | `name` | `String` | `String{MainModule, HelpersModule, OTHER}` | `override` | Preserve proof-relevant module naming distinctions |
| `OCLASTProof` | `Field` | `name` | `String` | `String{name, age, status, children, value, OTHER}` | `override` | Canonical finite field/property vocabulary |
| `OCLASTProof` | `Field` | `isStatic` | `Bool` | `Bool` | `unchanged` | non-attribute or already finite |
| `OCLASTProof` | `Operation` | `name` | `String` | `String{isAdult, resolveStatus, helper, compute, OTHER}` | `override` | Canonical finite operation-name vocabulary |
| `OCLASTProof` | `Operation` | `isStatic` | `Bool` | `Bool` | `unchanged` | non-attribute or already finite |
| `OCLASTProof` | `Parameter` | `varName` | `String` | `String{self, thisModule, arg, tmp, item, acc, OTHER}` | `override` | Canonical finite source parameter vocabulary |
| `OCLASTProof` | `LetVariable` | `varName` | `String` | `String{self, thisModule, arg, tmp, item, acc, OTHER}` | `override` | Canonical finite let-variable vocabulary |
| `OCLASTProof` | `Iterator` | `varName` | `String` | `String{self, thisModule, arg, tmp, item, acc, OTHER}` | `override` | Canonical finite iterator-variable vocabulary |
| `OCLASTProof` | `NavigationCall` | `propName` | `String` | `String{name, age, status, children, value, OTHER}` | `override` | Preserve navigation-property distinctions used in compilation |
| `OCLASTProof` | `NavigationCall` | `isStatic` | `Bool` | `Bool` | `unchanged` | non-attribute or already finite |
| `OCLASTProof` | `NavigationCall` | `isSuper` | `Bool` | `Bool` | `unchanged` | non-attribute or already finite |
| `OCLASTProof` | `OperationCall` | `opName` | `String` | `String{isAdult, resolveStatus, helper, not, and, or, =, <, >, oclIsUndefined, OTHER}` | `override` | Preserve operation-call distinctions used in compilation |
| `OCLASTProof` | `OperationCall` | `isStatic` | `Bool` | `Bool` | `unchanged` | non-attribute or already finite |
| `OCLASTProof` | `OperationCall` | `isSuper` | `Bool` | `Bool` | `unchanged` | non-attribute or already finite |
| `OCLASTProof` | `BuiltInCall` | `opName` | `String` | `String{not, and, or, =, <, >, oclIsUndefined, OTHER}` | `override` | Finite built-in operator vocabulary |
| `OCLASTProof` | `VariableExp` | `varName` | `String` | `String{self, thisModule, arg, tmp, item, acc, OTHER}` | `override` | Canonical finite variable-expression vocabulary |
| `OCLASTProof` | `IteratorExp` | `iterName` | `String` | `String{self, thisModule, arg, tmp, item, acc, OTHER}` | `override` | Canonical finite iterator-expression vocabulary |
| `OCLASTProof` | `StringExp` | `val` | `String` | `String{adult, minor, active, guest, OTHER}` | `override` | Finite representative string literal vocabulary |
| `OCLASTProof` | `IntegerExp` | `valInt` | `Int` | `Int[0..120]` | `override` | Finite integer range covering typical example predicates |
| `OCLASTProof` | `BooleanExp` | `valBool` | `Bool` | `Bool` | `unchanged` | non-attribute or already finite |
| `EMFTVMASTProof` | `ExecEnv` | `name` | `String` | `String{MainModule, HelpersModule, OTHER}` | `override` | Keep target exec env names aligned with source modules |
| `EMFTVMASTProof` | `Field` | `name` | `String` | `String{name, age, status, children, value, OTHER}` | `override` | Canonical finite field/property vocabulary |
| `EMFTVMASTProof` | `Field` | `isStatic` | `Bool` | `Bool` | `unchanged` | non-attribute or already finite |
| `EMFTVMASTProof` | `Operation` | `name` | `String` | `String{isAdult, resolveStatus, helper, compute, OTHER}` | `override` | Canonical finite operation-name vocabulary |
| `EMFTVMASTProof` | `Operation` | `isStatic` | `Bool` | `Bool` | `unchanged` | non-attribute or already finite |
| `EMFTVMASTProof` | `Parameter` | `name` | `String` | `String{self, thisModule, arg, tmp, item, acc, OTHER}` | `override` | Canonical finite target parameter vocabulary |
| `EMFTVMASTProof` | `LocalVariable` | `name` | `String` | `String{V1, V2, OTHER}` | `canonical_vocab` | attribute is touched by rules/properties; keep alias-supporting finite domain |
| `EMFTVMASTProof` | `Get` | `propName` | `String` | `String{name, age, status, children, value, OTHER}` | `override` | Align target Get instruction property names with source navigations |
| `EMFTVMASTProof` | `GetStatic` | `propName` | `String` | `String{name, age, status, children, value, OTHER}` | `override` | Align target GetStatic property names with source navigations |
| `EMFTVMASTProof` | `Invoke` | `opName` | `String` | `String{isAdult, resolveStatus, helper, not, and, or, =, <, >, oclIsUndefined, OTHER}` | `override` | Align target Invoke op names with source calls and built-ins |
| `EMFTVMASTProof` | `InvokeStatic` | `opName` | `String` | `String{isAdult, resolveStatus, helper, not, and, or, =, <, >, oclIsUndefined, OTHER}` | `override` | Align target InvokeStatic op names with source calls |
| `EMFTVMASTProof` | `InvokeSuper` | `opName` | `String` | `String{isAdult, resolveStatus, helper, not, and, or, =, <, >, oclIsUndefined, OTHER, name, age, status, children, value, OTHER}` | `override` | Align target InvokeSuper op names with source super calls and super navigations |
| `EMFTVMASTProof` | `Store` | `varName` | `String` | `String{self, thisModule, arg, tmp, item, acc, OTHER}` | `override` | Canonical finite store-variable vocabulary |
| `EMFTVMASTProof` | `Load` | `varName` | `String` | `String{self, thisModule, arg, tmp, item, acc, OTHER}` | `override` | Canonical finite load-variable vocabulary |
| `EMFTVMASTProof` | `Iterate` | `iterName` | `String` | `String{self, thisModule, arg, tmp, item, acc, OTHER}` | `override` | Canonical finite iterate-variable vocabulary |
| `EMFTVMASTProof` | `Push` | `val` | `String` | `String{adult, minor, active, guest, OTHER}` | `override` | Finite representative pushed string literal vocabulary |
| `EMFTVMASTProof` | `PushInt` | `valInt` | `Int` | `Int[0..120]` | `override` | Finite pushed integer range aligned with source integer literals |

## Property Projection

| Property | Status | Reason |
|---|---|---|
| `ModelHasModel` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `ModuleHasExecEnv` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `FieldHasField` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `OperationHasOperation` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `ParameterHasParameter` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `LetVariableHasLocalVariable` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `IteratorHasLocalVariable` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `FieldOwnedByTracedExecEnv` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `OperationOwnedByTracedExecEnv` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `ParameterOwnedByTracedOperation` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `LetVariableOwnedByTracedOperation` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `IteratorOwnedByTracedOperation` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `NavigationCallHasGet` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `StaticNavigationCallHasGetStatic` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `SuperNavigationCallHasInvokeSuper` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `OperationCallHasInvoke` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `StaticOperationCallHasInvokeStatic` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `SuperOperationCallHasInvokeSuper` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `BuiltInNotHasInvoke` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `BuiltInBinaryHasInvoke` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `BuiltInUndefinedHasIsnull` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `LetExpHasStore` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `VariableExpHasLoad` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `SelfExpHasLoad` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `ThisModuleExpHasLoad` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `IteratorExpHasIterate` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `StringExpHasPush` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `IntegerExpHasPushInt` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `BooleanTrueHasPushT` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `BooleanFalseHasPushF` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `SequenceExpHasPushSeq` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `SetExpHasPushSet` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `UndefinedExpHasPushUndef` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `IfExpHasIfInstr` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `OperationWithBodyHasTracedTargetOperation` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `ParameterTracedToLocalVariable_ShouldFail` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `FieldTracedToOperation_ShouldFail` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `VariableExpHasPushInt_ShouldFail` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `BuiltInNotHasGet_ShouldFail` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `IfExpHasPushSeq_ShouldFail` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |

## Notes

- The concrete spec remains the source of truth.
- The generated proof spec preserves the same structure and attribute surface.
- Infinite domains are replaced by finite proof domains; unused finite string domains may be reduced further during SMT encoding.

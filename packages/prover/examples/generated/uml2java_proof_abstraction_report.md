# Concrete-to-Proof Abstraction Report

- Concrete spec: `C:\Users\Levi\CascadeProjects\symbolic-execution\dsltrans-prover\examples\uml2java_concrete.dslt`
- Generated proof spec: `C:\Users\Levi\CascadeProjects\symbolic-execution\dsltrans-prover\examples\generated\uml2java_proof_generated.dslt`

## Mappings

| Concrete | Proof |
|---|---|
| metamodel `UMLConcrete` | `UMLProof` |
| metamodel `JavaASTConcrete` | `JavaASTProof` |
| transformation `UML2Java_concrete` | `UML2Java_proof` |

## Attribute Decisions

| Metamodel | Class | Attribute | Concrete Type | Abstract Type | Decision | Reason |
|---|---|---|---|---|---|---|
| `UMLProof` | `Model` | `name` | `String` | `String{RetailModel, OTHER}` | `override` | Preserve representative model names used by the UML case study |
| `UMLProof` | `Package` | `name` | `String` | `String{root, domain, service, OTHER}` | `override` | Preserve representative package namespaces |
| `UMLProof` | `Classifier` | `name` | `String` | `String{Customer, Order, CustomerService, String, Integer, OTHER}` | `override` | Keep core classifier/type names aligned across source and target |
| `UMLProof` | `Class` | `isAbstract` | `Bool` | `Bool` | `unchanged` | non-attribute or already finite |
| `UMLProof` | `Class` | `isFinal` | `Bool` | `Bool` | `unchanged` | non-attribute or already finite |
| `UMLProof` | `Class` | `priority` | `Int` | `Int[0..5]` | `override` | Finite class-priority range aligned with the proof fragment |
| `UMLProof` | `Class` | `layerTag` | `String` | `String{Core, Domain, Infra, OTHER}` | `override` | Preserve representative architectural layer tags |
| `UMLProof` | `Class` | `kind` | `ClassKind` | `ClassKind` | `unchanged` | non-attribute or already finite |
| `UMLProof` | `Feature` | `name` | `String` | `String{id, name, items, findById, OTHER}` | `override` | Canonical finite feature-name vocabulary |
| `UMLProof` | `Feature` | `visibility` | `String` | `String{public, private, protected, package}` | `override` | Finite representative visibility vocabulary |
| `UMLProof` | `Feature` | `isStatic` | `Bool` | `Bool` | `unchanged` | non-attribute or already finite |
| `UMLProof` | `Property` | `isDerived` | `Bool` | `Bool` | `unchanged` | non-attribute or already finite |
| `UMLProof` | `Property` | `isReadOnly` | `Bool` | `Bool` | `unchanged` | non-attribute or already finite |
| `UMLProof` | `Property` | `isOrdered` | `Bool` | `Bool` | `unchanged` | non-attribute or already finite |
| `UMLProof` | `Property` | `isUnique` | `Bool` | `Bool` | `unchanged` | non-attribute or already finite |
| `UMLProof` | `Property` | `lower` | `Int` | `Int[0..4]` | `override` | Finite multiplicity lower-bound range |
| `UMLProof` | `Property` | `upper` | `Int` | `Int[0..8]` | `override` | Finite multiplicity upper-bound range covering singular and collection cases |
| `UMLProof` | `Property` | `defaultValue` | `String` | `String{, OTHER}` | `override` | Finite representative default-value vocabulary |
| `UMLProof` | `Operation` | `isAbstract` | `Bool` | `Bool` | `unchanged` | non-attribute or already finite |
| `UMLProof` | `Operation` | `isQuery` | `Bool` | `Bool` | `unchanged` | non-attribute or already finite |
| `UMLProof` | `Parameter` | `name` | `String` | `String{id, item, obj, status, OTHER}` | `override` | Canonical finite parameter-name vocabulary |
| `UMLProof` | `Parameter` | `direction` | `String` | `String{in, out, inout}` | `override` | Finite representative parameter-direction vocabulary |
| `UMLProof` | `EnumerationLiteral` | `name` | `String` | `String{NEW, COMPLETE, OTHER}` | `override` | Finite representative enum-literal vocabulary |
| `UMLProof` | `Association` | `name` | `String` | `String{OTHER}` | `singleton_vocab` | attribute unused by rules/properties; keep explicit but collapsed domain |
| `UMLProof` | `Association` | `isDerived` | `Bool` | `Bool` | `unchanged` | non-attribute or already finite |
| `UMLProof` | `Dependency` | `name` | `String` | `String{uses, OTHER}` | `override` | Representative dependency labels for proof |
| `UMLProof` | `Generalization` | `isSubstitutable` | `Bool` | `Bool` | `unchanged` | non-attribute or already finite |
| `UMLProof` | `Comment` | `body` | `String` | `String{, Aggregate root for customer data., Repository contract., Service entry point., OTHER}` | `override` | Finite representative comment vocabulary |
| `JavaASTProof` | `CompilationUnit` | `fileName` | `String` | `String{Customer, Order, CustomerService, String, Integer, OTHER}` | `propagated_copy_domain` | propagated through attribute copy dependency graph |
| `JavaASTProof` | `PackageDeclaration` | `name` | `String` | `String{root, domain, service, OTHER}` | `propagated_copy_domain` | propagated through attribute copy dependency graph |
| `JavaASTProof` | `ImportDeclaration` | `name` | `String` | `String{Customer, Order, CustomerService, String, Integer, OTHER}` | `propagated_copy_domain` | propagated through attribute copy dependency graph |
| `JavaASTProof` | `ImportDeclaration` | `isStatic` | `Bool` | `Bool` | `unchanged` | non-attribute or already finite |
| `JavaASTProof` | `ImportDeclaration` | `isOnDemand` | `Bool` | `Bool` | `unchanged` | non-attribute or already finite |
| `JavaASTProof` | `TypeDeclaration` | `name` | `String` | `String{Customer, Order, CustomerService, String, Integer, OTHER}` | `propagated_copy_domain` | propagated through attribute copy dependency graph |
| `JavaASTProof` | `TypeDeclaration` | `visibility` | `String` | `String{public, OTHER}` | `finite_vocab` | derived from observed string literals plus OTHER |
| `JavaASTProof` | `ClassDeclaration` | `isAbstract` | `Bool` | `Bool` | `unchanged` | non-attribute or already finite |
| `JavaASTProof` | `ClassDeclaration` | `isFinal` | `Bool` | `Bool` | `unchanged` | non-attribute or already finite |
| `JavaASTProof` | `ClassDeclaration` | `priority` | `Int` | `Int[0..5]` | `propagated_copy_domain` | propagated through attribute copy dependency graph |
| `JavaASTProof` | `ClassDeclaration` | `layerTag` | `String` | `String{Core, Domain, Infra, OTHER}` | `propagated_copy_domain` | propagated through attribute copy dependency graph |
| `JavaASTProof` | `ClassDeclaration` | `kind` | `ClassKind` | `ClassKind` | `unchanged` | non-attribute or already finite |
| `JavaASTProof` | `FieldDeclaration` | `name` | `String` | `String{id, name, items, findById, OTHER}` | `propagated_copy_domain` | propagated through attribute copy dependency graph |
| `JavaASTProof` | `FieldDeclaration` | `visibility` | `String` | `String{public, private, protected, package}` | `propagated_copy_domain` | propagated through attribute copy dependency graph |
| `JavaASTProof` | `FieldDeclaration` | `isStatic` | `Bool` | `Bool` | `unchanged` | non-attribute or already finite |
| `JavaASTProof` | `FieldDeclaration` | `isFinal` | `Bool` | `Bool` | `unchanged` | non-attribute or already finite |
| `JavaASTProof` | `FieldDeclaration` | `isVolatile` | `Bool` | `Bool` | `unchanged` | non-attribute or already finite |
| `JavaASTProof` | `FieldDeclaration` | `isTransient` | `Bool` | `Bool` | `unchanged` | non-attribute or already finite |
| `JavaASTProof` | `MethodDeclaration` | `name` | `String` | `String{add, equals, hashCode, remove, toString, OTHER, id, name, items, findById}` | `propagated_copy_domain` | propagated through attribute copy dependency graph |
| `JavaASTProof` | `MethodDeclaration` | `visibility` | `String` | `String{public, OTHER, private, protected, package}` | `propagated_copy_domain` | propagated through attribute copy dependency graph |
| `JavaASTProof` | `MethodDeclaration` | `isStatic` | `Bool` | `Bool` | `unchanged` | non-attribute or already finite |
| `JavaASTProof` | `MethodDeclaration` | `isFinal` | `Bool` | `Bool` | `unchanged` | non-attribute or already finite |
| `JavaASTProof` | `MethodDeclaration` | `isAbstract` | `Bool` | `Bool` | `unchanged` | non-attribute or already finite |
| `JavaASTProof` | `MethodDeclaration` | `isSynchronized` | `Bool` | `Bool` | `unchanged` | non-attribute or already finite |
| `JavaASTProof` | `ConstructorDeclaration` | `visibility` | `String` | `String{public, OTHER}` | `finite_vocab` | derived from observed string literals plus OTHER |
| `JavaASTProof` | `EnumConstant` | `name` | `String` | `String{NEW, COMPLETE, OTHER}` | `propagated_copy_domain` | propagated through attribute copy dependency graph |
| `JavaASTProof` | `SingleVariableDeclaration` | `name` | `String` | `String{obj, OTHER, id, item, status, name, items, findById}` | `propagated_copy_domain` | propagated through attribute copy dependency graph |
| `JavaASTProof` | `SingleVariableDeclaration` | `isFinal` | `Bool` | `Bool` | `unchanged` | non-attribute or already finite |
| `JavaASTProof` | `SingleVariableDeclaration` | `isVarargs` | `Bool` | `Bool` | `unchanged` | non-attribute or already finite |
| `JavaASTProof` | `TypeReference` | `name` | `String` | `String{Customer, Order, CustomerService, String, Integer, OTHER}` | `propagated_copy_domain` | propagated through attribute copy dependency graph |
| `JavaASTProof` | `TypeReference` | `isArray` | `Bool` | `Bool` | `unchanged` | non-attribute or already finite |
| `JavaASTProof` | `TypeReference` | `arrayDimensions` | `Int` | `Int[0..2]` | `override` | Finite representative array-dimension range |
| `JavaASTProof` | `Annotation` | `name` | `String` | `String{Override, Deprecated, OTHER}` | `override` | Representative annotation vocabulary |
| `JavaASTProof` | `Javadoc` | `comment` | `String` | `String{, Aggregate root for customer data., Repository contract., Service entry point., OTHER}` | `propagated_copy_domain` | propagated through attribute copy dependency graph |
| `JavaASTProof` | `LineComment` | `text` | `String` | `String{OTHER}` | `singleton_vocab` | attribute unused by rules/properties; keep explicit but collapsed domain |
| `JavaASTProof` | `BlockComment` | `text` | `String` | `String{OTHER}` | `singleton_vocab` | attribute unused by rules/properties; keep explicit but collapsed domain |

## Property Projection

| Property | Status | Reason |
|---|---|---|
| `PackageHasPackageDeclaration` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `PackagedClassHasCompilationUnitAndDeclaration` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `PackagedInterfaceHasCompilationUnitAndDeclaration` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `PackagedEnumerationHasCompilationUnitAndDeclaration` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `OwnedPropertyHasOwnedField` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `PropertyTypeHasFieldTypeReference` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `MultiValuedPropertyHasArrayFieldType` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `StaticPropertyHasField` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `ReadOnlyPropertyHasField` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `ClassOperationHasOwnedMethod` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `InterfaceOperationHasOwnedMethod` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `OperationParameterHasOwnedParameter` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `OperationReturnTypeHasReference` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `EnumerationLiteralHasOwnedEnumConstant` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `ClassHasConstructor` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `PropertyHasConstructorParameter` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `PropertyHasGetter` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `WritablePropertyHasSetter` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `MultiValuedPropertyHasAddRemoveHelpers` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `GeneralizationHasExtendsReference` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `InterfaceRealizationHasImplementsReference` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `ClassCommentHasJavadoc` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `DependencyYieldsImport` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `PropertyTypeUsedHasImport` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `ClassHasObjectMethods` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `InterfaceMappedToClassDeclaration_ShouldFail` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `ClassMappedToInterfaceDeclaration_ShouldFail` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `PropertyMappedToJavadoc_ShouldFail` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |

## Notes

- The concrete spec remains the source of truth.
- The generated proof spec preserves the same structure and attribute surface.
- Infinite domains are replaced by finite proof domains; unused finite string domains may be reduced further during SMT encoding.

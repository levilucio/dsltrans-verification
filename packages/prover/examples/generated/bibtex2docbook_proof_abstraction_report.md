# Concrete-to-Proof Abstraction Report

- Concrete spec: `C:\Users\Levi\CascadeProjects\symbolic-execution\dsltrans-prover\examples\bibtex2docbook_concrete.dslt`
- Generated proof spec: `C:\Users\Levi\CascadeProjects\symbolic-execution\dsltrans-prover\examples\generated\bibtex2docbook_proof_generated.dslt`

## Mappings

| Concrete | Proof |
|---|---|
| metamodel `BibTeXConcrete` | `BibTeXProof` |
| metamodel `DocBookConcrete` | `DocBookProof` |
| transformation `BibTeX2DocBook_concrete` | `BibTeX2DocBook_proof` |

## Attribute Decisions

| Metamodel | Class | Attribute | Concrete Type | Abstract Type | Decision | Reason |
|---|---|---|---|---|---|---|
| `BibTeXProof` | `Entry` | `key` | `String` | `String{k1, k2, k3, OTHER}` | `override` | Preserve proof-relevant BibTeX key distinctions |
| `BibTeXProof` | `Entry` | `title` | `String` | `String{V1, V2, OTHER}` | `canonical_vocab` | attribute is touched by rules/properties; keep alias-supporting finite domain |
| `BibTeXProof` | `Article` | `year` | `Int` | `Int[1990..2025]` | `override` | Preserve year thresholds used by current property suite |
| `BibTeXProof` | `Article` | `journal` | `String` | `String{V1, V2, OTHER}` | `canonical_vocab` | attribute is touched by rules/properties; keep alias-supporting finite domain |
| `BibTeXProof` | `Book` | `year` | `Int` | `Int[1990..2025]` | `override` | Preserve year thresholds used by current property suite |
| `BibTeXProof` | `Book` | `publisher` | `String` | `String{V1, V2, OTHER}` | `canonical_vocab` | attribute is touched by rules/properties; keep alias-supporting finite domain |
| `BibTeXProof` | `InProceedings` | `year` | `Int` | `Int[1990..2025]` | `override` | Preserve year thresholds used by current property suite |
| `BibTeXProof` | `InProceedings` | `booktitle` | `String` | `String{V1, V2, OTHER}` | `canonical_vocab` | attribute is touched by rules/properties; keep alias-supporting finite domain |
| `BibTeXProof` | `Author` | `name` | `String` | `String{a1, a2, a3, OTHER}` | `override` | Canonical finite author-name abstraction |
| `BibTeXProof` | `Keyword` | `text` | `String` | `String{kw1, kw2, OTHER}` | `override` | Canonical finite keyword abstraction |
| `DocBookProof` | `DBEntry` | `key` | `String` | `String{k1, k2, k3, OTHER}` | `override` | Preserve proof-relevant DocBook key distinctions |
| `DocBookProof` | `DBEntry` | `title` | `String` | `String{V1, V2, OTHER}` | `canonical_vocab` | attribute is touched by rules/properties; keep alias-supporting finite domain |
| `DocBookProof` | `DBArticle` | `year` | `Int` | `Int[1990..2025]` | `override` | Preserve target year range corresponding to source article years |
| `DocBookProof` | `DBArticle` | `journal` | `String` | `String{V1, V2, OTHER}` | `canonical_vocab` | attribute is touched by rules/properties; keep alias-supporting finite domain |
| `DocBookProof` | `DBBook` | `year` | `Int` | `Int[1990..2025]` | `override` | Preserve target year range corresponding to source book years |
| `DocBookProof` | `DBBook` | `publisher` | `String` | `String{V1, V2, OTHER}` | `canonical_vocab` | attribute is touched by rules/properties; keep alias-supporting finite domain |
| `DocBookProof` | `DBInProceedings` | `year` | `Int` | `Int[1990..2025]` | `override` | Preserve target year range corresponding to source inproc years |
| `DocBookProof` | `DBInProceedings` | `booktitle` | `String` | `String{V1, V2, OTHER}` | `canonical_vocab` | attribute is touched by rules/properties; keep alias-supporting finite domain |
| `DocBookProof` | `PersonName` | `value` | `String` | `String{a1, a2, a3, OTHER}` | `override` | Canonical finite target author abstraction |
| `DocBookProof` | `SubjectTerm` | `value` | `String` | `String{kw1, kw2, OTHER}` | `override` | Canonical finite target keyword abstraction |
| `DocBookProof` | `DBCitation` | `citedKey` | `String` | `String{k1, k2, k3, OTHER}` | `override` | Keep cited-key abstraction aligned with source entry keys |

## Property Projection

| Property | Status | Reason |
|---|---|---|
| `ModelHasDocument` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `BibFileHasBibliography` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `ArticleBecomesDBArticle` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `BookBecomesDBBook` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `InProcBecomesDBInProc` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `AuthorBecomesPersonName` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `KeywordBecomesSubjectTerm` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `ArticleHasCitationElement` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `RecentArticleMapped` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `OldBookMapped` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `ArticleInBibFileAppearsInBibliography` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `BookInBibFileAppearsInBibliography` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `InProcInBibFileAppearsInBibliography` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `ArticleWithAuthorHasMappedEntry` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `BookWithAuthorHasMappedEntry` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `InProcWithAuthorHasMappedEntry` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `ArticleWithKeywordHasMappedEntry` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `BookWithKeywordHasMappedEntry` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `InProcWithKeywordHasMappedEntry` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `ArticleCitationKeepsArticleTrace` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `CitationAttachedToMappedArticle` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `CitationAlsoTracesToCitedEntry` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `ArticleAuthorLinkProducesAuthorRelation` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `BookAuthorLinkProducesAuthorRelation` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `InProcAuthorLinkProducesAuthorRelation` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `ArticleKeywordLinkProducesSubjectRelation` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `BookKeywordLinkProducesSubjectRelation` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `InProcKeywordLinkProducesSubjectRelation` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `ArticleBecomesDBBook_ShouldFail` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `BookBecomesDBArticle_ShouldFail` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `InProcBecomesDBBook_ShouldFail` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `ArticleAuthorBecomesSubject_ShouldFail` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |
| `ArticleKeywordBecomesAuthor_ShouldFail` | `exact` | all classes, associations, and referenced attributes are preserved; only domains are finite-ized |

## Notes

- The concrete spec remains the source of truth.
- The generated proof spec preserves the same structure and attribute surface.
- Infinite domains are replaced by finite proof domains; unused finite string domains may be reduced further during SMT encoding.

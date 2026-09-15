# Evaluation Harness

The evaluation harness checks behavior that API tests alone cannot protect. It is local-first: the default mode forces deterministic fallbacks and uses a temporary database, so it is reproducible, does not consume API credits and never changes application data.

## Suites

| Suite | Primary checks |
|---|---|
| Planning | task count, valid weeks, weekly budget, deliverables, acceptance criteria |
| Teaching | task grounding, example, exactly one check question, forbidden behavior |
| Assessment | expected decision, score consistency, criterion coverage, feedback |
| Recommendation | expected ranking, score range, explainability, score components |

Datasets are version-controlled JSONL files in `evals/datasets/`. Thresholds are explicit in `evals/baseline.json`. A case passes only when every deterministic check passes. The command exits non-zero when the overall or per-suite threshold regresses, which makes it a CI quality gate.

## Commands

```bash
make eval
python -m evals.run --suite teaching
python -m evals.run --suite assessment
```

Reports are written to `evals/reports/latest.json` and `evals/reports/latest.md` and intentionally ignored by Git.

To evaluate the configured model instead of the fallback:

```bash
python -m evals.run --suite teaching --live --no-gate
```

Live evaluation requires `OPENAI_API_KEY`. Start with `--no-gate`: model-based outputs are nondeterministic and should be reviewed before establishing a separate live baseline. The offline baseline must not be weakened to accommodate a live model regression.

## Adding a regression case

1. Reduce the production failure to the smallest input that reproduces it.
2. Add the input and expected behavior to the matching JSONL dataset.
3. Prefer a deterministic grader. Use an LLM judge only for behavior that cannot be checked reliably in code.
4. Run the suite and fix the product behavior rather than changing the expected result.
5. Run `make check` before committing.

The next evaluation stage should add curated human labels, ranking metrics such as Precision@K/NDCG, production-trace sampling and a separate model-judge suite.

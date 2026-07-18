# KAEOS Real-Data Benchmark

_Generated 2026-07-17T04:59:36.257982+00:00 · up to 5000 records/dataset_

KAEOS deterministic classifiers (the rule-based safety net the agents fall back to when the model is weak) scored against recorded human outcomes on real Kaggle enterprise datasets. No LLM in the loop - fully reproducible. Raw data gitignored; see kaggle_ref.

| Domain | Dataset | Metric | Score | N |
|--------|---------|--------|-------|---|
| hr | `ibm-hr-analytics-attrition-dataset` | acc / baseline / bal-acc / F1 | 81.2% / 83.9% [below] / 72.1% / 0.501 | 1470 |
| support | `customer-support-ticket-dataset` | exact / ±1 | 25.0% / 74.3% | 5000 |
| engineering | ServiceNow log | priority exact | 100.0% | 5000 |
| engineering | ServiceNow log | priority ±1 level | 100.0% | 5000 |
| engineering | ServiceNow log | SLA-breach F1 | 0.363 | 5000 |
| sales | `leadforge-lead-scoring-intro-v1` | acc / baseline / bal-acc / F1 | 50.4% / 57.8% [below] / 55.2% / 0.595 | 5000 |
| operations | `procurement-kpi-analysis-dataset` | acc / baseline / bal-acc / F1 | 70.0% / 82.4% [below] / 50.0% / 0.816 | 777 |
| finance | `finance-factoring-ibm-late-payment-histories` | acc / baseline / bal-acc / F1 | 81.1% / 64.4% [beats] / 76.5% / 0.696 | 2466 |
| legal | `atticus-open-contract-dataset-aok-beta` | exact / ±1 | 39.1% / 39.1% | 5000 |

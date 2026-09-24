# Research

This directory contains orchestration code for complete research workflows:

1. feature engineering
2. regime detection
3. multi-strategy alpha generation
4. adaptive allocation
5. risk controls
6. portfolio backtesting
7. performance reporting

Use `research.pipeline.ResearchPipeline` for end-to-end experiments.

The local dashboard now runs that pipeline through `research.workspace` and
`apps.research_api`, with persistent experiments, validation and risk views.
See [PM workflow and requirements](PM_WORKFLOW.md) for the institutional research
basis, daily workflow, module mapping, gate policy and outstanding production
requirements. The workspace exposes only strategies whose inputs and causal
contracts are supported; no synthetic fallback is used for market-data failures.


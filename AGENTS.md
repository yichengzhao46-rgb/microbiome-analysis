# Project AGENTS

Use `global_skill_router` as the default first-layer coordinator for work in this repository.

## Preferred Skill Flow

1. Route the task with `global_skill_router`.
2. Use `env-microbiology-phd-workflow` for microbiome and environmental microbiology tasks.
3. Use the most specialized skill for the active sub-task:
   - `spreadsheet` for `.xlsx`, `.csv`, and `.tsv`
   - `jupyter-notebook` for `.ipynb`
   - `python-expert` for scripts and refactors
   - `data-analyst` for pandas and statistical analysis
   - `visualization-expert` for chart planning
   - `research-paper-writing` and `editor` for manuscript-facing text
4. Chain multiple skills when the task spans data, code, figures, and writing.
5. End with a short skill-usage report.

## Repository Rules

- Treat `data/raw/` as immutable source data.
- Write cleaned outputs to `data/processed/`.
- Keep exploratory work in `notebooks/` and reusable logic in `scripts/`.
- Save final figures under `results/figures/` and final tables under `results/tables/`.
- Keep manuscript-facing notes in `docs/manuscript/`.
- Prefer reproducible scripts over manual spreadsheet-only steps.

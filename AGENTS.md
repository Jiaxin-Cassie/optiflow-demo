# AGENTS.md

## Project Rules

- This repository implements OptiFlow, a local business optimization decision workspace.
- All new code must be runnable through run_experiment.py.
- Do not hardcode the API key outside src/config.py.
- Do not print the full API key in logs, traces, README, or errors.
- All LLM calls must go through src/llm_client.py.
- All prompt templates must be stored in src/prompts.py.
- Do not scatter prompt strings across agent files.
- All task modes use shared modeling, code review and evaluation interfaces.
- Five-Element Formulation is adopted as a standardized intermediate representation and must not be described as the project innovation.
- Do not restore obsolete research baselines, datasets, literature, benchmark results or model caches.
- Task progress, model confirmation, solution validation and failure records must remain real and auditable.
- Keep run_experiment.py --method all --dry_run as an alias for the local business-template smoke check.
- Python code should be modular, readable, and debuggable.
- Before considering the task complete, run:
  python run_experiment.py --method all --dry_run

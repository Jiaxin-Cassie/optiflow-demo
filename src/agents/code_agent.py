from pathlib import Path
from src.solver_runtime import solver_environment
from src.errors import GenerationFailure
import re
from src.prompts import CODE_GENERATION_SYSTEM_PROMPT, CODE_GENERATION_USER_PROMPT, AUTONOMOUS_SOLVER_PROMPT
from src.utils import compact_text, ensure_dir, extract_python_code, safe_json_dumps
from src.knowledge_delivery import reference_payload, stage_references

class CodeAgent:

    def __init__(self, output_dir: str | Path, llm_client=None):
        self.output_dir = Path(output_dir)
        self.llm_client = llm_client

    def run(self, problem_id: str, method: str, problem_text: str, fef_text: str, activated_skills: list | None=None, selected_references: list | None=None, recommended_solver: str | None=None) -> tuple[str, str, str]:
        solver_instruction = self._choose_solver_instruction(problem_text, fef_text, activated_skills, selected_references, recommended_solver=recommended_solver)
        if self.llm_client is None:
            raise GenerationFailure('CodeAgent', 'missing_client')
        messages = [{'role': 'system', 'content': CODE_GENERATION_SYSTEM_PROMPT}, {'role': 'user', 'content': CODE_GENERATION_USER_PROMPT.format(problem_text=compact_text(problem_text, int(getattr(self.llm_client.config, 'max_downstream_problem_chars', 1800))) if getattr(self.llm_client.config, 'compact_prompts', False) else problem_text, fef_text=fef_text, solver_instruction=solver_instruction, programming_knowledge=safe_json_dumps(reference_payload(stage_references(selected_references, 'code'), self.llm_client.config)))}]
        code = extract_python_code(self.llm_client.chat(messages, agent_name='CodeAgent'))
        if not code.strip():
            raise GenerationFailure('CodeAgent', 'empty_code')
        path = self.output_dir / 'generated_code' / method / f'{problem_id}.py'
        ensure_dir(path.parent)
        path.write_text(code, encoding='utf-8')
        return (code, str(path), solver_instruction)

    def _choose_solver_instruction(self, problem_text, fef_text, activated_skills=None, selected_references=None, recommended_solver=None):
        config = getattr(self.llm_client, 'config', None)
        return AUTONOMOUS_SOLVER_PROMPT.format(environment=safe_json_dumps(solver_environment()), recommendation=recommended_solver or 'none', time_limit=getattr(config, 'solver_time_limit', 25))

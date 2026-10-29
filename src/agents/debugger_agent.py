from src.errors import GenerationFailure
from src.prompts import DEBUGGER_SYSTEM_PROMPT, DEBUGGER_USER_PROMPT
from src.utils import compact_text, extract_python_code, safe_json_dumps
from src.knowledge_delivery import reference_payload, stage_references

class DebuggerAgent:

    def __init__(self, llm_client=None):
        self.llm_client = llm_client

    def fix(self, problem_text: str, fef_text: str, current_code: str, error_message: str, solver_instruction: str='', selected_references=None) -> str:
        if self.llm_client is None:
            raise GenerationFailure('DebuggerAgent', 'missing_client')
        messages = [{'role': 'system', 'content': DEBUGGER_SYSTEM_PROMPT}, {'role': 'user', 'content': DEBUGGER_USER_PROMPT.format(problem_text=compact_text(problem_text, int(getattr(self.llm_client.config, 'max_downstream_problem_chars', 1800))) if getattr(self.llm_client.config, 'compact_prompts', False) else problem_text, fef_text=fef_text, solver_instruction=solver_instruction, programming_knowledge=safe_json_dumps(reference_payload(stage_references(selected_references, 'debugger'), self.llm_client.config)), current_code=current_code, error_message=error_message[-4000:])}]
        return extract_python_code(self.llm_client.chat(messages, agent_name='DebuggerAgent'))

"""Extract factual business requirements before modeling."""
from src.prompts import PROBLEM_PROFILER_SYSTEM_PROMPT, PROBLEM_PROFILER_USER_PROMPT
from src.schemas import ProblemProfile
from src.utils import extract_json_object


class ProblemProfilerAgent:

    def __init__(self, llm_client=None):
        self.llm_client = llm_client

    def run(self, problem_text: str) -> ProblemProfile:
        if self.llm_client is None:
            from src.errors import GenerationFailure
            raise GenerationFailure('ProblemProfilerAgent', 'missing_client')
        messages = [{'role': 'system', 'content': PROBLEM_PROFILER_SYSTEM_PROMPT}, {'role': 'user', 'content': PROBLEM_PROFILER_USER_PROMPT.format(problem_text=problem_text)}]
        try:
            data = extract_json_object(self.llm_client.chat(messages, agent_name='ProblemProfilerAgent'))
            return self.validate_facts(data)
        except (ValueError, TypeError) as exc:
            from src.errors import GenerationFailure
            raise GenerationFailure('ProblemProfilerAgent', 'invalid_factual_profile') from exc

    @staticmethod
    def validate_facts(answer):
        strings = {'problem_domain', 'objective_type', 'explicit_objective'}
        lists = {'entities', 'parameters', 'decision_targets', 'resource_relations', 'demand_relations', 'time_relations', 'conditional_relations', 'explicit_restrictions', 'ambiguities'}
        if not isinstance(answer, dict) or set(answer) - strings - lists:
            raise ValueError('Profile must contain factual fields only; no model-family or solver decisions')
        if any((not isinstance(value, str) for (key, value) in answer.items() if key in strings)):
            raise ValueError('Profile text fields must be strings')
        if any((not isinstance(value, list) or any((not isinstance(item, str) for item in value)) for (key, value) in answer.items() if key in lists)):
            raise ValueError('Profile relationship fields must be lists of strings')
        return ProblemProfile(**answer)

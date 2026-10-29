from src.modeling_records import extract_sections, extract_modeling_records
from src.errors import GenerationFailure
from src.knowledge_delivery import norm_category, reference_payload, stage_references
from src.prompts import FORMULATION_SYSTEM_PROMPT, FORMULATION_USER_PROMPT
from src.schemas import ActivatedSkill, FiveElementFormulation, ProblemProfile, SelectedReference
from src.utils import safe_json_dumps

def parse_fef(text: str) -> FiveElementFormulation:
    sections = extract_sections(text)
    return FiveElementFormulation(**sections, fef_text=text, modeling_records=extract_modeling_records(sections))

class FormulationAgent:

    def __init__(self, llm_client=None):
        self.llm_client = llm_client
        self.config = getattr(llm_client, 'config', None)

    def run(self, problem_text: str, profile: ProblemProfile, activated_skills: list[ActivatedSkill], selected_references: list[SelectedReference]) -> FiveElementFormulation:
        skill_payload = [{'name': skill.name, 'category': skill.category, 'description': skill.description, 'reason': skill.reason} for skill in activated_skills if norm_category(skill.category) in {'K1', 'K2'} and (not any((r.artifact_type == 'knowledge_unit' for r in skill.references)))]
        references_payload = reference_payload(stage_references(selected_references, 'formulation'), self.config)
        messages = [{'role': 'system', 'content': FORMULATION_SYSTEM_PROMPT}, {'role': 'user', 'content': FORMULATION_USER_PROMPT.format(problem_text=problem_text, problem_profile=safe_json_dumps(profile.model_dump()), activated_skills=safe_json_dumps(skill_payload), selected_references=safe_json_dumps(references_payload))}]
        if self.llm_client is None:
            raise GenerationFailure('FormulationAgent', 'missing_client')
        result = parse_fef(self.llm_client.chat(messages, agent_name='FormulationAgent'))
        if not all([result.sets, result.parameters, result.decision_variables, result.objective_function, result.constraints]):
            raise GenerationFailure('FormulationAgent', 'invalid_fef_structure')
        return result

from dataclasses import dataclass
import os

@dataclass
class Config:
    api_key: str
    base_url: str
    model: str
    temperature: float = 0.0
    max_candidate_skills: int = 6
    max_activated_skills: int = 4
    max_references: int = 10
    debug_rounds: int = 1
    code_timeout: int = 30
    min_reference_score: float = 0.03
    compact_prompts: bool = True
    max_reference_chars: int = 1800
    max_downstream_problem_chars: int = 1800
    reasoning_agents: tuple[str, ...] = ('FormulationAgent', 'CodeAgent', 'DebuggerAgent')
    use_llm_skill_judge: bool = True
HARDCODED_API_KEY = ''
HARDCODED_BASE_URL = 'https://api.deepseek.com'
HARDCODED_MODEL = 'deepseek-flash'

def mask_key(key: str) -> str:
    if not key:
        return ''
    if len(key) <= 10:
        return '***'
    return key[:6] + '...' + key[-4:]

def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {'0', 'false', 'no', 'off'}

def get_config() -> Config:
    api_key = os.getenv('DEEPSEEK_API_KEY') or os.getenv('MODELSCOPE_API_KEY') or os.getenv('SILICONFLOW_API_KEY') or HARDCODED_API_KEY
    base_url = os.getenv('DEEPSEEK_BASE_URL') or os.getenv('MODELSCOPE_BASE_URL') or os.getenv('SILICONFLOW_BASE_URL') or HARDCODED_BASE_URL
    model = os.getenv('LLM_MODEL') or HARDCODED_MODEL
    return Config(api_key=api_key, base_url=base_url, model=model, debug_rounds=int(os.getenv('DEBUG_ROUNDS', '1')), compact_prompts=_env_bool('COMPACT_PROMPTS', True), max_reference_chars=int(os.getenv('MAX_REFERENCE_CHARS', '1800')), max_downstream_problem_chars=int(os.getenv('MAX_DOWNSTREAM_PROBLEM_CHARS', '1800')), use_llm_skill_judge=_env_bool('USE_LLM_SKILL_JUDGE', True))

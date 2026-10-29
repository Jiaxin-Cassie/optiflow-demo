"""Connect shared modeling agents to the product's confirmation boundary."""
import ast
from pathlib import Path

from src.agents.code_agent import CodeAgent
from src.agents.debugger_agent import DebuggerAgent
from src.agents.formulation_agent import FormulationAgent
from src.agents.problem_profiler import ProblemProfilerAgent
from src.agents.reference_selector import ReferenceSelectorAgent
from src.agents.skill_router import SkillRouterAgent
from src.config import get_config
from src.llm_client import LLMClient
from src.prompts import WORKBENCH_MODEL_SYSTEM_PROMPT, WORKBENCH_MODEL_USER_PROMPT
from src.schemas import Problem, ActivatedSkill, SelectedReference
from src.skill_loader import load_skills
from src.utils import extract_json_object
from src.workbench.model import validate_model, ModelError
from src.workbench.store import ROOT


class AgentAdapter:
    def __init__(self):
        self.config = get_config()
        # The product adapter must never silently truncate the business specification.
        self.config.compact_prompts = False
        # Keep enough room for the full model and its business provenance.
        self.config.stage_max_tokens = {"FormulationAgent": 8192, "CodeAgent": 8192,
                                        "DebuggerAgent": 4096, "ProblemProfilerAgent": 2048}
        self.config.reasoning_agents = ()
        self.client = LLMClient(self.config)

    def close(self):
        self.client.client.close()

    def usage_summary(self):
        calls = self.client.interactions
        return {"calls": self.client.llm_calls, "total_tokens": self.client.token_estimate,
                "estimated_calls": sum(bool(c.get("usage_unknown")) for c in calls),
                "api_latency_seconds": sum(c.get("latency_seconds", 0) for c in calls),
                "note": "优先使用服务返回的 token 用量；未返回时使用估算，不折算未经配置的费用。"}

    def profile(self, text):
        return ProblemProfilerAgent(self.client).run(text)

    def route(self, task, profile):
        skills = load_skills(ROOT / "skill_library")
        requested = task["selected_skills"]
        if requested is not None:
            missing = set(requested) - {s.name for s in skills}
            if missing:
                raise ModelError("指定的 Skill 不存在。")
            skills = [s for s in skills if s.name in requested]
        problem = Problem(problem_id=task["task_id"], problem_text=task["effective_text"])
        _, _, activated = SkillRouterAgent(self.config, self.client).route(problem, profile, skills)
        references = ReferenceSelectorAgent(self.config).select(problem, profile, activated)
        return activated, references

    def formulate(self, task, profile, activated, references):
        fef = FormulationAgent(self.client).run(task["effective_text"], profile, activated, references)
        task["fef_text"] = fef.fef_text
        response = self.client.chat([
            {"role": "system", "content": WORKBENCH_MODEL_SYSTEM_PROMPT},
            {"role": "user", "content": WORKBENCH_MODEL_USER_PROMPT.format(
                problem_text=task["effective_text"], fef_text=fef.fef_text)},
        ], agent_name="WorkbenchModelAdapter", max_tokens=6000)
        model = validate_model(extract_json_object(response), task["effective_text"])
        return model, fef.fef_text

    def generate_artifact(self, task, directory):
        activated = [ActivatedSkill(**item) for item in task["activated_skills"]]
        references = [SelectedReference(**item) for item in task["selected_references"]]
        # Use exactly the reviewed data contract downstream, not a possibly divergent FEF.
        import json
        reviewed = json.dumps(task["model"], ensure_ascii=False, allow_nan=False)
        code, path, instruction = CodeAgent(directory, self.client).run(
            task["task_id"], "workbench", task["effective_text"], reviewed,
            activated_skills=activated, selected_references=references)
        fixes = 0
        try:
            ast.parse(code)
        except SyntaxError:
            code = DebuggerAgent(self.client).fix(task["effective_text"], reviewed, code,
                                                "Generated Python has a syntax error.", instruction, references)
            ast.parse(code)
            Path(path).write_text(code, encoding="utf-8")
            fixes = 1
        return {"path": path, "executed": False, "debug_rounds": fixes,
                "note": "AI 生成的代码仅供审阅；实际执行的是已确认模型的受控解释器。"}


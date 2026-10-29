"""Guard the product's live routing and clean dependency boundary."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest

from src.agents.reference_selector import ReferenceSelectorAgent
from src.agents.skill_router import SkillRouterAgent
from src.schemas import Problem, ProblemProfile
from src.skill_loader import load_skills
from src.workbench.store import ROOT


class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.config = SimpleNamespace(max_candidate_skills=6, max_activated_skills=4,
                                      max_references=10, use_llm_skill_judge=False)
        self.problem = Problem(problem_id="routing_check", problem_text="工厂生产两种产品，在人工和机器工时限制下最大化利润，产量为非负整数。")
        self.profile = ProblemProfile(problem_domain="生产计划", objective_type="maximization")

    def test_catalog_routes_into_valid_provenanced_references(self):
        candidates, _, activated = SkillRouterAgent(self.config).route(
            self.problem, self.profile, load_skills(ROOT / "skill_library"))
        self.assertTrue(activated)
        self.assertLessEqual(len(candidates), 6)
        self.assertLessEqual(len(activated), 4)
        references = ReferenceSelectorAgent(self.config).select(self.problem, self.profile, activated)
        self.assertTrue(references)
        self.assertTrue(all(r.text and r.knowledge_unit.get("sources") for r in references))
        self.assertEqual(SkillRouterAgent(self.config).route(self.problem, self.profile, []), ([], [], []))

    def test_unavailable_model_selection_has_a_visible_fallback(self):
        class Unavailable:
            def chat(self, *args, **kwargs):
                raise RuntimeError("service unavailable")
        self.config.use_llm_skill_judge = True
        _, _, activated = SkillRouterAgent(self.config, Unavailable()).route(
            self.problem, self.profile, load_skills(ROOT / "skill_library"))
        self.assertTrue(activated)
        self.assertTrue(all("降级" in s.reason for s in activated))

    def test_product_imports_do_not_depend_on_retired_packages(self):
        files = [ROOT / "run_experiment.py", *[ROOT / "src" / n for n in (
            "schemas.py", "storage.py", "retrieval.py", "utils.py", "knowledge_delivery.py", "knowledge_library.py",
            "llm_client.py", "modeling_records.py", "solver_runtime.py", "skill_loader.py")],
            *(ROOT / "src/agents").glob("*.py"), *(ROOT / "src/workbench").glob("*.py")]
        for path in files:
            if path.name == "history.py":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))
            imports = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module]
            self.assertFalse(any(x.startswith(("experiments", "src.baselines", "src.experiment_records")) for x in imports), path)

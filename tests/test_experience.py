"""P0 business explanations, safe comparisons and real template acceptance."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from src.workbench.cases import CASES
from src.workbench.explanations import model_review_data, decision_summary, compare_versions
from src.workbench.service import run_optimization_task, confirm_task, revise_task, model_hash
from src.workbench.store import TaskStore


def rehash(task):
    task["model_hash"] = model_hash(task["model"])
    task["human_review"]["model_hash"] = task["model_hash"]
    return task


class ExperienceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="optiflow_p0_")
        cls.addClassCleanup(cls.temp.cleanup)
        store = TaskStore(Path(cls.temp.name) / "tests.sqlite3")
        cls.solved = {}
        for case in CASES.values():
            task = run_optimization_task(case["text"], mode="case", case_id=case["id"], store=store)
            cls.solved[case["id"]] = confirm_task(task["task_id"], expected_version=1, store=store)
        task = cls.solved["production"]
        t = revise_task(task["task_id"], "A <= 100", expected_version=1, store=store)
        cls.cap100 = confirm_task(t["task_id"], expected_version=2, store=store)
        t = revise_task(task["task_id"], "A <= 80", expected_version=2, store=store)
        cls.cap80 = confirm_task(t["task_id"], expected_version=3, store=store)

    def test_three_actual_templates_have_business_summaries(self):
        for name, objective in (("production", 10000), ("allocation", 195), ("staffing", 2900)):
            with self.subTest(case=name):
                task = self.solved[name]
                self.assertEqual(task["status"], "completed")
                self.assertEqual(task["solver"]["objective_value"], objective)
                summary = decision_summary(task)
                self.assertTrue(summary["eligible"])
                for v in task["model"]["variables"]:
                    self.assertIn(v["label"], summary["recommendation"])
                    self.assertIn(v["unit"], summary["recommendation"])
                self.assertIn("不代表", summary["limitations"])

    def test_model_view_is_faithful_and_does_not_modify_json(self):
        model = deepcopy(CASES["production"]["model"])
        encoded = json.dumps(model, sort_keys=True)
        view = model_review_data(model)
        self.assertEqual(view["variable_count"], 2)
        self.assertEqual(view["constraint_count"], 2)
        labor = next(r for r in view["rules"] if r["label"] == "人工工时")
        self.assertIn("产品 A 产量 × (2)", labor["description"])
        self.assertIn("不能超过 400", labor["description"])
        self.assertIn("A", labor["formula"])
        self.assertNotIn("400 小时", labor["description"])  # The contract has no constraint unit.
        self.assertTrue(any(r["kind"] == "bound" for r in view["rules"]))
        self.assertEqual(json.dumps(model, sort_keys=True), encoded)

    def test_negative_coefficients_directions_and_variable_units(self):
        model = deepcopy(CASES["allocation"]["model"])
        rule = model["constraints"][0]
        for relation, phrase in ((">=", "至少达到"), ("==", "必须等于"), ("<=", "不能超过")):
            rule.update(relation=relation, coefficients={"search": -3, "feed": 2})
            view = model_review_data(model)
            card = next(r for r in view["rules"] if r["kind"] == "constraint")
            self.assertIn("(-3)", card["description"])
            self.assertIn(phrase, card["description"])
        self.assertEqual(view["decisions"][0]["upper"], "30")

    def test_empty_or_malformed_models_have_safe_views(self):
        for model in (None, {}, {"variables": [], "constraints": []}, {"variables": "bad", "objective": None, "constraints": [None]},
                      {"variables": [{"name": [], "domain": "unknown"}], "constraints": [{}]}):
            with self.subTest(model=model):
                view = model_review_data(model)
                self.assertIn("goal", view)

    def test_failed_incomplete_or_unreviewed_results_never_recommend(self):
        for status in ("Infeasible", "Unbounded", "Timeout", "Unknown", "OptimalInaccurate"):
            task = deepcopy(self.solved["production"])
            task["solver"]["status"] = status
            self.assertIsNone(decision_summary(task)["recommendation"])
        for mutate in (lambda t: t["validation"].update(numerical_feasibility="failed"),
                       lambda t: t["solver"].update(solution={"A": 100}),
                       lambda t: t["human_review"].update(status="pending"),
                       lambda t: t["model"]["objective"]["coefficients"].update(A=99),
                       lambda t: t.update(status="failed")):
            task = deepcopy(self.solved["production"])
            mutate(task)
            self.assertFalse(decision_summary(task)["eligible"])

    def test_true_production_comparison_including_the_100_cap(self):
        self.assertEqual(self.cap100["solver"]["objective_value"], 10000)
        unchanged = compare_versions(self.solved["production"], self.cap100)
        self.assertTrue(unchanged["comparable"])
        self.assertEqual(unchanged["delta"], 0)
        difference = compare_versions(self.solved["production"], self.cap80)
        self.assertTrue(difference["comparable"])
        self.assertEqual(difference["delta"], -500)
        self.assertEqual(difference["relative_percent"], -5)
        self.assertEqual(difference["improvement"], "下降")
        self.assertEqual({r["variable"]: r["delta"] for r in difference["variables"]}, {"A": -20, "B": 10})

    def test_incompatible_objectives_and_semantics_are_not_compared(self):
        for key, value in (("unit", "万元"), ("sense", "min"), ("label", "收入"), ("constant", 1), ("coefficients", {"A": 40, "B": 31})):
            after = deepcopy(self.cap80)
            after["model"]["objective"][key] = value
            result = compare_versions(self.solved["production"], rehash(after))
            self.assertFalse(result["comparable"], key)
            self.assertIsNone(result["delta"])
        for field in ("label", "unit", "domain"):
            after = deepcopy(self.cap80)
            after["model"]["variables"][0][field] = "changed"
            result = compare_versions(self.solved["production"], rehash(after))
            self.assertFalse(result["comparable"])
            self.assertIsNone(next(r for r in result["variables"] if r["variable"] == "A")["delta"])

    def test_empty_added_removed_and_failed_versions_are_safe(self):
        before = self.solved["production"]
        for after in ({"model_version": 7, "model": {}, "solver": {}}, deepcopy(self.cap80)):
            after["solver"]["solution"] = {}
            self.assertFalse(compare_versions(before, after)["comparable"])
        after = deepcopy(self.cap80)
        after["model"]["variables"].append({"name": "C", "label": "其他数量", "unit": "件", "domain": "integer"})
        after["solver"]["solution"]["C"] = 1
        self.assertFalse(compare_versions(before, rehash(after))["comparable"])

    def test_zero_negative_minimization_and_float_arithmetic(self):
        # Pure arithmetic fixtures derived from actual solved snapshots; never shown as solver evidence.
        before, after = deepcopy(self.solved["production"]), deepcopy(self.cap80)
        before["solver"]["objective_value"] = 0
        after["solver"]["objective_value"] = -500
        self.assertIsNone(compare_versions(before, after)["relative_percent"])
        before["solver"]["objective_value"] = -1000
        self.assertEqual(compare_versions(before, after)["relative_percent"], 50)
        for task in (before, after):
            task["model"]["objective"]["sense"] = "min"
            rehash(task)
        self.assertEqual(compare_versions(before, after)["improvement"], "下降")
        after["solver"]["objective_value"] = -1100
        self.assertEqual(compare_versions(before, after)["improvement"], "改善")
        after["solver"]["objective_value"] = -1000.000000001
        self.assertEqual(compare_versions(before, after)["delta"], 0)

from copy import deepcopy
import csv
from pathlib import Path
import tempfile
import unittest
from src.schemas import ProblemProfile
from src.workbench.cases import CASES
from src.workbench.model import validate_model, numerical_checks, ModelError
from src.workbench.service import create_task, run_optimization_task, prepare_task, confirm_task, revise_task, solve_task, model_hash, report_markdown
from src.workbench.store import TaskStore

class TaskTests(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='optiflow_test_')
        self.addCleanup(self.temp.cleanup)
        self.store = TaskStore(Path(self.temp.name) / 'tasks.sqlite3')

    def build(self, case_id='production'):
        case = CASES[case_id]
        return run_optimization_task(case['text'], mode='case', case_id=case_id, store=self.store)

    def solve(self, task):
        result = confirm_task(task['task_id'], expected_version=task['model_version'], store=self.store)
        self.assertEqual(result['status'], 'completed', result.get('failure'))
        return result

    def test_confirmation_gates_execution(self):
        task = self.build()
        self.assertEqual(task['status'], 'awaiting_confirmation')
        self.assertFalse(task['solver'])
        self.assertEqual([s['status'] for s in task['stages']], ['completed'] * 3 + ['pending'] * 3)
        with self.assertRaises(ValueError):
            solve_task(task['task_id'], store=self.store)
        self.assertFalse(list(Path(self.temp.name).rglob('trusted_solver.py')))

    def test_real_case_revision_and_result_comparison(self):
        first = self.solve(self.build())
        self.assertAlmostEqual(first['solver']['objective_value'], 10000)
        self.assertEqual(first['solver']['solution'], {'A': 100.0, 'B': 200.0})
        second = revise_task(first['task_id'], '产品 A 的产量不能超过 80 件。', expected_version=1, store=self.store)
        self.assertEqual(second['model_version'], 2)
        self.assertEqual(second['human_review']['status'], 'pending')
        self.assertEqual(second['validation']['numerical_feasibility'], 'not_checked')
        self.assertFalse(second['solver'])
        self.assertEqual(second['versions'][0]['solver']['objective_value'], 10000)
        second = self.solve(second)
        self.assertAlmostEqual(second['solver']['objective_value'], 9500)
        self.assertEqual(second['solver']['solution'], {'A': 80.0, 'B': 210.0})
        self.assertEqual(second['validation']['semantic_correctness'], 'not_verified')
        self.assertEqual(second['validation']['numerical_feasibility'], 'passed')
        self.assertIn('9500', report_markdown(second))
        self.assertEqual(self.store.metrics()['confirmations'], 2)
        self.assertTrue(list((Path(self.temp.name) / 'traces').glob('*.json')))

    def test_all_builtin_models_solve(self):
        for (case_id, objective) in (('allocation', 195), ('staffing', 2900)):
            with self.subTest(case=case_id):
                task = self.solve(self.build(case_id))
                self.assertAlmostEqual(task['solver']['objective_value'], objective)

    def test_infeasible_is_not_success(self):
        task = self.build()
        task = revise_task(task['task_id'], 'A >= 500', expected_version=1, store=self.store)
        result = confirm_task(task['task_id'], expected_version=2, store=self.store)
        self.assertEqual(result['status'], 'no_solution', result.get('failure'))
        self.assertEqual(result['solver']['status'], 'Infeasible')
        self.assertIsNone(result['solver']['objective_value'])
        self.assertFalse(result['solver']['solution'])
        self.assertEqual(result['validation']['numerical_feasibility'], 'not_checked')

    def test_stale_and_double_confirmation_rejected(self):
        task = self.build()
        with self.assertRaises(ValueError):
            confirm_task(task['task_id'], expected_version=0, store=self.store)
        confirm_task(task['task_id'], expected_version=1, store=self.store, defer=True)
        with self.assertRaises(ValueError):
            confirm_task(task['task_id'], expected_version=1, store=self.store)
        self.assertEqual(self.store.metrics()['confirmations'], 1)

    def test_model_tampering_blocks_confirmation(self):
        task = self.build()
        task['model']['objective']['coefficients']['A'] = 400
        self.store.save(task)
        with self.assertRaises(ModelError):
            confirm_task(task['task_id'], expected_version=1, store=self.store)

    def test_missing_inputs_block_confirmation(self):
        task = self.build()
        task['model']['missing_inputs'] = ['资源上限尚未明确']
        task['model_hash'] = model_hash(task['model'])
        self.store.save(task)
        with self.assertRaises(ModelError):
            confirm_task(task['task_id'], expected_version=1, store=self.store)

    def test_custom_text_never_silently_uses_case_fixture(self):
        with self.assertRaises(ModelError):
            create_task(CASES['production']['text'] + '增加其他条件', mode='case', case_id='production', store=self.store)
        task = self.build()
        with self.assertRaises(ModelError):
            revise_task(task['task_id'], '把利润改成 800', expected_version=1, store=self.store)
        self.assertEqual(self.store.get(task['task_id'])['status'], 'awaiting_confirmation')

    def test_unknown_variable_and_nonfinite_coefficients_rejected(self):
        for coefficient in (float('nan'), float('inf'), "__import__('os')", True):
            model = deepcopy(CASES['production']['model'])
            model['objective']['coefficients']['A'] = coefficient
            with self.assertRaises(ModelError):
                validate_model(model, CASES['production']['text'])
        model = deepcopy(CASES['production']['model'])
        model['constraints'][0]['coefficients']['unknown'] = 1
        with self.assertRaises(ModelError):
            validate_model(model, CASES['production']['text'])

    def test_false_source_rejected(self):
        model = deepcopy(CASES['production']['model'])
        model['constraints'][0]['source'] = '原文没有这句话'
        with self.assertRaises(ModelError):
            validate_model(model, CASES['production']['text'])

    def test_independent_checks_catch_feasibility_integrality_and_objective(self):
        model = CASES['production']['model']
        for (solution, obj) in (({'A': 200, 'B': 200}, 14000), ({'A': 99.5, 'B': 200}, 9980), ({'A': 100, 'B': 200}, 1)):
            with self.subTest(solution=solution, objective=obj):
                self.assertEqual(numerical_checks(model, solution, obj)['numerical_feasibility'], 'failed')
        self.assertEqual(numerical_checks(model, {}, None)['numerical_feasibility'], 'not_checked')

    def test_failure_is_persisted_without_provider_error_details(self):

        class BrokenAdapter:

            def profile(self, text):
                raise RuntimeError('sensitive_provider_payload_should_not_be_saved')
        task = run_optimization_task(CASES['production']['text'], store=self.store, adapter=BrokenAdapter())
        self.assertEqual(task['status'], 'failed')
        self.assertEqual(task['failure']['stage'], 'parse')
        self.assertNotIn('sensitive_provider', str(task))
        self.assertEqual(task['stages'][0]['status'], 'failed')

    def test_live_adapter_contract_and_confirmation(self):

        class FakeAdapter:

            def __init__(self):
                self.calls = []

            def profile(self, text):
                self.calls.append('profile')
                return ProblemProfile()

            def route(self, task, profile):
                self.calls.append('route')
                return ([], [])

            def formulate(self, task, profile, activated, references):
                self.calls.append('formulate')
                return (deepcopy(CASES['production']['model']), 'shared FEF')

            def generate_artifact(self, task, directory):
                self.calls.append('code')
                marker = directory / 'MUST_NOT_EXIST'
                path = directory / 'agent_code.py'
                path.write_text(f'from pathlib import Path\nPath({str(marker)!r}).touch()', encoding='utf-8')
                return {'path': str(path), 'executed': False}
        adapter = FakeAdapter()
        task = run_optimization_task(CASES['production']['text'], store=self.store, adapter=adapter)
        self.assertEqual(adapter.calls, ['profile', 'route', 'formulate'])
        result = confirm_task(task['task_id'], expected_version=1, store=self.store, adapter=adapter)
        self.assertEqual(result['status'], 'completed', result.get('failure'))
        self.assertFalse(list(Path(self.temp.name).rglob('MUST_NOT_EXIST')))
        self.assertEqual(adapter.calls[-1], 'code')

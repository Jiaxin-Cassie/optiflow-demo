"""Natural phrasing, visible modeling differences and verified decision advice."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from src.workbench.cases import CASES,parse_case_feedback
from src.workbench.model import ModelError
from src.workbench.review import model_alignment,decision_brief
from src.workbench.service import run_optimization_task,confirm_task,revise_task
from src.workbench.store import TaskStore


class ReviewTests(unittest.TestCase):
    def test_structured_input_rebuilds_without_confirming_on_behalf_of_user(self):
        import os
        from unittest.mock import patch
        from streamlit.testing.v1 import AppTest
        from src.workbench.store import ROOT
        from src.workbench.service import prepare_task
        with tempfile.TemporaryDirectory(prefix='optiflow_structured_ui_') as folder:
            db=str(Path(folder)/'tasks.sqlite3')
            store=TaskStore(db)
            case=CASES['production']
            task=run_optimization_task(case['text'],mode='case',case_id='production',store=store)
            def prepare(task_id,action,store):
                self.assertEqual(action,'prepare')
                return prepare_task(task_id,store=store)
            with patch.dict(os.environ,{'OPTIFLOW_DB':db}),patch('src.workbench.jobs.launch',side_effect=prepare):
                app=AppTest.from_file(str(ROOT/'src/workbench/app.py'),default_timeout=60)
                app.session_state['task_id']=task['task_id']
                app.session_state['of_view']='workspace'
                app.session_state['of_step']=1
                app.run()
                next(b for b in app.button if b.label=='需要修改').click().run()
                next(r for r in app.radio if r.label=='补充方式').set_value('选择产品和数量').run()
                next(b for b in app.button if b.label=='提交修改并重新建模').click().run()
                self.assertFalse(list(app.exception))
                updated=store.get(task['task_id'])
                self.assertEqual(updated['model_version'],2)
                self.assertEqual(updated['status'],'awaiting_confirmation')
                self.assertFalse(updated['solver'])
                self.assertEqual(updated['model']['constraints'][-1]['rhs'],100)

    def test_screenshot_wording_and_single_bound_variants_are_understood(self):
        for text in ['A 每天最多生产 100 件的新要求','A 产品每天最多只能生产 100 件。',
                     '新增一条要求：a 每天最多生产100件','补充一条约束：产品 A 的产量不能超过 100 件。']:
            with self.subTest(text=text):
                parsed=parse_case_feedback('production',text)
                self.assertEqual((parsed['name'],parsed['relation'],parsed['rhs']),('A','<=',100))
        self.assertEqual(parse_case_feedback('production','B 至少生产10件')['relation'],'>=')

    def test_ambiguous_extra_requests_and_wrong_units_are_rejected(self):
        for text in ['A最多100件，B至少20件','A不是最多100件','A最多100件或200件','A最多100件并提高利润','A最多100人','把利润改成200']:
            with self.subTest(text=text),self.assertRaises(ModelError):
                parse_case_feedback('production',text)

    def test_alignment_and_advice_use_the_actual_model_versions_and_solutions(self):
        with tempfile.TemporaryDirectory(prefix='optiflow_review_') as folder:
            store=TaskStore(Path(folder)/'test.sqlite3')
            case=CASES['production']
            task=run_optimization_task(case['text'],mode='case',case_id='production',store=store)
            first=deepcopy(task)
            self.assertIsNone(model_alignment(task)['previous_version'])
            self.assertFalse(decision_brief(task)['eligible'])
            task=confirm_task(task['task_id'],expected_version=1,store=store)
            task=revise_task(task['task_id'],'A 每天最多生产 100 件的新要求',expected_version=1,store=store)
            aligned=model_alignment(task)
            self.assertEqual(aligned['counts'],{'新增':1,'已修改':0,'已移除':0,'保持不变':5})
            self.assertEqual(aligned['rows'][0]['status'],'新增')
            self.assertEqual(aligned['rows'][0]['source'],'A 每天最多生产 100 件的新要求')
            self.assertIn('不能超过 100 件',aligned['rows'][0]['meaning'])
            self.assertEqual(first['model'],task['versions'][0]['model'])
            self.assertFalse(decision_brief(task)['eligible'])
            task=confirm_task(task['task_id'],expected_version=2,store=store)
            brief=decision_brief(task)
            self.assertTrue(brief['eligible'])
            self.assertEqual([r['value'] for r in brief['decision_rows']],[100,200])
            self.assertIn('沿用原方案',brief['change_explanation'])
            task=revise_task(task['task_id'],'A <= 80',expected_version=2,store=store)
            task=confirm_task(task['task_id'],expected_version=3,store=store)
            changed=decision_brief(task)
            self.assertNotIn('沿用原方案',changed['change_explanation'])
            self.assertEqual(task['solver']['objective_value'],9500)

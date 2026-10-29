"""Blocked-step reporting, recovery and truthful responsive charts."""
import unittest
from src.workbench.charts import quantity_chart_html
from src.workbench.guidance import step_guidance
from src.workbench.manual_study import begin_manual, save_step_note, manual_session, current_step, enrollment_records
from tests import test_manual_study as study_fixture


class GuidanceTests(unittest.TestCase):
    setUp = study_fixture.ManualStudyTests.setUp
    start = study_fixture.ManualStudyTests.start
    def test_problem_before_creation_is_saved_without_completing_t1(self):
        begin_manual(self.person,'不了解优化')
        save_step_note(self.person,'T1',issue_state='遇到问题 / 不知道怎么继续',issue='找不到开始按钮')
        session=manual_session(self.person)
        self.assertIsNone(session['task_id'])
        self.assertEqual(current_step(session)[0],'T1')
        self.assertIsNone(session['steps'][0]['submitted_at'])
        self.assertEqual(enrollment_records(self.manager)[0]['T1_issue'],'找不到开始按钮')
        with self.assertRaises(ValueError):
            save_step_note(self.person,'T1',issue_state='遇到问题 / 不知道怎么继续',issue='')

    def test_guidance_sends_unsolved_initial_plan_to_review_and_busy_task_to_progress(self):
        task=self.start()
        self.assertEqual(step_guidance('T4',task)['page'],'模型查看与确认')
        self.assertIn('初始',step_guidance('T4',task)['action'])
        task['status']='executing'
        self.assertEqual(step_guidance('T5',task)['page'],'Agent 工作流')


class ChartTests(unittest.TestCase):
    def test_chart_escapes_labels_and_keeps_units_separate(self):
        html=quantity_chart_html([{'决策项':'<script>alert(1)</script>','建议数量':100,'单位':'件'},
                                  {'决策项':'B','建议数量':200,'单位':'件'},
                                  {'决策项':'人数','建议数量':4,'单位':'人'}])
        self.assertNotIn('<script>',html)
        self.assertIn('&lt;script&gt;',html)
        self.assertEqual(html.count('class="quantity-group"'),2)
        self.assertIn('width:50.00000%',html)
        self.assertIn('100 <small>件</small>',html)

    def test_negative_zero_and_nonfinite_results_do_not_fake_bars(self):
        html=quantity_chart_html([{'决策项':'负值','建议数量':-10,'单位':'元'},
                                  {'决策项':'正值','建议数量':10,'单位':'元'},
                                  {'决策项':'零','建议数量':0,'单位':'元'}],recommended=False)
        self.assertIn('待复核',html)
        self.assertIn('left:50.00000%',html)
        self.assertIn('width:0.00000%',html)
        self.assertEqual(quantity_chart_html([{'建议数量':float('nan')}]),'')

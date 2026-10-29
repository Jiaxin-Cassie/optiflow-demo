"""Six-task protocol uses actual versions, real solves, scoped answers and exports."""
import csv
import io
from pathlib import Path
import tempfile
import unittest
from urllib.parse import urlsplit, parse_qs

from src.workbench.hosting import create_invites, ParticipantStore, start_invited_test
from src.workbench.manual_study import (begin_manual, manual_session, current_step, submit_step,
    record_comparison, save_observation, observation, enrollment_records, STEPS)
from src.workbench.service import prepare_task, confirm_task, revise_task
from src.workbench.store import TaskStore
from src.workbench.usability import (record_view, finish_test, study_for_task, submit_questionnaire,
    test_records, export_csv, delete_test)


class ManualStudyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='optiflow_manual_')
        self.addCleanup(self.temp.cleanup)
        self.manager = TaskStore(Path(self.temp.name) / 'study.sqlite3')
        self.links = create_invites(self.manager, 'production', 2, 'https://study.example.test')
        self.people = [ParticipantStore(self.manager.path, parse_qs(urlsplit(i['url']).query)['invite'][0]) for i in self.links]
        self.person = self.people[0]

    def start(self):
        begin_manual(self.person, '有少量了解')
        task = start_invited_test(self.person)
        return prepare_task(task['task_id'], store=self.person)

    def ack(self, step, task, answer='我的理解与观察'):
        submit_step(self.person, step, answer, expected_version=task['model_version'])

    def revised_result(self):
        task = self.start()
        self.ack('T1', task)
        record_view(self.person, task['task_id'], 'model_review_opened')
        self.ack('T2', task)
        self.ack('T3', task, '没有发现遗漏，不确定假设是否符合实际。')
        with self.assertRaisesRegex(ValueError, '初始模型'):
            revise_task(task['task_id'], 'A 产品每天最多只能生产 100 件。', expected_version=1, store=self.person)
        task = confirm_task(task['task_id'], expected_version=1, store=self.person)
        task = revise_task(task['task_id'], 'A 产品每天最多只能生产 100 件。', expected_version=1, store=self.person)
        self.assertEqual(task['model_version'], 2)
        self.ack('T4', task)
        task = confirm_task(task['task_id'], expected_version=2, store=self.person)
        record_view(self.person, task['task_id'], 'result_viewed')
        self.ack('T5', task, 'A=100，B=200，利润10000；还需核对业务假设。')
        return task

    def test_t1_enrollment_does_not_create_task_and_is_reconnect_safe(self):
        begin_manual(self.person, '不了解优化')
        begin_manual(self.person, '熟悉优化')
        self.assertEqual(self.manager.list(), [])
        self.assertEqual(len(enrollment_records(self.manager)), 1)
        self.assertEqual(manual_session(self.person)['background'], '不了解优化')
        self.assertEqual(current_step(manual_session(self.person))[0], 'T1')
        self.assertEqual(test_records(self.manager), [])

    def test_complete_protocol_keeps_unchanged_results_and_full_questionnaire(self):
        task = self.revised_result()
        study = study_for_task(self.person, task['task_id'])
        self.assertEqual(task['solver']['objective_value'], 10000)
        self.assertEqual(task['versions'][0]['solver']['objective_value'], 10000)
        with self.assertRaises(ValueError):
            finish_test(self.person, study['id'])
        with self.assertRaisesRegex(ValueError, '对比'):
            self.ack('T6', task)
        record_comparison(self.person, task)
        self.ack('T6', task, '两次均为A100、B200；原方案已满足新上限，无需调整。')
        with self.assertRaises(ValueError):
            self.ack('T6', task)
        finish_test(self.person, study['id'])
        with self.assertRaisesRegex(ValueError, '三道'):
            submit_questionnaire(self.person, study['id'], '基本能理解', '判断是否遗漏约束')
        answers = {'confusion': '版本对比的位置让我困惑。', 'work_use': '愿意，但希望支持实际工厂数据。', 'one_improvement': '=改进导航\n保留原话'}
        submit_questionnaire(self.person, study['id'], '基本能理解', '判断是否遗漏约束', interview=answers)
        rows = test_records(self.manager)
        self.assertEqual(rows[0]['confusion'], answers['confusion'])
        self.assertTrue(all(rows[0][key+'_submitted'] for key,_,_ in STEPS))
        self.assertTrue(all(rows[0][key+'_observer_status']=='' for key,_,_ in STEPS))
        csv_row = list(csv.DictReader(io.StringIO(export_csv(rows).decode('utf-8-sig'))))[0]
        self.assertEqual(csv_row['T5_answer'], 'A=100，B=200，利润10000；还需核对业务假设。')
        self.assertTrue(csv_row['one_improvement'].startswith("'="))
        with self.assertRaisesRegex(ValueError, '已结束'):
            revise_task(task['task_id'], 'A <= 80', expected_version=2, store=self.person)

    def test_step_order_stale_versions_and_peer_scope_are_rejected(self):
        task = self.start()
        with self.assertRaises(ValueError):
            self.ack('T2', task)
        with self.assertRaises(ValueError):
            submit_step(self.person, 'T1', expected_version=0)
        with self.assertRaises(PermissionError):
            manual_session(self.people[1], task['task_id'])
        self.ack('T1', task)
        self.assertEqual(current_step(manual_session(ParticipantStore(self.manager.path, parse_qs(urlsplit(self.links[0]['url']).query)['invite'][0])))[0], 'T2')

    def test_interrupted_questionnaire_is_saved_without_claiming_completion(self):
        task = self.start()
        study = study_for_task(self.person, task['task_id'])
        finish_test(self.person, study['id'], interrupted=True)
        submit_questionnaire(self.person, study['id'], '不太能理解', '其他', difficulty_other='找不到对比位置',
                             interview={'confusion':'不清楚', 'work_use':'暂时不会', 'one_improvement':'引导'})
        row = test_records(self.manager)[0]
        self.assertEqual(row['status'], 'interrupted')
        self.assertTrue(row['questionnaire_submitted'])
        self.assertFalse(row['T6_submitted'])

    def test_observer_record_is_separate_manager_only_and_deleted_with_study(self):
        task = self.start()
        study = study_for_task(self.person, task['task_id'])
        payload = {'steps': {key:{'status':'未测试','seconds':None,'issue':''} for key,_,_ in STEPS},
                   'technical_issues':'T1连接等待', 'severe_issue':'导航', 'impact':'找不到入口', 'hypothesis':'标识不清楚'}
        payload['steps']['T1'] = {'status':'提示','seconds':65.0,'issue':'需要观察者提示'}
        save_observation(self.manager, study['id'], payload)
        self.assertEqual(observation(self.manager, study['id']), payload)
        self.assertEqual(test_records(self.manager)[0]['T1_observer_seconds'],65)
        self.assertEqual(test_records(self.person)[0]['T1_observer_status'],'')
        with self.assertRaises(PermissionError):
            save_observation(self.person, study['id'], payload)
        with self.assertRaises(PermissionError):
            observation(self.person, study['id'])
        delete_test(self.manager, study['id'])
        with self.assertRaises(PermissionError):
            manual_session(self.person)
        self.assertEqual(enrollment_records(self.manager), [])

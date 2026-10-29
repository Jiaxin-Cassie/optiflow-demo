"""A remote participant follows the manual using the real product pages."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit, parse_qs

from streamlit.testing.v1 import AppTest
from src.workbench.hosting import create_invites
from src.workbench.service import prepare_task, solve_task
from src.workbench.store import ROOT, TaskStore
from src.workbench.usability import test_records


class ManualUITests(unittest.TestCase):
    def test_remote_six_task_journey_questionnaire_and_manager_collection(self):
        with tempfile.TemporaryDirectory(prefix='optiflow_manual_ui_') as folder:
            db = str(Path(folder) / 'shared.sqlite3')
            manager = TaskStore(db)
            invitation = create_invites(manager, 'production', 1, 'https://study.example.test')[0]
            secret = parse_qs(urlsplit(invitation['url']).query)['invite'][0]
            def worker(task_id, action, store):
                return (prepare_task if action=='prepare' else solve_task)(task_id,store=store)
            env = {'OPTIFLOW_DB':db,'OPTIFLOW_HOSTED_STUDY':'1','OPTIFLOW_ADMIN_PASSWORD':'test-only-manager-password'}
            with patch.dict(os.environ,env), patch('src.workbench.jobs.launch',side_effect=worker):
                app = AppTest.from_file(str(ROOT/'src/workbench/app.py'),default_timeout=60)
                app.query_params['invite'] = secret
                app.run()
                def button(label):
                    next(b for b in app.button if b.label==label).click().run()
                    self.assertFalse(list(app.exception),label)
                def page(label):
                    app.sidebar.radio[0].set_value(label).run()
                    self.assertFalse(list(app.exception),label)
                def ack(answer=''):
                    if answer:
                        next(t for t in app.text_area if t.label=='本步回答 / 发现的问题').set_value(answer)
                    issue_radio=next(r for r in app.radio if r.label=='使用网页时，本步是否遇到问题？')
                    if issue_radio.value is None:
                        issue_radio.set_value('没有遇到问题')
                    next(r for r in app.radio if r.label=='本步是否得到他人提示？').set_value('未获得提示')
                    button(next(b.label for b in app.button if b.label.startswith('提交本步记录，')))
                    self.assertNotEqual(app.sidebar.radio[0].value,'测试任务指引')
                next(r for r in app.radio if r.label=='你对优化的了解程度').set_value('不了解优化')
                button('开始六任务体验')
                self.assertEqual(len(manager.list()),0)
                self.assertEqual(app.sidebar.radio[0].value,'工作台总览')
                next(r for r in app.radio if r.label=='使用网页时，本步是否遇到问题？').set_value('遇到问题 / 不知道怎么继续')
                next(t for t in app.text_area if t.label=='问题说明（遇到问题时必填）').set_value('开发验收：开始入口不明确')
                button('先保存问题，不结束本步')
                self.assertEqual(len(manager.list()),0)
                button('新建优化任务')
                button('生成可确认的模型')
                ack()
                page('模型查看与确认')
                ack('目标是提高利润，资源有人工与机器限制，产量应为非负整数。')
                ack('目前没有发现遗漏，假设仍需业务确认。')
                page('模型查看与确认')
                next(c for c in app.checkbox if c.label.startswith('已检查')).check().run()
                button('确认模型并求解')
                button('查看求解结果')
                button('补充需求 / 调整方案')
                next(t for t in app.text_area if t.label=='补充需求').set_value('A 每天最多生产 100 件的新要求')
                button('补充需求并重新建模')
                button('检查并确认模型')
                self.assertTrue(any('新增规则' in s.value for s in app.success))
                self.assertTrue(any(t.label=='业务与模型对照' for t in app.tabs))
                ack()
                page('模型查看与确认')
                next(c for c in app.checkbox if c.label.startswith('已检查')).check().run()
                button('确认模型并求解')
                button('查看求解结果')
                self.assertTrue(any(m.value=='10,000.00' for m in app.metric))
                self.assertTrue(any('本次生产决策建议' in s.value for s in app.subheader))
                self.assertTrue(any('沿用原方案' in s.value for s in app.info))
                self.assertFalse(any(b.label=='标记测试完成' for b in app.button))
                ack('A100件，B200件，利润10000元。需要确认实际资源情况。')
                page('前后方案对比')
                ack('两次结果相同。原计划已经满足A上限，无需为了调整而调整。')
                self.assertEqual(app.sidebar.radio[0].value,'结束问卷')
                self.assertEqual(test_records(manager)[0]['status'],'completed')
                self.assertFalse(test_records(manager)[0]['questionnaire_submitted'])
                next(r for r in app.radio if r.label=='你是否能理解系统生成的业务模型？').set_value('基本能理解')
                next(s for s in app.selectbox if s.label=='你觉得哪个环节最困难？').set_value('判断是否遗漏约束')
                answers={'刚才哪个地方最让你困惑？为什么？':'比较版本的入口不明显。',
                         '你是否愿意在真实工作中使用？需要哪些条件？':'愿意，需要接入真实数据。',
                         '如果只能改进一处，你希望改哪里？':'改善导航。'}
                for label,answer in answers.items():
                    next(t for t in app.text_area if t.label==label).set_value(answer)
                button('提交结束问卷')
                self.assertTrue(test_records(TaskStore(db))[0]['questionnaire_submitted'])
                self.assertTrue(any('问卷已提交' in s.value for s in app.success))
                admin = AppTest.from_file(str(ROOT/'src/workbench/app.py'),default_timeout=60)
                admin.query_params['admin']='1'
                admin.run()
                admin.text_input[0].set_value('test-only-manager-password')
                next(b for b in admin.button if b.label=='进入管理后台').click().run()
                self.assertFalse(list(admin.exception))
                self.assertTrue(any(s.label=='查看参与者回答与问卷' for s in admin.selectbox))
                self.assertEqual(test_records(manager)[0]['one_improvement'],'改善导航。')
                self.assertEqual(test_records(manager)[0]['T1_issue'],'开发验收：开始入口不明确')
                self.assertTrue(any(b.label=='保存观察记录' for b in admin.button))

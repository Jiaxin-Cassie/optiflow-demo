"""Temporary entry contracts without starting external tunnels or using real data."""
import argparse
import hashlib
import json
from pathlib import Path
import tempfile
import os
from datetime import datetime,timezone,timedelta
import io
import unittest
from unittest.mock import patch

from src.workbench import cli, share
from src.workbench.package import product_files
from src.storage import atomic_json


class ShareTests(unittest.TestCase):
    def test_atomic_write_retries_file_lock_and_preserves_valid_destination(self):
        with tempfile.TemporaryDirectory(prefix='optiflow_atomic_') as folder:
            path=Path(folder)/'state.json'
            atomic_json(path,{'version':1})
            import src.storage as storage
            original_replace=storage.os.replace
            attempts=[]
            def replace_after_lock(source,destination):
                attempts.append(source)
                if len(attempts)<3:raise PermissionError('locked')
                return original_replace(source,destination)
            with patch.object(storage.os,'replace',side_effect=replace_after_lock) as replacement,patch.object(storage.time,'sleep'):
                atomic_json(path,{'version':2})
                source,destination=replacement.call_args.args
                self.assertEqual(len(attempts),3)
                self.assertEqual(json.loads(path.read_text('utf-8')),{'version':2})
                self.assertNotEqual(Path(source).name,path.name+'.tmp')
            with patch.object(storage.os,'replace',side_effect=PermissionError('locked')),patch.object(storage.time,'sleep'):
                with self.assertRaises(PermissionError):atomic_json(path,{'version':3})
            self.assertEqual(json.loads(path.read_text('utf-8')),{'version':2})
            atomic_json(path,{'version':4})
            self.assertEqual(json.loads(path.read_text('utf-8')),{'version':4})
            self.assertFalse(list(Path(folder).glob('*.tmp')))

    def test_locked_monitoring_file_does_not_raise_and_later_recovers(self):
        state={'state':'ready'}
        with patch.object(share,'atomic_json',side_effect=PermissionError('locked')),patch('builtins.print') as report:
            self.assertFalse(share._persist_status(Path('unused.json'),state))
            self.assertFalse(share._persist_status(Path('unused.json'),state))
            self.assertEqual(report.call_count,1)
        with patch.object(share,'atomic_json'):
            self.assertTrue(share._persist_status(Path('unused.json'),state))
            self.assertNotIn('status_write_delayed',state)

    def test_old_ready_state_is_not_presented_as_live_or_opened(self):
        with tempfile.TemporaryDirectory(prefix='optiflow_stale_') as folder,patch.object(share,'SHARE_DIR',Path(folder)):
            atomic_json(Path(folder)/'connection.json',{'state':'ready','last_seen':(datetime.now(timezone.utc)-timedelta(minutes=2)).isoformat()})
            self.assertEqual(share.read_status()['state'],'unresponsive')
            with patch.object(share.webbrowser,'open') as opened:
                with self.assertRaises(RuntimeError):share.open_entry()
                opened.assert_not_called()

    @unittest.skipUnless(os.name=='nt','Windows controller lock')
    def test_controller_keeps_children_running_after_a_failed_heartbeat_write(self):
        with tempfile.TemporaryDirectory(prefix='optiflow_heartbeat_') as folder:
            directory=Path(folder)
            stop=directory/'stop_requested'
            state_writes=[]
            processes=[]
            class Child:
                pid=123
                def poll(self):return None
            class Response(io.BytesIO):
                status=200
            class Opener:
                def open(self,*args,**kwargs):return Response(b'ok')
            def write_status(path,state):
                if state.get('last_seen') and state['state']=='ready':
                    state_writes.append(dict(state))
                    if len(state_writes)==1:raise PermissionError('locked heartbeat')
                    stop.touch()
                atomic_json(path,state)
            def child(*args,**kwargs):
                instance=Child();processes.append(instance);return instance
            def stop_child(process):
                self.assertTrue(stop.exists(),'Healthy children stopped before the requested shutdown')
            with patch.object(share,'SHARE_DIR',directory),patch.object(share,'ensure_tool',return_value=directory/'cloudflared.exe'), \
                 patch.object(share,'_password',return_value=('test-only-password',directory/'password.txt')), \
                 patch.object(share,'extract_tunnel_url',return_value='https://alpha-beta.trycloudflare.com'), \
                 patch.object(share.subprocess,'Popen',side_effect=child),patch.object(share,'_stop_child',side_effect=stop_child), \
                 patch.object(share.urllib.request,'build_opener',return_value=Opener()), \
                 patch.object(share.urllib.request,'urlopen',return_value=Response(b'ok')), \
                 patch.object(share,'atomic_json',side_effect=write_status),patch.object(share,'_entry_page'), \
                 patch.object(share.time,'sleep'),patch('builtins.print'):
                share.serve()
            self.assertEqual(len(state_writes),2)
            self.assertEqual(len(processes),2)
            self.assertEqual(json.loads((directory/'connection.json').read_text('utf-8'))['state'],'stopped')

    def test_only_expected_temporary_hostnames_are_accepted(self):
        self.assertEqual(share.extract_tunnel_url('Visit https://Alpha-Beta.trycloudflare.com now'),
                         'https://alpha-beta.trycloudflare.com')
        for value in ['http://alpha-beta.trycloudflare.com', 'https://alpha-beta.trycloudflare.com.evil.test',
                      'https://example.com', 'https://alpha-beta.trycloudflare.com-evil.test']:
            self.assertIsNone(share.extract_tunnel_url(value))

    def test_password_is_persistent_and_not_embedded_in_entry_page(self):
        with tempfile.TemporaryDirectory(prefix='optiflow_share_') as folder:
            directory = Path(folder)
            password, path = share._password(directory)
            self.assertGreaterEqual(len(password), 28)
            self.assertEqual(share._password(directory), (password, path))
            with patch.object(share, 'SHARE_DIR', directory):
                share._entry_page({'admin_url': 'https://alpha-beta.trycloudflare.com/?admin=1',
                                   'public_url': 'https://alpha-beta.trycloudflare.com'})
            self.assertNotIn(password, (directory / '入口信息.html').read_text('utf-8'))

    def test_cached_binary_requires_matching_checksum(self):
        with tempfile.TemporaryDirectory(prefix='optiflow_share_tool_') as folder:
            directory = Path(folder)
            binary = directory / 'cloudflared.exe'
            binary.write_bytes(b'verified-test-fixture')
            (directory / 'cloudflared.json').write_text(json.dumps({
                'sha256': hashlib.sha256(binary.read_bytes()).hexdigest()}), encoding='utf-8')
            with patch.object(share, 'TOOLS_DIR', directory), patch.object(share.platform, 'machine', return_value='AMD64'):
                self.assertEqual(share.ensure_tool(), binary)
                binary.write_bytes(b'altered')
                with self.assertRaisesRegex(RuntimeError, '校验失败'):
                    share.ensure_tool()

    def test_stop_and_status_do_not_include_password(self):
        with tempfile.TemporaryDirectory(prefix='optiflow_share_status_') as folder:
            with patch.object(share, 'SHARE_DIR', Path(folder)):
                self.assertEqual(share.read_status(), {'state': 'not_started'})
                self.assertEqual(share.request_stop(), {'state': 'not_started'})
                self.assertTrue((Path(folder) / 'stop_requested').exists())

    def test_entrypoint_routes_share_without_starting_local_unrestricted_app(self):
        parser = argparse.ArgumentParser()
        cli.add_arguments(parser)
        with patch.object(share, 'serve') as start:
            self.assertTrue(cli.dispatch(parser.parse_args(['--share'])))
            start.assert_called_once_with()
        names = product_files()
        self.assertIn('src/workbench/share.py', names)
        self.assertFalse(any(name.startswith('runtime/') for name in names))


if __name__ == '__main__':
    unittest.main()

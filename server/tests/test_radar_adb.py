from argparse import Namespace
import subprocess
import unittest
from unittest.mock import patch

from tools import radar_adb


class RadarAdbTest(unittest.TestCase):
    def test_control_parses_ordered_broadcast_reply_without_chat_text(self):
        reply = subprocess.CompletedProcess(
            [], 0, 'Broadcasting: Intent { ... }\n'
                   'Broadcast completed: result=0, data="{\\"ok\\":true,\\"pending\\":7}"\n', '')
        with patch.object(radar_adb, 'invoke', return_value=reply) as invoke:
            result = radar_adb.control(Namespace(adb='adb', serial='phone'), 'status')
        self.assertEqual({'ok': True, 'pending': 7}, result)
        argv = invoke.call_args.args
        self.assertEqual(('shell', 'am', 'broadcast', '--include-stopped-packages'), argv[1:5])
        self.assertIn('--es', argv)

    def test_control_wakes_collector_if_xiaomi_blocks_cold_broadcast(self):
        missing = subprocess.CompletedProcess([], 0, 'Broadcast completed: result=0\n', '')
        started = subprocess.CompletedProcess([], 0, 'Status: ok\n', '')
        reply = subprocess.CompletedProcess([], 0,
            'Broadcast completed: result=0, data="{\\"ok\\":true}"\n', '')
        with patch.object(radar_adb, 'invoke', side_effect=[missing, started, reply]) as invoke:
            self.assertEqual({'ok': True}, radar_adb.control(Namespace(adb='adb', serial='phone'), 'status'))
        self.assertEqual(('shell', 'am', 'start', '-W', '-n'), invoke.call_args_list[1].args[1:6])

    def test_drain_stops_after_progress_and_then_idle(self):
        results = iter([
            {'ok': True, 'outcome': 'SENT', 'processed': 100, 'pending': 2},
            {'ok': True, 'outcome': 'SENT', 'processed': 2, 'pending': 0},
        ])
        with patch.object(radar_adb, 'control', side_effect=lambda *_: next(results)):
            self.assertEqual({'batches': 2, 'processed': 102, 'pending': 0},
                             radar_adb.drain(Namespace(max_batches=40)))

    def test_drain_rejects_stalled_upload(self):
        with patch.object(radar_adb, 'control', return_value={
            'ok': True, 'outcome': 'SENT', 'processed': 0, 'pending': 4}):
            with self.assertRaisesRegex(RuntimeError, 'sync_no_progress'):
                radar_adb.drain(Namespace(max_batches=40))

    def test_drain_exposes_unselected_room_backlog(self):
        with patch.object(radar_adb, 'control', return_value={
            'ok': True, 'outcome': 'IDLE', 'pending': 5}):
            with self.assertRaisesRegex(RuntimeError, 'pending_rooms_not_selected'):
                radar_adb.drain(Namespace(max_batches=40))


if __name__ == '__main__':
    unittest.main()

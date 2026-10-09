from contextlib import nullcontext
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from tools.wake_kakao_before_delivery import scheduled_slot


class FakeDelivery:
    def __init__(self, now, due, enabled=True):
        self.now = now
        self.due = due
        self.policy = SimpleNamespace(enabled=enabled, timezone='Asia/Seoul',
                                      daily_times=['17:00'])
        self.store = SimpleNamespace(connect=lambda: nullcontext(object()))

    def _device(self, db, device):
        pass

    def _settings(self, db, device):
        return 1, self.policy, self.due

    def _now(self, db):
        return self.now


class WakeKakaoTest(unittest.TestCase):
    def test_wakes_for_hourly_slot_without_preexisting_summary(self):
        due = datetime(2026, 10, 6, 17, 0, tzinfo=ZoneInfo('Asia/Seoul'))
        self.assertEqual((due, 'scheduled_slot'),
                         scheduled_slot(FakeDelivery(due - timedelta(minutes=5), due), object()))

    def test_skips_outside_window_or_disabled_policy(self):
        due = datetime(2026, 10, 6, 17, 0, tzinfo=ZoneInfo('Asia/Seoul'))
        self.assertEqual((None, 'outside_wake_window'),
                         scheduled_slot(FakeDelivery(due - timedelta(minutes=30), due), object()))
        self.assertEqual((None, 'delivery_disabled'),
                         scheduled_slot(FakeDelivery(due - timedelta(minutes=5), due, False), object()))


if __name__ == '__main__':
    unittest.main()

from __future__ import annotations

import sys
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS_DIR))

from build_boss_report import aggregate_device_funnel


class DeviceFunnelTests(unittest.TestCase):
    def test_dated_rows_are_summed_instead_of_overwritten(self) -> None:
        data = {
            "results": {
                "event_device_current": {
                    "rows": [
                        {"date": "2026-07-01", "deviceCategory": "mobile", "eventName": "add_to_cart", "eventCount": 2},
                        {"date": "2026-07-02", "deviceCategory": "mobile", "eventName": "add_to_cart", "eventCount": 3},
                        {"date": "2026-07-01", "deviceCategory": "mobile", "eventName": "begin_checkout", "eventCount": 1},
                    ]
                }
            }
        }
        funnel = aggregate_device_funnel(data, "event_device_current")
        self.assertEqual(funnel["mobile"]["add_to_cart"], 5)
        self.assertEqual(funnel["mobile"]["begin_checkout"], 1)


if __name__ == "__main__":
    unittest.main()

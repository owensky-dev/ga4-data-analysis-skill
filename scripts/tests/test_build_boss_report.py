from __future__ import annotations

import sys
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS_DIR))

from build_boss_report import aggregate_device_funnel, build_key_event_reconciliation


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


class KeyEventReconciliationTests(unittest.TestCase):
    def test_purchase_counts_and_revenue_reconcile_across_datasets(self) -> None:
        data = {
            "results": {
                "key_events_current": {
                    "rows": [
                        {
                            "eventName": "purchase",
                            "eventCount": 2,
                            "keyEvents": 2,
                            "ecommercePurchases": 2,
                            "transactions": 2,
                            "purchaseRevenue": 885.54,
                            "totalRevenue": 885.54,
                        }
                    ]
                },
                "key_events_previous": {
                    "rows": [
                        {
                            "eventName": "ads_conversion_Shopping_Cart_1",
                            "eventCount": 4,
                            "keyEvents": 4,
                            "purchaseRevenue": 0,
                        }
                    ]
                },
                "purchase_transactions_current": {
                    "rows": [
                        {"transactionId": "order-1", "purchaseRevenue": 380.38},
                        {"transactionId": "order-2", "purchaseRevenue": 505.16},
                    ]
                },
                "items_current": {
                    "rows": [
                        {"itemName": "Sink", "itemRevenue": 380.38},
                        {"itemName": "Door", "itemRevenue": 505.16},
                    ]
                },
                "configured_key_events": {
                    "rows": [
                        {"eventName": "purchase"},
                        {"eventName": "ads_conversion_Shopping_Cart_1"},
                    ]
                },
            }
        }

        result = build_key_event_reconciliation(data)

        self.assertTrue(result["available"])
        self.assertTrue(result["purchase_counts_match"])
        self.assertTrue(result["purchase_revenue_matches"])
        self.assertTrue(result["item_revenue_matches"])
        self.assertEqual(result["unique_transaction_ids"], 2)
        self.assertEqual(result["transaction_revenue"], 885.54)

    def test_missing_transaction_id_breaks_count_reconciliation(self) -> None:
        data = {
            "results": {
                "key_events_current": {
                    "rows": [
                        {
                            "eventName": "purchase",
                            "eventCount": 1,
                            "keyEvents": 1,
                            "ecommercePurchases": 1,
                            "transactions": 1,
                            "purchaseRevenue": 99,
                            "totalRevenue": 99,
                        }
                    ]
                },
                "purchase_transactions_current": {
                    "rows": [{"transactionId": "(not set)", "purchaseRevenue": 99}]
                },
                "items_current": {"rows": [{"itemRevenue": 99}]},
            }
        }

        result = build_key_event_reconciliation(data)

        self.assertFalse(result["purchase_counts_match"])
        self.assertEqual(result["missing_transaction_ids"], 1)


if __name__ == "__main__":
    unittest.main()

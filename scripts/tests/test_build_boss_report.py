from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS_DIR))

import build_boss_report
from build_boss_report import (
    aggregate_device_funnel,
    bigquery_status_from_probe,
    build_key_event_reconciliation,
    paid_channel_diagnosis,
)


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


class ExternalReconciliationTests(unittest.TestCase):
    def test_ready_bigquery_probe_reports_readable_tables(self) -> None:
        result = bigquery_status_from_probe(
            {
                "propertyId": "123",
                "projectId": "example-project",
                "expectedDatasetId": "analytics_123",
                "status": "ready",
                "jobQuery": {"httpStatus": 200},
                "adminLinks": {"count": 1},
                "expectedDataset": {"tableIds": ["events_20260801", "events_20260802"]},
            },
            {},
        )

        self.assertIn("analytics_123 已可读取", result["datasetProbe"])
        self.assertIn("2 张表", result["datasetProbe"])
        self.assertIn("transaction-to-item", result["recommendedAccess"][0])

    def test_stale_shopify_window_is_excluded(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            reconciliation_path = Path(temp_dir) / "shopify.json"
            reconciliation_path.write_text(
                json.dumps(
                    {
                        "dateRange": {
                            "current": {"startDate": "2026-07-01", "endDate": "2026-07-07"}
                        },
                        "summary": {"shopifyMatchedOrders": 9},
                    }
                ),
                encoding="utf-8",
            )
            previous_shopify = build_boss_report.SHOPIFY_RECON_PATH
            previous_probe = build_boss_report.BIGQUERY_PROBE_PATH
            try:
                build_boss_report.SHOPIFY_RECON_PATH = reconciliation_path
                build_boss_report.BIGQUERY_PROBE_PATH = None
                result = build_boss_report.load_shopify_reconciliation(
                    {
                        "dateRanges": {
                            "current": {"startDate": "2026-07-08", "endDate": "2026-07-14"}
                        }
                    }
                )
            finally:
                build_boss_report.SHOPIFY_RECON_PATH = previous_shopify
                build_boss_report.BIGQUERY_PROBE_PATH = previous_probe

        self.assertTrue(result["staleShopifyReconciliation"])
        self.assertNotIn("summary", result)

    def test_paid_diagnosis_does_not_claim_zero_revenue_when_revenue_exists(self) -> None:
        result = paid_channel_diagnosis(
            {
                "results": {
                    "channel_current": {
                        "rows": [
                            {
                                "sessionDefaultChannelGroup": "Paid Search",
                                "sessions": 20,
                                "totalRevenue": 200,
                            }
                        ]
                    }
                }
            }
        )

        self.assertNotIn("没有收入", result["title"])
        self.assertIn("revenue/session", result["title"])


if __name__ == "__main__":
    unittest.main()

const assert = require("node:assert/strict");
const test = require("node:test");

const {
  buildReconciliation,
  coverageSummary,
  parseCsv,
  sqlFor,
  transactionId,
} = require("../reconcile_shopify_ga4.js");

function shopifyRow(id, amount, status = "PAID", source = "web", refunded = 0) {
  return {
    order_id: `gid://shopify/Order/${id}`,
    order_name: `#${id}`,
    financial_status: status,
    source_name: source,
    currency: "USD",
    total_price: String(amount),
    original_total_price: String(amount),
    total_refunded: String(refunded),
    test: "False",
    cancelled_at: "",
  };
}

function ga4Row(eventName, id, amount, eventCount = 1) {
  return {
    event_name: eventName,
    transaction_id: id,
    amount,
    event_count: eventCount,
  };
}

function reconcile(shopifyRows, ga4Rows, availableDates = ["2026-08-01"]) {
  return buildReconciliation({
    shopifyRows,
    ga4Rows,
    startDate: "2026-08-01",
    endDate: "2026-08-01",
    timezone: "America/New_York",
    availableDates,
    generatedAt: "2026-09-01T00:00:00.000Z",
  });
}

test("offsetting anomalies expose three missing purchases and one missing refund", () => {
  const shopifyRows = [
    shopifyRow("1001", 1000),
    shopifyRow("1002", 2000),
    shopifyRow("1003", 102.38),
    shopifyRow("1004", 494.69),
    shopifyRow("1005", 161.29),
    shopifyRow("1006", 224.02, "REFUNDED", "web", 224.02),
    shopifyRow("2001", 350.28, "PAID", "shop-app"),
  ];
  const ga4Rows = [
    ga4Row("purchase", "1001", 1000),
    ga4Row("purchase", "1002", 2000),
    ga4Row("purchase", "1006", 224.02),
  ];

  const output = reconcile(shopifyRows, ga4Rows);

  assert.equal(output.shopify.current_paid_web.orders, 5);
  assert.equal(output.ga4.purchase.unique_transactions, 3);
  assert.equal(output.shopify.eligible_web_purchase_cohort.orders, 6);
  assert.equal(output.reconciliation.purchase.missing_web_transactions, 3);
  assert.equal(output.reconciliation.purchase.capture_rate, 0.5);
  assert.equal(output.reconciliation.purchase.current_paid_web_coverage_rate, 0.4);
  assert.equal(output.reconciliation.refund.missing_transactions, 1);
  assert.equal(output.reconciliation.refund.capture_rate, 0);
  assert.equal(output.reconciliation.amount_bridge.aggregate_revenue_gap, 534.34);
  assert.equal(output.reconciliation.amount_bridge.current_paid_shopify_only_revenue, 758.36);
  assert.equal(output.reconciliation.amount_bridge.ga4_not_current_paid_revenue, 224.02);
  assert.equal(output.reconciliation.amount_bridge.unexplained_revenue_gap, 0);
  assert.deepEqual(
    output.exceptions.missing_web_purchases.map((row) => row.transaction_id),
    ["1003", "1004", "1005"],
  );
  assert.deepEqual(output.exceptions.refunds_missing_in_ga4.map((row) => row.transaction_id), ["1006"]);
  assert.equal(output.shopify.eligible_offsite_purchase_cohort.orders, 1);
});

test("equal aggregate totals do not imply transaction-level parity", () => {
  const output = reconcile(
    [shopifyRow("1001", 100), shopifyRow("1002", 200)],
    [ga4Row("purchase", "1001", 100), ga4Row("purchase", "9999", 200)],
  );

  assert.equal(output.shopify.current_paid_web.orders, output.ga4.purchase.unique_transactions);
  assert.equal(output.reconciliation.amount_bridge.aggregate_revenue_gap, 0);
  assert.equal(output.reconciliation.purchase.capture_rate, 0.5);
  assert.equal(output.reconciliation.purchase.missing_web_transactions, 1);
  assert.equal(output.reconciliation.purchase.ga4_only_transactions, 1);
  assert.equal(output.reconciliation.status, "exceptions");
});

test("duplicates and blank transaction IDs are reported separately", () => {
  const output = reconcile(
    [shopifyRow("1001", 100)],
    [
      ga4Row("purchase", "1001", 200, 2),
      ga4Row("purchase", "", 20, 1),
      ga4Row("refund", "", 10, 2),
    ],
  );

  assert.deepEqual(output.ga4.purchase.duplicate_transaction_ids, ["1001"]);
  assert.equal(output.ga4.purchase.blank_transaction_id_events, 1);
  assert.equal(output.ga4.refund.blank_transaction_id_events, 2);
  assert.equal(output.reconciliation.status, "exceptions");
});

test("missing or duplicate Shopify transaction IDs suppress coverage rates", () => {
  const missingId = shopifyRow("1002", 200);
  missingId.order_id = "";
  missingId.order_name = "#missing";
  const output = reconcile(
    [shopifyRow("1001", 100), shopifyRow("1001", 100), missingId],
    [ga4Row("purchase", "1001", 100)],
  );

  assert.equal(output.shopify.current_paid_web.orders, 3);
  assert.deepEqual(output.shopify.duplicate_transaction_ids, ["1001"]);
  assert.equal(output.shopify.missing_transaction_id_orders, 1);
  assert.equal(output.reconciliation.publishable, false);
  assert.equal(output.reconciliation.purchase.capture_rate, null);
  assert.equal(output.reconciliation.purchase.current_paid_web_coverage_rate, null);
  assert.equal(output.reconciliation.status, "invalid_shopify_transaction_ids");
  assert.deepEqual(output.exceptions.shopify_orders_missing_transaction_id, [
    { order_name: "#missing", financial_status: "PAID" },
  ]);
});

test("incomplete BigQuery daily coverage suppresses coverage rates", () => {
  const output = buildReconciliation({
    shopifyRows: [shopifyRow("1001", 100)],
    ga4Rows: [ga4Row("purchase", "1001", 100)],
    startDate: "2026-08-01",
    endDate: "2026-08-02",
    availableDates: ["2026-08-01"],
    generatedAt: "2026-09-01T00:00:00.000Z",
  });

  assert.equal(output.coverage.status, "incomplete");
  assert.deepEqual(output.coverage.missing_dates, ["2026-08-02"]);
  assert.equal(output.reconciliation.publishable, false);
  assert.equal(output.reconciliation.purchase.capture_rate, null);
  assert.equal(output.reconciliation.refund.capture_rate, null);
  assert.equal(output.reconciliation.status, "incomplete_bigquery_coverage");
});

test("offsite orders are excluded from web capture failures", () => {
  const output = reconcile(
    [shopifyRow("1001", 100), shopifyRow("2001", 300, "PAID", "shop-app")],
    [ga4Row("purchase", "1001", 100), ga4Row("purchase", "2001", 300)],
  );

  assert.equal(output.reconciliation.purchase.eligible_web_transactions, 1);
  assert.equal(output.reconciliation.purchase.missing_web_transactions, 0);
  assert.equal(output.shopify.eligible_offsite_purchase_cohort.orders, 1);
  assert.equal(output.reconciliation.purchase.capture_rate, 1);
  assert.equal(output.reconciliation.purchase.ga4_matched_offsite_transactions, 1);
  assert.equal(output.reconciliation.amount_bridge.aggregate_revenue_gap, -300);
  assert.equal(output.reconciliation.amount_bridge.ga4_not_current_paid_revenue, 300);
  assert.equal(output.reconciliation.amount_bridge.unexplained_revenue_gap, 0);
});

test("helpers normalize Shopify IDs, quoted CSV, coverage, and local-currency SQL", () => {
  assert.equal(transactionId("gid://shopify/Order/123"), "123");
  assert.deepEqual(parseCsv('a,b\n"x,y","z"\n'), [{ a: "x,y", b: "z" }]);
  assert.equal(coverageSummary("2026-08-01", "2026-08-02", ["2026-08-01"]).status, "incomplete");
  const sql = sqlFor("project-1", "analytics_1", "2026-08-01", "2026-08-31");
  assert.match(sql, /ecommerce\.transaction_id/);
  assert.match(sql, /ecommerce\.purchase_revenue/);
  assert.match(sql, /ecommerce\.refund_value/);
  assert.match(sql, /_TABLE_SUFFIX BETWEEN '20260801' AND '20260831'/);
});

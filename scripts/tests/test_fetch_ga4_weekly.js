const test = require("node:test");
const assert = require("node:assert/strict");

const { mapRows, requestDefs } = require("../fetch_ga4_weekly.js");

function definitions() {
  const dateRanges = {
    current: { startDate: "2026-07-01", endDate: "2026-07-07" },
    previous: { startDate: "2026-06-24", endDate: "2026-06-30" },
  };
  return new Map(requestDefs(dateRanges).map((definition) => [definition[0], definition]));
}

test("device funnel queries preserve the date dimension", () => {
  const defs = definitions();

  for (const name of ["event_device_current", "event_device_previous"]) {
    const [, dimensions, metrics, body] = defs.get(name);
    assert.deepEqual(dimensions.map((dimension) => dimension.name), ["date", "deviceCategory", "eventName"]);
    assert.deepEqual(metrics.map((metric) => metric.name), ["eventCount"]);
    assert.equal(body.limit, 200);
    assert.deepEqual(
      body.dimensionFilter.filter.inListFilter.values,
      ["view_item", "add_to_cart", "begin_checkout", "purchase"]
    );
  }
});

test("core reports request keyEvents without the deprecated conversions alias", () => {
  const defs = definitions();
  for (const name of ["summary_current", "channel_current", "campaign_current", "landing_current"]) {
    const [, , metrics] = defs.get(name);
    const metricNames = metrics.map((metric) => metric.name);
    assert.ok(metricNames.includes("keyEvents"));
    assert.ok(!metricNames.includes("conversions"));
  }
});

test("row mapping exposes conversions as a backward-compatible keyEvents alias", () => {
  const report = {
    rows: [{ dimensionValues: [], metricValues: [{ value: "4" }] }],
  };
  const mapped = mapRows(report, [], [{ name: "keyEvents" }]);
  assert.equal(mapped[0].keyEvents, 4);
  assert.equal(mapped[0].conversions, 4);
});

test("key event contribution queries include event and revenue evidence", () => {
  const defs = definitions();
  for (const name of ["key_events_current", "key_events_previous"]) {
    const [, dimensions, metrics, body] = defs.get(name);
    assert.deepEqual(dimensions.map((dimension) => dimension.name), ["eventName", "isKeyEvent"]);
    assert.deepEqual(
      metrics.map((metric) => metric.name),
      ["eventCount", "keyEvents", "eventValue", "totalRevenue", "purchaseRevenue", "ecommercePurchases", "transactions"]
    );
    assert.equal(body.limit, 200);
  }
});

test("purchase detail queries preserve transaction and attribution dimensions", () => {
  const defs = definitions();
  for (const name of ["purchase_transactions_current", "purchase_transactions_previous"]) {
    const [, dimensions, metrics, body] = defs.get(name);
    assert.deepEqual(
      dimensions.map((dimension) => dimension.name),
      ["date", "transactionId", "deviceCategory", "sessionDefaultChannelGroup", "sessionSourceMedium"]
    );
    assert.deepEqual(
      metrics.map((metric) => metric.name),
      ["eventCount", "keyEvents", "ecommercePurchases", "transactions", "itemsPurchased", "purchaseRevenue", "totalRevenue"]
    );
    assert.equal(body.dimensionFilter.filter.fieldName, "eventName");
    assert.equal(body.dimensionFilter.filter.stringFilter.value, "purchase");
  }
});

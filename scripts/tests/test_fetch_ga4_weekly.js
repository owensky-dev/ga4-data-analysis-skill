const test = require("node:test");
const assert = require("node:assert/strict");

const { requestDefs } = require("../fetch_ga4_weekly.js");

test("device funnel queries preserve the date dimension", () => {
  const dateRanges = {
    current: { startDate: "2026-07-01", endDate: "2026-07-07" },
    previous: { startDate: "2026-06-24", endDate: "2026-06-30" },
  };
  const definitions = new Map(requestDefs(dateRanges).map((definition) => [definition[0], definition]));

  for (const name of ["event_device_current", "event_device_previous"]) {
    const [, dimensions, metrics, body] = definitions.get(name);
    assert.deepEqual(dimensions.map((dimension) => dimension.name), ["date", "deviceCategory", "eventName"]);
    assert.deepEqual(metrics.map((metric) => metric.name), ["eventCount"]);
    assert.equal(body.limit, 200);
    assert.deepEqual(
      body.dimensionFilter.filter.inListFilter.values,
      ["view_item", "add_to_cart", "begin_checkout", "purchase"]
    );
  }
});

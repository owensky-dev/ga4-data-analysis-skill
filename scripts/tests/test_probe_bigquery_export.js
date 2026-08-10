const test = require("node:test");
const assert = require("node:assert/strict");

const { classifyStatus, splitDatasetIds } = require("../probe_bigquery_export.js");

test("classifies dataset-level permission denial as needs_data_viewer", () => {
  assert.equal(classifyStatus(200, 403, null, []), "needs_data_viewer");
  assert.equal(classifyStatus(200, 200, 403, []), "needs_data_viewer");
});

test("distinguishes dataset and table readiness", () => {
  assert.equal(classifyStatus(200, 404, null, []), "waiting_for_dataset");
  assert.equal(classifyStatus(200, 200, 200, []), "waiting_for_tables");
  assert.equal(classifyStatus(200, 200, 200, ["events_20260801"]), "ready");
});

test("ignores underscore-prefixed temporary datasets", () => {
  const result = splitDatasetIds([
    { datasetReference: { datasetId: "_temporary_query_results" } },
    { datasetReference: { datasetId: "analytics_123" } },
  ]);

  assert.deepEqual(result.visibleDatasetIds, ["analytics_123"]);
  assert.deepEqual(result.ignoredTemporaryDatasetIds, ["_temporary_query_results"]);
});

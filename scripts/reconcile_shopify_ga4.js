#!/usr/bin/env node
const crypto = require("crypto");
const fs = require("fs");
const https = require("https");

function parseArgs(argv) {
  const out = {};
  for (let i = 0; i < argv.length; i += 1) {
    if (!argv[i].startsWith("--")) continue;
    const key = argv[i].slice(2);
    out[key] = argv[i + 1] && !argv[i + 1].startsWith("--") ? argv[++i] : "true";
  }
  return out;
}

function b64url(value) {
  return Buffer.from(value).toString("base64").replace(/=/g, "").replace(/\+/g, "-").replace(/\//g, "_");
}

function request(method, url, headers = {}, body = "") {
  return new Promise((resolve, reject) => {
    const target = new URL(url);
    const req = https.request(
      { method, hostname: target.hostname, path: target.pathname + target.search, headers },
      (res) => {
        let data = "";
        res.setEncoding("utf8");
        res.on("data", (chunk) => { data += chunk; });
        res.on("end", () => resolve({ status: res.statusCode, body: data }));
      },
    );
    req.setTimeout(60000, () => req.destroy(new Error("request timeout")));
    req.on("error", reject);
    if (body) req.write(body);
    req.end();
  });
}

function parseJson(response) {
  try {
    return JSON.parse(response.body || "{}");
  } catch {
    return {};
  }
}

async function withRetry(fn) {
  let lastError;
  for (let attempt = 1; attempt <= 3; attempt += 1) {
    try {
      const response = await fn();
      if (![429, 500, 502, 503, 504].includes(response.status)) return response;
      lastError = new Error(`HTTP ${response.status}`);
    } catch (error) {
      lastError = error;
    }
    if (attempt < 3) await new Promise((resolve) => setTimeout(resolve, attempt * 1000));
  }
  throw lastError;
}

async function getAccessToken(key) {
  const now = Math.floor(Date.now() / 1000);
  const payload = {
    iss: key.client_email,
    scope: "https://www.googleapis.com/auth/cloud-platform",
    aud: key.token_uri,
    exp: now + 3600,
    iat: now,
  };
  const unsigned = `${b64url(JSON.stringify({ alg: "RS256", typ: "JWT" }))}.${b64url(JSON.stringify(payload))}`;
  const signature = crypto.createSign("RSA-SHA256").update(unsigned).sign(key.private_key);
  const assertion = `${unsigned}.${b64url(signature)}`;
  const body = new URLSearchParams({
    grant_type: "urn:ietf:params:oauth:grant-type:jwt-bearer",
    assertion,
  }).toString();
  const response = await withRetry(() => request("POST", key.token_uri, {
    "Content-Type": "application/x-www-form-urlencoded",
    "Content-Length": Buffer.byteLength(body),
  }, body));
  const parsed = parseJson(response);
  if (!parsed.access_token) throw new Error(`Token request failed: HTTP ${response.status}`);
  return parsed.access_token;
}

function assertIdentifier(value, label) {
  if (!/^[A-Za-z0-9_-]+$/.test(value || "")) {
    throw new Error(`${label} contains unsupported characters`);
  }
}

function assertDate(value, label) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value || "") || Number.isNaN(Date.parse(`${value}T00:00:00Z`))) {
    throw new Error(`${label} must be YYYY-MM-DD`);
  }
}

function expectedDates(startDate, endDate) {
  assertDate(startDate, "start-date");
  assertDate(endDate, "end-date");
  const start = new Date(`${startDate}T00:00:00Z`);
  const end = new Date(`${endDate}T00:00:00Z`);
  if (start > end) throw new Error("start-date must not be after end-date");
  const dates = [];
  for (let cursor = start; cursor <= end; cursor = new Date(cursor.getTime() + 86400000)) {
    dates.push(cursor.toISOString().slice(0, 10));
  }
  return dates;
}

function parseCsv(text) {
  const rows = [];
  let row = [];
  let field = "";
  let quoted = false;
  for (let i = 0; i < text.length; i += 1) {
    const char = text[i];
    if (quoted) {
      if (char === '"' && text[i + 1] === '"') {
        field += '"';
        i += 1;
      } else if (char === '"') {
        quoted = false;
      } else {
        field += char;
      }
    } else if (char === '"') {
      quoted = true;
    } else if (char === ",") {
      row.push(field);
      field = "";
    } else if (char === "\n") {
      row.push(field.replace(/\r$/, ""));
      rows.push(row);
      row = [];
      field = "";
    } else {
      field += char;
    }
  }
  if (field || row.length) {
    row.push(field.replace(/\r$/, ""));
    rows.push(row);
  }
  const headers = rows.shift() || [];
  return rows
    .filter((values) => values.some((value) => value !== ""))
    .map((values) => Object.fromEntries(headers.map((header, index) => [header, values[index] ?? ""])));
}

function number(value) {
  const parsed = Number(value || 0);
  return Number.isFinite(parsed) ? parsed : 0;
}

function rounded(value) {
  return Math.round((number(value) + Number.EPSILON) * 100) / 100;
}

function truthy(value) {
  return ["true", "1", "yes"].includes(String(value || "").trim().toLowerCase());
}

function transactionId(value) {
  const raw = String(value || "").trim();
  const match = raw.match(/^gid:\/\/shopify\/Order\/(\d+)$/);
  return match ? match[1] : raw;
}

function sum(rows, selector) {
  return rows.reduce((total, row) => total + number(selector(row)), 0);
}

function normalizeShopifyRows(rows) {
  const purchaseStatuses = new Set(["PAID", "PARTIALLY_REFUNDED", "REFUNDED"]);
  return rows.map((row) => {
    const status = String(row.financial_status || "").trim().toUpperCase();
    const id = transactionId(row.order_id || row.transaction_id);
    const totalPrice = number(row.total_price);
    const originalTotalPrice = number(row.original_total_price || row.total_price);
    const totalRefunded = number(row.total_refunded);
    const valid = !truthy(row.test) && !String(row.cancelled_at || "").trim();
    const web = String(row.source_name || "").trim().toLowerCase() === "web";
    const purchaseEligible = valid && purchaseStatuses.has(status);
    const refundExpected = purchaseEligible && (status === "REFUNDED" || status === "PARTIALLY_REFUNDED" || totalRefunded > 0);
    return {
      transaction_id: id,
      order_name: String(row.order_name || "").trim(),
      financial_status: status,
      source_name: String(row.source_name || "").trim(),
      currency: String(row.currency || "").trim().toUpperCase(),
      total_price: totalPrice,
      original_total_price: originalTotalPrice,
      total_refunded: totalRefunded,
      valid,
      web,
      purchase_eligible: purchaseEligible,
      current_paid: valid && status === "PAID",
      refund_expected: refundExpected,
    };
  });
}

function aggregateGa4Rows(rows, eventName) {
  const map = new Map();
  let blankEvents = 0;
  for (const row of rows.filter((item) => item.event_name === eventName)) {
    const id = transactionId(row.transaction_id);
    const eventCount = number(row.event_count);
    if (!id) {
      blankEvents += eventCount;
      continue;
    }
    const current = map.get(id) || { transaction_id: id, event_count: 0, amount: 0 };
    current.event_count += eventCount;
    current.amount += number(row.amount);
    map.set(id, current);
  }
  return { map, blank_events: blankEvents };
}

function rowSummary(rows, revenueField) {
  return {
    orders: rows.length,
    revenue: rounded(sum(rows, (row) => row[revenueField])),
  };
}

function ga4Summary(group) {
  const rows = [...group.map.values()];
  return {
    unique_transactions: rows.length,
    event_count: sum(rows, (row) => row.event_count),
    revenue: rounded(sum(rows, (row) => row.amount)),
    blank_transaction_id_events: group.blank_events,
    duplicate_transaction_ids: rows.filter((row) => row.event_count > 1).map((row) => row.transaction_id).sort(),
  };
}

function coverageSummary(startDate, endDate, availableDates) {
  const expected = expectedDates(startDate, endDate);
  const available = new Set(availableDates);
  const covered = expected.filter((value) => available.has(value));
  const missing = expected.filter((value) => !available.has(value));
  return {
    status: missing.length ? "incomplete" : "complete",
    expected_daily_tables: expected.length,
    available_daily_tables: covered.length,
    missing_dates: missing,
  };
}

function buildReconciliation({ shopifyRows, ga4Rows, startDate, endDate, timezone = "UTC", availableDates, generatedAt }) {
  const shopify = normalizeShopifyRows(shopifyRows);
  const coverage = coverageSummary(startDate, endDate, availableDates);
  const validRows = shopify.filter((row) => row.valid);
  const validWithId = validRows.filter((row) => row.transaction_id);
  const webEligible = validRows.filter((row) => row.web && row.purchase_eligible);
  const offsiteEligible = validRows.filter((row) => !row.web && row.purchase_eligible);
  const currentPaidWeb = validRows.filter((row) => row.web && row.current_paid);
  const expectedRefunds = webEligible.filter((row) => row.refund_expected);
  const missingShopifyIds = webEligible.filter((row) => !row.transaction_id);
  const shopifyIds = new Map();
  const duplicateShopifyIds = [];
  for (const row of validWithId) {
    if (shopifyIds.has(row.transaction_id)) duplicateShopifyIds.push(row.transaction_id);
    else shopifyIds.set(row.transaction_id, row);
  }

  const purchases = aggregateGa4Rows(ga4Rows, "purchase");
  const refunds = aggregateGa4Rows(ga4Rows, "refund");
  const purchaseSummary = ga4Summary(purchases);
  const refundSummary = ga4Summary(refunds);
  const currentPaidIds = new Set(currentPaidWeb.map((row) => row.transaction_id).filter(Boolean));
  const offsiteEligibleIds = new Set(offsiteEligible.map((row) => row.transaction_id).filter(Boolean));
  const purchaseIds = new Set(purchases.map.keys());
  const refundIds = new Set(refunds.map.keys());

  const matchedWeb = webEligible.filter((row) => purchaseIds.has(row.transaction_id));
  const missingWeb = webEligible.filter((row) => !purchaseIds.has(row.transaction_id));
  const matchedCurrentPaid = currentPaidWeb.filter((row) => purchaseIds.has(row.transaction_id));
  const missingCurrentPaid = currentPaidWeb.filter((row) => !purchaseIds.has(row.transaction_id));
  const ga4Only = [...purchaseIds]
    .filter((id) => !shopifyIds.has(id))
    .map((id) => purchases.map.get(id));
  const ga4MatchedOffsite = [...purchaseIds]
    .filter((id) => offsiteEligibleIds.has(id))
    .map((id) => purchases.map.get(id));
  const refundMatched = expectedRefunds.filter((row) => refundIds.has(row.transaction_id));
  const refundMissing = expectedRefunds.filter((row) => !refundIds.has(row.transaction_id));

  const currentShopifyOnlyRevenue = sum(missingCurrentPaid, (row) => row.total_price);
  const ga4NotCurrentPaid = [...purchaseIds]
    .filter((id) => !currentPaidIds.has(id))
    .map((id) => purchases.map.get(id));
  const ga4NotCurrentPaidRevenue = sum(ga4NotCurrentPaid, (row) => row.amount);
  const matchedValueDelta = sum(matchedCurrentPaid, (row) => row.total_price - purchases.map.get(row.transaction_id).amount);
  const currentPaidRevenue = sum(currentPaidWeb, (row) => row.total_price);
  const ga4PurchaseRevenue = sum([...purchases.map.values()], (row) => row.amount);
  const aggregateGap = currentPaidRevenue - ga4PurchaseRevenue;
  const explainedGap = currentShopifyOnlyRevenue - ga4NotCurrentPaidRevenue + matchedValueDelta;

  const currencies = [...new Set(validRows.filter((row) => row.purchase_eligible).map((row) => row.currency).filter(Boolean))].sort();
  const shopifyIdsComplete = missingShopifyIds.length === 0 && duplicateShopifyIds.length === 0;
  const publishable = coverage.status === "complete" && currencies.length <= 1 && shopifyIdsComplete;
  const purchaseCaptureRate = publishable
    ? (webEligible.length ? matchedWeb.length / webEligible.length : (ga4Only.length ? 0 : 1))
    : null;
  const currentPaidCoverageRate = publishable
    ? (currentPaidWeb.length ? matchedCurrentPaid.length / currentPaidWeb.length : (ga4Only.length ? 0 : 1))
    : null;
  const refundCaptureRate = publishable
    ? (expectedRefunds.length ? refundMatched.length / expectedRefunds.length : 1)
    : null;
  const hasExceptions = Boolean(
    missingWeb.length || ga4Only.length || refundMissing.length || duplicateShopifyIds.length
    || purchases.blank_events || refunds.blank_events || purchaseSummary.duplicate_transaction_ids.length
    || refundSummary.duplicate_transaction_ids.length
  );
  const status = !publishable
    ? (coverage.status !== "complete"
      ? "incomplete_bigquery_coverage"
      : (currencies.length > 1 ? "currency_mismatch" : "invalid_shopify_transaction_ids"))
    : (hasExceptions ? "exceptions" : "matched");

  return {
    schema_version: "1.0",
    producer: "ga4-data-analysis/scripts/reconcile_shopify_ga4.js",
    generated_at: generatedAt || new Date().toISOString(),
    period: { start_date: startDate, end_date: endDate, timezone },
    coverage,
    currency: { status: currencies.length <= 1 ? "consistent" : "mismatch", values: currencies },
    shopify: {
      current_paid_web: rowSummary(currentPaidWeb, "total_price"),
      eligible_web_purchase_cohort: rowSummary(webEligible, "original_total_price"),
      expected_web_refunds: {
        orders: expectedRefunds.length,
        refunded_amount: rounded(sum(expectedRefunds, (row) => row.total_refunded)),
      },
      eligible_offsite_purchase_cohort: rowSummary(offsiteEligible, "original_total_price"),
      duplicate_transaction_ids: [...new Set(duplicateShopifyIds)].sort(),
      missing_transaction_id_orders: missingShopifyIds.length,
    },
    ga4: {
      purchase: purchaseSummary,
      refund: refundSummary,
    },
    reconciliation: {
      status,
      publishable,
      purchase: {
        eligible_web_transactions: webEligible.length,
        matched_web_transactions: matchedWeb.length,
        capture_rate: purchaseCaptureRate,
        missing_web_transactions: missingWeb.length,
        ga4_only_transactions: ga4Only.length,
        ga4_matched_offsite_transactions: ga4MatchedOffsite.length,
        current_paid_web_transactions: currentPaidWeb.length,
        matched_current_paid_web_transactions: matchedCurrentPaid.length,
        current_paid_web_coverage_rate: currentPaidCoverageRate,
      },
      refund: {
        expected_transactions: expectedRefunds.length,
        matched_transactions: refundMatched.length,
        capture_rate: refundCaptureRate,
        missing_transactions: refundMissing.length,
      },
      amount_bridge: {
        current_paid_web_revenue: rounded(currentPaidRevenue),
        ga4_purchase_revenue: rounded(ga4PurchaseRevenue),
        aggregate_revenue_gap: rounded(aggregateGap),
        current_paid_shopify_only_revenue: rounded(currentShopifyOnlyRevenue),
        ga4_not_current_paid_revenue: rounded(ga4NotCurrentPaidRevenue),
        matched_transaction_value_delta: rounded(matchedValueDelta),
        explained_revenue_gap: rounded(explainedGap),
        unexplained_revenue_gap: rounded(aggregateGap - explainedGap),
      },
    },
    exceptions: {
      missing_web_purchases: missingWeb.map((row) => ({
        transaction_id: row.transaction_id,
        order_name: row.order_name,
        financial_status: row.financial_status,
        original_total_price: rounded(row.original_total_price),
      })),
      ga4_only_purchases: ga4Only.map((row) => ({ transaction_id: row.transaction_id, revenue: rounded(row.amount) })),
      refunds_missing_in_ga4: refundMissing.map((row) => ({
        transaction_id: row.transaction_id,
        order_name: row.order_name,
        total_refunded: rounded(row.total_refunded),
      })),
      shopify_orders_missing_transaction_id: missingShopifyIds.map((row) => ({
        order_name: row.order_name,
        financial_status: row.financial_status,
      })),
    },
  };
}

function sqlFor(projectId, datasetId, startDate, endDate) {
  const startSuffix = startDate.replace(/-/g, "");
  const endSuffix = endDate.replace(/-/g, "");
  return `
WITH commerce_events AS (
  SELECT
    event_name,
    NULLIF(TRIM(ecommerce.transaction_id), '') AS transaction_id,
    CASE
      WHEN event_name = 'purchase' THEN COALESCE(ecommerce.purchase_revenue, 0)
      WHEN event_name = 'refund' THEN COALESCE(ecommerce.refund_value, 0)
      ELSE 0
    END AS amount
  FROM \`${projectId}.${datasetId}.events_*\`
  WHERE _TABLE_SUFFIX BETWEEN '${startSuffix}' AND '${endSuffix}'
    AND event_name IN ('purchase', 'refund')
)
SELECT
  event_name,
  transaction_id,
  COUNT(*) AS event_count,
  SUM(amount) AS amount
FROM commerce_events
GROUP BY event_name, transaction_id
ORDER BY event_name, transaction_id`;
}

function rowObjects(queryResult) {
  const fields = queryResult.schema?.fields || [];
  return (queryResult.rows || []).map((row) => Object.fromEntries(
    fields.map((field, index) => [field.name, row.f?.[index]?.v ?? null]),
  ));
}

async function datasetInfo(projectId, datasetId, token) {
  const response = await withRetry(() => request(
    "GET",
    `https://bigquery.googleapis.com/bigquery/v2/projects/${encodeURIComponent(projectId)}/datasets/${encodeURIComponent(datasetId)}`,
    { Authorization: `Bearer ${token}` },
  ));
  const body = parseJson(response);
  if (response.status !== 200) throw new Error(body.error?.message || `Dataset lookup failed: HTTP ${response.status}`);
  return body;
}

async function listDailyTableDates(projectId, datasetId, token) {
  const dates = [];
  let pageToken = "";
  do {
    const query = new URLSearchParams({ maxResults: "1000" });
    if (pageToken) query.set("pageToken", pageToken);
    const response = await withRetry(() => request(
      "GET",
      `https://bigquery.googleapis.com/bigquery/v2/projects/${encodeURIComponent(projectId)}/datasets/${encodeURIComponent(datasetId)}/tables?${query}`,
      { Authorization: `Bearer ${token}` },
    ));
    const body = parseJson(response);
    if (response.status !== 200) throw new Error(body.error?.message || `Table listing failed: HTTP ${response.status}`);
    for (const table of body.tables || []) {
      const match = String(table.tableReference?.tableId || "").match(/^events_(\d{8})$/);
      if (match) dates.push(`${match[1].slice(0, 4)}-${match[1].slice(4, 6)}-${match[1].slice(6, 8)}`);
    }
    pageToken = body.nextPageToken || "";
  } while (pageToken);
  return [...new Set(dates)].sort();
}

async function runQuery(projectId, sql, location, token) {
  const payload = JSON.stringify({ query: sql, useLegacySql: false, location, timeoutMs: 60000 });
  const response = await withRetry(() => request(
    "POST",
    `https://bigquery.googleapis.com/bigquery/v2/projects/${encodeURIComponent(projectId)}/queries`,
    {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
      "Content-Length": Buffer.byteLength(payload),
    },
    payload,
  ));
  const body = parseJson(response);
  if (response.status !== 200 || body.errors?.length || !body.jobComplete) {
    throw new Error(body.error?.message || body.errors?.[0]?.message || `BigQuery failed: HTTP ${response.status}`);
  }
  return body;
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const propertyId = args["property-id"];
  const projectId = args["project-id"];
  const datasetId = args["dataset-id"] || `analytics_${propertyId}`;
  const keyFile = args["key-file"];
  const shopifyOrdersPath = args["shopify-orders"];
  const startDate = args["start-date"];
  const endDate = args["end-date"];
  const timezone = args.timezone || "UTC";
  const outPath = args.out || "purchase_reconciliation.json";
  if (!propertyId || !projectId || !keyFile || !shopifyOrdersPath || !startDate || !endDate) {
    throw new Error("Required: --property-id, --project-id, --key-file, --shopify-orders, --start-date, --end-date");
  }
  assertIdentifier(propertyId, "property-id");
  assertIdentifier(projectId, "project-id");
  assertIdentifier(datasetId, "dataset-id");
  expectedDates(startDate, endDate);

  const key = JSON.parse(fs.readFileSync(keyFile, "utf8"));
  const shopifyRows = parseCsv(fs.readFileSync(shopifyOrdersPath, "utf8"));
  const token = await getAccessToken(key);
  const info = await datasetInfo(projectId, datasetId, token);
  const availableDates = await listDailyTableDates(projectId, datasetId, token);
  const inRange = availableDates.filter((value) => value >= startDate && value <= endDate);
  let ga4Rows = [];
  let queryMetadata = { total_rows: 0, total_bytes_processed: 0, cache_hit: false };
  if (inRange.length) {
    const result = await runQuery(projectId, sqlFor(projectId, datasetId, startDate, endDate), info.location, token);
    ga4Rows = rowObjects(result).map((row) => ({
      event_name: row.event_name,
      transaction_id: row.transaction_id,
      event_count: number(row.event_count),
      amount: number(row.amount),
    }));
    queryMetadata = {
      total_rows: number(result.totalRows),
      total_bytes_processed: number(result.totalBytesProcessed),
      cache_hit: result.cacheHit === true,
    };
  }
  const output = buildReconciliation({
    shopifyRows,
    ga4Rows,
    startDate,
    endDate,
    timezone,
    availableDates: inRange,
  });
  output.source = {
    property_id: propertyId,
    project_id: projectId,
    dataset_id: datasetId,
    dataset_location: info.location,
    shopify_orders_file: shopifyOrdersPath,
  };
  output.query = queryMetadata;
  fs.writeFileSync(outPath, `${JSON.stringify(output, null, 2)}\n`);
  process.stdout.write(`${JSON.stringify({
    out: outPath,
    period: output.period,
    coverage: output.coverage,
    status: output.reconciliation.status,
    purchase: output.reconciliation.purchase,
    refund: output.reconciliation.refund,
    amount_bridge: output.reconciliation.amount_bridge,
  }, null, 2)}\n`);
}

if (require.main === module) {
  main().catch((error) => {
    console.error(error.message);
    process.exit(1);
  });
}

module.exports = {
  buildReconciliation,
  coverageSummary,
  expectedDates,
  normalizeShopifyRows,
  parseCsv,
  sqlFor,
  transactionId,
};

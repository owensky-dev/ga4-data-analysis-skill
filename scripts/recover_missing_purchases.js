#!/usr/bin/env node

const crypto = require("crypto");
const fs = require("fs");
const https = require("https");
const path = require("path");
const { spawnSync } = require("child_process");

function parseArgs(argv) {
  const out = {};
  for (let index = 0; index < argv.length; index += 1) {
    if (!argv[index].startsWith("--")) continue;
    const key = argv[index].slice(2);
    out[key] = argv[index + 1] && !argv[index + 1].startsWith("--") ? argv[++index] : "true";
  }
  return out;
}

function number(value) {
  const parsed = Number(value ?? 0);
  return Number.isFinite(parsed) ? parsed : 0;
}

function moneyAmount(value) {
  if (value && typeof value === "object") {
    return number(value.amount ?? value.shopMoney?.amount ?? value.shop_money?.amount);
  }
  return number(value);
}

function legacyId(value) {
  const match = String(value || "").match(/(\d+)$/);
  return match ? match[1] : null;
}

function normalizeOrder(order) {
  const rawItems = order.items || order.lineItems || order.line_items || [];
  const itemNodes = rawItems.nodes || rawItems.edges?.map((edge) => edge.node) || rawItems;
  const totalPrice = moneyAmount(
    order.totalPrice ?? order.total_price ?? order.totalPriceSet ?? order.shopifyOriginalTotal,
  );
  const subtotal = moneyAmount(
    order.subtotalPrice ?? order.subtotal_price ?? order.subtotalPriceSet ?? order.shopifyOriginalTotal,
  ) || totalPrice;
  const normalized = {
    transactionId: String(order.transactionId || order.legacyResourceId || legacyId(order.id) || ""),
    processedAt: order.processedAt || order.processed_at || order.createdAt || order.created_at,
    currency: order.currency || order.currencyCode || order.currency_code || "USD",
    value: totalPrice,
    subtotal,
    tax: moneyAmount(order.tax ?? order.total_tax ?? order.totalTaxSet),
    shipping: moneyAmount(
      order.shipping ?? order.total_shipping_price ?? order.totalShippingPriceSet ?? order.totalShipping,
    ),
    items: Array.from(itemNodes || []).map((item) => ({
      itemId: item.itemId || item.sku || item.variant?.sku
        || legacyId(item.variantId || item.variant?.id)
        || legacyId(item.productId || item.product?.id),
      itemName: item.itemName || item.name || item.title || "(not set)",
      itemVariant: item.itemVariant || item.variantTitle || item.variant?.title || null,
      sku: item.sku || item.variant?.sku || null,
      variantId: String(item.variantId || legacyId(item.variant?.id) || ""),
      productId: String(item.productId || legacyId(item.product?.id) || ""),
      price: moneyAmount(item.price ?? item.originalUnitPriceSet ?? item.discountedUnitPriceSet),
      quantity: Math.max(1, number(item.quantity) || 1),
    })),
  };
  if (normalized.items.length === 1 && !(normalized.items[0].price > 0)) {
    normalized.items[0].price = normalized.subtotal / normalized.items[0].quantity;
  }
  return normalized;
}

function orderErrors(order) {
  const errors = [];
  if (!/^\d+$/.test(order.transactionId)) errors.push("missing transactionId");
  if (!order.processedAt || Number.isNaN(Date.parse(order.processedAt))) errors.push("invalid processedAt");
  if (!order.currency) errors.push("missing currency");
  if (!(order.value > 0)) errors.push("value must be positive");
  if (!order.items.length) errors.push("missing items");
  return errors;
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
    if (attempt < 3) {
      await new Promise((resolve) => setTimeout(resolve, attempt * 1000));
    }
  }
  throw lastError;
}

async function googleAccessToken(key) {
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
  const form = new URLSearchParams({
    grant_type: "urn:ietf:params:oauth:grant-type:jwt-bearer",
    assertion,
  }).toString();
  const response = await withRetry(() => request("POST", key.token_uri, {
    "Content-Type": "application/x-www-form-urlencoded",
    "Content-Length": Buffer.byteLength(form),
  }, form));
  const parsed = JSON.parse(response.body || "{}");
  if (!parsed.access_token) throw new Error(`OAuth token failed: HTTP ${response.status}`);
  return parsed.access_token;
}

function sqlString(value) {
  return `'${String(value).replace(/\\/g, "\\\\").replace(/'/g, "\\'")}'`;
}

function shiftDate(isoDate, days) {
  const date = new Date(`${isoDate}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10).replace(/-/g, "");
}

function candidateSql(projectId, datasetId, order) {
  const orderDay = new Date(order.processedAt).toISOString().slice(0, 10);
  const startSuffix = shiftDate(orderDay, -1);
  const endSuffix = shiftDate(orderDay, 1);
  return `
SELECT
  FORMAT_TIMESTAMP('%Y-%m-%dT%H:%M:%E6SZ', TIMESTAMP_MICROS(event_timestamp), 'UTC') AS event_time_utc,
  event_name,
  user_pseudo_id,
  (SELECT value.int_value FROM UNNEST(event_params) WHERE key = 'ga_session_id') AS ga_session_id,
  NULLIF(ecommerce.transaction_id, '') AS transaction_id,
  TO_JSON_STRING(ARRAY(
    SELECT AS STRUCT
      item.item_id AS itemId,
      item.item_name AS itemName,
      item.item_variant AS itemVariant,
      item.quantity AS quantity,
      item.price AS price
    FROM UNNEST(items) AS item
  )) AS items_json
FROM \`${projectId}.${datasetId}.events_*\`
WHERE REGEXP_EXTRACT(_TABLE_SUFFIX, r'(\\d{8})$') BETWEEN '${startSuffix}' AND '${endSuffix}'
  AND event_name IN ('begin_checkout', 'add_payment_info', 'purchase')
  AND TIMESTAMP_MICROS(event_timestamp) BETWEEN TIMESTAMP_SUB(TIMESTAMP(${sqlString(order.processedAt)}), INTERVAL 40 MINUTE)
                                             AND TIMESTAMP_ADD(TIMESTAMP(${sqlString(order.processedAt)}), INTERVAL 10 MINUTE)
ORDER BY event_timestamp`;
}

function rowObjects(result) {
  const fields = result.schema?.fields || [];
  return (result.rows || []).map((row) => Object.fromEntries(
    fields.map((field, index) => [field.name, row.f?.[index]?.v ?? null]),
  ));
}

async function bigQueryRows(token, projectId, sql, location) {
  const body = JSON.stringify({
    query: sql,
    useLegacySql: false,
    location,
    timeoutMs: 60000,
  });
  const response = await withRetry(() => request(
    "POST",
    `https://bigquery.googleapis.com/bigquery/v2/projects/${projectId}/queries`,
    {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
      "Content-Length": Buffer.byteLength(body),
    },
    body,
  ));
  const parsed = JSON.parse(response.body || "{}");
  if (response.status !== 200 || parsed.errors?.length || !parsed.jobComplete) {
    throw new Error(parsed.error?.message || parsed.errors?.[0]?.message || `BigQuery failed: HTTP ${response.status}`);
  }
  return rowObjects(parsed).map((row) => ({
    ...row,
    ga_session_id: row.ga_session_id == null ? null : number(row.ga_session_id),
    items: JSON.parse(row.items_json || "[]"),
  }));
}

function itemTotal(items) {
  return items.reduce(
    (total, item) => total + number(item.price) * Math.max(1, number(item.quantity) || 1),
    0,
  );
}

function identifiers(items) {
  const values = new Set();
  for (const item of items) {
    for (const value of [item.itemId, item.sku, item.variantId, item.productId]) {
      if (value) values.add(String(value).toLowerCase());
    }
  }
  return values;
}

function sessionMatches(order, beginItems) {
  if (Math.abs(itemTotal(beginItems) - order.subtotal) > 0.05) return false;
  const expected = identifiers(order.items);
  const observedText = JSON.stringify(beginItems).toLowerCase();
  if (Array.from(expected).some((value) => observedText.includes(value))) return true;
  const words = (value) => new Set(String(value || "").toLowerCase().match(/[a-z0-9]+/g) || []);
  const expectedWords = words(order.items.map((item) => item.itemName).join(" "));
  const observedWords = words(beginItems.map((item) => item.itemName).join(" "));
  const overlap = Array.from(expectedWords).filter((word) => observedWords.has(word)).length;
  return overlap >= 4 && overlap / Math.max(1, expectedWords.size) >= 0.5;
}

function selectSession(order, rows) {
  const existingPurchase = rows.find(
    (row) => row.event_name === "purchase" && String(row.transaction_id) === order.transactionId,
  );
  if (existingPurchase) return { status: "already_present", session: null };
  const grouped = new Map();
  for (const row of rows) {
    if (!row.user_pseudo_id || !row.ga_session_id) continue;
    const key = `${row.user_pseudo_id}|${row.ga_session_id}`;
    if (!grouped.has(key)) {
      grouped.set(key, {
        userPseudoId: row.user_pseudo_id,
        sessionId: row.ga_session_id,
        rows: [],
      });
    }
    grouped.get(key).rows.push(row);
  }
  const orderMs = Date.parse(order.processedAt);
  const candidates = [];
  for (const session of grouped.values()) {
    const begin = session.rows.find(
      (row) => row.event_name === "begin_checkout" && sessionMatches(order, row.items),
    );
    const payment = session.rows
      .filter((row) => row.event_name === "add_payment_info")
      .sort((a, b) => Date.parse(b.event_time_utc) - Date.parse(a.event_time_utc))[0];
    if (!begin || !payment) continue;
    const secondsFromOrder = Math.abs(orderMs - Date.parse(payment.event_time_utc)) / 1000;
    if (secondsFromOrder > 900) continue;
    candidates.push({ ...session, secondsFromOrder });
  }
  candidates.sort((a, b) => a.secondsFromOrder - b.secondsFromOrder);
  if (!candidates.length) {
    return { status: "no_unique_session", session: null, candidateCount: 0 };
  }
  if (candidates.length > 1 && candidates[1].secondsFromOrder - candidates[0].secondsFromOrder < 60) {
    return { status: "no_unique_session", session: null, candidateCount: candidates.length };
  }
  return { status: "missing_purchase", session: candidates[0], candidateCount: candidates.length };
}

function recoveryPolicy(processedAt, now = Date.now(), allowDegradedAttribution = false) {
  const ageMs = now - Date.parse(processedAt);
  const hour = 60 * 60 * 1000;
  if (!Number.isFinite(ageMs) || ageMs < 0) return { status: "invalid_order_time" };
  if (ageMs <= 24 * hour) return { status: "eligible", attribution: "session_specific" };
  if (ageMs > 70 * hour) return { status: "expired_over_70h" };
  if (!allowDegradedAttribution) {
    return { status: "degraded_attribution_requires_opt_in", attribution: "degraded_over_24h" };
  }
  return { status: "eligible_degraded_attribution", attribution: "degraded_over_24h" };
}

function purchasePayload(order, session) {
  return {
    client_id: session.userPseudoId,
    timestamp_micros: String(Date.parse(order.processedAt) * 1000),
    events: [{
      name: "purchase",
      params: {
        session_id: session.sessionId,
        engagement_time_msec: 1,
        transaction_id: order.transactionId,
        currency: order.currency,
        value: order.value,
        tax: order.tax,
        shipping: order.shipping,
        items: order.items.map((item) => ({
          item_id: item.itemId || item.sku || item.variantId || item.productId,
          item_name: item.itemName,
          ...(item.itemVariant ? { item_variant: item.itemVariant } : {}),
          price: item.price,
          quantity: item.quantity,
        })),
      },
    }],
  };
}

function loadApiSecret(service, account) {
  if (process.env.GA4_MP_API_SECRET) return process.env.GA4_MP_API_SECRET;
  const result = spawnSync(
    "security",
    ["find-generic-password", "-w", "-s", service, "-a", account],
    { encoding: "utf8" },
  );
  if (result.status !== 0 || !result.stdout.trim()) {
    throw new Error("Missing GA4 Measurement Protocol API secret in GA4_MP_API_SECRET or macOS Keychain");
  }
  return result.stdout.trim();
}

function validationPayload(payload, send) {
  return send ? payload : { ...payload, validation_behavior: "ENFORCE_RECOMMENDATIONS" };
}

async function measurementProtocolRequest(measurementId, apiSecret, payload, send, transport = request) {
  const endpoint = send ? "mp/collect" : "debug/mp/collect";
  const url = `https://www.google-analytics.com/${endpoint}?measurement_id=${encodeURIComponent(measurementId)}&api_secret=${encodeURIComponent(apiSecret)}`;
  const body = JSON.stringify(validationPayload(payload, send));
  const invoke = () => transport("POST", url, {
    "Content-Type": "application/json",
    "Content-Length": Buffer.byteLength(body),
  }, body);
  const response = send ? await invoke() : await withRetry(invoke);
  const parsed = response.body ? JSON.parse(response.body) : {};
  if (response.status < 200 || response.status >= 300) {
    throw new Error(`Measurement Protocol failed: HTTP ${response.status}`);
  }
  return { status: response.status, validationMessages: parsed.validationMessages || [] };
}

function loadLedger(ledgerPath) {
  if (!fs.existsSync(ledgerPath)) return { version: 1, transactions: {} };
  return JSON.parse(fs.readFileSync(ledgerPath, "utf8"));
}

function ledgerBlockStatus(entry) {
  const statuses = {
    pending_submission: "previous_submission_pending",
    uncertain: "previous_submission_outcome_uncertain",
    submitted: "already_submitted_by_recovery",
    verified: "already_verified_by_recovery",
  };
  return entry ? statuses[entry.status] || null : null;
}

function saveLedger(ledgerPath, ledger) {
  fs.mkdirSync(path.dirname(path.resolve(ledgerPath)), { recursive: true });
  const tempPath = `${ledgerPath}.tmp-${process.pid}`;
  fs.writeFileSync(tempPath, `${JSON.stringify(ledger, null, 2)}\n`, { mode: 0o600 });
  fs.chmodSync(tempPath, 0o600);
  fs.renameSync(tempPath, ledgerPath);
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args["check-secret-access"] === "true" || args["verify-secret"] === "true") {
    if (!args["property-id"] || !args["measurement-id"]) {
      throw new Error("Secret access check requires --property-id and --measurement-id");
    }
    const apiSecret = loadApiSecret(
      args["keychain-service"] || `codex.ga4.${args["property-id"]}.measurement-protocol`,
      args["keychain-account"] || args["measurement-id"],
    );
    const result = await measurementProtocolRequest(args["measurement-id"], apiSecret, {
      client_id: "ga4-recovery-validation.0",
      events: [{ name: "ga4_recovery_validation", params: { engagement_time_msec: 1 } }],
    }, false);
    process.stdout.write(`${JSON.stringify({
      mode: "debug_only",
      apiSecretLoaded: true,
      apiSecretValidatedByDebugEndpoint: false,
      payloadValidationMessageCount: result.validationMessages.length,
    }, null, 2)}\n`);
    return;
  }

  const required = ["orders-file", "property-id", "project-id", "key-file", "measurement-id"];
  const missing = required.filter((name) => !args[name]);
  if (missing.length) throw new Error(`Missing arguments: ${missing.join(", ")}`);

  const send = args.send === "true";
  const allowDegradedAttribution = args["allow-degraded-attribution"] === "true";
  const ledgerPath = args.ledger || "work/ga4_purchase_recovery_ledger.json";
  const ordersInput = JSON.parse(fs.readFileSync(args["orders-file"], "utf8"));
  const sourceOrders = Array.isArray(ordersInput)
    ? ordersInput
    : [...(ordersInput.orders || []), ...(ordersInput.unmatchedShopifyOrders || [])];
  const orders = sourceOrders.map(normalizeOrder);
  const key = JSON.parse(fs.readFileSync(args["key-file"], "utf8"));
  const token = await googleAccessToken(key);
  const ledger = loadLedger(ledgerPath);
  const results = [];
  let apiSecret = null;

  for (const order of orders) {
    const errors = orderErrors(order);
    if (errors.length) {
      results.push({ transactionId: order.transactionId || null, status: "invalid_order", errors });
      continue;
    }
    const priorLedgerStatus = ledgerBlockStatus(ledger.transactions[order.transactionId]);
    if (priorLedgerStatus) {
      results.push({ transactionId: order.transactionId, status: priorLedgerStatus });
      continue;
    }
    const rows = await bigQueryRows(
      token,
      args["project-id"],
      candidateSql(args["project-id"], `analytics_${args["property-id"]}`, order),
      args["bigquery-location"] || "US",
    );
    const selected = selectSession(order, rows);
    if (selected.status !== "missing_purchase") {
      results.push({
        transactionId: order.transactionId,
        status: selected.status,
        candidateCount: selected.candidateCount ?? null,
      });
      continue;
    }
    const policy = recoveryPolicy(order.processedAt, Date.now(), allowDegradedAttribution);
    if (!policy.status.startsWith("eligible")) {
      results.push({ transactionId: order.transactionId, ...policy });
      continue;
    }
    if (!apiSecret) {
      apiSecret = loadApiSecret(
        args["keychain-service"] || `codex.ga4.${args["property-id"]}.measurement-protocol`,
        args["keychain-account"] || args["measurement-id"],
      );
    }
    const payload = purchasePayload(order, selected.session);
    const validation = await measurementProtocolRequest(
      args["measurement-id"],
      apiSecret,
      payload,
      false,
    );
    if (validation.validationMessages.length) {
      results.push({
        transactionId: order.transactionId,
        status: "validation_failed",
        validationMessages: validation.validationMessages,
      });
      continue;
    }
    if (!send) {
      results.push({
        transactionId: order.transactionId,
        status: "validated_dry_run",
        attribution: policy.attribution,
        secondsFromOrder: selected.session.secondsFromOrder,
      });
      continue;
    }
    const attempt = {
      status: "pending_submission",
      attemptedAt: new Date().toISOString(),
      sourceOrderTime: order.processedAt,
      attribution: policy.attribution,
      clientIdHash: crypto
        .createHash("sha256")
        .update(selected.session.userPseudoId)
        .digest("hex")
        .slice(0, 16),
    };
    ledger.transactions[order.transactionId] = attempt;
    saveLedger(ledgerPath, ledger);
    try {
      await measurementProtocolRequest(args["measurement-id"], apiSecret, payload, true);
    } catch (error) {
      ledger.transactions[order.transactionId] = {
        ...attempt,
        status: "uncertain",
        failedAt: new Date().toISOString(),
        failure: "production_submission_outcome_unknown",
      };
      saveLedger(ledgerPath, ledger);
      throw error;
    }
    ledger.transactions[order.transactionId] = {
      ...attempt,
      status: "submitted",
      submittedAt: new Date().toISOString(),
    };
    saveLedger(ledgerPath, ledger);
    results.push({
      transactionId: order.transactionId,
      status: "submitted",
      attribution: policy.attribution,
      secondsFromOrder: selected.session.secondsFromOrder,
    });
  }

  process.stdout.write(`${JSON.stringify({
    mode: send ? "send" : "dry_run",
    orderCount: orders.length,
    results,
  }, null, 2)}\n`);
}

if (require.main === module) {
  main().catch((error) => {
    console.error(error.message);
    process.exit(1);
  });
}

module.exports = {
  normalizeOrder,
  orderErrors,
  selectSession,
  recoveryPolicy,
  purchasePayload,
  validationPayload,
  measurementProtocolRequest,
  ledgerBlockStatus,
  sessionMatches,
};

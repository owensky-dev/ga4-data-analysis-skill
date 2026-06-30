#!/usr/bin/env node
const fs = require("fs");
const https = require("https");
const crypto = require("crypto");

function parseArgs(argv) {
  const out = {};
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (!arg.startsWith("--")) continue;
    const key = arg.slice(2);
    const value = argv[i + 1] && !argv[i + 1].startsWith("--") ? argv[++i] : "true";
    out[key] = value;
  }
  return out;
}

const args = parseArgs(process.argv.slice(2));
const propertyId = args["property-id"];
const keyFile = args["key-file"];
const outPath = args.out || "ga4_weekly_diagnosis_latest.json";
const propertyTimeZone = args.timezone || "America/Juneau";

if (!propertyId || !keyFile) {
  console.error("Usage: fetch_ga4_weekly.js --property-id <id> --key-file <service-account.json> --out <output.json>");
  process.exit(2);
}

const key = JSON.parse(fs.readFileSync(keyFile, "utf8"));

function b64url(input) {
  return Buffer.from(input).toString("base64").replace(/=/g, "").replace(/\+/g, "-").replace(/\//g, "_");
}

function request(method, url, headers, body) {
  return new Promise((resolve, reject) => {
    const target = new URL(url);
    const req = https.request(
      { method, hostname: target.hostname, path: target.pathname + target.search, headers },
      (res) => {
        let data = "";
        res.setEncoding("utf8");
        res.on("data", (chunk) => {
          data += chunk;
        });
        res.on("end", () => resolve({ status: res.statusCode, body: data }));
      }
    );
    req.on("error", reject);
    if (body) req.write(body);
    req.end();
  });
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function getAccessToken() {
  const now = Math.floor(Date.now() / 1000);
  const payload = {
    iss: key.client_email,
    scope: "https://www.googleapis.com/auth/analytics.readonly",
    aud: key.token_uri,
    exp: now + 3600,
    iat: now,
  };
  const unsigned = `${b64url(JSON.stringify({ alg: "RS256", typ: "JWT" }))}.${b64url(JSON.stringify(payload))}`;
  const signature = crypto.createSign("RSA-SHA256").update(unsigned).sign(key.private_key);
  const assertion = `${unsigned}.${signature.toString("base64").replace(/=/g, "").replace(/\+/g, "-").replace(/\//g, "_")}`;
  const body = new URLSearchParams({ grant_type: "urn:ietf:params:oauth:grant-type:jwt-bearer", assertion }).toString();
  const resp = await request("POST", key.token_uri, {
    "Content-Type": "application/x-www-form-urlencoded",
    "Content-Length": Buffer.byteLength(body),
  }, body);
  const json = JSON.parse(resp.body || "{}");
  if (!json.access_token) throw new Error(`Token failed ${resp.status}: ${resp.body}`);
  return json.access_token;
}

function ymdInTz(date, timeZone) {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(date);
  const map = Object.fromEntries(parts.map((p) => [p.type, p.value]));
  return `${map.year}-${map.month}-${map.day}`;
}

function shiftYmd(ymd, days) {
  const [year, month, day] = ymd.split("-").map(Number);
  const dt = new Date(Date.UTC(year, month - 1, day));
  dt.setUTCDate(dt.getUTCDate() + days);
  return dt.toISOString().slice(0, 10);
}

function getDateRanges() {
  if (args["current-start"] && args["current-end"] && args["previous-start"] && args["previous-end"]) {
    return {
      current: { startDate: args["current-start"], endDate: args["current-end"] },
      previous: { startDate: args["previous-start"], endDate: args["previous-end"] },
      propertyToday: ymdInTz(new Date(), propertyTimeZone),
    };
  }
  const propertyToday = ymdInTz(new Date(), propertyTimeZone);
  const currentEnd = shiftYmd(propertyToday, -1);
  const currentStart = shiftYmd(currentEnd, -6);
  const previousEnd = shiftYmd(currentStart, -1);
  const previousStart = shiftYmd(previousEnd, -6);
  return {
    current: { startDate: currentStart, endDate: currentEnd },
    previous: { startDate: previousStart, endDate: previousEnd },
    propertyToday,
  };
}

function normalizeDimensionValue(name, value) {
  if (!value) return "(not set)";
  if (name === "date" && /^\d{8}$/.test(value)) return `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)}`;
  return value;
}

function metricValue(value) {
  if (value == null || value === "") return 0;
  const num = Number(value);
  return Number.isNaN(num) ? value : num;
}

function mapRows(report, dimensions, metrics) {
  return (report.rows || []).map((row) => {
    const out = {};
    dimensions.forEach((d, idx) => {
      out[d.name] = normalizeDimensionValue(d.name, row.dimensionValues?.[idx]?.value);
    });
    metrics.forEach((m, idx) => {
      out[m.name] = metricValue(row.metricValues?.[idx]?.value);
    });
    if ("sessions" in out && "conversions" in out) out.sessionConversionRateCalc = out.sessions ? out.conversions / out.sessions : 0;
    if ("sessions" in out && "totalRevenue" in out) out.revenuePerSession = out.sessions ? out.totalRevenue / out.sessions : 0;
    return out;
  });
}

async function runReport(accessToken, name, body) {
  const payload = JSON.stringify(body);
  let lastError = null;
  for (let attempt = 1; attempt <= 3; attempt += 1) {
    try {
      const resp = await request("POST", `https://analyticsdata.googleapis.com/v1beta/properties/${propertyId}:runReport`, {
        Authorization: `Bearer ${accessToken}`,
        "Content-Type": "application/json",
        "Content-Length": Buffer.byteLength(payload),
      }, payload);
      const json = JSON.parse(resp.body || "{}");
      if (resp.status < 200 || resp.status >= 300) {
        return { name, ok: false, status: resp.status, error: json.error || json, rows: [] };
      }
      return { name, ok: true, status: resp.status, rowCount: json.rowCount || 0, raw: json };
    } catch (error) {
      lastError = error;
      if (attempt < 3) await sleep(500 * attempt);
    }
  }
  return { name, ok: false, status: 0, error: { message: lastError?.message || "Unknown request error" }, rows: [] };
}

function summarize(result, dimensions, metrics) {
  if (!result.ok) return result;
  return { ...result, rows: mapRows(result.raw, dimensions, metrics) };
}

function requestDefs(dateRanges) {
  const metrics10 = ["activeUsers", "newUsers", "sessions", "screenPageViews", "engagedSessions", "engagementRate", "averageSessionDuration", "eventCount", "conversions", "totalRevenue"].map((name) => ({ name }));
  const efficiency = ["sessions", "engagementRate", "conversions", "totalRevenue"].map((name) => ({ name }));
  const landing = ["sessions", "engagementRate", "conversions", "totalRevenue", "screenPageViews"].map((name) => ({ name }));
  const item = ["itemsViewed", "itemsAddedToCart", "itemsPurchased", "itemRevenue"].map((name) => ({ name }));
  const eventCount = [{ name: "eventCount" }];
  const eventFilter = {
    filter: { fieldName: "eventName", inListFilter: { values: ["view_item", "add_to_cart", "begin_checkout", "purchase"] } },
  };
  const aiFilter = {
    orGroup: {
      expressions: ["chatgpt", "perplexity", "reddit", "youtube", "pinterest", "bing / organic", "google / organic"].map((value) => ({
        filter: { fieldName: "sessionSourceMedium", stringFilter: { matchType: "CONTAINS", value } },
      })),
    },
  };
  const build = (name, rangeName, dimensions, metrics, extra = {}) => [name, dimensions, metrics, {
    dateRanges: [dateRanges[rangeName]],
    dimensions,
    metrics,
    ...extra,
  }];
  return [
    build("summary_current", "current", [], metrics10),
    build("summary_previous", "previous", [], metrics10),
    build("daily_current", "current", [{ name: "date" }], metrics10, { orderBys: [{ dimension: { dimensionName: "date" } }], limit: 20 }),
    build("daily_previous", "previous", [{ name: "date" }], metrics10, { orderBys: [{ dimension: { dimensionName: "date" } }], limit: 20 }),
    build("channel_current", "current", [{ name: "sessionDefaultChannelGroup" }], efficiency, { orderBys: [{ metric: { metricName: "sessions" }, desc: true }], limit: 30 }),
    build("channel_previous", "previous", [{ name: "sessionDefaultChannelGroup" }], efficiency, { orderBys: [{ metric: { metricName: "sessions" }, desc: true }], limit: 30 }),
    build("source_medium_current", "current", [{ name: "sessionSourceMedium" }], efficiency, { orderBys: [{ metric: { metricName: "sessions" }, desc: true }], limit: 80 }),
    build("source_medium_previous", "previous", [{ name: "sessionSourceMedium" }], efficiency, { orderBys: [{ metric: { metricName: "sessions" }, desc: true }], limit: 80 }),
    build("campaign_current", "current", [{ name: "sessionSourceMedium" }, { name: "sessionCampaignName" }], efficiency, { orderBys: [{ metric: { metricName: "sessions" }, desc: true }], limit: 100 }),
    build("campaign_previous", "previous", [{ name: "sessionSourceMedium" }, { name: "sessionCampaignName" }], efficiency, { orderBys: [{ metric: { metricName: "sessions" }, desc: true }], limit: 100 }),
    build("landing_current", "current", [{ name: "landingPagePlusQueryString" }], landing, { orderBys: [{ metric: { metricName: "sessions" }, desc: true }], limit: 120 }),
    build("landing_channel_current", "current", [{ name: "sessionDefaultChannelGroup" }, { name: "landingPagePlusQueryString" }], landing, { orderBys: [{ metric: { metricName: "sessions" }, desc: true }], limit: 120 }),
    build("device_current", "current", [{ name: "deviceCategory" }], efficiency, { orderBys: [{ metric: { metricName: "sessions" }, desc: true }], limit: 10 }),
    build("device_previous", "previous", [{ name: "deviceCategory" }], efficiency, { orderBys: [{ metric: { metricName: "sessions" }, desc: true }], limit: 10 }),
    build("event_device_current", "current", [{ name: "deviceCategory" }, { name: "eventName" }], eventCount, { dimensionFilter: eventFilter, orderBys: [{ metric: { metricName: "eventCount" }, desc: true }], limit: 80 }),
    build("event_device_previous", "previous", [{ name: "deviceCategory" }, { name: "eventName" }], eventCount, { dimensionFilter: eventFilter, orderBys: [{ metric: { metricName: "eventCount" }, desc: true }], limit: 80 }),
    build("items_current", "current", [{ name: "itemName" }], item, { orderBys: [{ metric: { metricName: "itemsViewed" }, desc: true }], limit: 120 }),
    build("items_previous", "previous", [{ name: "itemName" }], item, { orderBys: [{ metric: { metricName: "itemsViewed" }, desc: true }], limit: 120 }),
    build("pages_current", "current", [{ name: "pagePath" }, { name: "pageTitle" }], landing, { orderBys: [{ metric: { metricName: "screenPageViews" }, desc: true }], limit: 100 }),
    build("referral_ai_current", "current", [{ name: "sessionSourceMedium" }], efficiency, { dimensionFilter: aiFilter, orderBys: [{ metric: { metricName: "sessions" }, desc: true }], limit: 50 }),
  ];
}

async function main() {
  const accessToken = await getAccessToken();
  const dateRanges = getDateRanges();
  const results = {};
  for (const [name, dimensions, metrics, body] of requestDefs(dateRanges)) {
    const result = await runReport(accessToken, name, body);
    results[name] = summarize(result, dimensions, metrics);
    await sleep(150);
  }
  const output = {
    propertyId,
    serviceAccount: key.client_email,
    propertyTimeZone,
    generatedAt: new Date().toISOString(),
    dateRanges,
    results,
  };
  fs.mkdirSync(require("path").dirname(outPath), { recursive: true });
  fs.writeFileSync(outPath, JSON.stringify(output, null, 2));
  console.log(JSON.stringify({
    ok: true,
    outPath,
    dateRanges,
    failedQueries: Object.values(results).filter((r) => !r.ok).map((r) => ({ name: r.name, status: r.status, error: r.error })),
  }, null, 2));
}

main().catch((error) => {
  console.error(error.stack || error.message);
  process.exit(1);
});

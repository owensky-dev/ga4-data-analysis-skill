#!/usr/bin/env node
const fs = require("fs");
const https = require("https");
const crypto = require("crypto");

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
    req.on("error", reject);
    if (body) req.write(body);
    req.end();
  });
}

function jsonBody(response) {
  try {
    return JSON.parse(response.body || "{}");
  } catch {
    return {};
  }
}

async function getAccessToken(key) {
  const now = Math.floor(Date.now() / 1000);
  const payload = {
    iss: key.client_email,
    scope: "https://www.googleapis.com/auth/cloud-platform https://www.googleapis.com/auth/analytics.readonly",
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
  const response = await request("POST", key.token_uri, {
    "Content-Type": "application/x-www-form-urlencoded",
    "Content-Length": Buffer.byteLength(body),
  }, body);
  const parsed = jsonBody(response);
  if (!parsed.access_token) throw new Error(`Token request failed: HTTP ${response.status}`);
  return parsed.access_token;
}

function errorMessage(parsed) {
  return parsed.error?.message || parsed.errors?.[0]?.message || null;
}

function splitDatasetIds(datasets) {
  const ids = (datasets || [])
    .map((item) => item.datasetReference?.datasetId)
    .filter(Boolean);
  return {
    visibleDatasetIds: ids.filter((id) => !id.startsWith("_")),
    ignoredTemporaryDatasetIds: ids.filter((id) => id.startsWith("_")),
  };
}

function classifyStatus(queryStatus, datasetStatus, tableStatus, tableIds) {
  if (queryStatus !== 200) return "query_permission_error";
  if (datasetStatus === 403 || tableStatus === 403) return "needs_data_viewer";
  if (datasetStatus === 200 && tableIds.length === 0) return "waiting_for_tables";
  if (datasetStatus === 200 && tableIds.length > 0) return "ready";
  return "waiting_for_dataset";
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const propertyId = args["property-id"];
  const projectId = args["project-id"];
  const keyFile = args["key-file"];
  const outPath = args.out || "ga4_bigquery_probe_latest.json";
  if (!propertyId || !projectId || !keyFile) {
    throw new Error("Required: --property-id, --project-id, --key-file");
  }

  const expectedDatasetId = `analytics_${propertyId}`;
  const key = JSON.parse(fs.readFileSync(keyFile, "utf8"));
  const token = await getAccessToken(key);
  const auth = { Authorization: `Bearer ${token}` };

  const queryBody = JSON.stringify({ query: "SELECT 1 AS ok", useLegacySql: false, location: "US" });
  const queryResponse = await request(
    "POST",
    `https://bigquery.googleapis.com/bigquery/v2/projects/${projectId}/queries`,
    { ...auth, "Content-Type": "application/json", "Content-Length": Buffer.byteLength(queryBody) },
    queryBody,
  );
  const queryJson = jsonBody(queryResponse);

  const datasetsResponse = await request(
    "GET",
    `https://bigquery.googleapis.com/bigquery/v2/projects/${projectId}/datasets?all=true`,
    auth,
  );
  const datasetsJson = jsonBody(datasetsResponse);
  const { visibleDatasetIds, ignoredTemporaryDatasetIds } = splitDatasetIds(datasetsJson.datasets);

  const datasetResponse = await request(
    "GET",
    `https://bigquery.googleapis.com/bigquery/v2/projects/${projectId}/datasets/${expectedDatasetId}`,
    auth,
  );
  const datasetJson = jsonBody(datasetResponse);

  let tablesResponse = null;
  let tablesJson = {};
  if (datasetResponse.status === 200) {
    tablesResponse = await request(
      "GET",
      `https://bigquery.googleapis.com/bigquery/v2/projects/${projectId}/datasets/${expectedDatasetId}/tables?maxResults=1000`,
      auth,
    );
    tablesJson = jsonBody(tablesResponse);
  }
  const tableIds = (tablesJson.tables || [])
    .map((item) => item.tableReference?.tableId)
    .filter(Boolean);

  const linksResponse = await request(
    "GET",
    `https://analyticsadmin.googleapis.com/v1alpha/properties/${propertyId}/bigQueryLinks`,
    auth,
  );
  const linksJson = jsonBody(linksResponse);
  const links = linksJson.bigQueryLinks || [];
  const status = classifyStatus(queryResponse.status, datasetResponse.status, tablesResponse?.status, tableIds);

  const output = {
    generatedAt: new Date().toISOString(),
    propertyId,
    projectId,
    expectedDatasetId,
    serviceAccount: key.client_email,
    status,
    jobQuery: {
      httpStatus: queryResponse.status,
      jobComplete: queryJson.jobComplete === true,
      error: errorMessage(queryJson),
    },
    adminLinks: {
      httpStatus: linksResponse.status,
      count: links.length,
      rows: links.map((link) => ({
        name: link.name,
        project: link.project,
        dataLocation: link.dataLocation,
        dailyExportEnabled: link.dailyExportEnabled,
        streamingExportEnabled: link.streamingExportEnabled,
      })),
      error: errorMessage(linksJson),
    },
    datasets: {
      httpStatus: datasetsResponse.status,
      visibleDatasetIds,
      ignoredTemporaryDatasetIds,
      error: errorMessage(datasetsJson),
    },
    expectedDataset: {
      httpStatus: datasetResponse.status,
      location: datasetJson.location || null,
      tableListHttpStatus: tablesResponse?.status || null,
      tableIds,
      error: errorMessage(datasetJson) || errorMessage(tablesJson),
    },
  };
  fs.writeFileSync(outPath, `${JSON.stringify(output, null, 2)}\n`);
  process.stdout.write(`${JSON.stringify(output, null, 2)}\n`);
}

if (require.main === module) {
  main().catch((error) => {
    console.error(error.message);
    process.exit(1);
  });
}

module.exports = { classifyStatus, splitDatasetIds };

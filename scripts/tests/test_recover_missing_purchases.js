const test = require("node:test");
const assert = require("node:assert/strict");

const {
  normalizeOrder,
  orderErrors,
  selectSession,
  recoveryPolicy,
  purchasePayload,
  validationPayload,
  measurementProtocolRequest,
  ledgerBlockStatus,
} = require("../recover_missing_purchases.js");

const rawOrder = {
  id: "gid://shopify/Order/7000000000001",
  name: "#2001",
  processedAt: "2026-08-17T01:00:00Z",
  currencyCode: "USD",
  totalPrice: 102.38,
  subtotalPrice: 102.38,
  lineItems: [{
    title: "Sink",
    quantity: 1,
    price: 102.38,
    variant: {
      id: "gid://shopify/ProductVariant/48741881118935",
      sku: "SS-BL02D-231908-2",
      title: "Matte Black",
    },
    product: { id: "gid://shopify/Product/9164903121111" },
  }],
};

test("normalizes only order analytics fields", () => {
  const order = normalizeOrder({
    ...rawOrder,
    email: "private@example.com",
    shippingAddress: { address1: "secret" },
  });
  assert.equal(order.transactionId, "7000000000001");
  assert.equal(order.items[0].variantId, "48741881118935");
  assert.equal(order.email, undefined);
  assert.equal(order.shippingAddress, undefined);
  assert.deepEqual(orderErrors(order), []);
});

test("selects a unique checkout session and detects an existing purchase", () => {
  const order = normalizeOrder(rawOrder);
  const rows = [
    {
      event_name: "begin_checkout",
      event_time_utc: "2026-08-17T00:55:00Z",
      user_pseudo_id: "123.456",
      ga_session_id: 999,
      transaction_id: null,
      items: [{
        itemId: "shopify_ZZ_9164903121111_48741881118935",
        price: 102.38,
        quantity: 1,
      }],
    },
    {
      event_name: "add_payment_info",
      event_time_utc: "2026-08-17T00:59:56Z",
      user_pseudo_id: "123.456",
      ga_session_id: 999,
      transaction_id: null,
      items: [],
    },
  ];
  const selected = selectSession(order, rows);
  assert.equal(selected.status, "missing_purchase");
  assert.equal(selected.session.sessionId, 999);
  assert.equal(selected.session.secondsFromOrder, 4);
  assert.equal(
    selectSession(order, [
      ...rows,
      { ...rows[1], event_name: "purchase", transaction_id: order.transactionId },
    ]).status,
    "already_present",
  );
});

test("refuses ambiguous sessions", () => {
  const order = normalizeOrder(rawOrder);
  const makeRows = (clientId, sessionId, seconds) => [
    {
      event_name: "begin_checkout",
      event_time_utc: "2026-08-17T00:55:00Z",
      user_pseudo_id: clientId,
      ga_session_id: sessionId,
      items: [{
        itemId: "shopify_ZZ_9164903121111_48741881118935",
        price: 102.38,
        quantity: 1,
      }],
    },
    {
      event_name: "add_payment_info",
      event_time_utc: new Date(Date.parse(order.processedAt) - seconds * 1000).toISOString(),
      user_pseudo_id: clientId,
      ga_session_id: sessionId,
      items: [],
    },
  ];
  assert.equal(
    selectSession(order, [...makeRows("a", 1, 4), ...makeRows("b", 2, 20)]).status,
    "no_unique_session",
  );
});

test("allows high-fidelity recovery for at most 24 hours", () => {
  const now = Date.parse("2026-08-17T12:00:00Z");
  assert.equal(recoveryPolicy("2026-08-16T12:00:01Z", now).status, "eligible");
  assert.equal(recoveryPolicy("2026-08-16T11:59:59Z", now).status, "degraded_attribution_requires_opt_in");
});

test("allows an explicit degraded-attribution opt-in before the 70-hour safety limit", () => {
  const now = Date.parse("2026-08-17T12:00:00Z");
  assert.equal(
    recoveryPolicy("2026-08-14T14:01:00Z", now, true).status,
    "eligible_degraded_attribution",
  );
  assert.equal(recoveryPolicy("2026-08-14T13:59:00Z", now, true).status, "expired_over_70h");
});

test("builds an ecommerce purchase tied to the matched client and session", () => {
  const order = normalizeOrder(rawOrder);
  const payload = purchasePayload(order, { userPseudoId: "123.456", sessionId: 999 });
  assert.equal(payload.client_id, "123.456");
  assert.equal(payload.events[0].params.session_id, 999);
  assert.equal(payload.events[0].params.transaction_id, "7000000000001");
  assert.equal(payload.events[0].params.items[0].item_id, "SS-BL02D-231908-2");
});

test("uses strict recommendations only for debug validation", () => {
  const payload = purchasePayload(normalizeOrder(rawOrder), {
    userPseudoId: "123.456",
    sessionId: 999,
  });
  assert.equal(validationPayload(payload, false).validation_behavior, "ENFORCE_RECOMMENDATIONS");
  assert.equal(validationPayload(payload, true).validation_behavior, undefined);
  assert.equal(payload.validation_behavior, undefined);
});

test("attempts a production submission only once when the outcome is uncertain", async () => {
  let attempts = 0;
  const transport = async () => {
    attempts += 1;
    return { status: 503, body: "" };
  };
  await assert.rejects(
    measurementProtocolRequest("G-TEST", "secret", { client_id: "1.2", events: [] }, true, transport),
    /HTTP 503/,
  );
  assert.equal(attempts, 1);
});

test("blocks a retry after any possibly submitted production attempt", () => {
  assert.equal(ledgerBlockStatus({ status: "pending_submission" }), "previous_submission_pending");
  assert.equal(ledgerBlockStatus({ status: "uncertain" }), "previous_submission_outcome_uncertain");
  assert.equal(ledgerBlockStatus({ status: "submitted" }), "already_submitted_by_recovery");
  assert.equal(ledgerBlockStatus({ status: "verified" }), "already_verified_by_recovery");
  assert.equal(ledgerBlockStatus(null), null);
});

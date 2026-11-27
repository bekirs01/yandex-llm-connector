import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";

import {
  applyFeedbackResult,
  customerLocale,
  developerModeEnabled,
  exchangeIdentity,
  findExchangeMessage,
  normalizeLocale,
  packConversation,
  questionTreeExchangeHref,
  questionTreeRootHref,
  readFeedbackPayload,
  restoreConversation,
} from "../web/chat.js";

const CONVERSATION = "22222222-2222-4222-8222-222222222222";
const REQUEST = "11111111-1111-4111-8111-111111111111";
const OTHER = "33333333-3333-4333-8333-333333333333";

test("a stored Turkish preference cannot select the customer locale", () => {
  assert.equal(customerLocale("tr"), "ru");
  assert.equal(customerLocale("ru"), "ru");
  assert.equal(normalizeLocale("tr"), "ru");
  assert.equal(normalizeLocale("en"), "ru");
  const source = readFileSync(new URL("../web/chat.js", import.meta.url), "utf8");
  assert.equal(source.includes("locales/tr.json"), false);
  assert.equal(source.includes('getItem(LOCALE_STORAGE_KEY)'), false);
  const html = readFileSync(new URL("../web/index.html", import.meta.url), "utf8");
  assert.equal(html.includes('data-locale="tr"'), false);
  assert.equal(html.includes("Турецкий"), false);
  assert.equal(html.includes("headlamp.jpg"), true);
  assert.equal(html.includes("glass-metal-ornament.png"), false);
});

test("feedback attaches only to the exchange identity", () => {
  const history = [
    { role: "user", text: "один и тот же текст" },
    {
      role: "assistant",
      text: "ответ",
      exchange: { conversationId: CONVERSATION, requestId: REQUEST },
    },
    { role: "user", text: "ещё" },
    { role: "assistant", text: "ответ", exchange: null },
  ];
  const found = findExchangeMessage(history, CONVERSATION, REQUEST);
  assert.equal(found, history[1]);
  assert.equal(findExchangeMessage(history, CONVERSATION, OTHER), null);
  assert.equal(findExchangeMessage(history, OTHER, REQUEST), null);
  assert.equal(exchangeIdentity({ conversationId: "not-an-id", requestId: REQUEST }), null);
});

test("a late response does not move a rating onto another answer", () => {
  const entry = {
    conversationId: CONVERSATION,
    requestId: REQUEST,
    token: 2,
    revision: 2,
    confirmed: { stars: 5, resolved: null },
    draft: { stars: 5, resolved: null },
    status: "saving",
  };
  const stale = applyFeedbackResult(entry, {
    conversationId: CONVERSATION,
    requestId: REQUEST,
    token: 1,
    ok: true,
    applied: true,
    feedback: { stars: 1, resolved: false },
    revision: 1,
  });
  assert.equal(stale.appliedToEntry, false);
  assert.equal(stale.entry.draft.stars, 5);

  const other = applyFeedbackResult(entry, {
    conversationId: OTHER,
    requestId: REQUEST,
    token: 2,
    ok: true,
    applied: true,
    feedback: { stars: 2, resolved: true },
    revision: 2,
  });
  assert.equal(other.appliedToEntry, false);
  assert.equal(entry.confirmed.stars, 5);
});

test("a failed save does not become saved", () => {
  const entry = {
    conversationId: CONVERSATION,
    requestId: REQUEST,
    token: 4,
    confirmed: { stars: 2, resolved: null },
    draft: { stars: 4, resolved: false },
    status: "saving",
  };
  const failed = applyFeedbackResult(entry, {
    conversationId: CONVERSATION,
    requestId: REQUEST,
    token: 4,
    ok: false,
  });
  assert.equal(failed.entry.status, "error");
  assert.equal(failed.entry.draft.stars, 2);
  assert.equal(failed.entry.draft.resolved, null);
});

test("unrated feedback is absent and Нет stays false", () => {
  const unrated = readFeedbackPayload({
    conversation_id: CONVERSATION,
    request_id: REQUEST,
    revision: 0,
  });
  assert.equal(unrated.feedback, null);
  const answered = readFeedbackPayload({
    conversation_id: CONVERSATION,
    request_id: REQUEST,
    revision: 3,
    feedback: { stars: null, resolved: false },
  });
  assert.deepEqual(answered.feedback, { stars: null, resolved: false });
});

test("question tree links encode one exchange and the root stays bare", () => {
  assert.equal(questionTreeRootHref(), "/team/question-tree.html");
  assert.equal(
    questionTreeExchangeHref(CONVERSATION, REQUEST),
    `/team/question-tree.html?conversation_id=${CONVERSATION}&request_id=${REQUEST}`,
  );
  assert.equal(questionTreeExchangeHref("nope", REQUEST), null);
  assert.equal(developerModeEnabled("?developer=1"), true);
  assert.equal(developerModeEnabled(""), false);
});

test("reload keeps the original message text and only a verified identity", () => {
  const text = "  исходный текст клиента  ";
  const packed = packConversation(CONVERSATION, [
    { role: "user", text },
    {
      role: "assistant",
      text: "готовый ответ",
      exchange: { conversationId: CONVERSATION, requestId: REQUEST },
      feedback: { confirmed: { stars: 5, resolved: true }, status: "saved" },
    },
  ]);
  assert.equal(packed.history[0].text, text);
  assert.equal(packed.history[1].feedback, undefined);
  const restored = restoreConversation(JSON.stringify(packed));
  assert.equal(restored.history[0].text, text);
  assert.equal(restored.history[1].text, "готовый ответ");
  assert.deepEqual(restored.history[1].exchange, {
    conversationId: CONVERSATION,
    requestId: REQUEST,
  });
  assert.equal(restored.history[1].feedback.confirmed, null);
});

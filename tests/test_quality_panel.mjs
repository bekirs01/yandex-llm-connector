import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";

import { notifyOpenPanels, PANEL_EVENT_CHANNEL } from "../web/chat.js";
import {
  exchangeElementSelector,
  qualitySignal,
  readExchangeLink,
  PANEL_EVENT_CHANNEL as TREE_CHANNEL,
} from "../web/team/question-tree.js";

const CONVERSATION = "22222222-2222-4222-8222-222222222222";
const REQUEST = "11111111-1111-4111-8111-111111111111";
const OTHER = "33333333-3333-4333-8333-333333333333";

test("quality signals stay separate from an automatic approval", () => {
  assert.equal(qualitySignal({ stars: 5, resolved: true }), "positive");
  assert.equal(qualitySignal({ stars: 4, resolved: true }), "positive");
  assert.equal(qualitySignal({ stars: 2, resolved: null }), "examine");
  assert.equal(qualitySignal({ stars: null, resolved: false }), "examine");
  assert.equal(qualitySignal({ stars: 5, resolved: false }), "conflict");
  assert.equal(qualitySignal({ stars: 1, resolved: true }), "conflict");
  assert.equal(qualitySignal({ stars: 3, resolved: true }), "other");
  assert.equal(qualitySignal({ stars: 5, resolved: null }), "other");
  assert.equal(qualitySignal(null), null);
});

test("a deep link and the exchange selector use both ids", () => {
  assert.equal(readExchangeLink(""), null);
  assert.deepEqual(readExchangeLink(`?conversation_id=${CONVERSATION}&request_id=${REQUEST}`), {
    conversationId: CONVERSATION,
    requestId: REQUEST,
  });
  assert.deepEqual(readExchangeLink(`?conversation_id=${CONVERSATION}`), { error: "invalid" });
  const selector = exchangeElementSelector(CONVERSATION, REQUEST);
  assert.equal(selector.includes(CONVERSATION), true);
  assert.equal(selector.includes(REQUEST), true);
  assert.equal(exchangeElementSelector(CONVERSATION, OTHER).includes(REQUEST), false);
  assert.equal(exchangeElementSelector("not-an-id", REQUEST), "");
});

test("panel updates are event driven and the chat notification cannot throw", () => {
  assert.equal(PANEL_EVENT_CHANNEL, TREE_CHANNEL);
  assert.equal(notifyOpenPanels("nope", CONVERSATION, REQUEST), undefined);
  assert.equal(notifyOpenPanels("feedback", CONVERSATION, REQUEST), undefined);
  const source = readFileSync(new URL("../web/team/question-tree.js", import.meta.url), "utf8");
  assert.equal(source.includes("setInterval"), false);
  assert.equal(source.includes('`[data-request-id="'), false);
  assert.equal(source.includes("data-conversation-id"), true);
  assert.equal(source.includes("Качество ответов"), true);
  assert.equal(source.includes("Такой обмен не найден."), true);
  const chat = readFileSync(new URL("../web/chat.js", import.meta.url), "utf8");
  assert.equal(chat.includes("locales/tr.json"), false);
});

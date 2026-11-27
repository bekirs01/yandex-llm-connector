import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  LIMITS,
  appendAssistantContent,
  assistantHistoryMessage,
  codePointLength,
  formatStructuredJson,
  interpretChatPayload,
  normalizeDraft,
  offersNewConversation,
  presentedErrorCode,
  trimBoundaries,
  validateOutgoing,
} from "../web/chat.js";

const WHITE_SPACE = [
  0x0009, 0x000a, 0x000b, 0x000c, 0x000d, 0x0020, 0x0085, 0x00a0, 0x1680,
  0x2000, 0x2001, 0x2002, 0x2003, 0x2004, 0x2005, 0x2006, 0x2007, 0x2008,
  0x2009, 0x200a, 0x2028, 0x2029, 0x202f, 0x205f, 0x3000,
];

test("boundary trim removes Unicode White_Space and U+FEFF only at the edges", () => {
  for (const codePoint of WHITE_SPACE) {
    const char = String.fromCodePoint(codePoint);
    assert.equal(trimBoundaries(`${char}a${char}`), "a", `U+${codePoint.toString(16)}`);
  }
  assert.equal(trimBoundaries("\uFEFFhello\uFEFF"), "hello");
  assert.equal(trimBoundaries("\uFEFF\n hello \u3000"), "hello");
  assert.equal(trimBoundaries("hello \n world"), "hello \n world");
  assert.equal(trimBoundaries("a\uFEFFb"), "a\uFEFFb");
  assert.equal(trimBoundaries("\u001Chello"), "\u001Chello");
  assert.equal(trimBoundaries("\u001Dhello\u001E"), "\u001Dhello\u001E");
  assert.equal(trimBoundaries("\u001F"), "\u001F");
  assert.equal(trimBoundaries("\u200Bhello\u200B"), "\u200Bhello\u200B");
  assert.equal(trimBoundaries("\u180Ehello"), "\u180Ehello");
  assert.equal(trimBoundaries("\u2060hello"), "\u2060hello");
});

test("the same normalized draft is used for length and submission", () => {
  const raw = " \uFEFFhello \n world\u00A0";
  const normalized = normalizeDraft(raw);
  const result = validateOutgoing([], raw);
  assert.equal(normalized.text, "hello \n world");
  assert.equal(normalized.length, codePointLength("hello \n world"));
  assert.equal(normalized.blank, false);
  assert.equal(normalized.over, false);
  assert.equal(result.ok, true);
  assert.equal(result.text, normalized.text);
  assert.equal(result.messages[0].text, normalized.text);
  assert.equal(codePointLength(result.text), normalized.length);
});

test("boundary-only drafts are empty, including a draft longer than the limit", () => {
  assert.equal(validateOutgoing([], " \n\uFEFF\u3000 ").code, "EMPTY");
  assert.equal(validateOutgoing([], " ".repeat(5000)).code, "EMPTY");
  assert.equal(normalizeDraft(" \uFEFF ").length, 0);
  assert.equal(normalizeDraft(" \uFEFF ").blank, true);
});

test("a too-long draft is rejected without truncation", () => {
  const draft = `x${"я".repeat(LIMITS.maxMessageCodePoints)}`;
  const result = validateOutgoing([], ` \uFEFF${draft}\uFEFF `);
  assert.equal(result.ok, false);
  assert.equal(result.code, "MESSAGE_TOO_LONG");
  assert.equal(result.messages, undefined);
  assert.equal(normalizeDraft(` \uFEFF${draft}\uFEFF `).text, draft);
});

test("a stored message over 4000 code points is CONTEXT_LIMIT and is not truncated", () => {
  const reply = "я".repeat(LIMITS.maxMessageCodePoints + 1);
  const history = [
    { role: "user", text: "вопрос" },
    { role: "assistant", text: reply },
  ];
  const draft = "  ещё вопрос  ";
  const result = validateOutgoing(history, draft);
  assert.equal(result.ok, false);
  assert.equal(result.code, "CONTEXT_LIMIT");
  assert.equal(result.code === "MESSAGE_TOO_LONG", false);
  assert.equal(history[1].text, reply);
  assert.equal(history[1].text.length, reply.length);
  assert.equal(draft, "  ещё вопрос  ");
  assert.equal(offersNewConversation("CONTEXT_LIMIT"), true);
});

test("an exactly 4000-code-point stored reply can still be sent", () => {
  const reply = "я".repeat(LIMITS.maxMessageCodePoints);
  const history = [
    { role: "user", text: "вопрос" },
    { role: "assistant", text: reply },
  ];
  const result = validateOutgoing(history, "ещё");
  assert.equal(result.ok, true);
  assert.equal(result.messages[1].text, reply);
  assert.equal(result.messages[2].text, "ещё");
});

test("a valid draft is not blamed when only history is over the per-message limit", () => {
  const history = [
    { role: "user", text: "a" },
    { role: "assistant", text: "b".repeat(4001) },
  ];
  const result = validateOutgoing(history, "c".repeat(4000));
  assert.equal(result.code, "CONTEXT_LIMIT");
});

test("an invalid draft is reported before a long stored reply", () => {
  const history = [
    { role: "user", text: "a" },
    { role: "assistant", text: "b".repeat(4001) },
  ];
  const result = validateOutgoing(history, "c".repeat(4001));
  assert.equal(result.code, "MESSAGE_TOO_LONG");
});

test("code points, not UTF-16 units, decide the draft limit", () => {
  const emoji = "👍".repeat(LIMITS.maxMessageCodePoints);
  assert.equal(emoji.length, LIMITS.maxMessageCodePoints * 2);
  assert.equal(codePointLength(emoji), LIMITS.maxMessageCodePoints);
  assert.equal(validateOutgoing([], emoji).ok, true);
  assert.equal(validateOutgoing([], `${emoji}👍`).code, "MESSAGE_TOO_LONG");
});

test("history objects stay intact while outgoing text is boundary-normalized", () => {
  assert.equal(validateOutgoing([{ role: "user", text: " \uFEFF " }], "ещё").code, "INVALID_REQUEST");
  assert.equal(validateOutgoing([{ role: "user", text: " ".repeat(5000) }], "ещё").code, "INVALID_REQUEST");
  const spaced = "hello ";
  const history = [
    { role: "user", text: spaced },
    { role: "assistant", text: "  ответ \n " },
  ];
  const result = validateOutgoing(history, "ещё");
  assert.equal(result.ok, true);
  assert.equal(result.messages[0].text, "hello");
  assert.equal(result.messages[1].text, "ответ");
  assert.notEqual(result.messages[0], history[0]);
  assert.equal(history[0].text, spaced);
  assert.equal(history[1].text, "  ответ \n ");
});

test("boundary-only excess on a stored reply is trimmed before the limit check", () => {
  const reply = `${"я".repeat(LIMITS.maxMessageCodePoints)}\uFEFF`;
  const history = [
    { role: "user", text: " \uFEFFвопрос\u00A0" },
    { role: "assistant", text: reply },
  ];
  const result = validateOutgoing(history, " \uFEFFещё\uFEFF ");
  assert.equal(result.ok, true);
  assert.equal(result.messages[0].text, "вопрос");
  assert.equal(result.messages[1].text, "я".repeat(LIMITS.maxMessageCodePoints));
  assert.equal(result.messages[2].text, "ещё");
  assert.equal(history[1].text, reply);
});

test("internal whitespace survives normalization", () => {
  const history = [
    { role: "user", text: "hello \n world" },
    { role: "assistant", text: "a  b" },
  ];
  const result = validateOutgoing(history, "ещё");
  assert.equal(result.ok, true);
  assert.equal(result.messages[0].text, "hello \n world");
  assert.equal(result.messages[1].text, "a  b");
});

test("a provider MESSAGE_TOO_LONG for a long stored reply is presented as CONTEXT_LIMIT", () => {
  const history = [
    { role: "user", text: "a" },
    { role: "assistant", text: ` ${"b".repeat(4001)} ` },
  ];
  assert.equal(presentedErrorCode("MESSAGE_TOO_LONG", history, "короткий"), "CONTEXT_LIMIT");
  assert.equal(presentedErrorCode("MESSAGE_TOO_LONG", history, "c".repeat(4001)), "MESSAGE_TOO_LONG");
  assert.equal(presentedErrorCode("PROVIDER_UNAVAILABLE", history, "короткий"), "PROVIDER_UNAVAILABLE");
  assert.equal(history[1].text.startsWith(" "), true);
});

function chatPayload(messageText, structured) {
  return {
    request_id: "request-1",
    conversation_id: "conversation-1",
    message: { role: "assistant", text: messageText },
    model: "local-preview",
    metrics: { elapsed_ms: 4, input_tokens: null, output_tokens: null, total_tokens: null },
    ...(structured === undefined ? {} : { structured }),
  };
}

function interpret(payload) {
  return interpretChatPayload(payload, "request-1", "conversation-1");
}

function stubDocument() {
  function createElement(tagName) {
    const node = {
      tagName: String(tagName).toUpperCase(),
      className: "",
      textContent: "",
      children: [],
      append(...kids) {
        node.children.push(...kids);
      },
    };
    Object.defineProperty(node, "innerHTML", {
      configurable: true,
      set() {
        throw new Error("HTML insertion is not allowed");
      },
    });
    return node;
  }
  return { createElement };
}

test("a reply without structured data keeps the natural message text and no developer panel", () => {
  const text = "Здравствуйте! Напишите марку, модель и год автомобиля.";
  const absent = interpret(chatPayload(text));
  assert.equal(absent.ok, true);
  assert.equal(absent.text, text);
  assert.equal(absent.structured, null);
  assert.equal(absent.model, "local-preview");
  assert.equal(absent.metrics.elapsed_ms, 4);

  const explicitNull = interpret(chatPayload(text, null));
  assert.equal(explicitNull.ok, true);
  assert.equal(explicitNull.text, text);
  assert.equal(explicitNull.structured, null);

  const parent = stubDocument().createElement("article");
  appendAssistantContent(parent, stubDocument(), text, null, "Данные разработчика");
  assert.equal(parent.children.length, 1);
  assert.equal(parent.children[0].tagName, "P");
  assert.equal(parent.children[0].className, "bubble");
  assert.equal(parent.children[0].textContent, text);
});

test("structured slots and evidence are copied beside the natural message text", () => {
  const text = "Записал: Skoda Octavia 2018 года.";
  const slots = { vehicle: "Skoda Octavia, 2018" };
  const evidence = [{ slot: "vehicle", raw_text: "Skoda Octavia 2018" }];
  const result = interpret(chatPayload(text, {
    extra: true,
    slots_after_message: slots,
    evidence,
  }));
  assert.equal(result.ok, true);
  assert.equal(result.text, text);
  assert.equal(result.text.includes("slots_after_message"), false);
  assert.deepEqual(result.structured, {
    slots_after_message: { vehicle: "Skoda Octavia, 2018" },
    evidence: [{ slot: "vehicle", raw_text: "Skoda Octavia 2018" }],
  });
  assert.equal(Object.prototype.hasOwnProperty.call(result.structured, "extra"), false);
  slots.vehicle = "changed";
  evidence[0].raw_text = "changed";
  assert.equal(result.structured.slots_after_message.vehicle, "Skoda Octavia, 2018");
  assert.equal(result.structured.evidence[0].raw_text, "Skoda Octavia 2018");
});

test("unusable structured data does not replace or reject the natural reply", () => {
  const text = "Здравствуйте! Опишите автомобиль.";
  const samples = [
    [],
    "slots",
    { slots_after_message: [], evidence: [] },
    { slots_after_message: {}, evidence: "none" },
    { evidence: [] },
  ];
  for (const structured of samples) {
    const result = interpret(chatPayload(text, structured));
    assert.equal(result.ok, true);
    assert.equal(result.text, text);
    assert.equal(result.structured, null);
  }

  const circular = { slots_after_message: { note: "ok" }, evidence: [] };
  circular.evidence.push(circular);
  const copied = interpret(chatPayload("Текст ответа", circular));
  assert.equal(copied.ok, true);
  assert.equal(copied.text, "Текст ответа");
  assert.equal(copied.structured, null);
});

test("whitespace-only model text is still an empty response when structured data is present", () => {
  const result = interpret(chatPayload(" \n\uFEFF ", {
    slots_after_message: {},
    evidence: [],
  }));
  assert.equal(result.ok, false);
  assert.equal(result.code, "EMPTY_RESPONSE");
});

test("provider errors stay errors when structured data is also present", () => {
  const result = interpret({
    request_id: "request-1",
    conversation_id: "conversation-1",
    error: { code: "PROVIDER_UNAVAILABLE", message: "down" },
    message: { role: "assistant", text: "Этот текст не показывается." },
    structured: { slots_after_message: {}, evidence: [] },
  });
  assert.equal(result.ok, false);
  assert.equal(result.code, "PROVIDER_UNAVAILABLE");
  assert.equal(result.diagnostic, "down");
  assert.equal(Object.prototype.hasOwnProperty.call(result, "structured"), false);
});

test("model content is rendered as text in the bubble and a collapsed developer panel", () => {
  const structured = {
    slots_after_message: { complaint: "запотевают стёкла" },
    evidence: [{ raw_text: "<img src=x onerror=alert(1)>" }],
  };
  const text = "<script>alert(1)</script> Здравствуйте";
  const doc = stubDocument();
  const parent = doc.createElement("article");
  appendAssistantContent(parent, doc, text, structured, "Данные разработчика");

  const bubble = parent.children[0];
  const details = parent.children[1];
  assert.equal(parent.children.length, 2);
  assert.equal(bubble.textContent, text);
  assert.equal(details.tagName, "DETAILS");
  assert.equal(details.className, "structured-details");
  assert.notEqual(details.open, true);
  assert.equal(details.children[0].tagName, "SUMMARY");
  assert.equal(details.children[0].className, "structured-summary");
  assert.equal(details.children[0].textContent, "Данные разработчика");
  assert.equal(details.children[1].tagName, "PRE");
  assert.equal(details.children[1].className, "structured-json mono");
  assert.equal(details.children[1].textContent, formatStructuredJson(structured));
  assert.equal(details.children[1].textContent.includes("<img src=x onerror=alert(1)>"), true);
  assert.equal(formatStructuredJson(structured).startsWith("{\n  \"slots_after_message\""), true);
});

test("history keeps structured data off the outgoing provider transcript", () => {
  const structured = {
    slots_after_message: { city: "Екатеринбург" },
    evidence: [],
  };
  const stored = assistantHistoryMessage("Понял, Екатеринбург.", structured);
  assert.equal(stored.role, "assistant");
  assert.equal(stored.text, "Понял, Екатеринбург.");
  assert.deepEqual(stored.structured, structured);
  structured.slots_after_message.city = "Москва";
  assert.equal(stored.structured.slots_after_message.city, "Екатеринбург");

  const plain = assistantHistoryMessage("Только текст", null);
  assert.deepEqual(plain, { role: "assistant", text: "Только текст" });
  assert.equal(Object.prototype.hasOwnProperty.call(plain, "structured"), false);

  const history = [
    { role: "user", text: "Я в Екатеринбурге" },
    stored,
  ];
  const result = validateOutgoing(history, "ещё");
  assert.equal(result.ok, true);
  assert.deepEqual(result.messages[1], {
    role: "assistant",
    text: "Понял, Екатеринбург.",
  });
  assert.equal(history[1].text, "Понял, Екатеринбург.");
  assert.equal(history[1].structured.slots_after_message.city, "Екатеринбург");
});

test("locale files label the collapsed structured developer panel", () => {
  const ru = JSON.parse(readFileSync(new URL("../web/locales/ru.json", import.meta.url), "utf8"));
  const tr = JSON.parse(readFileSync(new URL("../web/locales/tr.json", import.meta.url), "utf8"));
  assert.equal(ru.structuredDetails, "Данные разработчика");
  assert.equal(typeof tr.structuredDetails, "string");
  assert.equal(tr.structuredDetails.length > 0, true);
  assert.notEqual(tr.structuredDetails, ru.structuredDetails);
});

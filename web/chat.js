// Chat workspace. This module does not import the motion effects.

export const LOCALE_STORAGE_KEY = "yandex-llm-connector.ui-locale";
export const CHAT_STORAGE_KEY = "yandex-llm-connector.chat";

export const LIMITS = {
  maxMessages: 41,
  maxMessageCodePoints: 4000,
  maxContextCodePoints: 24000,
};

// Boundary trim is Unicode White_Space plus U+FEFF.
// It is not String.prototype.trim and not Python str.strip:
// U+001C–U+001F stay, and U+FEFF is removed from the ends.
const BOUNDARY_WHITESPACE = /^[\p{White_Space}\uFEFF]$/u;

export function trimBoundaries(value) {
  const text = String(value);
  const chars = Array.from(text);
  let from = 0;
  let to = chars.length;
  while (from < to && BOUNDARY_WHITESPACE.test(chars[from])) from += 1;
  while (to > from && BOUNDARY_WHITESPACE.test(chars[to - 1])) to -= 1;
  if (from === 0 && to === chars.length) return text;
  return chars.slice(from, to).join("");
}

export function normalizeDraft(value) {
  if (typeof value !== "string") {
    return { text: "", length: 0, blank: true, over: false };
  }
  const text = trimBoundaries(value);
  const length = codePointLength(text);
  return {
    text,
    length,
    blank: text === "",
    over: length > LIMITS.maxMessageCodePoints,
  };
}

const NEW_CONVERSATION_CODES = new Set([
  "MESSAGE_COUNT",
  "CONTEXT_SIZE",
  "CONTEXT_LIMIT",
]);

const dictionaries = new Map();

const state = {
  locale: "ru",
  strings: null,
  conversationId: "",
  history: [],
  draft: "",
  pending: null,
  showTyping: false,
  slowStatus: false,
  sending: false,
  error: null,
  health: null,
  exchange: emptyExchange(),
};

let requestSerial = 0;
let healthSerial = 0;
let abortController = null;
let slowTimer = null;
let revealTimer = null;

export const PRESENTATION = {
  revealAfterMs: 1500,
  slowAfterMs: 6000,
};

export function revealDelayMs(elapsedMs, minimumMs = PRESENTATION.revealAfterMs) {
  const elapsed = typeof elapsedMs === "number" && Number.isFinite(elapsedMs) ? Math.max(0, elapsedMs) : 0;
  const minimum = typeof minimumMs === "number" && Number.isFinite(minimumMs) ? minimumMs : 0;
  return Math.max(0, minimum - elapsed);
}

function nowMs() {
  return globalThis.performance && typeof performance.now === "function" ? performance.now() : Date.now();
}

function clearPresentationTimers() {
  if (slowTimer !== null) {
    clearTimeout(slowTimer);
    slowTimer = null;
  }
  if (revealTimer !== null) {
    clearTimeout(revealTimer);
    revealTimer = null;
  }
}

function hideTyping() {
  clearPresentationTimers();
  state.showTyping = false;
  state.slowStatus = false;
}

export function normalizeLocale(_value) {
  return "ru";
}

export function customerLocale(_stored) {
  return "ru";
}

export function codePointLength(value) {
  return Array.from(String(value)).length;
}

export function formatMetric(value) {
  return typeof value === "number" && Number.isFinite(value) ? String(value) : null;
}

export function offersNewConversation(code) {
  return NEW_CONVERSATION_CODES.has(code);
}

export function presentedErrorCode(code, history, draft) {
  if (code !== "MESSAGE_TOO_LONG") return code;
  const current = normalizeDraft(typeof draft === "string" ? draft : "");
  if (current.over) return code;
  if (!Array.isArray(history)) return code;
  for (const message of history) {
    if (!message || typeof message.text !== "string") continue;
    if (codePointLength(trimBoundaries(message.text)) > LIMITS.maxMessageCodePoints) {
      return "CONTEXT_LIMIT";
    }
  }
  return code;
}

export function createId() {
  if (globalThis.crypto && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

export function validateOutgoing(history, text) {
  if (typeof text !== "string") {
    return { ok: false, code: "EMPTY" };
  }
  const draft = normalizeDraft(text);
  if (draft.blank) {
    return { ok: false, code: "EMPTY" };
  }
  if (draft.over) {
    return { ok: false, code: "MESSAGE_TOO_LONG" };
  }
  if (!Array.isArray(history)) {
    return { ok: false, code: "INVALID_REQUEST" };
  }

  const messages = [];
  let total = 0;
  for (let index = 0; index < history.length; index += 1) {
    const message = history[index];
    const expectedRole = index % 2 === 0 ? "user" : "assistant";
    if (
      !message
      || message.role !== expectedRole
      || typeof message.text !== "string"
    ) {
      return { ok: false, code: "INVALID_REQUEST" };
    }
    const normalizedText = trimBoundaries(message.text);
    if (normalizedText === "") {
      return { ok: false, code: "INVALID_REQUEST" };
    }
    const storedLength = codePointLength(normalizedText);
    if (storedLength > LIMITS.maxMessageCodePoints) {
      return { ok: false, code: "CONTEXT_LIMIT" };
    }
    total += storedLength;
    messages.push({ role: message.role, text: normalizedText });
  }
  total += draft.length;
  messages.push({ role: "user", text: draft.text });

  if (messages[0].role !== "user" || messages[messages.length - 1].role !== "user") {
    return { ok: false, code: "INVALID_REQUEST" };
  }
  for (let index = 1; index < messages.length; index += 1) {
    if (messages[index].role === messages[index - 1].role) {
      return { ok: false, code: "INVALID_REQUEST" };
    }
  }
  if (messages.length > LIMITS.maxMessages) {
    return { ok: false, code: "MESSAGE_COUNT" };
  }
  if (total > LIMITS.maxContextCodePoints) {
    return { ok: false, code: "CONTEXT_SIZE" };
  }
  return { ok: true, text: draft.text, messages };
}

export function buildChatRequest(requestId, conversationId, messages, credentials) {
  return {
    ...(credentials ? { credentials } : {}),
    request_id: requestId,
    conversation_id: conversationId,
    messages: messages.map((message) => ({
      role: message.role,
      text: message.text,
    })),
  };
}

function isDataRecord(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

// Optional top-level structured data is a developer record.
// Absent, null, or unusable values leave the natural message.text unchanged.
export function readOptionalStructured(value) {
  if (value == null) return null;
  if (!isDataRecord(value)) return null;
  if (!isDataRecord(value.slots_after_message) || !Array.isArray(value.evidence)) return null;
  let structured;
  try {
    structured = JSON.parse(JSON.stringify({
      slots_after_message: value.slots_after_message,
      evidence: value.evidence,
    }));
  } catch {
    return null;
  }
  if (
    !isDataRecord(structured)
    || !isDataRecord(structured.slots_after_message)
    || !Array.isArray(structured.evidence)
  ) {
    return null;
  }
  return structured;
}

export function formatStructuredJson(structured) {
  return JSON.stringify({
    slots_after_message: structured.slots_after_message,
    evidence: structured.evidence,
  }, null, 2);
}

export function assistantHistoryMessage(text, structured) {
  const message = { role: "assistant", text };
  if (structured) {
    message.structured = JSON.parse(JSON.stringify({
      slots_after_message: structured.slots_after_message,
      evidence: structured.evidence,
    }));
  }
  return message;
}

export function appendAssistantContent(parent, documentRef, text, structured, detailsLabel) {
  const bubble = documentRef.createElement("p");
  bubble.className = "bubble";
  bubble.textContent = text;
  parent.append(bubble);
  if (!structured) return parent;
  const details = documentRef.createElement("details");
  details.className = "structured-details";
  const summary = documentRef.createElement("summary");
  summary.className = "structured-summary";
  summary.textContent = detailsLabel;
  const pre = documentRef.createElement("pre");
  pre.className = "structured-json mono";
  pre.textContent = formatStructuredJson(structured);
  details.append(summary, pre);
  parent.append(details);
  return parent;
}

export function interpretHealth(payload, httpOk) {
  if (!httpOk || !payload || typeof payload !== "object") {
    return { available: false };
  }
  if (payload.status !== "ok") return { available: false };
  if (typeof payload.provider !== "string" || payload.provider.length === 0) {
    return { available: false };
  }
  if (typeof payload.configured !== "boolean") return { available: false };
  if (!(typeof payload.model === "string" || payload.model === null)) {
    return { available: false };
  }
  return {
    available: true,
    status: payload.status,
    provider: payload.provider,
    configured: payload.configured,
    model: payload.model,
  };
}

export function interpretChatPayload(payload, requestId, conversationId) {
  if (!payload || typeof payload !== "object") {
    return { ok: false, code: "UNKNOWN", diagnostic: "" };
  }

  const requestMismatch = payload.request_id != null && payload.request_id !== requestId;
  const conversationMismatch = payload.conversation_id != null && payload.conversation_id !== conversationId;

  if (payload.error) {
    const error = payload.error;
    const code = error && typeof error === "object" && typeof error.code === "string" && error.code
      ? error.code
      : "UNKNOWN";
    const diagnostic = error && typeof error === "object" && typeof error.message === "string"
      ? error.message
      : "";
    if (requestMismatch || conversationMismatch) {
      return { ok: false, ignore: true, code, diagnostic };
    }
    return { ok: false, code, diagnostic };
  }

  if (payload.request_id !== requestId || payload.conversation_id !== conversationId) {
    return { ok: false, ignore: true, code: "UNKNOWN", diagnostic: "" };
  }

  const message = payload.message;
  if (
    !message
    || typeof message !== "object"
    || message.role !== "assistant"
    || typeof message.text !== "string"
  ) {
    return { ok: false, code: "UNKNOWN", diagnostic: "" };
  }
  if (trimBoundaries(message.text) === "") {
    return { ok: false, code: "EMPTY_RESPONSE", diagnostic: "" };
  }

  const metrics = payload.metrics && typeof payload.metrics === "object" ? payload.metrics : {};
  return {
    ok: true,
    text: message.text,
    structured: readOptionalStructured(payload.structured),
    model: typeof payload.model === "string" ? payload.model : null,
    metrics: {
      elapsed_ms: metrics.elapsed_ms ?? null,
      input_tokens: metrics.input_tokens ?? null,
      output_tokens: metrics.output_tokens ?? null,
      total_tokens: metrics.total_tokens ?? null,
    },
  };
}

export const EXCHANGE_UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

export function canonicalUuid(value) {
  if (typeof value !== "string") return "";
  const text = value.trim().toLowerCase();
  return EXCHANGE_UUID.test(text) ? text : "";
}

export function exchangeIdentity(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const conversationId = canonicalUuid(value.conversationId ?? value.conversation_id);
  const requestId = canonicalUuid(value.requestId ?? value.request_id);
  if (!conversationId || !requestId) return null;
  return { conversationId, requestId };
}

export const PANEL_EVENT_CHANNEL = "autoservice-panel-events";

export function notifyOpenPanels(kind, conversationId, requestId) {
  if (kind !== "exchange" && kind !== "feedback" && kind !== "quality") return;
  try {
    if (typeof BroadcastChannel !== "function") return;
    const channel = new BroadcastChannel(PANEL_EVENT_CHANNEL);
    channel.postMessage({ kind, conversationId, requestId });
    channel.close();
  } catch {
    // The chat stays available when another tab cannot be notified.
  }
}

export function questionTreeRootHref() {
  return "/team/question-tree.html";
}

export function questionTreeExchangeHref(conversationId, requestId) {
  const identity = exchangeIdentity({ conversationId, requestId });
  if (!identity) return null;
  return `/team/question-tree.html?conversation_id=${encodeURIComponent(identity.conversationId)}&request_id=${encodeURIComponent(identity.requestId)}`;
}

export function developerModeEnabled(search) {
  const query = typeof search === "string" ? search.replace(/^\?/, "") : "";
  const params = new URLSearchParams(query);
  return params.get("developer") === "1" || params.get("dev") === "1";
}

export function parseFeedbackFields(value) {
  if (value == null) return { ok: true, feedback: null };
  if (typeof value !== "object" || Array.isArray(value)) return { ok: false };
  const stars = Object.prototype.hasOwnProperty.call(value, "stars") ? value.stars : null;
  const resolved = Object.prototype.hasOwnProperty.call(value, "resolved") ? value.resolved : null;
  if (!(stars === null || (Number.isInteger(stars) && stars >= 1 && stars <= 5))) return { ok: false };
  if (!(resolved === null || resolved === true || resolved === false)) return { ok: false };
  if (stars === null && resolved === null) return { ok: true, feedback: null };
  return { ok: true, feedback: { stars, resolved } };
}

export function readFeedbackPayload(payload) {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) return null;
  const identity = exchangeIdentity({
    conversationId: payload.conversation_id,
    requestId: payload.request_id,
  });
  if (!identity) return null;
  const revision = payload.revision;
  if (!Number.isInteger(revision) || revision < 0) return null;
  let feedback = null;
  if (Object.prototype.hasOwnProperty.call(payload, "feedback")) {
    const parsed = parseFeedbackFields(payload.feedback);
    if (!parsed.ok) return null;
    feedback = parsed.feedback;
  }
  return {
    conversationId: identity.conversationId,
    requestId: identity.requestId,
    revision,
    feedback,
    applied: payload.applied === true,
  };
}

export function emptyFeedbackState() {
  return {
    confirmed: null,
    draft: null,
    revision: 0,
    token: 0,
    status: "idle",
  };
}

export function shownFeedback(feedback) {
  if (!feedback || typeof feedback !== "object") return null;
  if (feedback.status === "saving") return feedback.draft || null;
  return feedback.confirmed || null;
}

export function applyFeedbackResult(entry, result) {
  if (!entry || !result) return { entry, appliedToEntry: false };
  const entryIdentity = exchangeIdentity(entry);
  const resultIdentity = exchangeIdentity(result);
  if (!entryIdentity || !resultIdentity) return { entry, appliedToEntry: false };
  if (
    entryIdentity.conversationId !== resultIdentity.conversationId
    || entryIdentity.requestId !== resultIdentity.requestId
    || result.token !== entry.token
  ) {
    return { entry, appliedToEntry: false };
  }
  if (!result.ok) {
    return {
      appliedToEntry: true,
      entry: {
        ...entry,
        draft: entry.confirmed ?? null,
        status: "error",
      },
    };
  }
  if (result.applied !== true) {
    return {
      appliedToEntry: true,
      entry: {
        ...entry,
        confirmed: result.feedback ?? null,
        draft: result.feedback ?? null,
        revision: result.revision,
        status: "idle",
      },
    };
  }
  return {
    appliedToEntry: true,
    entry: {
      ...entry,
      confirmed: result.feedback ?? null,
      draft: result.feedback ?? null,
      revision: result.revision,
      status: "saved",
    },
  };
}

export function findExchangeMessage(history, conversationId, requestId) {
  const identity = exchangeIdentity({ conversationId, requestId });
  if (!identity || !Array.isArray(history)) return null;
  let found = null;
  for (const message of history) {
    if (!message || message.role !== "assistant") continue;
    const messageIdentity = exchangeIdentity(message.exchange);
    if (!messageIdentity) continue;
    if (
      messageIdentity.conversationId !== identity.conversationId
      || messageIdentity.requestId !== identity.requestId
    ) {
      continue;
    }
    if (found) return null;
    found = message;
  }
  return found;
}

export function packConversation(conversationId, history) {
  const id = canonicalUuid(conversationId);
  if (!id || !Array.isArray(history)) return null;
  const packed = [];
  for (const message of history) {
    if (!message || (message.role !== "user" && message.role !== "assistant")) return null;
    if (typeof message.text !== "string") return null;
    const item = { role: message.role, text: message.text };
    if (message.role === "assistant") {
      const structured = readOptionalStructured(message.structured);
      if (structured) item.structured = structured;
      const identity = exchangeIdentity(message.exchange);
      if (identity && identity.conversationId === id) item.exchange = identity;
    }
    packed.push(item);
  }
  return { version: 1, conversationId: id, history: packed };
}

export function restoreConversation(raw) {
  let parsed = raw;
  if (typeof raw === "string") {
    try {
      parsed = JSON.parse(raw);
    } catch {
      return null;
    }
  }
  if (!parsed || parsed.version !== 1) return null;
  const conversationId = canonicalUuid(parsed.conversationId);
  if (!conversationId || !Array.isArray(parsed.history) || parsed.history.length % 2 !== 0) return null;
  const history = [];
  for (let index = 0; index < parsed.history.length; index += 1) {
    const message = parsed.history[index];
    const expected = index % 2 === 0 ? "user" : "assistant";
    if (!message || message.role !== expected || typeof message.text !== "string" || message.text === "") {
      return null;
    }
    const item = { role: message.role, text: message.text };
    if (message.role === "assistant") {
      const structured = readOptionalStructured(message.structured);
      if (structured) item.structured = structured;
      const identity = exchangeIdentity(message.exchange);
      if (identity && identity.conversationId === conversationId) item.exchange = identity;
      item.feedback = emptyFeedbackState();
    }
    history.push(item);
  }
  return { conversationId, history };
}

function emptyExchange() {
  return {
    requestId: "",
    conversationId: "",
    model: null,
    metrics: null,
    errorCode: "",
    diagnostic: "",
  };
}

function init() {
  const draft = document.getElementById("draft");
  const thread = document.getElementById("thread");
  const empty = document.getElementById("empty");
  const starters = document.getElementById("starters");
  const form = document.getElementById("composer");
  const sendButton = document.getElementById("send");
  const retryButton = document.getElementById("retry");
  const errorBox = document.getElementById("error");
  const errorText = document.getElementById("error-text");
  const errorNew = document.getElementById("error-new");
  const counter = document.getElementById("counter");
  const newConversationButton = document.getElementById("new-conversation");
  const developerMode = developerModeEnabled(typeof location !== "undefined" ? location.search : "");
  let feedbackFocus = null;

  const textBindings = [
    ["brand-title", "brandTitle"],
    ["brand-subtitle", "brandSubtitle"],
    ["rail-title", "railTitle"],
    ["rail-lead", "railLead"],
    ["replies-note", "repliesNote"],
    ["new-conversation", "newConversation"],
    ["settings-open", "settingsTitle"],
    ["conversation-open", "conversationTitle"],
    ["settings-title", "settingsTitle"],
    ["conversation-title", "conversationTitle"],
    ["settings-close", "close"],
    ["conversation-close", "close"],
    ["log-label", "logLabel"],
    ["empty-kicker", "emptyKicker"],
    ["empty-title", "emptyTitle"],
    ["empty-lead", "emptyLead"],
    ["starter-label", "starterLabel"],
    ["composer-label", "composerLabel"],
    ["composer-hint", "composerHint"],
    ["retry", "retry"],
    ["error-close", "close"],
    ["credentials-type-label", "credentialsType"],
    ["credentials-token-label", "credentialsToken"],
    ["credentials-folder-label", "credentialsFolder"],
    ["credentials-note", "credentialsNote"],
    ["error-new", "offerNew"],
    ["dev-note", "devNote"],
    ["label-health-status", "healthStatus"],
    ["label-health-provider", "healthProvider"],
    ["label-health-configured", "healthConfigured"],
    ["label-health-model", "healthModel"],
    ["label-conversation-id", "conversationId"],
    ["label-request-id", "requestId"],
    ["label-response-model", "responseModel"],
    ["label-elapsed", "elapsed"],
    ["label-input-tokens", "inputTokens"],
    ["label-output-tokens", "outputTokens"],
    ["label-total-tokens", "totalTokens"],
    ["label-last-error", "lastError"],
    ["label-diagnostic", "diagnostic"],
    ["question-tree-link", "questionTree"],
    ["show-in-tree", "showInTree"],
  ];

  function fitComposer() {
    draft.style.height = "auto";
    const next = Math.min(Math.max(draft.scrollHeight, 44), 160);
    draft.style.height = `${next}px`;
  }

  function syncDraft() {
    if (draft.value !== state.draft) draft.value = state.draft;
    fitComposer();
  }

  function translateError(code) {
    const errors = state.strings && state.strings.errors;
    if (errors && Object.prototype.hasOwnProperty.call(errors, code) && typeof errors[code] === "string") {
      return errors[code];
    }
    return errors && typeof errors.UNKNOWN === "string" ? errors.UNKNOWN : "";
  }

  function metricText(value) {
    const formatted = formatMetric(value);
    return formatted === null ? state.strings.unavailable : formatted;
  }

  function setText(id, value) {
    const node = document.getElementById(id);
    if (!node) return;
    const slot = node.querySelector("[data-text]");
    if (slot) {
      slot.textContent = value;
      if (node.tagName === "BUTTON") node.setAttribute("aria-label", value);
      return;
    }
    node.textContent = value;
  }

  const starterIcons = [
    '<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" focusable="false"><path d="M14.7 6.3a4.2 4.2 0 0 0-5.8 5.8L4 17l3 3 4.9-4.9a4.2 4.2 0 0 0 5.8-5.8L15 12l-3-3 2.7-2.7Z" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"></path></svg>',
    '<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" focusable="false"><path d="M8 4.5h6.5L19 9v10.5H8V4.5Z" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"></path><path d="M14.5 4.5V9H19M10.5 13h5M10.5 16h5" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"></path></svg>',
    '<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" focusable="false"><circle cx="12" cy="12" r="7.2" fill="none" stroke="currentColor" stroke-width="1.6"></circle><path d="M9.6 9.4a2.4 2.4 0 1 1 3.5 2.1c-.7.4-1.1.9-1.1 1.7V14" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"></path><circle cx="12" cy="16.6" r="0.8" fill="currentColor"></circle></svg>',
  ];
  const starterChevron = '<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true" focusable="false"><path d="M9 6.5 15 12l-6 5.5" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"></path></svg>';

  function renderStarters() {
    starters.replaceChildren();
    const items = state.strings && Array.isArray(state.strings.starters) ? state.strings.starters : [];
    items.forEach((text, index) => {
      if (typeof text !== "string") return;
      const item = document.createElement("li");
      const button = document.createElement("button");
      button.type = "button";
      button.className = "starter";
      button.disabled = state.sending;
      const icon = document.createElement("span");
      icon.className = "starter-icon";
      icon.innerHTML = starterIcons[index % starterIcons.length];
      const label = document.createElement("span");
      label.className = "starter-copy";
      label.textContent = text;
      const chevron = document.createElement("span");
      chevron.className = "starter-chevron";
      chevron.innerHTML = starterChevron;
      button.append(icon, label, chevron);
      item.append(button);
      starters.append(item);
    });
  }

  function structuredDetailsLabel() {
    return typeof state.strings.structuredDetails === "string"
      ? state.strings.structuredDetails
      : "Developer data";
  }

  function stringOr(key, fallback) {
    return state.strings && typeof state.strings[key] === "string" ? state.strings[key] : fallback;
  }

  function renderMessage(role, text, pending, structured, item) {
    const article = document.createElement("article");
    article.className = `message message-${role}`;
    if (pending) article.classList.add("is-pending");
    if (role === "assistant") article.lang = "ru";
    const who = document.createElement("span");
    who.className = "who";
    who.textContent = role === "user" ? state.strings.you : state.strings.assistant;
    article.append(who);
    if (role === "assistant" && !pending) {
      appendAssistantContent(article, document, text, structured || null, structuredDetailsLabel());
      appendFeedback(article, item);
      appendTreeLink(article, item);
      return article;
    }
    const bubble = document.createElement("p");
    bubble.className = "bubble";
    bubble.textContent = text;
    if (role === "user") bubble.dir = "auto";
    article.append(bubble);
    return article;
  }

  function appendFeedback(article, item) {
    const identity = item ? exchangeIdentity(item.exchange) : null;
    if (!identity || !item.feedback) return;
    const shown = shownFeedback(item.feedback);
    const box = document.createElement("div");
    box.className = "feedback";
    box.dataset.conversationId = identity.conversationId;
    box.dataset.requestId = identity.requestId;
    const labelId = `feedback-label-${identity.requestId}`;
    const resolvedId = `feedback-resolved-${identity.requestId}`;
    const label = document.createElement("p");
    label.className = "feedback-label";
    label.id = labelId;
    label.textContent = stringOr("feedbackLegend", "Оцените ответ");
    const group = document.createElement("div");
    group.className = "feedback-stars";
    group.setAttribute("role", "radiogroup");
    group.setAttribute("aria-labelledby", labelId);
    const selected = shown && Number.isInteger(shown.stars) ? shown.stars : 0;
    for (let value = 1; value <= 5; value += 1) {
      const star = document.createElement("button");
      star.type = "button";
      star.className = value <= selected ? "star is-filled" : "star";
      star.dataset.star = String(value);
      star.dataset.focusKey = `star-${identity.requestId}-${value}`;
      star.setAttribute("role", "radio");
      star.setAttribute("aria-checked", value === selected ? "true" : "false");
      star.setAttribute("aria-label", stringOr("feedbackStar", "{n} из 5").replace("{n}", String(value)));
      star.textContent = "★";
      group.append(star);
    }
    const resolvedRow = document.createElement("div");
    resolvedRow.className = "feedback-resolved";
    const resolvedLabel = document.createElement("span");
    resolvedLabel.id = resolvedId;
    resolvedLabel.textContent = stringOr("feedbackResolved", "Вопрос решён?");
    const choices = document.createElement("div");
    choices.className = "feedback-choices";
    choices.setAttribute("role", "group");
    choices.setAttribute("aria-labelledby", resolvedId);
    for (const choice of [
      ["yes", true, stringOr("feedbackYes", "Да")],
      ["no", false, stringOr("feedbackNo", "Нет")],
    ]) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "resolved-choice";
      button.dataset.resolved = choice[0];
      button.dataset.focusKey = `resolved-${identity.requestId}-${choice[0]}`;
      button.textContent = choice[2];
      button.setAttribute("aria-pressed", shown && shown.resolved === choice[1] ? "true" : "false");
      choices.append(button);
    }
    resolvedRow.append(resolvedLabel, choices);
    const status = document.createElement("p");
    status.className = "feedback-status";
    status.setAttribute("role", "status");
    status.textContent = feedbackStatusText(item.feedback);
    if (item.feedback.status === "saving") box.setAttribute("aria-busy", "true");
    box.append(label, group, resolvedRow, status);
    article.append(box);
  }

  function feedbackStatusText(feedback) {
    if (!feedback) return "";
    if (feedback.status === "saving") return stringOr("feedbackSaving", "Сохранение…");
    if (feedback.status === "saved") return stringOr("feedbackSaved", "Сохранено");
    if (feedback.status === "error") return stringOr("feedbackError", "Не удалось сохранить оценку. Диалог продолжается.");
    if (feedback.status === "load-error") return stringOr("feedbackUnavailable", "Оценка сейчас недоступна.");
    return "";
  }

  function appendTreeLink(article, item) {
    if (!developerMode) return;
    const identity = item ? exchangeIdentity(item.exchange) : null;
    if (!identity) return;
    const href = questionTreeExchangeHref(identity.conversationId, identity.requestId);
    if (!href) return;
    const link = document.createElement("a");
    link.className = "exchange-tree-link";
    link.href = href;
    link.textContent = stringOr("showInTree", "Показать в дереве");
    article.append(link);
  }

  function renderTyping() {
    const line = document.createElement("div");
    line.className = "typing-dots";
    const slowText = state.slowStatus ? state.strings.slowStatus : "";
    if (slowText) line.classList.add("has-slow");
    line.setAttribute("role", "status");
    line.setAttribute("aria-live", "polite");
    const row = document.createElement("span");
    row.className = "typing-dots-row";
    row.setAttribute("aria-hidden", "true");
    for (let index = 0; index < 3; index += 1) {
      const dot = document.createElement("span");
      dot.className = "typing-dot";
      row.append(dot);
    }
    if (slowText) {
      const note = document.createElement("p");
      note.className = "typing-slow";
      note.textContent = slowText;
      line.append(row, note);
      return line;
    }
    const status = document.createElement("span");
    status.className = "sr-only";
    status.textContent = state.strings.pendingStatus || "Идёт ответ";
    line.append(status, row);
    return line;
  }

  function renderMessages(options = {}) {
    const stick = options.stick === true;
    const nearBottom = thread.scrollHeight - thread.scrollTop - thread.clientHeight < 80;
    const previous = thread.scrollTop;
    for (const node of thread.querySelectorAll(".message, .typing-line, .typing-dots")) node.remove();
    const visible = state.history.length > 0 || Boolean(state.pending);
    empty.hidden = visible;
    if (!state.strings) return;
    for (const item of state.history) {
      thread.append(renderMessage(item.role, item.text, false, item.structured || null, item));
    }
    if (state.pending) {
      thread.append(renderMessage("user", state.pending.text, false));
      if (state.showTyping) thread.append(renderTyping());
    }
    if (stick || nearBottom) thread.scrollTop = thread.scrollHeight;
    else thread.scrollTop = previous;
    if (feedbackFocus) {
      const key = feedbackFocus;
      feedbackFocus = null;
      const node = thread.querySelector(`[data-focus-key="${CSS.escape(key)}"]`);
      if (node) node.focus();
    }
  }

  function renderError() {
    if (!state.error || !state.strings) {
      errorBox.hidden = true;
      retryButton.hidden = false;
      return;
    }
    errorText.textContent = translateError(state.error.code);
    const offer = offersNewConversation(state.error.code);
    errorNew.hidden = !offer;
    retryButton.hidden = offer;
    errorBox.hidden = false;
  }

  function renderCounter() {
    if (!state.strings) return;
    const count = normalizeDraft(state.draft).length;
    counter.textContent = state.strings.counter
      .replace("{count}", String(count))
      .replace("{max}", String(LIMITS.maxMessageCodePoints));
    counter.classList.toggle("is-over", count > LIMITS.maxMessageCodePoints);
    counter.setAttribute(
      "aria-label",
      `${state.strings.counterLabel}: ${count} / ${LIMITS.maxMessageCodePoints}`,
    );
    draft.setAttribute("aria-invalid", count > LIMITS.maxMessageCodePoints ? "true" : "false");
  }

  function renderComposer() {
    const draftState = normalizeDraft(state.draft);
    const historyBlocked = Boolean(state.error && offersNewConversation(state.error.code));
    draft.disabled = state.sending;
    sendButton.disabled = state.sending || draftState.blank || draftState.over || historyBlocked;
    retryButton.disabled = state.sending || draftState.blank || draftState.over || historyBlocked;
    sendButton.classList.toggle("is-busy", state.sending);
    sendButton.setAttribute("aria-busy", state.sending ? "true" : "false");
    if (state.strings) {
      const label = state.sending ? state.strings.sending : state.strings.send;
      sendButton.setAttribute("aria-label", label);
      const sendLabel = document.getElementById("send-label");
      if (sendLabel) sendLabel.textContent = label;
    }
  }

  function renderDev() {
    if (!state.strings) return;
    const strings = state.strings;
    setText("dev-conversation-id", state.conversationId);
    if (!state.health) {
      setText("dev-health-status", strings.healthLoading);
      setText("dev-health-provider", strings.unavailable);
      setText("dev-health-configured", strings.configuredUnknown);
      setText("dev-health-model", strings.unavailable);
    } else if (!state.health.available) {
      setText("dev-health-status", strings.healthUnavailable);
      setText("dev-health-provider", strings.unavailable);
      setText("dev-health-configured", strings.configuredUnknown);
      setText("dev-health-model", strings.unavailable);
    } else {
      setText("dev-health-status", state.health.status);
      setText("dev-health-provider", state.health.provider);
      setText(
        "dev-health-configured",
        state.health.configured ? strings.configuredYes : strings.configuredNo,
      );
      setText("dev-health-model", state.health.model ? state.health.model : strings.unavailable);
    }

    const exchange = state.exchange;
    setText("dev-request-id", exchange.requestId || strings.none);
    setText("dev-response-model", exchange.model ? exchange.model : strings.unavailable);
    const metrics = exchange.metrics;
    setText("dev-elapsed", metrics ? metricText(metrics.elapsed_ms) : strings.unavailable);
    setText("dev-input-tokens", metrics ? metricText(metrics.input_tokens) : strings.unavailable);
    setText("dev-output-tokens", metrics ? metricText(metrics.output_tokens) : strings.unavailable);
    setText("dev-total-tokens", metrics ? metricText(metrics.total_tokens) : strings.unavailable);
    setText("dev-last-error", exchange.errorCode || strings.none);
    setText("dev-diagnostic", exchange.diagnostic || strings.none);
    const rootLink = document.getElementById("question-tree-link");
    if (rootLink) rootLink.href = questionTreeRootHref();
    const showLink = document.getElementById("show-in-tree");
    if (showLink) {
      const href = exchange.errorCode
        ? null
        : questionTreeExchangeHref(exchange.conversationId, exchange.requestId);
      if (href) {
        showLink.href = href;
        showLink.hidden = false;
      } else {
        showLink.hidden = true;
        showLink.removeAttribute("href");
      }
    }
  }

  function applyStrings() {
    if (!state.strings) return;
    const strings = state.strings;
    document.documentElement.lang = "ru";
    document.title = strings.documentTitle;
    for (const [id, key] of textBindings) setText(id, strings[key]);
    draft.placeholder = strings.composerPlaceholder;
    renderStarters();
    renderMessages();
    renderError();
    renderCounter();
    renderComposer();
    renderDev();
    syncDraft();
  }

  function stillCurrent(serial, requestId, conversationId) {
    return serial === requestSerial
      && state.conversationId === conversationId
      && Boolean(state.pending)
      && state.pending.serial === serial
      && state.pending.requestId === requestId
      && state.pending.conversationId === conversationId;
  }

  function failTurn(serial, requestId, conversationId, code, diagnostic) {
    if (!stillCurrent(serial, requestId, conversationId)) return;
    const text = state.pending.text;
    hideTyping();
    state.pending = null;
    state.sending = false;
    state.error = { code: presentedErrorCode(code, state.history, text) };
    state.draft = text;
    state.exchange = {
      requestId,
      conversationId: "",
      model: null,
      metrics: null,
      errorCode: code,
      diagnostic: typeof diagnostic === "string" ? diagnostic : "",
    };
    abortController = null;
    draft.value = text;
    fitComposer();
    renderMessages({ stick: true });
    renderError();
    renderStarters();
    renderCounter();
    renderComposer();
    renderDev();
    draft.focus();
  }

  function commitTurn(serial, requestId, conversationId, userText, result) {
    if (!stillCurrent(serial, requestId, conversationId)) return;
    const assistantMessage = assistantHistoryMessage(result.text, result.structured);
    assistantMessage.exchange = { conversationId, requestId };
    assistantMessage.feedback = emptyFeedbackState();
    state.history.push({ role: "user", text: userText });
    state.history.push(assistantMessage);
    hideTyping();
    state.pending = null;
    state.sending = false;
    state.error = null;
    state.exchange = {
      requestId,
      conversationId,
      model: result.model,
      metrics: result.metrics,
      errorCode: "",
      diagnostic: "",
    };
    abortController = null;
    renderMessages({ stick: true });
    renderError();
    renderStarters();
    renderComposer();
    renderDev();
    persistConversation();
    notifyOpenPanels("exchange", conversationId, requestId);
    void loadFeedback(assistantMessage);
    draft.focus();
  }

  function persistConversation() {
    try {
      const packed = packConversation(state.conversationId, state.history);
      if (!packed) {
        localStorage.removeItem(CHAT_STORAGE_KEY);
        return;
      }
      localStorage.setItem(CHAT_STORAGE_KEY, JSON.stringify(packed));
    } catch {
      // The visible chat continues when storage is unavailable.
    }
  }

  function sameSelection(left, right) {
    const a = left || { stars: null, resolved: null };
    const b = right || { stars: null, resolved: null };
    return a.stars === b.stars && a.resolved === b.resolved;
  }

  async function saveFeedback(message, selection) {
    const identity = exchangeIdentity(message && message.exchange);
    if (!identity || !message.feedback) return;
    const current = shownFeedback(message.feedback);
    if (
      sameSelection(current, selection)
      && message.feedback.status !== "error"
      && message.feedback.status !== "load-error"
    ) {
      return;
    }
    message.feedback.token += 1;
    message.feedback.revision += 1;
    const token = message.feedback.token;
    const revision = message.feedback.revision;
    message.feedback.draft = selection;
    message.feedback.status = "saving";
    renderMessages();
    let payload = null;
    let ok = false;
    try {
      const response = await fetch("/api/feedback", {
        method: "POST",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          conversation_id: identity.conversationId,
          request_id: identity.requestId,
          stars: selection.stars,
          resolved: selection.resolved,
          revision,
        }),
      });
      payload = await readJson(response);
      ok = response.ok;
    } catch {
      payload = null;
      ok = false;
    }
    if (state.conversationId !== identity.conversationId) return;
    const live = findExchangeMessage(state.history, identity.conversationId, identity.requestId);
    if (!live || live !== message || live.feedback.token !== token) return;
    const parsed = ok ? readFeedbackPayload(payload) : null;
    const result = applyFeedbackResult({
      conversationId: identity.conversationId,
      requestId: identity.requestId,
      token,
      revision: live.feedback.revision,
      confirmed: live.feedback.confirmed,
      draft: live.feedback.draft,
      status: live.feedback.status,
    }, parsed && parsed.conversationId === identity.conversationId && parsed.requestId === identity.requestId
      ? { ...parsed, token, ok: true, applied: payload.applied === true }
      : { conversationId: identity.conversationId, requestId: identity.requestId, token, ok: false });
    if (!result.appliedToEntry) return;
    live.feedback.confirmed = result.entry.confirmed;
    live.feedback.draft = result.entry.draft;
    live.feedback.revision = Number.isInteger(result.entry.revision) ? result.entry.revision : live.feedback.revision;
    live.feedback.status = result.entry.status;
    renderMessages();
    if (result.entry.status === "saved") {
      notifyOpenPanels("feedback", identity.conversationId, identity.requestId);
    }
  }

  async function loadFeedback(message) {
    const identity = exchangeIdentity(message && message.exchange);
    if (!identity || !message.feedback) return;
    const token = message.feedback.token;
    let response = null;
    try {
      response = await fetch(
        `/api/feedback?conversation_id=${encodeURIComponent(identity.conversationId)}&request_id=${encodeURIComponent(identity.requestId)}`,
        { headers: { Accept: "application/json" } },
      );
    } catch {
      response = null;
    }
    if (state.conversationId !== identity.conversationId) return;
    const live = findExchangeMessage(state.history, identity.conversationId, identity.requestId);
    if (!live || live !== message || live.feedback.token !== token || live.feedback.status === "saving") return;
    if (!response) {
      live.feedback.status = "load-error";
      live.feedback.confirmed = null;
      live.feedback.draft = null;
      renderMessages();
      return;
    }
    const payload = await readJson(response);
    if (live.feedback.token !== token || live.feedback.status === "saving") return;
    if (!response.ok) {
      live.feedback.status = "load-error";
      live.feedback.confirmed = null;
      live.feedback.draft = null;
      renderMessages();
      return;
    }
    const parsed = readFeedbackPayload(payload);
    if (!parsed || parsed.conversationId !== identity.conversationId || parsed.requestId !== identity.requestId) {
      live.feedback.status = "load-error";
      live.feedback.confirmed = null;
      live.feedback.draft = null;
      renderMessages();
      return;
    }
    live.feedback.confirmed = parsed.feedback;
    live.feedback.draft = parsed.feedback;
    live.feedback.revision = parsed.revision;
    live.feedback.status = "idle";
    renderMessages();
  }

  async function readJson(response) {
    try {
      return await response.json();
    } catch {
      return null;
    }
  }

  async function sendCurrentDraft() {
    if (state.sending || !state.strings) return;
    const validation = validateOutgoing(state.history, state.draft);
    if (!validation.ok) {
      if (validation.code === "EMPTY") return;
      state.error = { code: validation.code };
      renderError();
      renderCounter();
      renderComposer();
      return;
    }

    const requestId = createId();
    const conversationId = state.conversationId;
    const serial = requestSerial + 1;
    requestSerial = serial;
    const controller = new AbortController();
    abortController = controller;
    const sentAt = nowMs();
    state.sending = true;
    state.error = null;
    hideTyping();
    state.showTyping = true;
    state.slowStatus = false;
    state.pending = {
      serial,
      requestId,
      conversationId,
      text: validation.text,
      sentAt,
    };
    state.draft = "";
    draft.value = "";
    fitComposer();
    renderMessages({ stick: true });
    slowTimer = setTimeout(() => {
      if (!stillCurrent(serial, requestId, conversationId)) return;
      state.slowStatus = true;
      renderMessages({ stick: true });
    }, PRESENTATION.slowAfterMs);
    renderError();
    renderStarters();
    renderCounter();
    renderComposer();

    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
        },
        body: JSON.stringify(buildChatRequest(requestId, conversationId, validation.messages,
          document.getElementById("credentials-token").value.trim() ? {
            type: document.getElementById("credentials-type").value,
            token: document.getElementById("credentials-token").value.trim(),
            folder_id: document.getElementById("credentials-folder").value.trim(),
          } : undefined)),
        signal: controller.signal,
      });
      if (!stillCurrent(serial, requestId, conversationId)) return;
      const payload = await readJson(response);
      if (!stillCurrent(serial, requestId, conversationId)) return;
      const result = interpretChatPayload(payload, requestId, conversationId);
      if (!stillCurrent(serial, requestId, conversationId)) return;
      if (!response.ok || !result.ok) {
        failTurn(
          serial,
          requestId,
          conversationId,
          result.ignore ? "UNKNOWN" : (result.code || "UNKNOWN"),
          result.diagnostic || "",
        );
        return;
      }
      const wait = revealDelayMs(nowMs() - sentAt);
      const deliver = () => {
        revealTimer = null;
        commitTurn(serial, requestId, conversationId, validation.text, result);
      };
      if (wait === 0) deliver();
      else revealTimer = setTimeout(deliver, wait);
    } catch (error) {
      if (!stillCurrent(serial, requestId, conversationId)) return;
      if (error && error.name === "AbortError") {
        hideTyping();
        renderMessages();
        return;
      }
      failTurn(serial, requestId, conversationId, "NETWORK", "");
    }
  }

  function startNewConversation() {
    const pendingText = state.pending ? state.pending.text : null;
    requestSerial += 1;
    hideTyping();
    if (abortController) {
      abortController.abort();
      abortController = null;
    }
    state.conversationId = createId();
    state.history = [];
    state.pending = null;
    state.sending = false;
    state.error = null;
    state.exchange = emptyExchange();
    if (typeof pendingText === "string") {
      state.draft = pendingText;
      draft.value = pendingText;
    }
    fitComposer();
    renderMessages({ stick: true });
    renderError();
    renderStarters();
    renderCounter();
    renderComposer();
    renderDev();
    persistConversation();
    draft.focus();
  }

  async function loadHealth() {
    const serial = healthSerial + 1;
    healthSerial = serial;
    try {
      const response = await fetch("/api/health", {
        headers: { Accept: "application/json" },
      });
      const payload = await readJson(response);
      if (serial !== healthSerial) return;
      state.health = interpretHealth(payload, response.ok);
    } catch {
      if (serial !== healthSerial) return;
      state.health = { available: false };
    }
    renderDev();
  }

  async function ensureStrings(locale) {
    if (dictionaries.has(locale)) {
      state.strings = dictionaries.get(locale);
      return;
    }
    const response = await fetch(`/locales/${locale}.json`, {
      headers: { Accept: "application/json" },
    });
    if (!response.ok) throw new Error("Locale request failed");
    const data = await response.json();
    if (!data || typeof data !== "object" || !data.errors || !Array.isArray(data.starters)) {
      throw new Error("Locale file is incomplete");
    }
    dictionaries.set(locale, data);
    state.strings = data;
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    void sendCurrentDraft();
  });

  draft.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" || event.shiftKey) return;
    if (event.isComposing || event.keyCode === 229) return;
    event.preventDefault();
    void sendCurrentDraft();
  });

  draft.addEventListener("input", () => {
    state.draft = draft.value;
    fitComposer();
    renderCounter();
    renderComposer();
    if (
      state.error
      && state.error.code === "MESSAGE_TOO_LONG"
      && !normalizeDraft(state.draft).over
    ) {
      state.error = null;
      renderError();
    }
  });

  starters.addEventListener("click", (event) => {
    const button = event.target.closest("button");
    if (!button || state.sending) return;
    state.draft = button.textContent;
    draft.value = state.draft;
    fitComposer();
    renderCounter();
    renderComposer();
    draft.focus();
  });

  retryButton.addEventListener("click", () => {
    void sendCurrentDraft();
  });

  document.getElementById("error-close").addEventListener("click", () => {
    state.error = null;
    renderError();
    renderComposer();
    draft.focus();
  });

  newConversationButton.addEventListener("click", startNewConversation);
  errorNew.addEventListener("click", startNewConversation);

  thread.addEventListener("click", (event) => {
    const star = event.target.closest("[data-star]");
    const choice = event.target.closest("[data-resolved]");
    const control = star || choice;
    if (!control || !thread.contains(control)) return;
    const box = control.closest("[data-conversation-id]");
    if (!box) return;
    const message = findExchangeMessage(state.history, box.dataset.conversationId, box.dataset.requestId);
    if (!message || !message.feedback) return;
    const shown = shownFeedback(message.feedback);
    if (star) {
      const stars = Number(star.dataset.star);
      if (!Number.isInteger(stars) || stars < 1 || stars > 5) return;
      feedbackFocus = star.dataset.focusKey;
      void saveFeedback(message, { stars, resolved: shown ? shown.resolved : null });
      return;
    }
    const resolved = choice.dataset.resolved === "yes" ? true : choice.dataset.resolved === "no" ? false : null;
    if (resolved === null) return;
    feedbackFocus = choice.dataset.focusKey;
    void saveFeedback(message, { stars: shown && shown.stars ? shown.stars : null, resolved });
  });

  thread.addEventListener("keydown", (event) => {
    const star = event.target.closest("[data-star]");
    if (!star || !thread.contains(star)) return;
    if (event.key !== "ArrowRight" && event.key !== "ArrowLeft" && event.key !== "ArrowDown" && event.key !== "ArrowUp") {
      return;
    }
    const group = star.closest("[role='radiogroup']");
    if (!group) return;
    const stars = Array.from(group.querySelectorAll("[data-star]"));
    const index = stars.indexOf(star);
    if (index < 0) return;
    const forward = event.key === "ArrowRight" || event.key === "ArrowDown";
    const next = stars[forward ? Math.min(index + 1, stars.length - 1) : Math.max(index - 1, 0)];
    event.preventDefault();
    if (!next || next === star) {
      next.focus();
      return;
    }
    next.click();
  });

  for (const name of ["settings", "conversation"]) {
    const dialog = document.getElementById(`${name}-dialog`);
    document.getElementById(`${name}-open`).addEventListener("click", () => {
      dialog.showModal();
      if (name === "settings") void loadHealth();
    });
    document.getElementById(`${name}-close`).addEventListener("click", () => dialog.close());
  }

  state.locale = customerLocale(null);
  try {
    const restored = restoreConversation(localStorage.getItem(CHAT_STORAGE_KEY));
    if (restored) {
      state.conversationId = restored.conversationId;
      state.history = restored.history;
    } else {
      state.conversationId = createId();
    }
  } catch {
    state.conversationId = createId();
  }
  void (async () => {
    try {
      await ensureStrings("ru");
    } catch {
      state.strings = null;
    }
    state.locale = "ru";
    applyStrings();
    for (const item of state.history) {
      if (item.role === "assistant" && exchangeIdentity(item.exchange)) void loadFeedback(item);
    }
    void loadHealth();
  })();
}

if (typeof document !== "undefined") {
  init();
}

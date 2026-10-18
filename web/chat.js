// Chat workspace. This module does not import the motion effects.

export const LOCALE_STORAGE_KEY = "yandex-llm-connector.ui-locale";

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
  sending: false,
  error: null,
  health: null,
  exchange: emptyExchange(),
};

let requestSerial = 0;
let healthSerial = 0;
let abortController = null;

export function normalizeLocale(value) {
  return value === "ru" || value === "tr" ? value : "ru";
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

export function buildChatRequest(requestId, conversationId, messages) {
  return {
    request_id: requestId,
    conversation_id: conversationId,
    messages: messages.map((message) => ({
      role: message.role,
      text: message.text,
    })),
  };
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
    model: typeof payload.model === "string" ? payload.model : null,
    metrics: {
      elapsed_ms: metrics.elapsed_ms ?? null,
      input_tokens: metrics.input_tokens ?? null,
      output_tokens: metrics.output_tokens ?? null,
      total_tokens: metrics.total_tokens ?? null,
    },
  };
}

function emptyExchange() {
  return {
    requestId: "",
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
  const devPanel = document.getElementById("dev-panel");
  const devToggle = document.getElementById("dev-toggle");
  const newConversationButton = document.getElementById("new-conversation");
  const languageGroup = document.querySelector(".lang");
  const russianButton = languageGroup.querySelector('[data-locale="ru"]');
  const turkishButton = languageGroup.querySelector('[data-locale="tr"]');

  const textBindings = [
    ["brand-title", "brandTitle"],
    ["brand-subtitle", "brandSubtitle"],
    ["rail-title", "railTitle"],
    ["rail-lead", "railLead"],
    ["replies-note", "repliesNote"],
    ["new-conversation", "newConversation"],
    ["language-label", "languageLabel"],
    ["dev-toggle", "devToggle"],
    ["log-label", "logLabel"],
    ["empty-kicker", "emptyKicker"],
    ["empty-title", "emptyTitle"],
    ["empty-lead", "emptyLead"],
    ["starter-label", "starterLabel"],
    ["composer-label", "composerLabel"],
    ["composer-hint", "composerHint"],
    ["retry", "retry"],
    ["error-new", "offerNew"],
    ["dev-title", "devTitle"],
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
  ];

  function readStoredLocale() {
    try {
      const saved = localStorage.getItem(LOCALE_STORAGE_KEY);
      const locale = normalizeLocale(saved);
      if (saved != null && saved !== locale) persistLocale(locale);
      return locale;
    } catch {
      return "ru";
    }
  }

  function persistLocale(locale) {
    try {
      localStorage.setItem(LOCALE_STORAGE_KEY, locale);
    } catch {
      // The visible language still changes when storage is unavailable.
    }
  }

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

  function renderMessage(role, text, pending) {
    const article = document.createElement("article");
    article.className = `message message-${role}`;
    if (pending) article.classList.add("is-pending");
    if (role === "assistant") article.lang = "ru";
    const who = document.createElement("span");
    who.className = "who";
    who.textContent = role === "user" ? state.strings.you : state.strings.assistant;
    const bubble = document.createElement("p");
    bubble.className = "bubble";
    bubble.textContent = text;
    if (role === "user") bubble.dir = "auto";
    article.append(who, bubble);
    return article;
  }

  function renderPendingReply() {
    const article = document.createElement("article");
    article.className = "message message-assistant is-pending";
    article.setAttribute("aria-busy", "true");
    const who = document.createElement("span");
    who.className = "who";
    who.textContent = state.strings.assistant;
    const bubble = document.createElement("p");
    bubble.className = "bubble";
    bubble.textContent = state.strings.pendingReply;
    article.append(who, bubble);
    return article;
  }

  function renderMessages(options = {}) {
    const stick = options.stick === true;
    const nearBottom = thread.scrollHeight - thread.scrollTop - thread.clientHeight < 80;
    const previous = thread.scrollTop;
    for (const node of thread.querySelectorAll(".message")) node.remove();
    const visible = state.history.length > 0 || Boolean(state.pending);
    empty.hidden = visible;
    if (!state.strings) return;
    for (const item of state.history) {
      thread.append(renderMessage(item.role, item.text, false));
    }
    if (state.pending) {
      thread.append(renderMessage("user", state.pending.text, true));
      thread.append(renderPendingReply());
    }
    if (stick || nearBottom) thread.scrollTop = thread.scrollHeight;
    else thread.scrollTop = previous;
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
  }

  function applyStrings() {
    if (!state.strings) return;
    const strings = state.strings;
    document.documentElement.lang = state.locale;
    document.title = strings.documentTitle;
    for (const [id, key] of textBindings) setText(id, strings[key]);
    draft.placeholder = strings.composerPlaceholder;
    russianButton.setAttribute("aria-label", strings.languageRussian);
    turkishButton.setAttribute("aria-label", strings.languageTurkish);
    russianButton.setAttribute("aria-pressed", state.locale === "ru" ? "true" : "false");
    turkishButton.setAttribute("aria-pressed", state.locale === "tr" ? "true" : "false");
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
    state.pending = null;
    state.sending = false;
    state.error = { code: presentedErrorCode(code, state.history, text) };
    state.draft = text;
    state.exchange = {
      requestId,
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
    state.history.push({ role: "user", text: userText });
    state.history.push({ role: "assistant", text: result.text });
    state.pending = null;
    state.sending = false;
    state.error = null;
    state.exchange = {
      requestId,
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
    draft.focus();
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
    state.sending = true;
    state.error = null;
    state.pending = {
      serial,
      requestId,
      conversationId,
      text: validation.text,
    };
    state.draft = "";
    draft.value = "";
    fitComposer();
    renderMessages({ stick: true });
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
        body: JSON.stringify(buildChatRequest(requestId, conversationId, validation.messages)),
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
      commitTurn(serial, requestId, conversationId, validation.text, result);
    } catch (error) {
      if (!stillCurrent(serial, requestId, conversationId)) return;
      if (error && error.name === "AbortError") return;
      failTurn(serial, requestId, conversationId, "NETWORK", "");
    }
  }

  function startNewConversation() {
    const pendingText = state.pending ? state.pending.text : null;
    requestSerial += 1;
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

  async function setLocale(locale) {
    const next = normalizeLocale(locale);
    if (next === state.locale && state.strings) return;
    const previousLocale = state.locale;
    const previousStrings = state.strings;
    try {
      await ensureStrings(next);
    } catch {
      state.locale = previousLocale;
      state.strings = previousStrings;
      return;
    }
    state.locale = next;
    persistLocale(next);
    applyStrings();
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

  newConversationButton.addEventListener("click", startNewConversation);
  errorNew.addEventListener("click", startNewConversation);

  languageGroup.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-locale]");
    if (!button) return;
    void setLocale(button.dataset.locale);
  });

  devToggle.addEventListener("click", () => {
    const willOpen = devPanel.hidden;
    devPanel.hidden = !willOpen;
    devToggle.setAttribute("aria-expanded", willOpen ? "true" : "false");
    if (willOpen) void loadHealth();
  });

  state.locale = readStoredLocale();
  state.conversationId = createId();
  void (async () => {
    try {
      await ensureStrings(state.locale);
    } catch {
      if (state.locale !== "ru") {
        try {
          await ensureStrings("ru");
          state.locale = "ru";
        } catch {
          state.strings = null;
        }
      } else {
        state.strings = null;
      }
    }
    applyStrings();
    void loadHealth();
  })();
}

if (typeof document !== "undefined") {
  init();
}

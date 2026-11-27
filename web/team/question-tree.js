// Team question tree. The customer chat does not load this module.
// Wave 3 connects loadQuestionTree to read_question_tree. No sample exchanges live here.

export const QUESTION_TREE_ENDPOINT = "/api/question-tree";
export const QUESTION_TREE_LOCATE_ENDPOINT = "/api/question-tree-locate";
export const PANEL_REVISION_ENDPOINT = "/api/panel-revision";
export const QUALITY_REVIEW_ENDPOINT = "/api/quality-review";
export const PANEL_EVENT_CHANNEL = "autoservice-panel-events";
export const QUESTION_TREE_LIMIT = 20;
export const LOCALE_STORAGE_KEY = "yandex-llm-connector.ui-locale";
export const THEME_STORAGE_KEY = "yandex-llm-connector.question-tree.theme";
export const PLACEMENT_STORAGE_KEY = "yandex-llm-connector.question-tree.placement";
const DRAG_THRESHOLD = 6;

const VIEWS = ["tree", "frequent", "review"];
const KINDS = new Set(["root", "category", "service", "question_type", "exchange"]);
const QUESTION_TYPE_LABELS = {
  price: "Цена",
  equipment: "Наличие оборудования",
  booking: "Запись",
  availability: "Свободное окно",
  hours: "Часы работы",
  diagnosis: "Диагностика",
  workshop: "Мастерская",
};

const FALLBACK_STRINGS = {
  documentTitle: "Дерево вопросов",
  brandTitle: "Дерево вопросов",
  brandSubtitle: "Панель команды",
  teamNote: "Записанные обмены. Это не клиентский чат.",
  viewsLabel: "Раздел",
  viewTree: "Дерево",
  viewFrequent: "Частые вопросы",
  viewReview: "На проверку",
  treeLabel: "Ветки",
  branchColumn: "Ветка",
  countColumn: "Обмены",
  countNote: "Число — это обмены, то есть ходы диалога, а не число клиентов.",
  historyLabel: "История обменов",
  customer: "Клиент",
  assistant: "Ассистент",
  loading: "Загрузка…",
  emptyTitle: "Записанных обменов пока нет",
  emptyLead: "База пуста. Здесь появятся только реальные диалоги, когда их начнут сохранять.",
  reviewOnlyTitle: "Все обмены ждут проверки",
  reviewOnlyLead: "В дереве нет размещённых веток. База не пуста: эти записи лежат в разделе «На проверку».",
  reviewOnlyAction: "Открыть «На проверку»",
  reviewClear: "Записей на проверку нет. Размещённые обмены остаются в дереве.",
  historyEmpty: "В этой ветке нет обменов.",
  errorTitle: "Не удалось прочитать дерево",
  errorNotReady: "Чтение дерева ещё не подключено.",
  errorNetwork: "Нет связи с сервисом.",
  errorRead: "Не удалось получить обмены.",
  errorBad: "Ответ сервиса не похож на дерево вопросов.",
  retry: "Повторить",
  backToTree: "К веткам",
  showHistory: "История",
  expand: "Развернуть",
  collapse: "Свернуть",
  previous: "Назад",
  next: "Дальше",
  page: "{from}–{to} из {total}",
  pageEmpty: "0 из {total}",
  selectedBranch: "Выбранная ветка",
  themeLabel: "Тема",
  themeLight: "Светлая",
  themeDark: "Тёмная",
  themeSystem: "Как в системе",
  openError: "Не удалось открыть ветку.",
  noChildren: "Нет вложенных веток.",
  reviewMark: "Проверка",
  branchOne: "ветка",
  branchFew: "ветки",
  branchMany: "веток",
  exchangeOne: "обмен",
  exchangeFew: "обмена",
  exchangeMany: "обменов",
  fitView: "Вписать в экран",
  resetLayout: "Восстановить раскладку",
  zoomIn: "Приблизить",
  zoomOut: "Отдалить",
  zoomReset: "Масштаб 100%",
  refresh: "Обновить",
  showOnTree: "На дереве",
  minimapLabel: "Карта",
  canvasLabel: "Дерево вопросов",
  frequentLead: "Услуга и тип вопроса. Крупное число — сколько было таких обменов, а не сколько клиентов.",
  reviewLead: "Сообщение клиента, услуга, если она есть в данных, и короткая причина проверки.",
  reasonNoService: "Не удалось определить услугу",
  reasonReview: "Классификацию нужно проверить",
  earlierContext: "Ранее",
  messageUnavailable: "Текст сообщения недоступен",
  feedbackResolved: "Вопрос решён",
  feedbackOpen: "Вопрос не решён",
  ratingOne: "оценка",
  ratingFew: "оценки",
  ratingMany: "оценок",
  loadingBranch: "Загрузка…",
  layoutFixture: "Проверка раскладки. Это не живые данные.",
  suppliedLabel: "Переданный код",
  qualityToggle: "Качество",
  qualityTitle: "Качество ответов",
  qualityNote: "Это не проверка ветки. Здесь решается, годится ли ответ как пример. Оценка клиента не меняет следующие ответы.",
  qualityPositive: "Кандидаты",
  qualityExamine: "На разбор",
  qualityConflict: "Спорные",
  qualityOther: "Другие сигналы",
  qualityApproved: "Одобренные",
  qualityExcluded: "Исключённые",
  qualityApprove: "Одобрить пример",
  qualityExclude: "Исключить",
  qualityExport: "Скачать одобренные",
  qualityEmpty: "В этом разделе пусто.",
  qualityLowNote: "Низкая оценка сама по себе не является исправленным примером.",
  qualityConflictNote: "Сигналы расходятся. Автоматического одобрения нет.",
  qualityReopened: "Оценка изменилась. Пример снова ждёт решения и не попадёт в файл.",
  qualityExportEmpty: "Нет одобренных примеров.",
  qualityExportFailed: "Не удалось подготовить файл.",
  qualityReadFailed: "Не удалось прочитать проверку качества.",
  qualityContext: "Контекст разговора",
  qualitySaved: "Решение сохранено.",
  linkMissing: "Такой обмен не найден.",
  linkFailed: "Не удалось открыть этот обмен.",
  linkBack: "К дереву",
};

const VIEW_TEXT = {
  tree: "viewTree",
  frequent: "viewFrequent",
  review: "viewReview",
};

function isInteger(value, min = 0) {
  return typeof value === "number" && Number.isInteger(value) && value >= min;
}

function isText(value) {
  return typeof value === "string";
}

function isNullableText(value) {
  return value === null || typeof value === "string";
}

function isNode(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  if (!isText(value.id) || !KINDS.has(value.kind) || !isText(value.label)) return false;
  if (!isInteger(value.exchange_count) || !isInteger(value.membership_count)) return false;
  if (typeof value.needs_review !== "boolean") return false;
  if (!isNullableText(value.category_id) || !isNullableText(value.category_label)) return false;
  if (!isNullableText(value.service_id) || !isNullableText(value.service_label)) return false;
  if (!isNullableText(value.question_type)) return false;
  if (!isNullableText(value.supplied_service_id) || !isNullableText(value.supplied_category_id)) return false;
  return true;
}

function isExchange(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  if (!isText(value.conversation_id) || !isText(value.request_id)) return false;
  if (!isText(value.customer_message) || !isText(value.assistant_reply)) return false;
  if (!isText(value.exchanged_at)) return false;
  if (!Array.isArray(value.question_types) || !value.question_types.every(isText)) return false;
  if (typeof value.needs_review !== "boolean") return false;
  if (!isNullableText(value.service_id) || !isNullableText(value.service_label)) return false;
  if (!isNullableText(value.category_id) || !isNullableText(value.category_label)) return false;
  if (!isNullableText(value.supplied_service_id) || !isNullableText(value.supplied_category_id)) return false;
  return true;
}

export function isQuestionTreeResponse(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  if (!VIEWS.includes(value.view) || !isNode(value.node)) return false;
  if (!Array.isArray(value.children) || !value.children.every(isNode)) return false;
  const history = value.history;
  if (!history || typeof history !== "object" || Array.isArray(history)) return false;
  if (!isInteger(history.total) || !isInteger(history.limit, 1) || !isInteger(history.offset)) return false;
  if (!Array.isArray(history.exchanges) || !history.exchanges.every(isExchange)) return false;
  return true;
}

export function displayedExchangeCount(node) {
  if (!node || typeof node !== "object") return null;
  const count = node.exchange_count;
  if (!isInteger(count)) return null;
  return count;
}

export function historyPage(history) {
  const total = history.total;
  const limit = history.limit;
  const offset = history.offset;
  const shown = Array.isArray(history.exchanges) ? history.exchanges.length : 0;
  const hasRows = shown > 0;
  return {
    total,
    limit,
    offset,
    shown,
    from: hasRows ? offset + 1 : 0,
    to: hasRows ? offset + shown : 0,
    hasPrev: offset > 0,
    hasNext: offset + shown < total,
  };
}

export function panelPresentation(phase) {
  if (phase === "loading" || phase === "empty" || phase === "error" || phase === "review-only") return phase;
  return "ready";
}

export function formatExchangedAt(value) {
  if (typeof value !== "string" || value.trim() === "") return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  try {
    return new Intl.DateTimeFormat("ru-RU", { dateStyle: "medium", timeStyle: "short" }).format(date);
  } catch {
    return value;
  }
}

function questionTypeLabel(code) {
  return Object.prototype.hasOwnProperty.call(QUESTION_TYPE_LABELS, code)
    ? QUESTION_TYPE_LABELS[code]
    : code;
}

export function normalizeTheme(value) {
  return value === "light" || value === "dark" || value === "system" ? value : "system";
}

function normalizeError(error) {
  const code = error && typeof error.code === "string" ? error.code : "READ_FAILED";
  const known = code === "NETWORK" || code === "NOT_READY" || code === "BAD_RESPONSE" || code === "READ_FAILED";
  const detail = error && typeof error.detail === "string" ? error.detail : null;
  return {
    code: known ? code : "READ_FAILED",
    status: error && Number.isInteger(error.status) ? error.status : null,
    detail: safeDetail(detail),
  };
}

function safeDetail(value) {
  if (typeof value !== "string") return null;
  const text = value.trim();
  if (!text || text.length > 160 || text.includes("<") || text.includes(">")) return null;
  return text;
}

function readFailure(status, detail) {
  const error = new Error(detail || "question tree read failed");
  error.code = status === 404 ? "NOT_READY" : "READ_FAILED";
  error.status = status;
  error.detail = status === 404 ? null : safeDetail(detail);
  return error;
}

async function errorDetail(response) {
  try {
    const payload = await response.json();
    if (payload && typeof payload.error === "string") return payload.error;
  } catch {
    return null;
  }
  return null;
}

// Replace this function when the read route differs. Arguments are the
// read_question_tree inputs. Return that function's object. Throw on failure.
export async function loadQuestionTree(query) {
  const nodeId = query && typeof query.nodeId === "string" && query.nodeId ? query.nodeId : "root";
  const view = query && typeof query.view === "string" ? query.view : "tree";
  const limit = query && Number.isInteger(query.limit) ? query.limit : QUESTION_TREE_LIMIT;
  const offset = query && Number.isInteger(query.offset) && query.offset >= 0 ? query.offset : 0;
  const params = new URLSearchParams({
    node_id: nodeId,
    view,
    limit: String(limit),
    offset: String(offset),
  });
  let response;
  try {
    response = await fetch(`${QUESTION_TREE_ENDPOINT}?${params}`, {
      headers: { Accept: "application/json" },
    });
  } catch {
    const error = new Error("question tree unavailable");
    error.code = "NETWORK";
    throw error;
  }
  if (!response.ok) throw readFailure(response.status, await errorDetail(response));
  let payload;
  try {
    payload = await response.json();
  } catch {
    const error = new Error("question tree response was not json");
    error.code = "BAD_RESPONSE";
    error.status = response.status;
    throw error;
  }
  if (!isQuestionTreeResponse(payload)) {
    const error = new Error("question tree response was not recognized");
    error.code = "BAD_RESPONSE";
    error.status = response.status;
    throw error;
  }
  return payload;
}

function pageKey(view, id, offset) {
  return `${view}\0${id}\0${offset}`;
}

function branchLabels(node) {
  if (!node) return [];
  if (node.kind === "root") return [node.label];
  const parts = [];
  if (typeof node.category_label === "string" && node.category_label) parts.push(node.category_label);
  if (
    node.kind !== "category"
    && typeof node.service_label === "string"
    && node.service_label
    && node.service_label !== parts[parts.length - 1]
  ) {
    parts.push(node.service_label);
  }
  if (typeof node.label === "string" && node.label && node.label !== parts[parts.length - 1]) {
    parts.push(node.label);
  }
  return parts.length ? parts : [node.id];
}

function presentFeedback(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const clean = {};
  if (typeof value.stars === "number" && Number.isFinite(value.stars) && value.stars >= 1 && value.stars <= 5) {
    clean.stars = Math.round(value.stars * 10) / 10;
  }
  if (typeof value.resolved === "boolean") clean.resolved = value.resolved;
  return Object.keys(clean).length ? clean : null;
}

function presentExchange(item) {
  return {
    conversationId: item.conversation_id,
    requestId: item.request_id,
    customerMessage: item.customer_message,
    assistantReply: item.assistant_reply,
    exchangedAt: item.exchanged_at,
    questionTypes: item.question_types.slice(),
    needsReview: item.needs_review,
    feedback: presentFeedback(item.feedback),
    serviceId: item.service_id || null,
    serviceLabel: item.service_label || null,
    suppliedServiceId: item.supplied_service_id || null,
  };
}

function viewIsEmpty(response) {
  return Boolean(
    response
    && response.node
    && response.node.id === "root"
    && response.node.exchange_count === 0
    && response.children.length === 0
    && response.history.total === 0
  );
}

const TREE_GAP_X = 92;
const TREE_GAP_Y = 26;
const SVG_NS = "http://www.w3.org/2000/svg";
const LABEL_FONT = '650 13.5px "Segoe UI", "Avenir Next", "Helvetica Neue", sans-serif';
const PALETTE_CYCLE = ["sage", "amber", "sky", "rose", "lilac", "mint"];
const PALETTES = {
  petrol: { soft: "#0d4547", edge: "#6f948c", icon: "#f3fbfa" },
  sage: { soft: "#e6f0e1", edge: "#7e987c", icon: "#3d6a48" },
  amber: { soft: "#f8efdf", edge: "#c4a36c", icon: "#8d6840" },
  sky: { soft: "#e3eef6", edge: "#7f9bb4", icon: "#3d6484" },
  rose: { soft: "#f6ecea", edge: "#c49a96", icon: "#8d5c58" },
  lilac: { soft: "#efeaf5", edge: "#a394bc", icon: "#6d5d8c" },
  mint: { soft: "#e5f3ef", edge: "#6fa396", icon: "#2f6d62" },
};

let labelRuler = null;

export function arrangeQuestionNodes(items) {
  if (!Array.isArray(items) || items.length === 0) return [];
  const nodes = new Map();
  for (const item of items) {
    nodes.set(item.id, {
      id: item.id,
      parentId: item.parentId || null,
      width: Number(item.width) || 0,
      height: Number(item.height) || 0,
      children: [],
    });
  }
  const roots = [];
  for (const node of nodes.values()) {
    const parent = node.parentId ? nodes.get(node.parentId) : null;
    if (parent) parent.children.push(node);
    else roots.push(node);
  }
  const columnWidth = [];
  const walkDepth = (node, depth) => {
    node.depth = depth;
    columnWidth[depth] = Math.max(columnWidth[depth] || 0, node.width);
    for (const child of node.children) walkDepth(child, depth + 1);
  };
  for (const root of roots) walkDepth(root, 0);
  const columnX = [];
  let cursorX = 0;
  for (let depth = 0; depth < columnWidth.length; depth += 1) {
    columnX[depth] = cursorX;
    cursorX += columnWidth[depth] + TREE_GAP_X;
  }
  const measure = (node) => {
    if (!node.children.length) {
      node.span = node.height;
      return;
    }
    for (const child of node.children) measure(child);
    const inner = node.children.reduce((sum, child) => sum + child.span, 0) + TREE_GAP_Y * (node.children.length - 1);
    node.span = Math.max(node.height, inner);
  };
  const place = (node, top) => {
    node.x = columnX[node.depth];
    const inner = node.children.length
      ? node.children.reduce((sum, child) => sum + child.span, 0) + TREE_GAP_Y * (node.children.length - 1)
      : 0;
    const childTop = top + (node.span - inner) / 2;
    node.y = childTop + inner / 2 - node.height / 2;
    let cursor = childTop;
    for (const child of node.children) {
      place(child, cursor);
      cursor += child.span + TREE_GAP_Y;
    }
  };
  let top = 0;
  for (const root of roots) {
    measure(root);
    place(root, top);
    top += root.span + TREE_GAP_Y;
  }
  return items.map((item) => {
    const node = nodes.get(item.id);
    return { id: item.id, x: node.x, y: node.y, width: node.width, height: node.height };
  });
}

export function cameraForAnchor(camera, before, after) {
  const zoom = camera.zoom;
  const screenX = camera.x + (before.x + before.width / 2) * zoom;
  const screenY = camera.y + (before.y + before.height / 2) * zoom;
  return {
    x: screenX - (after.x + after.width / 2) * zoom,
    y: screenY - (after.y + after.height / 2) * zoom,
    zoom,
  };
}

export function readStoredOffsets(raw) {
  let parsed = raw;
  if (typeof raw === "string") {
    if (!raw.trim()) return new Map();
    try {
      parsed = JSON.parse(raw);
    } catch {
      return new Map();
    }
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return new Map();
  const map = new Map();
  for (const [id, value] of Object.entries(parsed)) {
    if (!id || id.length > 240) continue;
    if (!value || typeof value !== "object" || Array.isArray(value)) continue;
    const x = Number(value.x);
    const y = Number(value.y);
    if (!Number.isFinite(x) || !Number.isFinite(y)) continue;
    if (Math.abs(x) > 50000 || Math.abs(y) > 50000) continue;
    map.set(id, { x, y });
  }
  return map;
}

export function placedWithOffsets(autoNodes, offsetMap) {
  const list = Array.isArray(autoNodes) ? autoNodes : [];
  const parentOf = new Map(list.map((node) => [node.id, node.parentId || null]));
  const own = (id) => {
    const value = offsetMap instanceof Map ? offsetMap.get(id) : offsetMap?.[id];
    if (!value || typeof value !== "object") return { x: 0, y: 0 };
    const x = Number(value.x);
    const y = Number(value.y);
    if (!Number.isFinite(x) || !Number.isFinite(y)) return { x: 0, y: 0 };
    return { x, y };
  };
  return list.map((node) => {
    let dx = 0;
    let dy = 0;
    let cursor = node.id;
    const seen = new Set();
    while (cursor && !seen.has(cursor)) {
      seen.add(cursor);
      const shift = own(cursor);
      dx += shift.x;
      dy += shift.y;
      cursor = parentOf.get(cursor) || null;
    }
    return { ...node, x: node.x + dx, y: node.y + dy };
  });
}

export function offsetAfterSubtreeDrag(offsets, nodeId, dx, dy) {
  const next = new Map();
  if (offsets instanceof Map) {
    for (const [id, value] of offsets) next.set(id, { x: value.x, y: value.y });
  } else if (offsets && typeof offsets === "object") {
    for (const [id, value] of Object.entries(offsets)) {
      if (value && Number.isFinite(Number(value.x)) && Number.isFinite(Number(value.y))) {
        next.set(id, { x: Number(value.x), y: Number(value.y) });
      }
    }
  }
  const current = next.get(nodeId) || { x: 0, y: 0 };
  const x = Math.max(-20000, Math.min(20000, current.x + dx));
  const y = Math.max(-20000, Math.min(20000, current.y + dy));
  if (Math.abs(x) < 0.5 && Math.abs(y) < 0.5) next.delete(nodeId);
  else next.set(nodeId, { x, y });
  return next;
}

export function frequentCardTitle(row) {
  if (!row || typeof row !== "object") return "";
  const typeCode = row.questionType || row.question_type || "";
  const typeLabel = typeCode ? questionTypeLabel(typeCode) : "";
  const service = String(row.serviceLabel || row.service_label || "").trim();
  const own = String(row.label || "").trim();
  const head = typeLabel || own;
  if (head && service && service.localeCompare(head, "ru") !== 0) return `${head} · ${service}`;
  return head || service;
}

export function reviewReason(row, strings = FALLBACK_STRINGS) {
  const serviceId = row && (row.serviceId || row.service_id);
  if (!serviceId) return strings.reasonNoService;
  return strings.reasonReview;
}

export function isTerseCustomerMessage(value) {
  if (typeof value !== "string") return false;
  const text = value.trim();
  return text.length > 0 && text.length <= 24;
}

export function previousCustomerContext(message, exchange, history) {
  if (!isTerseCustomerMessage(message)) return null;
  if (!exchange || typeof exchange.conversationId !== "string" || !exchange.conversationId) return null;
  const when = Date.parse(exchange.exchangedAt || "");
  if (Number.isNaN(when)) return null;
  let best = null;
  let bestAt = -Infinity;
  for (const item of Array.isArray(history) ? history : []) {
    if (!item || item.conversationId !== exchange.conversationId) continue;
    if (item.requestId && exchange.requestId && item.requestId === exchange.requestId) continue;
    const at = Date.parse(item.exchangedAt || "");
    if (Number.isNaN(at) || at >= when || at <= bestAt) continue;
    if (typeof item.customerMessage !== "string" || !item.customerMessage.trim()) continue;
    best = item.customerMessage;
    bestAt = at;
  }
  return best;
}

export function ratingText(averageStars, ratingCount, strings = FALLBACK_STRINGS) {
  if (typeof ratingCount !== "number" || !Number.isInteger(ratingCount) || ratingCount < 1) return null;
  if (typeof averageStars !== "number" || !Number.isFinite(averageStars) || averageStars <= 0 || averageStars > 5) return null;
  const rounded = Math.round(averageStars * 10) / 10;
  const average = rounded.toFixed(1).replace(".", ",");
  return `${average} из 5 · ${unitPhrase(ratingCount, strings, "rating")}`;
}

export function feedbackText(feedback, strings = FALLBACK_STRINGS) {
  if (!feedback || typeof feedback !== "object" || Array.isArray(feedback)) return null;
  const parts = [];
  const stars = feedback.stars;
  if (typeof stars === "number" && Number.isFinite(stars) && stars >= 1 && stars <= 5) {
    const shown = Number.isInteger(stars) ? String(stars) : (Math.round(stars * 10) / 10).toFixed(1).replace(".", ",");
    parts.push(`${shown} из 5`);
  }
  if (feedback.resolved === true) parts.push(strings.feedbackResolved);
  else if (feedback.resolved === false) parts.push(strings.feedbackOpen);
  return parts.length ? parts.join(" · ") : null;
}

const EXCHANGE_UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

export function qualitySignal(feedback) {
  if (!feedback || typeof feedback !== "object" || Array.isArray(feedback)) return null;
  const stars = feedback.stars;
  const resolved = feedback.resolved;
  const hasStars = typeof stars === "number" && Number.isInteger(stars) && stars >= 1 && stars <= 5;
  const hasResolved = typeof resolved === "boolean";
  if (!hasStars && !hasResolved) return null;
  const high = hasStars && stars >= 4;
  const low = hasStars && stars <= 2;
  if (high && resolved === true) return "positive";
  if ((high && resolved === false) || (low && resolved === true)) return "conflict";
  if (low || resolved === false) return "examine";
  return "other";
}

export function readExchangeLink(search) {
  const text = typeof search === "string" ? search : "";
  const params = new URLSearchParams(text.startsWith("?") ? text.slice(1) : text);
  if (!params.has("conversation_id") && !params.has("request_id")) return null;
  const conversationId = String(params.get("conversation_id") || "").trim().toLowerCase();
  const requestId = String(params.get("request_id") || "").trim().toLowerCase();
  if (!EXCHANGE_UUID.test(conversationId) || !EXCHANGE_UUID.test(requestId)) return { error: "invalid" };
  return { conversationId, requestId };
}

export function exchangeElementSelector(conversationId, requestId) {
  if (typeof conversationId !== "string" || typeof requestId !== "string") return "";
  if (!EXCHANGE_UUID.test(conversationId) || !EXCHANGE_UUID.test(requestId)) return "";
  return `[data-conversation-id="${cssEscape(conversationId)}"][data-request-id="${cssEscape(requestId)}"]`;
}

async function fetchExchangeLocation(link) {
  try {
    const response = await fetch(
      `${QUESTION_TREE_LOCATE_ENDPOINT}?conversation_id=${encodeURIComponent(link.conversationId)}&request_id=${encodeURIComponent(link.requestId)}`,
      { headers: { Accept: "application/json" }, cache: "no-store" },
    );
    const body = await response.json().catch(() => null);
    if (response.status === 404) return { ok: false, message: "missing" };
    if (!response.ok || !body || typeof body.node_id !== "string" || !VIEWS.includes(body.view)) {
      return { ok: false, message: "failed" };
    }
    return {
      ok: true,
      target: {
        view: body.view,
        nodeId: body.node_id,
        categoryId: body.category_id,
        offset: body.offset,
        conversationId: body.conversation_id,
        requestId: body.request_id,
      },
    };
  } catch {
    return { ok: false, message: "failed" };
  }
}

function stressNode(id, kind, label, count, extra = {}) {
  return {
    id,
    kind,
    label,
    exchange_count: count,
    membership_count: count,
    needs_review: false,
    category_id: extra.category_id ?? null,
    category_label: extra.category_label ?? null,
    service_id: extra.service_id ?? null,
    service_label: extra.service_label ?? null,
    question_type: extra.question_type ?? null,
    supplied_service_id: null,
    supplied_category_id: null,
  };
}

// Opt-in layout probe. The live page never calls this unless ?nav=stress is present.
export function createStressLoader() {
  const types = [
    ["price", "Цена"],
    ["booking", "Запись"],
    ["equipment", "Оборудование"],
    ["diagnosis", "Диагностика"],
  ];
  const nodes = new Map();
  const childIds = new Map();
  const categories = [];
  for (let c = 1; c <= 8; c += 1) {
    const categoryId = `nav-c${String(c).padStart(2, "0")}`;
    const categoryNode = `category:${categoryId}`;
    const categoryLabel = `Группа ${String(c).padStart(2, "0")}`;
    const serviceCount = 5 + ((c - 1) % 4);
    const services = [];
    for (let s = 1; s <= serviceCount; s += 1) {
      const serviceId = `${categoryId}-s${String(s).padStart(2, "0")}`;
      const serviceNode = `service:${serviceId}`;
      const serviceLabel = s % 3 === 0
        ? `Сервис проверки ${String(c).padStart(2, "0")}-${String(s).padStart(2, "0")} с длинным именем`
        : `Сервис ${String(c).padStart(2, "0")}-${String(s).padStart(2, "0")}`;
      const leaves = types.map(([code, label], index) => {
        const leaf = `leaf:${serviceId}:${code}`;
        nodes.set(leaf, stressNode(leaf, "question_type", label, 1 + ((c + s + index) % 3), {
          category_id: categoryId,
          category_label: categoryLabel,
          service_id: serviceId,
          service_label: serviceLabel,
          question_type: code,
        }));
        childIds.set(leaf, []);
        return leaf;
      });
      services.push(serviceNode);
      nodes.set(serviceNode, stressNode(serviceNode, "service", serviceLabel, leaves.length, {
        category_id: categoryId,
        category_label: categoryLabel,
        service_id: serviceId,
        service_label: serviceLabel,
      }));
      childIds.set(serviceNode, leaves);
    }
    categories.push(categoryNode);
    nodes.set(categoryNode, stressNode(categoryNode, "category", categoryLabel, services.length, {
      category_id: categoryId,
      category_label: categoryLabel,
    }));
    childIds.set(categoryNode, services);
  }
  nodes.set("root", stressNode("root", "root", "Вопросы клиентов", categories.length));
  childIds.set("root", categories);
  return function stressLoader(query) {
    const view = query && VIEWS.includes(query.view) ? query.view : "tree";
    const limit = query && Number.isInteger(query.limit) && query.limit >= 1 ? query.limit : QUESTION_TREE_LIMIT;
    const offset = query && Number.isInteger(query.offset) && query.offset >= 0 ? query.offset : 0;
    const nodeId = query && typeof query.nodeId === "string" && query.nodeId ? query.nodeId : "root";
    const history = { total: 0, limit, offset, exchanges: [] };
    if (view !== "tree") {
      return {
        view,
        node: {
          ...stressNode("root", "root", view === "review" ? "Нужна проверка" : "Частые вопросы", 0),
          needs_review: view === "review",
        },
        children: [],
        history,
      };
    }
    const node = nodes.get(nodeId);
    if (!node) {
      const error = new Error("unknown node");
      error.code = "READ_FAILED";
      throw error;
    }
    return {
      view,
      node: { ...node },
      children: (childIds.get(nodeId) || []).map((id) => ({ ...nodes.get(id) })),
      history,
    };
  };
}

export function createQuestionTreeSession({ loader, limit = QUESTION_TREE_LIMIT } = {}) {
  if (typeof loader !== "function") throw new Error("loader is required");
  let serial = 0;
  const expandSerial = new Map();
  const memory = {
    tree: { selectedId: "root", offset: 0, expanded: new Set() },
    frequent: { selectedId: "root", offset: 0, expanded: new Set() },
    review: { selectedId: "root", offset: 0, expanded: new Set() },
  };
  const state = {
    view: "tree",
    selectedId: "root",
    offset: 0,
    limit,
    narrow: false,
    pane: "tree",
    expanded: new Set(),
    pages: new Map(),
    phase: "loading",
    error: null,
    historyPending: true,
    expandErrors: new Map(),
    pendingExpand: new Set(),
    focusId: null,
    linkedExchange: null,
  };

  function page(view, id, offset) {
    return state.pages.get(pageKey(view, id, offset)) || null;
  }

  function anyPage(view, id) {
    let found = null;
    for (const response of state.pages.values()) {
      if (response.view !== view || response.node.id !== id) continue;
      if (!found || response.history.offset < found.history.offset) found = response;
    }
    return found;
  }

  function findNode(id) {
    for (const response of state.pages.values()) {
      if (response.view !== state.view) continue;
      if (response.node.id === id) return response.node;
      for (const child of response.children) {
        if (child.id === id) return child;
      }
    }
    return null;
  }

  function selectedNode() {
    const current = page(state.view, state.selectedId, state.offset);
    if (current) return current.node;
    return findNode(state.selectedId);
  }

  function remember(response) {
    state.pages.set(pageKey(response.view, response.node.id, response.history.offset), response);
  }

  function saveMemory() {
    memory[state.view] = {
      selectedId: state.selectedId,
      offset: state.offset,
      expanded: new Set(state.expanded),
    };
  }

  function restoreMemory(view) {
    const saved = memory[view];
    state.selectedId = saved.selectedId;
    state.offset = saved.offset;
    state.expanded = view === "tree" ? new Set(saved.expanded) : new Set();
  }

  function historyRows(view, id) {
    const seen = new Set();
    const items = [];
    for (const response of state.pages.values()) {
      if (response.view !== view || response.node.id !== id) continue;
      for (const item of response.history.exchanges) {
        const key = `${item.conversation_id}:${item.request_id}`;
        if (seen.has(key)) continue;
        seen.add(key);
        items.push(item);
      }
    }
    return items;
  }

  function matchPreview(row, items) {
    if (typeof row.id === "string" && row.id.startsWith("review:exchange:")) {
      const rest = row.id.slice("review:exchange:".length);
      const conversationId = rest.slice(0, 36);
      const requestId = rest.slice(37);
      return items.find((item) => item.conversation_id === conversationId && item.request_id === requestId) || null;
    }
    if (row.serviceId && row.questionType) {
      return items.find((item) => item.service_id === row.serviceId && item.question_types.includes(row.questionType)) || null;
    }
    if (row.suppliedServiceId && row.questionType) {
      return items.find((item) => item.supplied_service_id === row.suppliedServiceId && item.question_types.includes(row.questionType)) || null;
    }
    return null;
  }

  function cachedChildCount(node) {
    if (!node || (node.kind !== "root" && node.kind !== "category")) return null;
    const loaded = anyPage(state.view, node.id);
    if (!loaded) return null;
    return loaded.children.length;
  }

  function canExpand(node) {
    return Boolean(node)
      && state.view === "tree"
      && (node.kind === "category" || node.kind === "service");
  }

  function rowDetail(node) {
    if (state.view === "tree" || !node || node.kind === "root" || node.kind === "category") return "";
    const parts = [];
    if (typeof node.category_label === "string" && node.category_label && node.category_label !== node.label) {
      parts.push(node.category_label);
    }
    if (
      typeof node.service_label === "string"
      && node.service_label
      && node.service_label !== node.label
      && node.service_label !== node.category_label
    ) {
      parts.push(node.service_label);
    }
    return parts.join(" · ");
  }

  function ratingFields(node) {
    const loaded = anyPage(state.view, node.id);
    let averageStars = null;
    let ratingCount = null;
    for (const source of [loaded ? loaded.node : null, node]) {
      if (!source) continue;
      if (averageStars === null && typeof source.average_stars === "number") averageStars = source.average_stars;
      if (ratingCount === null && Number.isInteger(source.rating_count)) ratingCount = source.rating_count;
    }
    return { averageStars, ratingCount };
  }

  function addRow(rows, node, depth, expandable, expanded) {
    const rating = ratingFields(node);
    rows.push({
      id: node.id,
      kind: node.kind,
      label: node.label,
      depth,
      count: displayedExchangeCount(node) ?? 0,
      expandable,
      expanded,
      selected: node.id === state.selectedId,
      needsReview: Boolean(node.needs_review) && node.kind !== "root",
      detail: rowDetail(node),
      childCount: cachedChildCount(node),
      questionType: node.question_type || null,
      categoryId: node.category_id || null,
      serviceId: node.service_id || null,
      categoryLabel: node.category_label || null,
      serviceLabel: node.service_label || null,
      suppliedServiceId: node.supplied_service_id || null,
      suppliedCategoryId: node.supplied_category_id || null,
      averageStars: rating.averageStars,
      ratingCount: rating.ratingCount,
      preview: null,
      previewAt: null,
      conversationId: null,
      requestId: null,
      questionTypes: [],
    });
  }

  function addBranch(rows, node, depth) {
    const expandable = node.kind === "category" || node.kind === "service";
    const expanded = expandable && state.expanded.has(node.id);
    addRow(rows, node, depth, expandable, expanded);
    if (!expandable || !expanded) return;
    if (state.pendingExpand.has(node.id)) {
      rows.push({ pending: true, depth: depth + 1, parentId: node.id });
      return;
    }
    if (state.expandErrors.has(node.id)) {
      rows.push({ error: true, depth: depth + 1, parentId: node.id });
      return;
    }
    const loaded = anyPage(state.view, node.id);
    if (!loaded) {
      rows.push({ pending: true, depth: depth + 1, parentId: node.id });
      return;
    }
    if (loaded.children.length === 0) {
      rows.push({ empty: true, depth: depth + 1, parentId: node.id });
      return;
    }
    for (const child of loaded.children) addBranch(rows, child, depth + 1);
  }

  function visibleRows() {
    const root = anyPage(state.view, "root");
    if (!root) return [];
    const rows = [];
    addRow(rows, root.node, 0, false, false);
    if (state.view === "tree") {
      for (const child of root.children) addBranch(rows, child, 1);
    } else {
      for (const child of root.children) addRow(rows, child, 1, false, false);
    }
    if (state.view === "review") {
      const items = historyRows("review", "root");
      for (const row of rows) {
        const match = matchPreview(row, items);
        if (!match) continue;
        row.preview = match.customer_message;
        row.previewAt = match.exchanged_at;
        row.conversationId = match.conversation_id;
        row.requestId = match.request_id;
        row.questionTypes = Array.isArray(match.question_types) ? match.question_types.slice() : [];
        if (!row.serviceId && match.service_id) row.serviceId = match.service_id;
        if (!row.serviceLabel && match.service_label) row.serviceLabel = match.service_label;
        if (!row.suppliedServiceId && match.supplied_service_id) row.suppliedServiceId = match.supplied_service_id;
      }
    }
    return rows;
  }

  function reviewContextItems() {
    return historyRows("review", "root").map((item) => ({
      conversationId: item.conversation_id,
      requestId: item.request_id,
      customerMessage: item.customer_message,
      exchangedAt: item.exchanged_at,
    }));
  }

  function historyStatus() {
    if (state.phase === "loading") return "loading";
    if (state.phase === "empty") return "empty";
    if (state.phase === "error" || state.error) return "error";
    if (state.historyPending) return "loading";
    const current = page(state.view, state.selectedId, state.offset);
    if (!current) return "loading";
    if (current.history.total === 0) return "branch-empty";
    return "ready";
  }

  function snapshot() {
    const current = page(state.view, state.selectedId, state.offset);
    const node = selectedNode();
    const status = historyStatus();
    const showPage = current && (state.phase === "ready" || state.phase === "empty") && !state.error;
    return {
      view: state.view,
      selectedId: state.selectedId,
      pane: state.pane,
      phase: state.phase,
      historyStatus: status,
      error: state.error,
      exchangeCount: state.phase === "error" || !node ? null : displayedExchangeCount(node),
      branch: state.phase === "error" ? [] : branchLabels(node),
      rows: state.phase === "ready" ? visibleRows() : [],
      history: status === "ready" && current ? current.history.exchanges.map(presentExchange) : [],
      page: showPage ? historyPage(current.history) : null,
      focusId: state.focusId,
      linkedExchange: state.linkedExchange,
      context: state.view === "review" && state.phase === "ready" ? reviewContextItems() : [],
    };
  }

  async function prefetchReviewPages(token, requested) {
    if (requested.view !== "review" || requested.nodeId !== "root") return;
    const first = page("review", "root", 0);
    if (!first) return;
    let next = first.history.offset + first.history.exchanges.length;
    let guard = 0;
    while (next < first.history.total && next < 240 && guard < 14) {
      guard += 1;
      const response = await loader({
        nodeId: "root",
        view: "review",
        limit: state.limit,
        offset: next,
      });
      if (token !== serial || state.view !== "review") return;
      if (!isQuestionTreeResponse(response) || response.view !== "review" || response.node.id !== "root") return;
      const end = response.history.offset + response.history.exchanges.length;
      remember(response);
      if (response.history.exchanges.length === 0 || end <= next) return;
      next = end;
    }
  }

  async function phaseForRoot(response, token, requested) {
    if (token !== serial || state.view !== requested.view || state.selectedId !== requested.nodeId) {
      return null;
    }
    if (!response || !viewIsEmpty(response)) return "ready";
    const counterpart = response.view === "review" ? "tree" : "review";
    let other;
    try {
      other = await loader({
        nodeId: "root",
        view: counterpart,
        limit: state.limit,
        offset: 0,
      });
    } catch {
      return "ready";
    }
    if (token !== serial || state.view !== requested.view || state.selectedId !== requested.nodeId) {
      return null;
    }
    if (!isQuestionTreeResponse(other) || other.view !== counterpart || other.node.id !== "root") {
      return "ready";
    }
    remember(other);
    if (viewIsEmpty(other)) return "empty";
    if (response.view !== "review") return "review-only";
    return "ready";
  }

  async function loadSelected() {
    const token = ++serial;
    const requested = {
      nodeId: state.selectedId,
      view: state.view,
      offset: state.offset,
    };
    const existing = page(requested.view, requested.nodeId, requested.offset);
    state.historyPending = !existing;
    state.error = null;
    if (!anyPage(requested.view, "root") && !existing) state.phase = "loading";
    try {
      const response = await loader({
        nodeId: requested.nodeId,
        view: requested.view,
        limit: state.limit,
        offset: requested.offset,
      });
      if (token !== serial || state.view !== requested.view || state.selectedId !== requested.nodeId) {
        return snapshot();
      }
      if (
        !isQuestionTreeResponse(response)
        || response.view !== requested.view
        || response.node.id !== requested.nodeId
      ) {
        return failRead({ code: "BAD_RESPONSE" });
      }
      remember(response);
      state.offset = response.history.offset;
      state.historyPending = false;
      state.error = null;
      state.phase = await phaseForRoot(response, token, requested);
      if (state.phase === null) return snapshot();
      try {
        await prefetchReviewPages(token, requested);
      } catch {
        // Review previews are optional. The selected page is already stored.
      }
      if (token !== serial || state.view !== requested.view || state.selectedId !== requested.nodeId) {
        return snapshot();
      }
      return snapshot();
    } catch (error) {
      if (token !== serial || state.view !== requested.view || state.selectedId !== requested.nodeId) {
        return snapshot();
      }
      return failRead(error);
    }
  }

  function failRead(error) {
    state.error = normalizeError(error);
    state.historyPending = false;
    state.phase = anyPage(state.view, "root") ? "ready" : "error";
    return snapshot();
  }

  async function openSelection(nodeId, offset = 0) {
    if (typeof nodeId !== "string" || nodeId === "") return snapshot();
    state.selectedId = nodeId;
    state.offset = Number.isInteger(offset) && offset >= 0 ? offset : 0;
    if (state.narrow) state.pane = "history";
    return loadSelected();
  }

  async function select(nodeId) {
    return openSelection(nodeId, 0);
  }

  function linkExchange(conversationId, requestId, scroll) {
    if (!EXCHANGE_UUID.test(conversationId || "") || !EXCHANGE_UUID.test(requestId || "")) return snapshot();
    state.linkedExchange = {
      conversationId,
      requestId,
      scroll: Boolean(scroll),
    };
    return snapshot();
  }

  function ackExchangeScroll() {
    if (!state.linkedExchange) return snapshot();
    state.linkedExchange = { ...state.linkedExchange, scroll: false };
    return snapshot();
  }

  async function revealExchange(target) {
    const view = target && target.view;
    const nodeId = target && target.nodeId;
    const offset = target && Number.isInteger(target.offset) && target.offset >= 0 ? target.offset : 0;
    if (!VIEWS.includes(view) || typeof nodeId !== "string" || nodeId === "") return snapshot();
    const token = ++serial;
    if (state.view !== view) saveMemory();
    state.view = view;
    state.selectedId = nodeId;
    state.offset = offset;
    state.error = null;
    state.historyPending = true;
    const expanded = new Set(view === "tree" ? state.expanded : []);
    if (view === "tree" && typeof target.categoryId === "string" && target.categoryId) {
      expanded.add(`category:${target.categoryId}`);
    }
    if (view === "tree" && nodeId.startsWith("service:")) expanded.add(nodeId);
    state.expanded = expanded;
    if (EXCHANGE_UUID.test(target.conversationId || "") && EXCHANGE_UUID.test(target.requestId || "")) {
      state.linkedExchange = {
        conversationId: target.conversationId,
        requestId: target.requestId,
        scroll: true,
      };
    }
    const jobs = [{ id: "root", offset: 0 }];
    if (view === "tree" && typeof target.categoryId === "string" && target.categoryId) {
      jobs.push({ id: `category:${target.categoryId}`, offset: 0 });
    }
    if (nodeId !== "root") jobs.push({ id: nodeId, offset });
    let responses;
    try {
      responses = await Promise.all(jobs.map((job) => loader({
        nodeId: job.id,
        view,
        limit: state.limit,
        offset: job.offset,
      })));
    } catch (error) {
      if (token !== serial) return snapshot();
      return failRead(error);
    }
    if (token !== serial || state.view !== view || state.selectedId !== nodeId) return snapshot();
    for (let index = 0; index < responses.length; index += 1) {
      const response = responses[index];
      const expected = jobs[index];
      if (!isQuestionTreeResponse(response) || response.view !== view || response.node.id !== expected.id) {
        return failRead({ code: "BAD_RESPONSE" });
      }
      remember(response);
    }
    state.historyPending = false;
    state.error = null;
    state.phase = "ready";
    if (state.narrow) state.pane = "history";
    saveMemory();
    return snapshot();
  }

  async function refreshBranch(nodeId) {
    const view = state.view;
    const token = (expandSerial.get(nodeId) || 0) + 1;
    expandSerial.set(nodeId, token);
    if (!anyPage(view, nodeId)) state.pendingExpand.add(nodeId);
    state.expandErrors.delete(nodeId);
    try {
      const response = await loader({
        nodeId,
        view,
        limit: state.limit,
        offset: 0,
      });
      if (expandSerial.get(nodeId) !== token || state.view !== view || !state.expanded.has(nodeId)) {
        return snapshot();
      }
      state.pendingExpand.delete(nodeId);
      if (!isQuestionTreeResponse(response) || response.view !== view || response.node.id !== nodeId) {
        state.expandErrors.set(nodeId, "BAD_RESPONSE");
        return snapshot();
      }
      remember(response);
      return snapshot();
    } catch (error) {
      if (expandSerial.get(nodeId) !== token || state.view !== view) return snapshot();
      state.pendingExpand.delete(nodeId);
      state.expandErrors.set(nodeId, normalizeError(error).code);
      return snapshot();
    }
  }

  async function retryBranch(nodeId) {
    if (typeof nodeId !== "string" || nodeId === "") return snapshot();
    state.expanded.add(nodeId);
    return refreshBranch(nodeId);
  }

  async function toggleExpanded(nodeId) {
    const node = findNode(nodeId);
    if (!canExpand(node)) return snapshot();
    if (state.expanded.has(nodeId)) {
      state.expanded.delete(nodeId);
      state.expandErrors.delete(nodeId);
      state.pendingExpand.delete(nodeId);
      return snapshot();
    }
    state.expanded.add(nodeId);
    return refreshBranch(nodeId);
  }

  async function refreshVisible() {
    const view = state.view;
    const selectedId = state.selectedId;
    const offset = state.offset;
    const token = ++serial;
    const ids = new Set([selectedId]);
    if (view === "tree") {
      ids.add("root");
      for (const id of state.expanded) ids.add(id);
    } else {
      ids.add("root");
    }
    const results = await Promise.all([...ids].map(async (nodeId) => {
      try {
        const response = await loader({
          nodeId,
          view,
          limit: state.limit,
          offset: nodeId === selectedId ? offset : 0,
        });
        return { nodeId, response };
      } catch (error) {
        return { nodeId, error };
      }
    }));
    if (token !== serial || state.view !== view || state.selectedId !== selectedId || state.offset !== offset) {
      return snapshot();
    }
    let selectedOk = false;
    for (const result of results) {
      if (result.error) {
        if (state.expanded.has(result.nodeId) && !anyPage(view, result.nodeId)) {
          state.expandErrors.set(result.nodeId, normalizeError(result.error).code);
        }
        continue;
      }
      if (!isQuestionTreeResponse(result.response) || result.response.view !== view || result.response.node.id !== result.nodeId) {
        continue;
      }
      remember(result.response);
      state.expandErrors.delete(result.nodeId);
      state.pendingExpand.delete(result.nodeId);
      if (result.nodeId === selectedId) selectedOk = true;
    }
    if (!selectedOk && !page(view, selectedId, offset)) return failRead({ code: "READ_FAILED" });
    if (selectedOk) {
      state.error = null;
      state.historyPending = false;
      const current = page(view, selectedId, state.offset);
      state.phase = await phaseForRoot(current, token, { view, nodeId: selectedId });
      if (state.phase === null) return snapshot();
    }
    try {
      await prefetchReviewPages(token, { view, nodeId: selectedId });
    } catch {
      // Keep the pages that refreshed successfully.
    }
    if (token !== serial || state.view !== view || state.selectedId !== selectedId) return snapshot();
    return snapshot();
  }

  async function expandSpine() {
    if (state.view !== "tree" || state.expanded.size > 0) return snapshot();
    const root = anyPage(state.view, "root");
    if (!root) return snapshot();
    const categories = root.children.filter((child) => child.kind === "category").slice(0, 8);
    if (categories.length === 0) return snapshot();
    for (const category of categories) state.expanded.add(category.id);
    await Promise.all(categories.map((category) => refreshBranch(category.id)));
    const singles = [];
    for (const category of categories) {
      const loaded = anyPage(state.view, category.id);
      const services = (loaded?.children || []).filter((child) => child.kind === "service");
      if (services.length === 1) singles.push(services[0]);
    }
    for (const service of singles) state.expanded.add(service.id);
    if (singles.length > 0) await Promise.all(singles.map((service) => refreshBranch(service.id)));
    return snapshot();
  }

  async function expandAll() {
    if (state.view !== "tree") return snapshot();
    const root = anyPage(state.view, "root");
    if (!root) return snapshot();
    const categories = root.children.filter((child) => child.kind === "category").slice(0, 24);
    for (const category of categories) state.expanded.add(category.id);
    await Promise.all(categories.map((category) => refreshBranch(category.id)));
    const services = [];
    for (const category of categories) {
      const loaded = anyPage(state.view, category.id);
      for (const child of loaded?.children || []) {
        if (child.kind === "service") services.push(child);
      }
    }
    const capped = services.slice(0, 80);
    for (const service of capped) state.expanded.add(service.id);
    await Promise.all(capped.map((service) => refreshBranch(service.id)));
    return snapshot();
  }

  async function openOnTree(nodeId) {
    const node = findNode(nodeId);
    if (!node || node.kind !== "question_type" || String(node.id).startsWith("review:")) return snapshot();
    if (!node.category_id || !node.service_id || !node.question_type) return snapshot();
    const category = `category:${node.category_id}`;
    const service = `service:${node.service_id}`;
    const leaf = node.id.startsWith("leaf:") ? node.id : `leaf:${node.service_id}:${node.question_type}`;
    const baseExpanded = new Set(state.view === "tree" ? state.expanded : memory.tree.expanded);
    const token = ++serial;
    let responses;
    try {
      responses = await Promise.all([category, service, leaf, "root"].map((id) => loader({
        nodeId: id,
        view: "tree",
        limit: state.limit,
        offset: 0,
      })));
    } catch (error) {
      if (token !== serial) return snapshot();
      return failRead(error);
    }
    if (token !== serial) return snapshot();
    const expected = [category, service, leaf, "root"];
    if (responses.some((response, index) => (
      !isQuestionTreeResponse(response) || response.view !== "tree" || response.node.id !== expected[index]
    ))) {
      return failRead({ code: "BAD_RESPONSE" });
    }
    if (state.view !== "tree") saveMemory();
    baseExpanded.add(category);
    baseExpanded.add(service);
    state.view = "tree";
    state.expanded = baseExpanded;
    state.selectedId = leaf;
    state.offset = 0;
    state.error = null;
    state.historyPending = false;
    state.phase = "ready";
    state.focusId = leaf;
    if (state.narrow) state.pane = "history";
    for (const response of responses) remember(response);
    saveMemory();
    return snapshot();
  }

  function ackFocus() {
    state.focusId = null;
    return snapshot();
  }

  async function setView(view) {
    if (!VIEWS.includes(view) || view === state.view) return snapshot();
    saveMemory();
    state.view = view;
    restoreMemory(view);
    state.pane = "tree";
    state.error = null;
    state.expandErrors.clear();
    state.pendingExpand.clear();
    return refreshVisible();
  }

  async function step(direction) {
    const current = page(state.view, state.selectedId, state.offset);
    if (!current || state.phase !== "ready" || state.error) return snapshot();
    const window = historyPage(current.history);
    if (direction > 0 && !window.hasNext) return snapshot();
    if (direction < 0 && !window.hasPrev) return snapshot();
    state.offset = direction > 0
      ? window.offset + window.limit
      : Math.max(0, window.offset - window.limit);
    return loadSelected();
  }

  function showTree() {
    state.pane = "tree";
    return snapshot();
  }

  function showHistory() {
    state.pane = "history";
    return snapshot();
  }

  function setNarrow(narrow) {
    state.narrow = Boolean(narrow);
    return snapshot();
  }

  return {
    loadSelected,
    select,
    toggleExpanded,
    setView,
    step,
    showTree,
    showHistory,
    setNarrow,
    retryBranch,
    refreshVisible,
    expandSpine,
    expandAll,
    openOnTree,
    ackFocus,
    openSelection,
    linkExchange,
    ackExchangeScroll,
    revealExchange,
    snapshot,
  };
}

function fill(template, values) {
  return String(template).replace(/\{(\w+)\}/g, (match, key) => (
    Object.prototype.hasOwnProperty.call(values, key) ? String(values[key]) : match
  ));
}

function errorCopy(error, strings) {
  if (!error) return strings.errorRead;
  if (error.code === "NOT_READY") return strings.errorNotReady;
  if (error.code === "NETWORK") return strings.errorNetwork;
  if (error.code === "BAD_RESPONSE") return strings.errorBad;
  return strings.errorRead;
}

function pluralForm(count) {
  const value = Math.abs(Number(count) || 0);
  const mod10 = value % 10;
  const mod100 = value % 100;
  if (mod10 === 1 && mod100 !== 11) return "One";
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return "Few";
  return "Many";
}

function unitPhrase(count, strings, stem) {
  return `${count} ${strings[stem + pluralForm(count)]}`;
}

function nodeSubtitle(row, strings) {
  const exchanges = unitPhrase(row.count, strings, "exchange");
  let base = "";
  if (row.kind === "service") base = exchanges;
  else if (row.kind === "root" || row.kind === "category") {
    base = Number.isInteger(row.childCount)
      ? `${unitPhrase(row.childCount, strings, "branch")} · ${exchanges}`
      : exchanges;
  }
  const rating = ratingText(row.averageStars, row.ratingCount, strings);
  if (rating && base) return `${base} · ${rating}`;
  return rating || base;
}

function canRevealRow(row) {
  return Boolean(
    row
    && row.kind === "question_type"
    && typeof row.id === "string"
    && row.id.startsWith("leaf:")
    && row.categoryId
    && row.serviceId
    && row.questionType
  );
}

function el(tag, { className, attrs, text } = {}) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (attrs) {
    for (const [key, value] of Object.entries(attrs)) {
      if (key === "disabled") {
        node.disabled = Boolean(value);
        continue;
      }
      if (value === null || value === undefined || value === false) continue;
      node.setAttribute(key, value === true ? "" : String(value));
    }
  }
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

function button(text, attrs, className = "qt-button") {
  return el("button", { className, attrs: { type: "button", ...attrs }, text });
}

function svgEl(tag, attrs) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
    node.setAttribute(key, String(value));
  }
  return node;
}

function svgIcon(children, size = 18) {
  const svg = svgEl("svg", {
    viewBox: "0 0 24 24",
    width: size,
    height: size,
    fill: "none",
    stroke: "currentColor",
    "stroke-width": "1.8",
    "stroke-linecap": "round",
    "stroke-linejoin": "round",
    "aria-hidden": "true",
  });
  for (const child of children) svg.append(child);
  return svg;
}

function svgPath(d) {
  return svgEl("path", { d });
}

function kindIcon(kind, questionType) {
  if (questionType === "price") {
    return svgIcon([
      svgPath("M20 13l-7 7-9-9V4h7z"),
      svgEl("circle", { cx: "9", cy: "9", r: "1.1", fill: "currentColor", stroke: "none" }),
    ]);
  }
  if (questionType === "booking" || questionType === "availability") {
    return svgIcon([svgPath("M7 4v3M17 4v3M5 9h14M6 6h12a1 1 0 0 1 1 1v11a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1z")]);
  }
  if (questionType === "equipment") return svgIcon([svgPath("M14.5 6.5l3 3M4 20l8.5-8.5a2.1 2.1 0 0 0-3-3L4 14v6h6z")]);
  if (questionType === "hours") return svgIcon([svgEl("circle", { cx: "12", cy: "12", r: "7" }), svgPath("M12 8v5l3 2")]);
  if (questionType === "diagnosis") return svgIcon([svgPath("M4 12h4l2-5 4 10 2-5h4")]);
  if (questionType === "workshop") return svgIcon([svgPath("M4 11l8-7 8 7v8a1 1 0 0 1-1 1h-5v-6H10v6H5a1 1 0 0 1-1-1z")]);
  if (kind === "root") return svgIcon([svgPath("M6 17l-2 3V7a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H8z")]);
  if (kind === "service") return svgIcon([svgPath("M12 3s5 6 5 10a5 5 0 0 1-10 0c0-4 5-10 5-10z")]);
  return svgIcon([
    svgEl("circle", { cx: "7", cy: "8", r: "2.1" }),
    svgEl("circle", { cx: "16", cy: "8", r: "2.1" }),
    svgEl("circle", { cx: "11.5", cy: "16", r: "2.1" }),
    svgPath("M8.6 9.4l1.8 4.2M15.2 9.5l-1.8 4.1"),
  ]);
}

function brandMark() {
  return svgIcon([
    svgEl("circle", { cx: "6", cy: "15", r: "2.3", fill: "currentColor", stroke: "none" }),
    svgEl("circle", { cx: "13", cy: "7", r: "2.3", fill: "currentColor", stroke: "none" }),
    svgEl("circle", { cx: "18", cy: "16", r: "2.3", fill: "currentColor", stroke: "none" }),
    svgPath("M8 13.6L11.2 8.6M8.2 15.4l7.6 1.2"),
  ], 26);
}

function refreshGlyph() {
  return svgIcon([svgPath("M20 12a8 8 0 1 1-2.2-5.5M20 4v5h-5")], 16);
}

function measureLabel(text) {
  const value = String(text || "");
  if (typeof document === "undefined") return value.length * 7.2;
  if (!labelRuler) {
    labelRuler = document.createElement("span");
    labelRuler.style.cssText = "position:absolute;left:-9999px;top:0;white-space:pre;visibility:hidden;";
    document.body.append(labelRuler);
  }
  labelRuler.style.font = LABEL_FONT;
  labelRuler.textContent = value;
  return labelRuler.getBoundingClientRect().width;
}

function measureNode(row, subtitle) {
  const raw = measureLabel(row.label);
  const textWidth = Math.min(Math.max(raw, 64), 280);
  const wrapped = raw > 280;
  const leaf = row.kind === "question_type" || row.kind === "exchange";
  const lead = row.kind === "root" ? 8 : 18;
  const width = Math.round(16 + lead + 18 + 8 + textWidth + (leaf ? 36 : 0) + 14);
  const height = Math.round(16 + (wrapped ? 36 : 18) + (subtitle ? 16 : 0));
  return { width, height };
}

function buildVisibleTree(rows) {
  if (!rows.length || !rows[0] || !rows[0].id) return null;
  const root = { ...rows[0], children: [] };
  const stack = [root];
  for (const row of rows.slice(1)) {
    if (row.pending || row.error || row.empty) {
      const parent = stack[row.depth - 1];
      if (!parent) continue;
      parent.children.push({
        id: `${row.pending ? "pending" : row.error ? "error" : "empty"}:${row.parentId}`,
        kind: "note",
        note: row.pending ? "pending" : row.error ? "error" : "empty",
        parentRef: row.parentId,
        depth: row.depth,
        children: [],
      });
      continue;
    }
    const node = { ...row, children: [] };
    while (stack.length > row.depth) stack.pop();
    const parent = stack[row.depth - 1];
    if (parent) parent.children.push(node);
    stack[row.depth] = node;
  }
  return root;
}

function assignPalette(node, name) {
  node.palette = name;
  node.children.forEach((child, index) => {
    const next = node.kind === "root" ? PALETTE_CYCLE[index % PALETTE_CYCLE.length] : name;
    assignPalette(child, next);
  });
}

function markPath(node, selectedId) {
  let hit = node.id === selectedId;
  for (const child of node.children) {
    if (markPath(child, selectedId)) hit = true;
  }
  node.onPath = hit;
  return hit;
}

function flattenMeasured(node, parentId, items, byId, strings) {
  if (node.kind === "note") {
    node.width = node.note === "error" ? 360 : 188;
    node.height = node.note === "error" ? 52 : 36;
  } else {
    const subtitle = nodeSubtitle(node, strings);
    const size = measureNode(node, subtitle);
    node.width = size.width;
    node.height = size.height;
    node.subtitle = subtitle;
  }
  node.parentId = parentId;
  items.push({ id: node.id, parentId, width: node.width, height: node.height });
  byId.set(node.id, node);
  for (const child of node.children) flattenMeasured(child, node.id, items, byId, strings);
}

function boundsOf(placed) {
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const box of placed) {
    minX = Math.min(minX, box.x);
    minY = Math.min(minY, box.y);
    maxX = Math.max(maxX, box.x + box.width);
    maxY = Math.max(maxY, box.y + box.height);
  }
  if (!Number.isFinite(minX)) return { minX: 0, minY: 0, width: 1, height: 1 };
  return {
    minX: minX - 12,
    minY: minY - 12,
    width: Math.max(1, maxX - minX + 24),
    height: Math.max(1, maxY - minY + 24),
  };
}

function renderState(kind, strings, error) {
  const wrap = el("div", { className: `qt-state qt-state-${kind}` });
  const card = el("div", {
    className: "qt-state-card",
    attrs: { role: kind === "error" ? "alert" : "status" },
  });
  if (kind === "loading") {
    card.append(el("h2", { text: strings.loading }));
  } else if (kind === "empty") {
    card.append(el("h2", { text: strings.emptyTitle }), el("p", { text: strings.emptyLead }));
  } else if (kind === "review-only") {
    card.append(
      el("h2", { text: strings.reviewOnlyTitle }),
      el("p", { text: strings.reviewOnlyLead }),
      button(strings.reviewOnlyAction, { "data-open-review": "true" }, "qt-button qt-button-primary"),
    );
  } else {
    card.append(el("h2", { text: strings.errorTitle }), el("p", { text: errorCopy(error, strings) }));
    if (error && error.detail) card.append(el("p", { text: error.detail }));
    card.append(button(strings.retry, { "data-retry": "true" }, "qt-button qt-button-primary"));
  }
  wrap.append(card);
  return wrap;
}

function renderInlineError(model, strings) {
  const card = el("div", { className: "qt-inline-error", attrs: { role: "alert" } });
  card.append(el("h2", { text: strings.errorTitle }), el("p", { text: errorCopy(model.error, strings) }));
  if (model.error && model.error.detail) card.append(el("p", { text: model.error.detail }));
  card.append(button(strings.retry, { "data-retry": "true" }, "qt-button qt-button-primary"));
  return card;
}

function renderExchange(item, strings, linked) {
  const selected = Boolean(
    linked
    && linked.conversationId === item.conversationId
    && linked.requestId === item.requestId
  );
  const article = el("li", {
    className: selected ? "qt-exchange is-linked" : "qt-exchange",
    attrs: {
      "data-request-id": item.requestId,
      "data-conversation-id": item.conversationId,
    },
  });
  const head = el("div", { className: "qt-exchange-head" });
  const when = formatExchangedAt(item.exchangedAt) || item.exchangedAt;
  const time = el("time", { className: "qt-time", text: when });
  if (item.exchangedAt && !Number.isNaN(new Date(item.exchangedAt).getTime())) time.dateTime = item.exchangedAt;
  head.append(time);
  const feedback = feedbackText(item.feedback, strings);
  if (feedback) head.append(el("p", { className: "qt-feedback", text: feedback }));
  article.append(head);
  if (item.questionTypes.length > 1) {
    article.append(el("p", {
      className: "qt-types",
      text: item.questionTypes.map(questionTypeLabel).join(" · "),
      attrs: { lang: "ru" },
    }));
  }
  const pair = el("div", { className: "qt-pair" });
  for (const turn of [
    ["customer", strings.customer, item.customerMessage],
    ["assistant", strings.assistant, item.assistantReply],
  ]) {
    const block = el("div", { className: `qt-turn qt-turn-${turn[0]}` });
    block.append(
      el("p", { className: "qt-who", text: turn[1] }),
      el("div", { className: "qt-bubble", text: turn[2], attrs: { lang: "ru" } }),
    );
    pair.append(block);
  }
  article.append(pair);
  return article;
}

function renderInspector(model, strings, quality) {
  if (quality && quality.open) return renderQualityInspector(strings, quality);
  const pane = el("aside", {
    className: "qt-inspector",
    attrs: { "data-inspector": "true", "aria-label": strings.historyLabel },
  });
  const inner = el("div", { className: "qt-inspector-inner" });
  inner.append(button(strings.backToTree, { "data-show-tree": "true" }, "qt-button qt-drawer-back"));
  if (model.phase === "loading") {
    inner.append(el("p", { className: "qt-history-status", attrs: { role: "status" }, text: strings.loading }));
    pane.append(inner);
    return pane;
  }
  if (model.phase === "empty") {
    inner.append(el("h2", { text: strings.emptyTitle }), el("p", { className: "qt-history-status", text: strings.emptyLead }));
    pane.append(inner);
    return pane;
  }
  if (model.phase === "error") {
    inner.append(renderInlineError(model, strings));
    pane.append(inner);
    return pane;
  }
  const row = model.rows.find((item) => item.id === model.selectedId) || null;
  const crumbs = model.branch.length > 1 ? model.branch.slice(0, -1).join(" / ") : "";
  if (crumbs) inner.append(el("p", { className: "qt-crumb", text: crumbs, attrs: { lang: "ru" } }));
  const hero = el("div", { className: "qt-hero" });
  const mark = el("span", { className: "qt-hero-mark", attrs: { "aria-hidden": "true" } });
  mark.append(kindIcon(row ? row.kind : "root", row ? row.questionType : null));
  const copy = el("div");
  const frequentTitle = model.view === "frequent" && row && row.depth > 0 ? frequentCardTitle(row) : "";
  const reviewTitle = model.view === "review" && row && typeof row.preview === "string" && row.preview.trim()
    ? row.preview
    : "";
  const heading = reviewTitle || frequentTitle || (model.branch.length ? model.branch[model.branch.length - 1] : strings.historyLabel);
  copy.append(el("h2", { text: heading, attrs: { lang: "ru" } }));
  if (model.exchangeCount !== null) {
    const countLine = unitPhrase(model.exchangeCount, strings, "exchange");
    const rating = row ? ratingText(row.averageStars, row.ratingCount, strings) : null;
    copy.append(el("p", {
      className: "qt-hero-count",
      text: rating ? `${countLine} · ${rating}` : countLine,
    }));
  }
  hero.append(mark, copy);
  inner.append(hero);
  if (model.view === "review" && row && row.depth > 0 && !reviewTitle) {
    inner.append(el("p", { className: "qt-history-status", text: strings.messageUnavailable }));
  }
  if (model.view === "review" && row && row.depth > 0) {
    inner.append(el("p", { className: "qt-reason", text: reviewReason(row, strings) }));
  } else if (row && row.needsReview) {
    inner.append(el("p", { className: "qt-mark", text: strings.reviewMark }));
  }
  const context = el("div", { className: "qt-context" });
  let contextUsed = false;
  if (row && row.serviceLabel && !model.branch.includes(row.serviceLabel)) {
    context.append(el("p", { text: row.serviceLabel, attrs: { lang: "ru" } }));
    contextUsed = true;
  }
  if (row && !row.serviceLabel && row.suppliedServiceId) {
    context.append(el("p", { text: `${strings.suppliedLabel}: ${row.suppliedServiceId}` }));
    contextUsed = true;
  }
  if (contextUsed) inner.append(context);
  if (model.view !== "tree" && canRevealRow(row)) {
    inner.append(button(strings.showOnTree, { "data-open-tree": row.id }, "qt-button"));
  }
  if (model.historyStatus === "loading") {
    inner.append(el("p", { className: "qt-history-status", attrs: { role: "status" }, text: strings.loading }));
  } else if (model.historyStatus === "error") {
    inner.append(renderInlineError(model, strings));
  } else if (model.historyStatus === "branch-empty") {
    inner.append(el("p", { className: "qt-history-status", attrs: { role: "status" }, text: strings.historyEmpty }));
  } else if (model.historyStatus === "ready") {
    const list = el("ol", { className: "qt-thread" });
    for (const item of model.history) list.append(renderExchange(item, strings, model.linkedExchange));
    inner.append(list);
    if (model.page && model.page.total > model.page.limit) {
      const pager = el("div", { className: "qt-pager" });
      pager.append(
        button(strings.previous, { "data-step": "-1", disabled: !model.page.hasPrev }),
        el("p", { className: "qt-page", text: fill(strings.page, model.page) }),
        button(strings.next, { "data-step": "1", disabled: !model.page.hasNext }),
      );
      inner.append(pager);
    } else if (model.page && model.page.total > 0) {
      inner.append(el("p", { className: "qt-page", text: fill(strings.page, model.page) }));
    }
  }
  pane.append(inner);
  return pane;
}

function orderedReview(rows) {
  return rows
    .filter((row) => row.depth > 0)
    .map((row, index) => ({ row, index }))
    .sort((a, b) => {
      const left = Date.parse(a.row.previewAt || "");
      const right = Date.parse(b.row.previewAt || "");
      if (Number.isNaN(left) && Number.isNaN(right)) return a.index - b.index;
      if (Number.isNaN(left)) return 1;
      if (Number.isNaN(right)) return -1;
      return right - left || a.index - b.index;
    })
    .map((item) => item.row);
}

function countBlock(count, strings) {
  const wrap = el("span", { className: "qt-count" });
  wrap.append(
    el("span", {
      className: "qt-badge",
      text: String(count),
      attrs: { "aria-label": unitPhrase(count, strings, "exchange") },
    }),
    el("span", { className: "qt-count-word", text: strings[`exchange${pluralForm(count)}`] }),
  );
  return wrap;
}

function serviceContextLine(row, strings) {
  if (row.serviceId && row.serviceLabel) return row.serviceLabel;
  if (row.suppliedServiceId) return `${strings.suppliedLabel}: ${row.suppliedServiceId}`;
  return "";
}

function renderCard(row, index, model, strings) {
  const card = el("div", {
    className: row.selected ? "qt-card is-selected" : "qt-card",
    attrs: {
      "data-select": row.id,
      "data-node-id": row.id,
      tabindex: row.selected ? "0" : "-1",
    },
  });
  const top = el("div", { className: "qt-card-top" });
  const frequent = model.view === "frequent";
  const titleText = frequent
    ? frequentCardTitle(row)
    : (typeof row.preview === "string" && row.preview.trim() ? row.preview : strings.messageUnavailable);
  const title = el("span", {
    className: titleText === strings.messageUnavailable ? "qt-card-title is-missing" : "qt-card-title",
    text: titleText,
    attrs: { lang: "ru" },
  });
  if (frequent) {
    const line = el("div", { className: "qt-card-line" });
    line.append(el("span", { className: "qt-rank", text: String(index + 1).padStart(2, "0") }), title);
    top.append(line, countBlock(row.count, strings));
  } else {
    top.append(title);
  }
  card.append(top);
  if (frequent && row.categoryLabel && row.categoryLabel !== row.serviceLabel && row.categoryLabel !== titleText) {
    card.append(el("p", { className: "qt-card-meta", text: row.categoryLabel, attrs: { lang: "ru" } }));
  }
  if (!frequent) {
    const service = serviceContextLine(row, strings);
    if (service) card.append(el("p", { className: "qt-card-meta", text: service, attrs: { lang: "ru" } }));
    card.append(el("p", { className: "qt-reason", text: reviewReason(row, strings) }));
    const earlier = previousCustomerContext(row.preview, {
      conversationId: row.conversationId,
      requestId: row.requestId,
      exchangedAt: row.previewAt,
    }, model.context);
    if (earlier) {
      card.append(el("p", {
        className: "qt-earlier",
        text: `${strings.earlierContext}: ${earlier}`,
        attrs: { lang: "ru" },
      }));
    }
    if (row.previewAt) {
      card.append(el("p", { className: "qt-card-meta", text: formatExchangedAt(row.previewAt) || row.previewAt }));
    }
  }
  const rating = ratingText(row.averageStars, row.ratingCount, strings);
  if (rating) card.append(el("p", { className: "qt-rating", text: rating }));
  if (frequent && canRevealRow(row)) {
    card.append(button(strings.showOnTree, { "data-open-tree": row.id }, "qt-card-action"));
  }
  return card;
}

function renderBoard(model, strings) {
  const board = el("section", {
    className: "qt-board",
    attrs: { "aria-label": strings[VIEW_TEXT[model.view]] },
  });
  const inner = el("div", { className: "qt-board-inner" });
  inner.append(el("p", { className: "qt-lead", text: model.view === "review" ? strings.reviewLead : strings.frequentLead }));
  const cards = model.view === "review"
    ? orderedReview(model.rows)
    : model.rows.filter((row) => row.depth > 0);
  if (!cards.length) {
    const text = model.view === "review" ? strings.reviewClear : strings.historyEmpty;
    inner.append(el("p", { className: "qt-history-status", text }));
  } else {
    const list = el("div", { className: "qt-card-list" });
    cards.forEach((row, index) => list.append(renderCard(row, index, model, strings)));
    inner.append(list);
  }
  board.append(inner);
  return board;
}

function renderGraphNode(node, box, strings) {
  const item = el("div", {
    className: `qt-node${node.selected ? " is-selected" : ""}${node.onPath ? " is-path" : ""}`,
    attrs: {
      role: "treeitem",
      tabindex: node.selected ? "0" : "-1",
      "data-node-id": node.id,
      "data-select": node.id,
      "data-kind": node.kind,
      "data-palette": node.palette || "sage",
      "data-expandable": node.expandable ? "true" : "false",
      "aria-selected": node.selected ? "true" : "false",
      "aria-level": String((node.depth || 0) + 1),
      "aria-expanded": node.expandable ? String(Boolean(node.expanded)) : null,
      "data-parent-id": node.parentId || "",
      title: node.label,
    },
  });
  item.style.width = `${box.width}px`;
  item.style.height = `${box.height}px`;
  item.style.transform = `translate(${box.x}px, ${box.y}px)`;
  item.dataset.x = String(box.x);
  item.dataset.y = String(box.y);
  item.dataset.w = String(box.width);
  item.dataset.h = String(box.height);
  if (node.kind !== "root") {
    item.append(el("span", { className: "qt-port qt-port-in", attrs: { "aria-hidden": "true" } }));
  }
  if (node.expandable) {
    const toggle = button("", {
      "data-expand": node.id,
      tabindex: "-1",
      "aria-expanded": node.expanded ? "true" : "false",
      "aria-label": `${node.expanded ? strings.collapse : strings.expand}: ${node.label}`,
    }, "qt-expand");
    toggle.append(svgIcon([svgPath(node.expanded ? "M6 12h12" : "M12 6v12M6 12h12")], 12));
    item.append(toggle);
  }
  const icon = el("span", { className: "qt-node-icon", attrs: { "aria-hidden": "true" } });
  icon.append(kindIcon(node.kind, node.questionType));
  const copy = el("span", { className: "qt-node-copy" });
  copy.append(el("span", { className: "qt-node-label", text: node.label, attrs: { lang: "ru" } }));
  if (node.subtitle) copy.append(el("span", { className: "qt-node-sub", text: node.subtitle }));
  item.append(icon, copy);
  if (node.kind === "question_type" || node.kind === "exchange") {
    item.append(el("span", {
      className: "qt-badge",
      text: String(node.count),
      attrs: { "aria-label": `${node.count}, ${strings.countColumn}` },
    }));
  } else {
    item.append(el("span", { className: "qt-port qt-port-out", attrs: { "aria-hidden": "true" } }));
  }
  return item;
}

function renderNote(node, box, strings) {
  const chip = el("div", {
    className: node.note === "error" ? "qt-note-chip is-error" : "qt-note-chip",
    attrs: {
      "data-node-id": node.id,
      "data-parent-id": node.parentId || "",
      role: node.note === "error" ? "alert" : "status",
    },
  });
  chip.style.width = `${box.width}px`;
  chip.style.height = `${box.height}px`;
  chip.style.transform = `translate(${box.x}px, ${box.y}px)`;
  chip.dataset.x = String(box.x);
  chip.dataset.y = String(box.y);
  chip.dataset.w = String(box.width);
  chip.dataset.h = String(box.height);
  chip.dataset.autoX = String(box.x);
  chip.dataset.autoY = String(box.y);
  if (node.note === "error") {
    chip.append(
      el("span", { text: strings.openError }),
      button(strings.retry, { "data-retry-expand": node.parentRef }, "qt-button qt-button-primary qt-retry"),
    );
  } else if (node.note === "empty") {
    chip.append(el("span", { text: strings.noChildren }));
  } else {
    chip.append(el("span", { text: strings.loadingBranch }));
  }
  return chip;
}

function edgePath(parent, box, bounds) {
  const x1 = parent.x + parent.width - bounds.minX;
  const y1 = parent.y + parent.height / 2 - bounds.minY;
  const x2 = box.x - bounds.minX;
  const y2 = box.y + box.height / 2 - bounds.minY;
  const bend = Math.max(28, Math.abs(x2 - x1) * 0.45);
  return `M ${x1.toFixed(1)} ${y1.toFixed(1)} C ${(x1 + bend).toFixed(1)} ${y1.toFixed(1)}, ${(x2 - bend).toFixed(1)} ${y2.toFixed(1)}, ${x2.toFixed(1)} ${y2.toFixed(1)}`;
}

function renderCanvas(model, strings, offsets) {
  const canvas = el("section", {
    className: "qt-canvas",
    attrs: { "data-canvas": "true", "aria-label": strings.canvasLabel },
  });
  const tree = buildVisibleTree(model.rows);
  if (!tree) {
    canvas.append(renderState("empty", strings, null));
    return { element: canvas, layout: null };
  }
  assignPalette(tree, "petrol");
  markPath(tree, model.selectedId);
  const items = [];
  const byId = new Map();
  flattenMeasured(tree, null, items, byId, strings);
  const automatic = arrangeQuestionNodes(items);
  const autoNodes = automatic.map((box) => {
    const source = items.find((item) => item.id === box.id);
    return { ...box, parentId: source ? source.parentId : null };
  });
  const placed = placedWithOffsets(autoNodes, offsets);
  const placeById = new Map(placed.map((item) => [item.id, item]));
  const autoById = new Map(autoNodes.map((item) => [item.id, item]));
  const bounds = boundsOf(placed);
  const world = el("div", {
    className: "qt-world",
    attrs: { "data-world": "true", role: "tree", "aria-label": strings.canvasLabel },
  });
  const svg = svgEl("svg", {
    class: "qt-edges",
    viewBox: `0 0 ${bounds.width} ${bounds.height}`,
    width: bounds.width,
    height: bounds.height,
    "aria-hidden": "true",
  });
  svg.style.left = `${bounds.minX}px`;
  svg.style.top = `${bounds.minY}px`;
  for (const node of byId.values()) {
    if (!node.parentId) continue;
    const parent = placeById.get(node.parentId);
    const box = placeById.get(node.id);
    if (!parent || !box) continue;
    const palette = PALETTES[node.palette] || PALETTES.sage;
    svg.append(svgEl("path", {
      d: edgePath(parent, box, bounds),
      "data-from": node.parentId,
      "data-to": node.id,
      fill: "none",
      stroke: palette.edge,
      "stroke-width": node.onPath ? "2.25" : "1.5",
      "stroke-linecap": "round",
      opacity: node.onPath ? "1" : "0.8",
      "stroke-dasharray": node.kind === "note" ? "3 4" : null,
    }));
  }
  const nodes = el("div", { className: "qt-nodes" });
  for (const node of byId.values()) {
    const box = placeById.get(node.id);
    if (!box) continue;
    const view = node.kind === "note" ? renderNote(node, box, strings) : renderGraphNode(node, box, strings);
    const auto = autoById.get(node.id);
    if (auto) {
      view.dataset.autoX = String(auto.x);
      view.dataset.autoY = String(auto.y);
    }
    nodes.append(view);
  }
  world.append(svg, nodes);
  const zoom = el("div", { className: "qt-zoom", attrs: { role: "group", "aria-label": strings.zoomReset } });
  zoom.append(
    button("−", { "data-zoom": "out", "aria-label": strings.zoomOut }, ""),
    button("100%", { "data-zoom": "0", "data-zoom-label": "true", "aria-label": strings.zoomReset }, ""),
    button("+", { "data-zoom": "in", "aria-label": strings.zoomIn }, ""),
  );
  const layoutBar = el("div", { className: "qt-layout-bar", attrs: { role: "group", "aria-label": strings.resetLayout } });
  layoutBar.append(
    button(strings.resetLayout, { "data-reset-layout": "true" }),
    button(strings.fitView, { "data-fit": "true" }),
  );
  const map = el("div", {
    className: "qt-map",
    attrs: { "data-minimap": "true", role: "group", "aria-label": strings.minimapLabel },
  });
  const mapSvg = svgEl("svg", { viewBox: `${bounds.minX} ${bounds.minY} ${bounds.width} ${bounds.height}` });
  for (const node of byId.values()) {
    if (node.kind === "note") continue;
    const box = placeById.get(node.id);
    if (!box) continue;
    mapSvg.append(svgEl("rect", {
      "data-node-id": node.id,
      "data-palette": node.palette || "sage",
      "data-kind": node.kind,
      class: node.selected || node.kind === "root" ? "qt-map-node is-selected" : "qt-map-node",
      x: box.x,
      y: box.y,
      width: box.width,
      height: box.height,
      rx: "12",
    }));
  }
  map.append(mapSvg, el("div", { className: "qt-map-view", attrs: { "data-map-view": "true" } }));
  canvas.append(world, layoutBar, zoom, map);
  return { element: canvas, layout: { bounds, nodes: placed, autoNodes } };
}

function qualityBucketLabel(bucket, strings) {
  if (bucket === "positive") return strings.qualityPositive;
  if (bucket === "examine") return strings.qualityExamine;
  if (bucket === "conflict") return strings.qualityConflict;
  if (bucket === "other") return strings.qualityOther;
  if (bucket === "approved") return strings.qualityApproved;
  if (bucket === "excluded") return strings.qualityExcluded;
  return bucket;
}

function renderQualityInspector(strings, quality) {
  const pane = el("aside", {
    className: "qt-inspector qt-quality",
    attrs: { "data-inspector": "true", "aria-label": strings.qualityTitle },
  });
  const inner = el("div", { className: "qt-inspector-inner" });
  inner.append(
    el("h2", { text: strings.qualityTitle }),
    el("p", { className: "qt-quality-note", text: strings.qualityNote }),
  );
  const filters = el("div", { className: "qt-quality-filters", attrs: { role: "group", "aria-label": strings.qualityTitle } });
  for (const bucket of ["positive", "examine", "conflict", "other", "approved", "excluded"]) {
    filters.append(button(qualityBucketLabel(bucket, strings), {
      "data-quality-bucket": bucket,
      "data-quality-key": `bucket-${bucket}`,
      "aria-pressed": quality.bucket === bucket ? "true" : "false",
    }, "qt-button"));
  }
  inner.append(filters);
  if (quality.notice) inner.append(el("p", { className: "qt-quality-note", attrs: { role: "status" }, text: quality.notice }));
  if (quality.loading) {
    inner.append(el("p", { className: "qt-history-status", attrs: { role: "status" }, text: strings.loading }));
  } else if (quality.error) {
    inner.append(el("p", { className: "qt-history-status", attrs: { role: "alert" }, text: quality.error }));
  } else if (!quality.page || quality.page.total === 0) {
    inner.append(el("p", { className: "qt-history-status", text: strings.qualityEmpty }));
  } else {
    const list = el("ol", { className: "qt-thread" });
    for (const item of quality.page.items) {
      const article = el("li", {
        className: "qt-exchange",
        attrs: {
          "data-conversation-id": item.conversation_id,
          "data-request-id": item.request_id,
        },
      });
      const signal = qualitySignal(item.feedback);
      const head = el("p", { className: "qt-feedback", text: feedbackText(item.feedback, strings) || qualityBucketLabel(signal || item.signal, strings) });
      article.append(head);
      if (item.reopened) article.append(el("p", { className: "qt-quality-note", text: strings.qualityReopened }));
      if (signal === "examine" || (item.feedback && item.feedback.stars >= 1 && item.feedback.stars <= 2)) {
        article.append(el("p", { className: "qt-quality-note", text: strings.qualityLowNote }));
      }
      if (signal === "conflict") article.append(el("p", { className: "qt-quality-note", text: strings.qualityConflictNote }));
      if (Array.isArray(item.context) && item.context.length) {
        const context = el("div", { className: "qt-quality-context" });
        context.append(el("p", { className: "qt-who", text: strings.qualityContext }));
        for (const turn of item.context) {
          const who = turn.speaker === "assistant" ? strings.assistant : strings.customer;
          context.append(el("p", { text: `${who}: ${turn.text}` }));
        }
        article.append(context);
      }
      article.append(el("div", { className: "qt-bubble", text: item.customer_message, attrs: { lang: "ru" } }));
      article.append(el("div", { className: "qt-bubble", text: item.assistant_reply, attrs: { lang: "ru" } }));
      const actions = el("div", { className: "qt-quality-actions" });
      actions.append(
        button(strings.qualityApprove, {
          "data-quality-decision": "approved",
          "data-conversation-id": item.conversation_id,
          "data-request-id": item.request_id,
          "data-quality-key": `approve-${item.conversation_id}-${item.request_id}`,
        }, "qt-button qt-button-primary"),
        button(strings.qualityExclude, {
          "data-quality-decision": "excluded",
          "data-conversation-id": item.conversation_id,
          "data-request-id": item.request_id,
          "data-quality-key": `exclude-${item.conversation_id}-${item.request_id}`,
        }, "qt-button"),
      );
      article.append(actions);
      list.append(article);
    }
    inner.append(list);
  }
  inner.append(button(strings.qualityExport, { "data-quality-export": "true", "data-quality-key": "export" }, "qt-button"));
  pane.append(inner);
  return pane;
}

function renderHeader(strings, theme, view, qualityOpen) {
  const header = el("header", { className: "qt-topbar" });
  const brand = el("div", { className: "qt-brand" });
  const mark = el("span", { className: "qt-brand-mark", attrs: { "aria-hidden": "true" } });
  mark.append(brandMark());
  brand.append(mark, el("h1", { className: "qt-title", text: strings.brandTitle }));
  const views = el("div", {
    className: "qt-views",
    attrs: { role: "tablist", "aria-label": strings.viewsLabel },
  });
  for (const name of VIEWS) {
    views.append(button(strings[VIEW_TEXT[name]], {
      role: "tab",
      "data-view": name,
      "aria-selected": name === view ? "true" : "false",
      tabindex: name === view ? "0" : "-1",
    }, ""));
  }
  const tools = el("div", { className: "qt-tools" });
  const nav = el("div", { className: "qt-nav" });
  nav.append(
    button(strings.showHistory, { "data-show-history": "true" }),
    button(strings.backToTree, { "data-show-tree": "true" }),
  );
  const refresh = button("", { "data-refresh": "true", "aria-label": strings.refresh }, "qt-icon-button");
  refresh.append(refreshGlyph());
  const themeBar = el("div", {
    className: "qt-theme",
    attrs: { role: "group", "aria-label": strings.themeLabel },
  });
  for (const [name, label] of [
    ["light", strings.themeLight],
    ["dark", strings.themeDark],
    ["system", strings.themeSystem],
  ]) {
    themeBar.append(button(label, {
      "data-theme": name,
      "aria-pressed": theme === name ? "true" : "false",
    }, ""));
  }
  const qualityButton = button(strings.qualityToggle, {
    "data-quality-toggle": "true",
    "data-quality-key": "toggle",
    "aria-pressed": qualityOpen ? "true" : "false",
  }, "qt-button");
  tools.append(nav, qualityButton, refresh, themeBar);
  header.append(brand, views, tools);
  return header;
}

function stringsComplete(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  return Object.keys(FALLBACK_STRINGS).every((key) => typeof value[key] === "string" && value[key] !== "");
}

function cssEscape(value) {
  if (typeof CSS !== "undefined" && typeof CSS.escape === "function") return CSS.escape(value);
  return String(value).replace(/["\\]/g, "\\$&");
}

function clampZoom(value) {
  return Math.min(2.4, Math.max(0.18, value));
}

export function mountQuestionTree(root, { loader = loadQuestionTree, stress = false } = {}) {
  const session = createQuestionTreeSession({ loader });
  const locale = "ru";
  let strings = FALLBACK_STRINGS;
  let bootReady = false;
  let lastLayout = null;
  let pendingAnchor = null;
  let holdCamera = false;
  let suppressClick = false;
  let nodeGesture = null;
  const camera = { x: 48, y: 40, zoom: 1, userMoved: false };
  const pointers = new Map();
  let panBase = null;
  let pinchBase = null;
  let mapDrag = null;
  let offsets = readStoredOffsets(storedValue(PLACEMENT_STORAGE_KEY));
  let themeChoice = normalizeTheme(storedValue(THEME_STORAGE_KEY));
  let scene = null;
  let linkNotice = null;
  const qualityState = {
    open: false,
    bucket: "positive",
    offset: 0,
    page: null,
    loading: false,
    error: "",
    notice: "",
    serial: 0,
  };
  const shell = el("div", { className: "qt-shell" });
  const header = el("div", { attrs: { "data-region": "header" } });
  const body = el("div", { className: "qt-body", attrs: { "data-region": "body" } });
  const banner = el("div", { attrs: { "data-region": "banner" } });
  shell.append(header, banner, body);
  root.replaceChildren(shell);

  function applyCamera() {
    const world = root.querySelector("[data-world]");
    const canvas = root.querySelector("[data-canvas]");
    if (world) world.style.transform = `translate(${camera.x}px, ${camera.y}px) scale(${camera.zoom})`;
    if (canvas) {
      const size = 18 * camera.zoom;
      canvas.style.backgroundSize = `${size}px ${size}px`;
      canvas.style.backgroundPosition = `${camera.x}px ${camera.y}px`;
    }
    const label = root.querySelector("[data-zoom-label]");
    if (label) label.textContent = `${Math.round(camera.zoom * 100)}%`;
    const view = root.querySelector("[data-map-view]");
    if (view && canvas && lastLayout && lastLayout.bounds.width > 0 && lastLayout.bounds.height > 0) {
      const bounds = lastLayout.bounds;
      const left = -camera.x / camera.zoom;
      const top = -camera.y / camera.zoom;
      view.style.left = `${((left - bounds.minX) / bounds.width) * 100}%`;
      view.style.top = `${((top - bounds.minY) / bounds.height) * 100}%`;
      view.style.width = `${(canvas.clientWidth / camera.zoom / bounds.width) * 100}%`;
      view.style.height = `${(canvas.clientHeight / camera.zoom / bounds.height) * 100}%`;
    }
    if (world) shell.dataset.placed = "true";
  }

  function fitCamera() {
    const canvas = root.querySelector("[data-canvas]");
    if (!canvas || !lastLayout) return false;
    const bounds = lastLayout.bounds;
    const viewWidth = canvas.clientWidth;
    const viewHeight = canvas.clientHeight;
    if (viewWidth < 40 || viewHeight < 40 || bounds.width < 1 || bounds.height < 1) return false;
    const pad = 72;
    camera.zoom = clampZoom(Math.min((viewWidth - pad * 2) / bounds.width, (viewHeight - pad * 2) / bounds.height, 1));
    camera.x = viewWidth / 2 - (bounds.minX + bounds.width / 2) * camera.zoom;
    camera.y = viewHeight / 2 - (bounds.minY + bounds.height / 2) * camera.zoom;
    return true;
  }

  function zoomAt(clientX, clientY, nextZoom) {
    const canvas = root.querySelector("[data-canvas]");
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const px = clientX - rect.left;
    const py = clientY - rect.top;
    const worldX = (px - camera.x) / camera.zoom;
    const worldY = (py - camera.y) / camera.zoom;
    camera.zoom = clampZoom(nextZoom);
    camera.x = px - worldX * camera.zoom;
    camera.y = py - worldY * camera.zoom;
    camera.userMoved = true;
    applyCamera();
  }

  function centerOnNode(id, zoom) {
    const canvas = root.querySelector("[data-canvas]");
    const node = root.querySelector(`[data-node-id="${cssEscape(id)}"]`);
    if (!canvas || !node || node.dataset.x === undefined) return false;
    if (zoom) camera.zoom = clampZoom(zoom);
    const x = Number(node.dataset.x);
    const y = Number(node.dataset.y);
    const width = Number(node.dataset.w);
    const height = Number(node.dataset.h);
    camera.x = canvas.clientWidth / 2 - (x + width / 2) * camera.zoom;
    camera.y = canvas.clientHeight / 2 - (y + height / 2) * camera.zoom;
    camera.userMoved = true;
    applyCamera();
    return true;
  }

  function applyNodeAnchor(before) {
    const node = root.querySelector(`[data-node-id="${cssEscape(before.id)}"]`);
    if (!node || node.dataset.x === undefined) return false;
    const next = cameraForAnchor(camera, before, {
      x: Number(node.dataset.x),
      y: Number(node.dataset.y),
      width: Number(node.dataset.w),
      height: Number(node.dataset.h),
    });
    camera.x = next.x;
    camera.y = next.y;
    camera.zoom = next.zoom;
    applyCamera();
    return true;
  }

  function settle(model) {
    if (!bootReady || model.view !== "tree" || model.phase !== "ready") {
      holdCamera = false;
      return;
    }
    if (pendingAnchor) {
      holdCamera = false;
      const anchor = pendingAnchor;
      pendingAnchor = null;
      if (!applyNodeAnchor(anchor)) applyCamera();
      camera.userMoved = true;
      return;
    }
    if (model.focusId) {
      holdCamera = false;
      const focusId = model.focusId;
      session.ackFocus();
      if (!centerOnNode(focusId, 1)) applyCamera();
      return;
    }
    if (holdCamera) {
      holdCamera = false;
      applyCamera();
      return;
    }
    if (!camera.userMoved) {
      if (!fitCamera()) {
        requestAnimationFrame(() => {
          if (!camera.userMoved) fitCamera();
          applyCamera();
        });
      }
    }
    applyCamera();
  }

  function paint() {
    const model = session.snapshot();
    const active = document.activeElement;
    const restoreId = active && root.contains(active)
      ? active.closest("[data-node-id]")?.dataset.nodeId || null
      : null;
    const restoreExpand = Boolean(active && active.closest && active.closest("[data-expand]"));
    const restoreView = active && active.dataset ? active.dataset.view || null : null;
    const restoreQuality = active && active.dataset ? active.dataset.qualityKey || null : null;
    const previousSelected = shell.dataset.selected || "";
    const previousInspector = root.querySelector("[data-inspector]");
    const previousScroll = previousInspector ? previousInspector.scrollTop : 0;
    shell.dataset.state = panelPresentation(model.phase);
    shell.dataset.pane = model.pane;
    shell.dataset.screen = model.view;
    shell.dataset.selected = model.selectedId || "";
    shell.setAttribute("aria-busy", model.phase === "loading" || model.historyStatus === "loading" ? "true" : "false");
    document.documentElement.lang = locale;
    document.title = strings.documentTitle;
    header.replaceChildren(renderHeader(strings, themeChoice, model.view, qualityState.open));
    const bannerHost = root.querySelector("[data-region='banner']");
    if (bannerHost) {
      bannerHost.replaceChildren();
      if (linkNotice) {
        const note = el("div", { className: "qt-link-banner", attrs: { role: "alert" } });
        note.append(
          el("p", { text: linkNotice === "failed" ? strings.linkFailed : strings.linkMissing }),
          el("a", { text: strings.linkBack, attrs: { href: "/team/question-tree.html" } }),
        );
        bannerHost.append(note);
      }
    }
    let main;
    let layout = null;
    if (model.phase !== "ready") {
      main = el("div", { className: "qt-main" });
      main.append(renderState(panelPresentation(model.phase), strings, model.error));
    } else if (model.view === "tree") {
      const view = renderCanvas(model, strings, offsets);
      main = view.element;
      layout = view.layout;
    } else {
      main = renderBoard(model, strings);
    }
    if (stress) {
      main.append(el("p", { className: "qt-fixture", attrs: { role: "status" }, text: strings.layoutFixture }));
    }
    const stage = el("div", { className: "qt-stage" });
    stage.append(main);
    const showInspector = model.phase === "ready";
    if (showInspector) stage.append(renderInspector(model, strings, qualityState));
    lastLayout = layout;
    if (layout && layout.autoNodes) scene = layout;
    body.replaceChildren(stage);
    const nextInspector = root.querySelector("[data-inspector]");
    if (nextInspector && previousSelected && previousSelected === shell.dataset.selected) {
      nextInspector.scrollTop = previousScroll;
    }
    const link = model.linkedExchange;
    if (link && link.scroll && link.conversationId && link.requestId) {
      const exchange = nextInspector
        ? nextInspector.querySelector(exchangeElementSelector(link.conversationId, link.requestId))
        : null;
      session.ackExchangeScroll();
      if (exchange) {
        exchange.scrollIntoView({ block: "start" });
        exchange.querySelector(".qt-turn-customer")?.scrollIntoView({ block: "nearest" });
        exchange.querySelector(".qt-turn-assistant")?.scrollIntoView({ block: "nearest" });
      }
    }
    if (restoreId) {
      const row = root.querySelector(`[data-node-id="${cssEscape(restoreId)}"]`);
      const target = restoreExpand ? row?.querySelector("[data-expand]") : row;
      target?.focus({ preventScroll: true });
    } else if (restoreQuality) {
      root.querySelector(`[data-quality-key="${cssEscape(restoreQuality)}"]`)?.focus({ preventScroll: true });
    } else if (restoreView) {
      root.querySelector(`[data-view="${restoreView}"]`)?.focus({ preventScroll: true });
    }
    settle(model);
  }

  function persistOffsets() {
    const payload = {};
    for (const [id, value] of offsets) {
      if (!id || !value || !Number.isFinite(value.x) || !Number.isFinite(value.y)) continue;
      payload[id] = {
        x: Math.round(value.x * 10) / 10,
        y: Math.round(value.y * 10) / 10,
      };
    }
    try {
      localStorage.setItem(PLACEMENT_STORAGE_KEY, JSON.stringify(payload));
    } catch {
      // The arrangement still applies for this visit when storage is blocked.
    }
  }

  function repositionWorld() {
    if (!scene || !scene.autoNodes) return;
    const placed = placedWithOffsets(scene.autoNodes, offsets);
    const placeById = new Map(placed.map((item) => [item.id, item]));
    const bounds = boundsOf(placed);
    scene = { ...scene, bounds, nodes: placed };
    lastLayout = scene;
    const world = root.querySelector("[data-world]");
    if (!world) return;
    for (const box of placed) {
      const node = world.querySelector(`[data-node-id="${cssEscape(box.id)}"]`);
      if (!node) continue;
      node.style.transform = `translate(${box.x}px, ${box.y}px)`;
      node.dataset.x = String(box.x);
      node.dataset.y = String(box.y);
    }
    const svg = world.querySelector(".qt-edges");
    if (svg) {
      svg.setAttribute("viewBox", `0 0 ${bounds.width} ${bounds.height}`);
      svg.setAttribute("width", String(bounds.width));
      svg.setAttribute("height", String(bounds.height));
      svg.style.left = `${bounds.minX}px`;
      svg.style.top = `${bounds.minY}px`;
      for (const path of svg.querySelectorAll("path")) {
        const parent = placeById.get(path.dataset.from);
        const box = placeById.get(path.dataset.to);
        if (!parent || !box) continue;
        path.setAttribute("d", edgePath(parent, box, bounds));
      }
    }
    const mapSvg = root.querySelector("[data-minimap] svg");
    if (mapSvg) {
      mapSvg.setAttribute("viewBox", `${bounds.minX} ${bounds.minY} ${bounds.width} ${bounds.height}`);
      for (const rect of mapSvg.querySelectorAll("rect")) {
        const box = placeById.get(rect.dataset.nodeId);
        if (!box) continue;
        rect.setAttribute("x", String(box.x));
        rect.setAttribute("y", String(box.y));
      }
    }
    applyCamera();
  }

  function captureAnchor(id) {
    const node = root.querySelector(`[data-node-id="${cssEscape(id)}"]`);
    if (!node || node.dataset.x === undefined) return null;
    return {
      id,
      x: Number(node.dataset.x),
      y: Number(node.dataset.y),
      width: Number(node.dataset.w),
      height: Number(node.dataset.h),
    };
  }

  function pinchSnapshot() {
    const points = [...pointers.values()];
    const a = points[0];
    const b = points[1];
    return {
      dist: Math.hypot(a.x - b.x, a.y - b.y) || 1,
      midX: (a.x + b.x) / 2,
      midY: (a.y + b.y) / 2,
      zoom: camera.zoom,
      camX: camera.x,
      camY: camera.y,
    };
  }

  function jumpMap(event, map) {
    if (!lastLayout) return;
    const rect = map.getBoundingClientRect();
    const bounds = lastLayout.bounds;
    const canvas = root.querySelector("[data-canvas]");
    if (!canvas || rect.width < 1 || rect.height < 1) return;
    const worldX = bounds.minX + ((event.clientX - rect.left) / rect.width) * bounds.width;
    const worldY = bounds.minY + ((event.clientY - rect.top) / rect.height) * bounds.height;
    camera.x = canvas.clientWidth / 2 - worldX * camera.zoom;
    camera.y = canvas.clientHeight / 2 - worldY * camera.zoom;
    camera.userMoved = true;
    applyCamera();
  }

  root.addEventListener("click", (event) => {
    if (suppressClick) {
      suppressClick = false;
      event.preventDefault();
      event.stopPropagation();
      return;
    }
    const nextNarrow = viewportNarrow();
    if (nextNarrow !== narrowApplied) {
      narrowApplied = nextNarrow;
      session.setNarrow(nextNarrow);
    }
    const expand = event.target.closest("[data-expand]");
    if (expand) {
      event.preventDefault();
      pendingAnchor = captureAnchor(expand.dataset.expand);
      void session.toggleExpanded(expand.dataset.expand).then(paint);
      return;
    }
    const stepButton = event.target.closest("[data-step]");
    if (stepButton) {
      void session.step(Number(stepButton.dataset.step)).then(paint);
      return;
    }
    const retryExpand = event.target.closest("[data-retry-expand]");
    if (retryExpand) {
      pendingAnchor = captureAnchor(retryExpand.dataset.retryExpand);
      void session.retryBranch(retryExpand.dataset.retryExpand).then(paint);
      return;
    }
    if (event.target.closest("[data-retry]")) {
      const reopen = session.snapshot().phase !== "ready";
      void session.loadSelected().then(async (model) => {
        if (reopen && model.view === "tree" && model.phase === "ready") await session.expandSpine();
        paint();
      });
      return;
    }
    if (event.target.closest("[data-open-review]")) {
      void session.setView("review").then(paint);
      return;
    }
    if (event.target.closest("[data-show-tree]")) {
      session.showTree();
      paint();
      return;
    }
    if (event.target.closest("[data-show-history]")) {
      session.showHistory();
      paint();
      return;
    }
    if (event.target.closest("[data-refresh]")) {
      holdCamera = true;
      void session.refreshVisible().then(paint);
      return;
    }
    if (event.target.closest("[data-quality-toggle]")) {
      qualityState.open = !qualityState.open;
      qualityState.notice = "";
      if (qualityState.open) {
        if (session.snapshot().narrow) session.showHistory();
        void loadQuality(qualityState.bucket, 0);
      } else {
        paint();
      }
      return;
    }
    const qualityBucket = event.target.closest("[data-quality-bucket]");
    if (qualityBucket) {
      qualityState.bucket = qualityBucket.dataset.qualityBucket;
      qualityState.notice = "";
      void loadQuality(qualityState.bucket, 0);
      return;
    }
    const qualityDecision = event.target.closest("[data-quality-decision]");
    if (qualityDecision) {
      void saveQualityDecision(
        qualityDecision.dataset.qualityDecision,
        qualityDecision.dataset.conversationId,
        qualityDecision.dataset.requestId,
      );
      return;
    }
    if (event.target.closest("[data-quality-export]")) {
      void downloadApprovedExamples();
      return;
    }
    if (event.target.closest("[data-reset-layout]")) {
      offsets = new Map();
      persistOffsets();
      camera.userMoved = false;
      paint();
      return;
    }
    const themeButton = event.target.closest(".qt-theme [data-theme]");
    if (themeButton) {
      themeChoice = normalizeTheme(themeButton.dataset.theme);
      try {
        localStorage.setItem(THEME_STORAGE_KEY, themeChoice);
      } catch {
        // The chosen theme still applies until the page is closed.
      }
      applyTheme();
      paint();
      return;
    }
    const openTree = event.target.closest("[data-open-tree]");
    if (openTree) {
      event.preventDefault();
      void session.openOnTree(openTree.dataset.openTree).then(paint);
      return;
    }
    const zoom = event.target.closest("[data-zoom]");
    if (zoom) {
      const canvas = root.querySelector("[data-canvas]");
      if (!canvas) return;
      const rect = canvas.getBoundingClientRect();
      const mode = zoom.dataset.zoom;
      const next = mode === "in" ? camera.zoom * 1.15 : mode === "out" ? camera.zoom / 1.15 : 1;
      zoomAt(rect.left + rect.width / 2, rect.top + rect.height / 2, next);
      return;
    }
    if (event.target.closest("[data-fit]")) {
      fitCamera();
      camera.userMoved = true;
      applyCamera();
      return;
    }
    const view = event.target.closest(".qt-views [data-view]");
    if (view) {
      void session.setView(view.dataset.view).then(paint);
      return;
    }
    const select = event.target.closest("[data-select]");
    if (select) void session.select(select.dataset.select).then(paint);
  });

  root.addEventListener("keydown", (event) => {
    const tab = event.target.closest(".qt-views [data-view]");
    if (tab && (event.key === "ArrowRight" || event.key === "ArrowLeft")) {
      event.preventDefault();
      const tabs = [...root.querySelectorAll(".qt-views [data-view]")];
      const index = tabs.indexOf(tab);
      const next = tabs[(index + (event.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length];
      next.focus();
      void session.setView(next.dataset.view).then(paint);
      return;
    }
    const tree = event.target.closest("[role=tree]");
    if (!tree) {
      if ((event.key === "Enter" || event.key === " ") && event.target.closest("[data-select]") && !event.target.closest("button")) {
        event.preventDefault();
        const select = event.target.closest("[data-select]");
        void session.select(select.dataset.select).then(paint);
      }
      return;
    }
    const items = [...root.querySelectorAll("[role=treeitem]")];
    const row = event.target.closest("[role=treeitem]");
    const index = items.indexOf(row);
    const focusItem = (item) => {
      if (!item) return;
      for (const entry of items) entry.tabIndex = -1;
      item.tabIndex = 0;
      item.focus({ preventScroll: true });
    };
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      focusItem(items[index + (event.key === "ArrowDown" ? 1 : -1)]);
      return;
    }
    if (event.key === "Home" || event.key === "End") {
      event.preventDefault();
      focusItem(items[event.key === "Home" ? 0 : items.length - 1]);
      return;
    }
    if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
      if (!row) return;
      event.preventDefault();
      const expand = row.querySelector("[data-expand]");
      const open = expand?.getAttribute("aria-expanded") === "true";
      const level = Number(row.getAttribute("aria-level") || "1");
      if (event.key === "ArrowRight") {
        if (expand && !open) {
          expand.click();
          return;
        }
        const child = items[index + 1];
        if (child && Number(child.getAttribute("aria-level") || "1") > level) focusItem(child);
        return;
      }
      if (open && expand) {
        expand.click();
        return;
      }
      for (let cursor = index - 1; cursor >= 0; cursor -= 1) {
        if (Number(items[cursor].getAttribute("aria-level") || "1") < level) {
          focusItem(items[cursor]);
          return;
        }
      }
      return;
    }
    if ((event.key === "Enter" || event.key === " ") && row && !event.target.closest("[data-expand]")) {
      event.preventDefault();
      void session.select(row.dataset.nodeId).then(paint);
    }
  });

  root.addEventListener("pointerdown", (event) => {
    const map = event.target.closest("[data-minimap]");
    if (map) {
      event.preventDefault();
      try { map.setPointerCapture(event.pointerId); } catch { /* The pointer may already be gone. */ }
      if (!event.target.closest("[data-map-view]")) jumpMap(event, map);
      mapDrag = { pointerId: event.pointerId, x: event.clientX, y: event.clientY, camX: camera.x, camY: camera.y };
      return;
    }
    const graphNode = event.target.closest(".qt-canvas .qt-node[data-select]");
    if (graphNode && event.button === 0 && !event.target.closest("button, a")) {
      const origin = offsets.get(graphNode.dataset.nodeId) || { x: 0, y: 0 };
      nodeGesture = {
        pointerId: event.pointerId,
        id: graphNode.dataset.nodeId,
        x: event.clientX,
        y: event.clientY,
        originX: origin.x,
        originY: origin.y,
        moved: false,
      };
      try { graphNode.setPointerCapture(event.pointerId); } catch { /* The pointer may already be gone. */ }
      return;
    }
    const canvas = event.target.closest("[data-canvas]");
    if (!canvas || event.target.closest("button, a, [data-select], .qt-zoom, .qt-layout-bar, .qt-note-chip")) return;
    if (event.button !== 0 && event.button !== 1) return;
    event.preventDefault();
    try { canvas.setPointerCapture(event.pointerId); } catch { /* Ignore a pointer that ended immediately. */ }
    pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
    shell.dataset.panning = "true";
    if (pointers.size >= 2) {
      panBase = null;
      pinchBase = pinchSnapshot();
    } else {
      panBase = { x: event.clientX, y: event.clientY, camX: camera.x, camY: camera.y };
      pinchBase = null;
    }
  });

  root.addEventListener("pointermove", (event) => {
    if (nodeGesture && event.pointerId === nodeGesture.pointerId) {
      const dx = event.clientX - nodeGesture.x;
      const dy = event.clientY - nodeGesture.y;
      if (!nodeGesture.moved && Math.hypot(dx, dy) < DRAG_THRESHOLD) return;
      nodeGesture.moved = true;
      shell.dataset.dragging = "true";
      const base = new Map(offsets);
      base.set(nodeGesture.id, { x: nodeGesture.originX, y: nodeGesture.originY });
      offsets = offsetAfterSubtreeDrag(base, nodeGesture.id, dx / camera.zoom, dy / camera.zoom);
      repositionWorld();
      return;
    }
    if (mapDrag && event.pointerId === mapDrag.pointerId && lastLayout) {
      const map = root.querySelector("[data-minimap]");
      if (!map) return;
      const rect = map.getBoundingClientRect();
      const bounds = lastLayout.bounds;
      if (rect.width < 1 || rect.height < 1) return;
      const dx = event.clientX - mapDrag.x;
      const dy = event.clientY - mapDrag.y;
      camera.x = mapDrag.camX - dx * (bounds.width / rect.width) * camera.zoom;
      camera.y = mapDrag.camY - dy * (bounds.height / rect.height) * camera.zoom;
      camera.userMoved = true;
      applyCamera();
      return;
    }
    if (!pointers.has(event.pointerId)) return;
    pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
    if (pointers.size >= 2) {
      if (!pinchBase) pinchBase = pinchSnapshot();
      const canvas = root.querySelector("[data-canvas]");
      if (!canvas) return;
      const points = [...pointers.values()];
      const dist = Math.hypot(points[0].x - points[1].x, points[0].y - points[1].y) || pinchBase.dist;
      const midX = (points[0].x + points[1].x) / 2;
      const midY = (points[0].y + points[1].y) / 2;
      const rect = canvas.getBoundingClientRect();
      const worldX = (pinchBase.midX - rect.left - pinchBase.camX) / pinchBase.zoom;
      const worldY = (pinchBase.midY - rect.top - pinchBase.camY) / pinchBase.zoom;
      const zoom = clampZoom(pinchBase.zoom * (dist / pinchBase.dist));
      camera.zoom = zoom;
      camera.x = midX - rect.left - worldX * zoom;
      camera.y = midY - rect.top - worldY * zoom;
      camera.userMoved = true;
      applyCamera();
      return;
    }
    if (!panBase) return;
    camera.x = panBase.camX + (event.clientX - panBase.x);
    camera.y = panBase.camY + (event.clientY - panBase.y);
    camera.userMoved = true;
    applyCamera();
  });

  const endPointer = (event) => {
    if (nodeGesture && event.pointerId === nodeGesture.pointerId) {
      if (nodeGesture.moved) {
        persistOffsets();
        suppressClick = true;
      }
      nodeGesture = null;
      delete shell.dataset.dragging;
    }
    if (mapDrag && event.pointerId === mapDrag.pointerId) mapDrag = null;
    if (!pointers.has(event.pointerId)) return;
    pointers.delete(event.pointerId);
    if (pointers.size < 2) pinchBase = null;
    if (pointers.size === 0) {
      panBase = null;
      delete shell.dataset.panning;
      return;
    }
    const remaining = [...pointers.values()][0];
    panBase = { x: remaining.x, y: remaining.y, camX: camera.x, camY: camera.y };
  };
  root.addEventListener("pointerup", endPointer);
  root.addEventListener("pointercancel", endPointer);

  root.addEventListener("wheel", (event) => {
    const canvas = event.target.closest("[data-canvas]");
    if (!canvas || event.target.closest(".qt-map")) return;
    event.preventDefault();
    const line = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? canvas.clientHeight : 1;
    if (event.ctrlKey || event.metaKey) {
      zoomAt(event.clientX, event.clientY, camera.zoom * Math.exp(-event.deltaY * line * 0.0016));
      return;
    }
    let dx = event.deltaX * line;
    let dy = event.deltaY * line;
    if (event.shiftKey && dx === 0) {
      dx = dy;
      dy = 0;
    }
    camera.x -= dx;
    camera.y -= dy;
    camera.userMoved = true;
    applyCamera();
  }, { passive: false });

  function storedValue(key) {
    try {
      return localStorage.getItem(key);
    } catch {
      return null;
    }
  }

  async function loadStrings() {
    try {
      const url = new URL("./locales/ru.json", import.meta.url);
      const response = await fetch(url);
      if (!response.ok) return false;
      const data = await response.json();
      if (!stringsComplete(data)) return false;
      strings = data;
      return true;
    } catch {
      return false;
    }
  }

  const themeMedia = window.matchMedia("(prefers-color-scheme: dark)");
  function applyTheme() {
    const dark = themeChoice === "dark" || (themeChoice === "system" && themeMedia.matches);
    document.documentElement.dataset.theme = dark ? "dark" : "light";
    document.documentElement.dataset.themeChoice = themeChoice;
    document.documentElement.style.colorScheme = dark ? "dark" : "light";
  }
  themeMedia.addEventListener("change", () => {
    if (themeChoice === "system") applyTheme();
  });
  applyTheme();

  const media = window.matchMedia("(max-width: 900px)");
  let narrowApplied = false;
  function viewportNarrow() {
    const width = Math.min(window.innerWidth, document.documentElement.clientWidth || window.innerWidth);
    return width <= 900 || media.matches;
  }
  function syncNarrow() {
    const next = viewportNarrow();
    if (next === narrowApplied) return;
    narrowApplied = next;
    session.setNarrow(next);
    paint();
  }
  root.addEventListener("pointerdown", () => {
    const next = viewportNarrow();
    if (next === narrowApplied) return;
    narrowApplied = next;
    session.setNarrow(next);
  }, true);
  if (typeof ResizeObserver !== "undefined") {
    const observer = new ResizeObserver(() => {
      if (!bootReady) return;
      const next = viewportNarrow();
      if (next !== narrowApplied) {
        narrowApplied = next;
        session.setNarrow(next);
        paint();
        return;
      }
      const model = session.snapshot();
      if (model.view !== "tree" || model.phase !== "ready") return;
      if (!camera.userMoved) fitCamera();
      applyCamera();
    });
    observer.observe(shell);
  }
  narrowApplied = viewportNarrow();
  session.setNarrow(narrowApplied);
  paint();
  media.addEventListener("change", syncNarrow);
  const panel = {
    refresh() {
      holdCamera = true;
      return session.refreshVisible().then((model) => {
        paint();
        return model;
      });
    },
    async selectExchange(target = {}) {
      const nodeId = target && typeof target.nodeId === "string" ? target.nodeId : "";
      const requestId = target && typeof target.requestId === "string" ? target.requestId : "";
      const conversationId = target && typeof target.conversationId === "string" ? target.conversationId : "";
      const hasOffset = target && Number.isInteger(target.offset) && target.offset >= 0;
      holdCamera = true;
      if (nodeId) await session.openSelection(nodeId, hasOffset ? target.offset : 0);
      if (conversationId && requestId) session.linkExchange(conversationId, requestId, true);
      paint();
      return session.snapshot();
    },
  };
  mountedPanel = panel;

  async function loadQuality(bucket, offset) {
    const serial = ++qualityState.serial;
    qualityState.loading = true;
    qualityState.error = "";
    qualityState.bucket = bucket;
    qualityState.offset = offset;
    paint();
    let body = null;
    let ok = false;
    try {
      const response = await fetch(
        `${QUALITY_REVIEW_ENDPOINT}?bucket=${encodeURIComponent(bucket)}&limit=20&offset=${offset}`,
        { headers: { Accept: "application/json" }, cache: "no-store" },
      );
      body = await response.json().catch(() => null);
      ok = response.ok && body && Array.isArray(body.items);
    } catch {
      ok = false;
    }
    if (serial !== qualityState.serial) return;
    qualityState.loading = false;
    if (!ok) {
      qualityState.error = strings.qualityReadFailed;
      qualityState.page = null;
    } else {
      qualityState.page = body;
      qualityState.error = "";
    }
    paint();
  }

  async function saveQualityDecision(decision, conversationId, requestId) {
    if (decision !== "approved" && decision !== "excluded") return;
    qualityState.notice = "";
    let ok = false;
    try {
      const response = await fetch(QUALITY_REVIEW_ENDPOINT, {
        method: "POST",
        headers: { Accept: "application/json", "Content-Type": "application/json" },
        body: JSON.stringify({
          conversation_id: conversationId,
          request_id: requestId,
          decision,
        }),
      });
      ok = response.ok;
    } catch {
      ok = false;
    }
    if (!ok) {
      qualityState.notice = strings.qualityReadFailed;
      paint();
      return;
    }
    qualityState.notice = strings.qualitySaved;
    postPanelEvent("quality", conversationId, requestId);
    await loadQuality(qualityState.bucket, qualityState.offset);
  }

  async function downloadApprovedExamples() {
    qualityState.notice = "";
    try {
      const response = await fetch(`${QUALITY_REVIEW_ENDPOINT}/export`, { cache: "no-store" });
      if (!response.ok) throw new Error("export");
      const count = Number(response.headers.get("X-Export-Count") || "0");
      const text = await response.text();
      if (!Number.isInteger(count) || count < 1 || text.trim() === "") {
        qualityState.notice = strings.qualityExportEmpty;
        paint();
        return;
      }
      const blob = new Blob([text], { type: "application/x-ndjson" });
      const url = URL.createObjectURL(blob);
      const link = el("a", { attrs: { href: url, download: "approved-examples.jsonl" } });
      document.body.append(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch {
      qualityState.notice = strings.qualityExportFailed;
      paint();
    }
  }

  let liveTimer = null;
  let liveTicket = 0;
  let seenRevision = null;
  let revisionTicket = 0;
  let panelChannel = null;

  function postPanelEvent(kind, conversationId, requestId) {
    if (!panelChannel) return;
    try {
      panelChannel.postMessage({ kind, conversationId, requestId });
    } catch {
      // The stored decision remains. Another open tab catches up when it returns.
    }
  }

  function scheduleLiveRefresh() {
    if (liveTimer !== null) return;
    liveTimer = setTimeout(() => {
      liveTimer = null;
      const ticket = ++liveTicket;
      holdCamera = true;
      void session.refreshVisible().then(() => {
        if (ticket !== liveTicket) return;
        paint();
        if (qualityState.open) void loadQuality(qualityState.bucket, qualityState.offset);
      }).catch(() => {
        // A failed panel refresh leaves the current tree in place.
      });
    }, 80);
  }

  async function rememberRevision() {
    const ticket = ++revisionTicket;
    try {
      const response = await fetch(PANEL_REVISION_ENDPOINT, {
        headers: { Accept: "application/json" },
        cache: "no-store",
      });
      if (!response.ok) return;
      const body = await response.json();
      if (ticket !== revisionTicket || typeof body.revision !== "string" || body.revision === "") return;
      seenRevision = body.revision;
    } catch {
      // The visible tree stays. The customer chat does not wait on this.
    }
  }

  async function syncRevision() {
    const ticket = ++revisionTicket;
    try {
      const response = await fetch(PANEL_REVISION_ENDPOINT, {
        headers: { Accept: "application/json" },
        cache: "no-store",
      });
      if (ticket !== revisionTicket || !response.ok) return;
      const body = await response.json();
      if (ticket !== revisionTicket || typeof body.revision !== "string" || body.revision === "") return;
      if (seenRevision === null) {
        seenRevision = body.revision;
        return;
      }
      if (body.revision !== seenRevision) {
        seenRevision = body.revision;
        scheduleLiveRefresh();
      }
    } catch {
      // The next visible tab or reconnect tries again.
    }
  }

  try {
    panelChannel = new BroadcastChannel(PANEL_EVENT_CHANNEL);
    panelChannel.onmessage = (event) => {
      const data = event && event.data;
      if (!data || (data.kind !== "exchange" && data.kind !== "feedback" && data.kind !== "quality")) return;
      scheduleLiveRefresh();
    };
  } catch {
    panelChannel = null;
  }
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") void syncRevision();
  });
  window.addEventListener("online", () => {
    void syncRevision();
  });
  window.addEventListener("pageshow", () => {
    void syncRevision();
  });

  void (async () => {
    await loadStrings();
    paint();
    await session.loadSelected();
    const loaded = session.snapshot();
    if (loaded.view === "tree" && loaded.phase === "ready") {
      if (stress) await session.expandAll();
      else await session.expandSpine();
    }
    const link = readExchangeLink(typeof location !== "undefined" ? location.search : "");
    if (link && link.error) {
      linkNotice = "missing";
    } else if (link) {
      const located = await fetchExchangeLocation(link);
      if (!located.ok) linkNotice = located.message;
      else await session.revealExchange(located.target);
    }
    bootReady = true;
    paint();
    void rememberRevision();
  })();
  return session;
}

let mountedPanel = null;

// refreshQuestionTree reloads the visible pages and keeps the camera, manual
// positions, expanded branches, selected record, and inspector scroll.
// selectQuestionTreeExchange({ nodeId, conversationId, requestId, offset })
// opens that branch and scrolls to the exchange only when both ids match.
export function refreshQuestionTree() {
  return mountedPanel ? mountedPanel.refresh() : Promise.resolve(null);
}

export function selectQuestionTreeExchange(target) {
  return mountedPanel ? mountedPanel.selectExchange(target) : Promise.resolve(null);
}

if (typeof document !== "undefined") {
  const root = document.querySelector("[data-question-tree]");
  if (root) {
    const stress = typeof location !== "undefined" && new URLSearchParams(location.search).get("nav") === "stress";
    mountQuestionTree(root, stress ? { loader: createStressLoader(), stress: true } : {});
  }
}

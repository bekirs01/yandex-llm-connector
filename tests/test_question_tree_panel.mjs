import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  displayedExchangeCount,
  historyPage,
  isQuestionTreeResponse,
  panelPresentation,
  createQuestionTreeSession,
  arrangeQuestionNodes,
  cameraForAnchor,
  createStressLoader,
  QUESTION_TREE_ENDPOINT,
  placedWithOffsets,
  offsetAfterSubtreeDrag,
  readStoredOffsets,
  frequentCardTitle,
  reviewReason,
  isTerseCustomerMessage,
  previousCustomerContext,
  ratingText,
  feedbackText,
  normalizeTheme,
  refreshQuestionTree,
  selectQuestionTreeExchange,
} from "../web/team/question-tree.js";

const CATEGORY = "category:brake-service";
const SERVICE = "service:brake-pad-replacement";
const PRICE = "leaf:brake-pad-replacement:price";
const BOOKING = "leaf:brake-pad-replacement:booking";
const CATEGORY_LABEL = "Тормоза";
const SERVICE_LABEL = "Замена тормозных колодок";
const DUAL_REQUEST = "22222222-2222-4222-8222-222222222222";
const PRICE_REQUEST = "44444444-4444-4444-8444-444444444444";
const DUAL_CUSTOMER = "Сколько стоит замена колодок и можно ли записаться на завтра?";
const DUAL_ASSISTANT = "Замена колодок выполняется по записи. Точную цену подтвердит мастерская.";
const PRICE_CUSTOMER = "Какая цена только на колодки, без записи?";
const PRICE_ASSISTANT = "Стоимость колодок зависит от автомобиля. Запись в этом ответе не оформлялась.";

function node(fields) {
  return {
    id: "root",
    kind: "root",
    label: "Вопросы клиентов",
    exchange_count: 0,
    membership_count: 0,
    needs_review: false,
    category_id: null,
    category_label: null,
    service_id: null,
    service_label: null,
    question_type: null,
    supplied_service_id: null,
    supplied_category_id: null,
    ...fields,
  };
}

function exchange(fields) {
  return {
    conversation_id: fields.conversationId,
    request_id: fields.requestId,
    customer_message: fields.customer,
    assistant_reply: fields.assistant,
    exchanged_at: fields.at,
    question_types: fields.types,
    needs_review: false,
    service_id: "brake-pad-replacement",
    service_label: SERVICE_LABEL,
    category_id: "brake-service",
    category_label: CATEGORY_LABEL,
    supplied_service_id: null,
    supplied_category_id: null,
  };
}

const dual = exchange({
  conversationId: "11111111-1111-4111-8111-111111111111",
  requestId: DUAL_REQUEST,
  customer: DUAL_CUSTOMER,
  assistant: DUAL_ASSISTANT,
  at: "2026-11-26T09:30:00+00:00",
  types: ["booking", "price"],
});
const priceOnly = exchange({
  conversationId: "33333333-3333-4333-8333-333333333333",
  requestId: PRICE_REQUEST,
  customer: PRICE_CUSTOMER,
  assistant: PRICE_ASSISTANT,
  at: "2026-11-25T14:00:00+00:00",
  types: ["price"],
});

const categoryNode = {
  id: CATEGORY,
  kind: "category",
  label: CATEGORY_LABEL,
  exchange_count: 2,
  membership_count: 3,
  category_id: "brake-service",
  category_label: CATEGORY_LABEL,
};
const serviceNode = {
  id: SERVICE,
  kind: "service",
  label: SERVICE_LABEL,
  exchange_count: 2,
  membership_count: 3,
  category_id: "brake-service",
  category_label: CATEGORY_LABEL,
  service_id: "brake-pad-replacement",
  service_label: SERVICE_LABEL,
};
const priceLeaf = {
  id: PRICE,
  kind: "question_type",
  label: "Цена",
  exchange_count: 2,
  membership_count: 2,
  category_id: "brake-service",
  category_label: CATEGORY_LABEL,
  service_id: "brake-pad-replacement",
  service_label: SERVICE_LABEL,
  question_type: "price",
};
const bookingLeaf = {
  id: BOOKING,
  kind: "question_type",
  label: "Запись",
  exchange_count: 1,
  membership_count: 1,
  category_id: "brake-service",
  category_label: CATEGORY_LABEL,
  service_id: "brake-pad-replacement",
  service_label: SERVICE_LABEL,
  question_type: "booking",
};

function page(query, nodeFields, children, exchanges) {
  return {
    view: query.view,
    node: node(nodeFields),
    children: children.map((child) => node(child)),
    history: {
      total: exchanges.length,
      limit: query.limit,
      offset: query.offset,
      exchanges: exchanges.slice(query.offset, query.offset + query.limit),
    },
  };
}

function unknownNode() {
  const error = new Error("unknown node");
  error.code = "READ_FAILED";
  return error;
}

function fixture(query) {
  if (query.view === "frequent" && query.nodeId === "root") {
    return page(query, {
      id: "root",
      label: "Частые вопросы",
      exchange_count: 2,
      membership_count: 3,
    }, [priceLeaf, bookingLeaf], [dual, priceOnly]);
  }
  if (query.view === "review" && query.nodeId === "root") {
    return page(query, {
      id: "root",
      label: "Нужна проверка",
      exchange_count: 1,
      membership_count: 1,
      needs_review: true,
    }, [{
      id: "review:service:brake-pad-replacement:price",
      kind: "question_type",
      label: "Цена",
      exchange_count: 1,
      membership_count: 1,
      needs_review: true,
      service_id: "brake-pad-replacement",
      service_label: SERVICE_LABEL,
      question_type: "price",
    }], [dual]);
  }
  const pages = {
    root: () => page(query, {
      id: "root",
      exchange_count: 2,
      membership_count: 3,
    }, [categoryNode], [dual, priceOnly]),
    [CATEGORY]: () => page(query, categoryNode, [serviceNode], [dual, priceOnly]),
    [SERVICE]: () => page(query, serviceNode, [bookingLeaf, priceLeaf], [dual, priceOnly]),
    [PRICE]: () => page(query, priceLeaf, [], [dual, priceOnly]),
    [BOOKING]: () => page(query, bookingLeaf, [], [dual]),
  };
  const build = pages[query.nodeId];
  if (!build) throw unknownNode();
  return build();
}

function emptyTree(query) {
  return page(query, {
    id: "root",
    exchange_count: 0,
    membership_count: 0,
  }, [], []);
}

test("selecting a leaf shows its transcript and keeps that branch", async () => {
  const queries = [];
  const session = createQuestionTreeSession({
    loader: async (query) => {
      queries.push({ ...query });
      return fixture(query);
    },
  });
  await session.loadSelected();
  await session.toggleExpanded(CATEGORY);
  await session.toggleExpanded(SERVICE);
  const opened = session.snapshot();
  assert.equal(opened.rows.find((row) => row.id === "root").count, 2);
  assert.equal(opened.rows.find((row) => row.id === SERVICE).count, 2);
  assert.equal(opened.rows.find((row) => row.id === PRICE).count, 2);
  assert.equal(opened.rows.find((row) => row.id === BOOKING).count, 1);

  const service = await session.select(SERVICE);
  assert.equal(service.exchangeCount, 2);
  assert.equal(service.page.total, 2);
  assert.equal(service.page.limit, 20);
  assert.equal(service.page.offset, 0);
  assert.equal(service.history.length, 2);
  assert.equal(service.history.filter((item) => item.requestId === DUAL_REQUEST).length, 1);

  session.setNarrow(true);
  const leaf = await session.select(BOOKING);
  assert.equal(queries.at(-1).nodeId, BOOKING);
  assert.equal(queries.at(-1).view, "tree");
  assert.equal(leaf.pane, "history");
  assert.equal(leaf.selectedId, BOOKING);
  assert.equal(leaf.history.length, 1);
  assert.equal(leaf.history[0].customerMessage, DUAL_CUSTOMER);
  assert.equal(leaf.history[0].assistantReply, DUAL_ASSISTANT);
  assert.equal(leaf.history.some((item) => item.customerMessage === PRICE_CUSTOMER), false);
  assert.deepEqual(leaf.branch, [CATEGORY_LABEL, SERVICE_LABEL, "Запись"]);

  const back = session.showTree();
  assert.equal(back.pane, "tree");
  assert.equal(back.selectedId, BOOKING);
  assert.equal(back.history[0].customerMessage, DUAL_CUSTOMER);
});

test("a price and booking exchange is counted once at the service", async () => {
  const session = createQuestionTreeSession({ loader: fixture });
  await session.loadSelected();
  await session.toggleExpanded(CATEGORY);
  await session.toggleExpanded(SERVICE);
  const opened = session.snapshot();
  const leaves = opened.rows.filter((row) => row.kind === "question_type");
  const leafSum = leaves.reduce((sum, row) => sum + row.count, 0);
  assert.equal(leafSum, 3);
  assert.equal(opened.rows.find((row) => row.id === SERVICE).count, 2);
  assert.notEqual(opened.rows.find((row) => row.id === SERVICE).count, leafSum);
  assert.equal(displayedExchangeCount({
    exchange_count: 2,
    children: [{ exchange_count: 2 }, { exchange_count: 1 }],
  }), 2);

  const service = await session.select(SERVICE);
  assert.equal(service.exchangeCount, 2);
  assert.equal(service.page.total, 2);
  assert.equal(service.history.filter((item) => item.requestId === DUAL_REQUEST).length, 1);
  assert.equal(service.history.filter((item) => item.requestId === PRICE_REQUEST).length, 1);
});

test("a failed refresh keeps the loaded tree and a failed branch stays on the canvas", async () => {
  let fail = false;
  const session = createQuestionTreeSession({
    loader: async (query) => {
      if (fail) {
        const error = new Error("down");
        error.code = "READ_FAILED";
        error.status = 500;
        throw error;
      }
      if (query.nodeId === PRICE) {
        const error = new Error("branch down");
        error.code = "READ_FAILED";
        error.status = 500;
        throw error;
      }
      return fixture(query);
    },
  });
  await session.loadSelected();
  await session.toggleExpanded(CATEGORY);
  fail = true;
  const refreshed = await session.refreshVisible();
  assert.equal(refreshed.phase, "ready");
  assert.equal(refreshed.rows.some((row) => row.id === CATEGORY), true);
  assert.equal(refreshed.rows.find((row) => row.id === CATEGORY).expanded, true);
  assert.equal(refreshed.selectedId, "root");
  fail = false;
  const branch = await session.select(PRICE);
  assert.equal(branch.phase, "ready");
  assert.equal(branch.historyStatus, "error");
  assert.equal(branch.error.code, "READ_FAILED");
  assert.equal(branch.rows.some((row) => row.id === CATEGORY), true);
});

test("review records are not shown as an empty database", async () => {
  const reviewNode = {
    id: "review:exchange:11111111-1111-4111-8111-111111111111:22222222-2222-4222-8222-222222222222",
    kind: "exchange",
    label: "Нужна проверка",
    exchange_count: 1,
    membership_count: 1,
    needs_review: true,
  };
  const session = createQuestionTreeSession({
    loader: async (query) => {
      if (query.view === "review") {
        return page(query, {
          id: "root",
          label: "Нужна проверка",
          exchange_count: 1,
          membership_count: 1,
          needs_review: true,
        }, [reviewNode], [dual]);
      }
      return emptyTree(query);
    },
  });
  const tree = await session.loadSelected();
  assert.equal(tree.phase, "review-only");
  assert.equal(panelPresentation(tree.phase), "review-only");
  const review = await session.setView("review");
  assert.equal(review.view, "review");
  assert.equal(review.phase, "ready");
  assert.equal(review.rows.some((row) => row.needsReview), true);
  assert.equal(review.history.some((item) => item.customerMessage === DUAL_CUSTOMER), true);
});

test("an empty review list is not an empty database", async () => {
  const session = createQuestionTreeSession({
    loader: async (query) => (query.view === "review" ? emptyTree(query) : fixture(query)),
  });
  await session.setView("review");
  const review = session.snapshot();
  assert.equal(review.phase, "ready");
  assert.notEqual(review.phase, "empty");
  assert.equal(review.rows.find((row) => row.id === "root").count, 0);
});

test("empty and error reads stay distinct", async () => {
  const empty = await createQuestionTreeSession({ loader: emptyTree }).loadSelected();
  const failed = await createQuestionTreeSession({
    loader: async () => {
      throw Object.assign(new Error("down"), { code: "READ_FAILED" });
    },
  }).loadSelected();

  assert.equal(empty.phase, "empty");
  assert.equal(empty.exchangeCount, 0);
  assert.equal(empty.page.total, 0);
  assert.equal(empty.history.length, 0);
  assert.equal(failed.phase, "error");
  assert.equal(failed.error.code, "READ_FAILED");
  assert.equal(failed.exchangeCount, null);
  assert.equal(failed.page, null);
  assert.equal(failed.history.length, 0);
  assert.notEqual(panelPresentation(empty.phase), panelPresentation(failed.phase));
  assert.equal(failed.history.some((item) => item.customerMessage === DUAL_CUSTOMER), false);
});

test("frequent and review lists keep the supplied counts", async () => {
  const views = [];
  const session = createQuestionTreeSession({
    loader: async (query) => {
      views.push(query.view);
      return fixture(query);
    },
  });
  await session.setView("frequent");
  const frequent = session.snapshot();
  assert.equal(views.at(-1), "frequent");
  assert.equal(frequent.rows.find((row) => row.id === "root").count, 2);
  const leaves = frequent.rows.filter((row) => row.kind === "question_type");
  assert.equal(leaves.reduce((sum, row) => sum + row.count, 0), 3);
  assert.equal(leaves.some((row) => row.expandable), false);

  await session.setView("review");
  const review = session.snapshot();
  assert.equal(review.view, "review");
  assert.equal(review.rows.some((row) => row.needsReview), true);
  assert.equal(review.rows.find((row) => row.id === "root").count, 1);
});

test("history pages use the supplied total, limit, and offset", () => {
  const middle = historyPage({ total: 5, limit: 2, offset: 2, exchanges: [{}, {}] });
  assert.equal(middle.total, 5);
  assert.equal(middle.limit, 2);
  assert.equal(middle.offset, 2);
  assert.equal(middle.from, 3);
  assert.equal(middle.to, 4);
  assert.equal(middle.hasPrev, true);
  assert.equal(middle.hasNext, true);
  const last = historyPage({ total: 5, limit: 2, offset: 4, exchanges: [{}] });
  assert.equal(last.hasNext, false);
  assert.equal(last.to, 5);
  const none = historyPage({ total: 0, limit: 20, offset: 0, exchanges: [] });
  assert.equal(none.from, 0);
  assert.equal(none.hasNext, false);
});

test("the panel accepts the read contract and keeps fixtures out of its source", () => {
  const root = fixture({ nodeId: "root", view: "tree", limit: 20, offset: 0 });
  assert.equal(isQuestionTreeResponse(root), true);
  assert.equal(isQuestionTreeResponse({ messages: [{ role: "user", text: DUAL_CUSTOMER }] }), false);
  const source = [
    "web/team/question-tree.js",
    "web/team/question-tree.html",
    "web/team/question-tree.css",
    "web/team/locales/ru.json",
    "web/team/locales/tr.json",
  ].map((path) => readFileSync(new URL(`../${path}`, import.meta.url), "utf8")).join("\n");
  assert.equal(source.includes(DUAL_CUSTOMER), false);
  assert.equal(source.includes(PRICE_CUSTOMER), false);
  assert.equal(source.includes("innerHTML"), false);
  const ru = JSON.parse(readFileSync(new URL("../web/team/locales/ru.json", import.meta.url), "utf8"));
  const tr = JSON.parse(readFileSync(new URL("../web/team/locales/tr.json", import.meta.url), "utf8"));
  assert.deepEqual(Object.keys(ru).sort(), Object.keys(tr).sort());
  assert.equal(ru.viewTree, "Дерево");
  assert.equal(ru.viewFrequent, "Частые вопросы");
  assert.equal(ru.viewReview, "На проверку");
  assert.equal(ru.countColumn, "Обмены");
  assert.equal(ru.countColumn.includes("клиент"), false);
});

test("opening one branch keeps it when another tab is visited", async () => {
  const session = createQuestionTreeSession({ loader: fixture });
  await session.loadSelected();
  await session.toggleExpanded(CATEGORY);
  await session.select(SERVICE);
  await session.setView("frequent");
  await session.setView("tree");
  const back = session.snapshot();
  assert.equal(back.view, "tree");
  assert.equal(back.selectedId, SERVICE);
  assert.equal(back.rows.find((row) => row.id === CATEGORY).expanded, true);
  assert.equal(back.rows.some((row) => row.id === SERVICE), true);
});

test("refresh keeps the open branch", async () => {
  const session = createQuestionTreeSession({ loader: fixture });
  await session.loadSelected();
  await session.toggleExpanded(CATEGORY);
  const refreshed = await session.refreshVisible();
  assert.equal(refreshed.rows.find((row) => row.id === CATEGORY).expanded, true);
  assert.equal(refreshed.selectedId, "root");
  assert.equal(refreshed.rows.find((row) => row.id === "root").count, 2);
});

test("a single branch opens through its only service", async () => {
  const session = createQuestionTreeSession({ loader: fixture });
  await session.loadSelected();
  const seeded = await session.expandSpine();
  assert.equal(seeded.rows.find((row) => row.id === CATEGORY).expanded, true);
  assert.equal(seeded.rows.find((row) => row.id === SERVICE).expanded, true);
  assert.equal(seeded.rows.some((row) => row.id === PRICE), true);
  const again = await session.expandSpine();
  assert.equal(again.rows.find((row) => row.id === SERVICE).expanded, true);
});

test("a frequent leaf can open its real branch", async () => {
  const session = createQuestionTreeSession({ loader: fixture });
  await session.setView("frequent");
  const opened = await session.openOnTree(PRICE);
  assert.equal(opened.view, "tree");
  assert.equal(opened.selectedId, PRICE);
  assert.equal(opened.rows.find((row) => row.id === CATEGORY).expanded, true);
  assert.equal(opened.rows.find((row) => row.id === SERVICE).expanded, true);
  assert.equal(opened.history.some((item) => item.customerMessage === DUAL_CUSTOMER), true);
  assert.equal(opened.history.some((item) => item.customerMessage === PRICE_CUSTOMER), true);
});

test("a stale read does not replace the latest selection", async () => {
  let release;
  const gate = new Promise((resolve) => {
    release = resolve;
  });
  const session = createQuestionTreeSession({
    loader: async (query) => {
      if (query.nodeId === PRICE) await gate;
      return fixture(query);
    },
  });
  await session.loadSelected();
  const slow = session.select(PRICE);
  const latest = await session.select(BOOKING);
  release();
  await slow;
  assert.equal(latest.selectedId, BOOKING);
  assert.equal(session.snapshot().selectedId, BOOKING);
  assert.equal(session.snapshot().history.some((item) => item.customerMessage === PRICE_CUSTOMER), false);
  assert.equal(session.snapshot().history[0].customerMessage, DUAL_CUSTOMER);
});

test("layout keeps a wide tree from overlapping and anchors the opened node", () => {
  const items = [{ id: "root", parentId: null, width: 180, height: 58 }];
  for (let categoryIndex = 0; categoryIndex < 8; categoryIndex += 1) {
    const category = `c${categoryIndex}`;
    items.push({ id: category, parentId: "root", width: 150 + (categoryIndex % 3) * 24, height: 56 });
    const services = 4 + (categoryIndex % 3);
    for (let serviceIndex = 0; serviceIndex < services; serviceIndex += 1) {
      const service = `s${categoryIndex}-${serviceIndex}`;
      items.push({
        id: service,
        parentId: category,
        width: 130 + (serviceIndex % 4) * 28,
        height: serviceIndex % 2 ? 64 : 48,
      });
      for (let typeIndex = 0; typeIndex < 4; typeIndex += 1) {
        items.push({
          id: `l${categoryIndex}-${serviceIndex}-${typeIndex}`,
          parentId: service,
          width: 96 + (typeIndex % 2) * 48,
          height: 42,
        });
      }
    }
  }
  assert.ok(items.length > 200);
  const laid = arrangeQuestionNodes(items);
  const byId = new Map(laid.map((node) => [node.id, node]));
  assert.equal(laid.length, items.length);
  for (let left = 0; left < laid.length; left += 1) {
    for (let right = left + 1; right < laid.length; right += 1) {
      const a = laid[left];
      const b = laid[right];
      const overlap = a.x < b.x + b.width && a.x + a.width > b.x && a.y < b.y + b.height && a.y + a.height > b.y;
      assert.equal(overlap, false);
    }
  }
  for (const item of items) {
    if (!item.parentId) continue;
    const parent = byId.get(item.parentId);
    const child = byId.get(item.id);
    assert.ok(child.x >= parent.x + parent.width);
  }
  const camera = { x: 12, y: -40, zoom: 0.8 };
  const before = byId.get("c3");
  const after = { ...before, x: before.x + 80, y: before.y - 120 };
  const next = cameraForAnchor(camera, before, after);
  const center = (cam, box) => ({
    x: cam.x + (box.x + box.width / 2) * cam.zoom,
    y: cam.y + (box.y + box.height / 2) * cam.zoom,
  });
  const start = center(camera, before);
  const end = center(next, after);
  assert.ok(Math.abs(start.x - end.x) < 1e-6);
  assert.ok(Math.abs(start.y - end.y) < 1e-6);
});

test("the layout probe stays off the live endpoint until it is asked for", async () => {
  assert.equal(QUESTION_TREE_ENDPOINT, "/api/question-tree");
  const loader = createStressLoader();
  const root = await loader({ nodeId: "root", view: "tree", limit: 20, offset: 0 });
  assert.equal(isQuestionTreeResponse(root), true);
  let count = 1 + root.children.length;
  for (const category of root.children) {
    const categoryPage = await loader({ nodeId: category.id, view: "tree", limit: 20, offset: 0 });
    count += categoryPage.children.length;
    for (const service of categoryPage.children) {
      const servicePage = await loader({ nodeId: service.id, view: "tree", limit: 20, offset: 0 });
      count += servicePage.children.length;
    }
  }
  assert.ok(count > 200);
  const frequent = await loader({ nodeId: "root", view: "frequent", limit: 20, offset: 0 });
  assert.equal(frequent.children.length, 0);
});

test("a dragged ancestor moves the subtree once", () => {
  const auto = [
    { id: "parent", parentId: null, x: 0, y: 0, width: 40, height: 20 },
    { id: "child", parentId: "parent", x: 80, y: 30, width: 40, height: 20 },
    { id: "gone", parentId: null, x: 10, y: 10, width: 10, height: 10 },
  ];
  const stored = readStoredOffsets(JSON.stringify({
    parent: { x: 12, y: 4 },
    child: { x: 3, y: -2 },
    "retired-node": { x: 9, y: 9 },
    broken: { x: "no" },
  }));
  assert.equal(stored.has("retired-node"), true);
  assert.equal(stored.has("broken"), false);
  assert.equal(readStoredOffsets("{").size, 0);
  const moved = offsetAfterSubtreeDrag(stored, "parent", 5, 0);
  assert.equal(moved.get("parent").x, 17);
  assert.equal(moved.get("child").x, 3);
  const placed = placedWithOffsets(auto, moved);
  const child = placed.find((node) => node.id === "child");
  assert.equal(child.x, 80 + 3 + 17);
  assert.equal(child.y, 30 - 2 + 4);
});

test("frequent cards name the service without declining it", () => {
  const title = frequentCardTitle({
    label: "Цена",
    questionType: "price",
    serviceLabel: "Проверка герметичности впуска дымогенератором",
  });
  assert.equal(title, "Цена · Проверка герметичности впуска дымогенератором");
  assert.equal(frequentCardTitle({
    label: "Цена",
    questionType: "price",
    serviceLabel: "Замена моторного масла и масляного фильтра",
  }), "Цена · Замена моторного масла и масляного фильтра");
  assert.equal(title.includes("Стоимость проверки"), false);
});

test("review cards use the message, a supported reason, and same-conversation context", () => {
  assert.equal(reviewReason({ serviceId: null, suppliedServiceId: "x" }), "Не удалось определить услугу");
  assert.equal(reviewReason({ serviceId: "engine-oil-change" }), "Классификацию нужно проверить");
  assert.equal(isTerseCustomerMessage("да"), true);
  assert.equal(isTerseCustomerMessage("1.6"), true);
  assert.equal(isTerseCustomerMessage("Вы меняете масло в двигателе?"), false);
  const history = [
    {
      conversationId: "same",
      requestId: "earlier",
      customerMessage: "Ford Focus, бьёт в руль",
      exchangedAt: "2026-11-26T09:00:00+00:00",
    },
    {
      conversationId: "other",
      requestId: "other",
      customerMessage: "Чужой разговор",
      exchangedAt: "2026-11-26T09:10:00+00:00",
    },
  ];
  const exchange = {
    conversationId: "same",
    requestId: "now",
    exchangedAt: "2026-11-26T09:20:00+00:00",
  };
  assert.equal(previousCustomerContext("да", exchange, history), "Ford Focus, бьёт в руль");
  assert.equal(previousCustomerContext("да", { ...exchange, conversationId: "missing" }, history), null);
  assert.equal(previousCustomerContext("Какая цена на замену масла завтра утром?", exchange, history), null);
});

test("ratings stay on the supplied node and unrated work shows no stars", () => {
  assert.equal(ratingText(4.25, 12), "4,3 из 5 · 12 оценок");
  assert.equal(ratingText(4, 1), "4,0 из 5 · 1 оценка");
  assert.equal(ratingText(0, 4), null);
  assert.equal(ratingText(4.2, 0), null);
  assert.equal(ratingText(null, null), null);
  assert.equal(feedbackText(undefined), null);
  assert.equal(feedbackText({ stars: 0, resolved: false }), "Вопрос не решён");
  assert.equal(feedbackText({ stars: 4, resolved: true }), "4 из 5 · Вопрос решён");
  assert.equal(normalizeTheme("tr"), "system");
  assert.equal(normalizeTheme("dark"), "dark");
});

test("optional feedback is kept and a branch rating is not summed from children", async () => {
  const session = createQuestionTreeSession({
    loader: async (query) => {
      const response = fixture(query);
      response.node = {
        ...response.node,
        average_stars: response.node.id === SERVICE ? 4.5 : null,
        rating_count: response.node.id === SERVICE ? 10 : null,
      };
      response.history.exchanges = response.history.exchanges.map((item, index) => (
        index === 0 ? { ...item, feedback: { stars: 5, resolved: true } } : item
      ));
      if (query.nodeId === SERVICE) {
        response.children = response.children.map((child) => ({
          ...child,
          average_stars: 1,
          rating_count: 99,
        }));
      }
      return response;
    },
  });
  await session.loadSelected();
  await session.toggleExpanded(CATEGORY);
  const opened = await session.select(SERVICE);
  assert.equal(opened.history[0].feedback.stars, 5);
  assert.equal(opened.history[0].feedback.resolved, true);
  assert.equal(opened.history[1].feedback, null);
  const service = opened.rows.find((row) => row.id === SERVICE);
  assert.equal(service.averageStars, 4.5);
  assert.equal(service.ratingCount, 10);
  assert.equal(service.ratingCount, 10);
  assert.notEqual(service.ratingCount, 99);
  assert.equal(await refreshQuestionTree(), null);
  assert.equal(await selectQuestionTreeExchange({ nodeId: SERVICE, requestId: DUAL_REQUEST }), null);
});

test("the workspace is Russian and does not poll for live updates", () => {
  const source = readFileSync(new URL("../web/team/question-tree.js", import.meta.url), "utf8");
  assert.equal(source.includes("data-locale"), false);
  assert.equal(source.includes("Восстановить раскладку"), true);
  assert.equal(source.includes("Вписать в экран"), true);
  assert.equal(source.includes("Как в системе"), true);
  assert.equal(source.includes("setInterval"), false);
  assert.equal(source.includes("Повторить"), true);
  assert.equal(source.includes("Клиент"), true);
  assert.equal(source.includes("Ассистент"), true);
});

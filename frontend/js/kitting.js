/**
 * Kitting board (IT staff): every device in kitting with its progress,
 * grouped by the person who last worked on it, plus the in-stock devices
 * waiting to be kitted with a button to start.
 *
 * The grouping comes from the server (GET /api/kitting/board): the worker is
 * whoever ticked a step of the current run most recently, or whoever started it.
 */

import { ApiError, api } from "./api.js";
import { ADMIN_ROLES } from "./asset-fields.js";
import { t, tError } from "./i18n.js";
import { el, fmtNumber, showStatus, startPage } from "./page.js";

const status = document.getElementById("page-status");
const message = document.getElementById("kitting-message");
let board = null;
let waiting = null;
let waitingError = null;
let lastMessage = null;

const errorCode = (error) => (error instanceof ApiError ? error.code : "UNKNOWN_ERROR");

function deviceCard(device) {
  const card = el("li", { class: `board-card${device.percent === 100 ? " complete" : ""}` });
  const title = el("a", { class: "board-tag", href: `device.html?id=${encodeURIComponent(device.asset_id)}` }, device.asset_tag);
  const meta = el("p", { class: "muted board-meta" }, `${t(`type.${device.type}`)} / ${device.model}`);
  const bar = el("progress", { max: "100", value: String(device.percent) });
  bar.setAttribute("aria-label", t("kitting.progress_of", { tag: device.asset_tag }));
  const count = el(
    "p",
    { class: "board-count" },
    t("device.kitting_count_percent", {
      done: fmtNumber(device.done),
      total: fmtNumber(device.total),
      percent: fmtNumber(device.percent),
    }),
  );
  card.append(title, meta, bar, count);
  if (device.run_no > 1) {
    card.append(el("span", { class: "badge" }, t("device.kitting_run_label", { run: fmtNumber(device.run_no) })));
  }
  if (device.percent === 100) {
    card.append(el("span", { class: "badge badge-ready" }, t("kitting.ready_to_finish")));
  }
  return card;
}

function renderBoard() {
  const container = document.getElementById("board");
  const devices = board.reduce((sum, group) => sum + group.devices.length, 0);
  document.getElementById("board-summary").textContent = t("kitting.summary", {
    devices: fmtNumber(devices),
    people: fmtNumber(board.filter((group) => group.worker).length),
  });
  document.getElementById("board-empty").hidden = board.length > 0;
  container.replaceChildren(
    ...board.map((group) => {
      const column = el("section", { class: "board-column" });
      const name = group.worker ? group.worker.email || `#${group.worker.id}` : t("kitting.unassigned");
      const heading = el("h2", {}, name);
      heading.append(el("span", { class: "board-column-count" }, fmtNumber(group.devices.length)));
      const list = el("ul", { class: "board-list" });
      list.append(...group.devices.map(deviceCard));
      column.append(heading, list);
      return column;
    }),
  );
}

function renderWaiting() {
  const errorBox = document.getElementById("waiting-error");
  errorBox.hidden = !waitingError;
  errorBox.textContent = waitingError ? tError(waitingError) : "";
  if (!waiting) {
    return;
  }
  document.getElementById("waiting-empty").hidden = waiting.length > 0;
  document.getElementById("waiting-table").hidden = waiting.length === 0;
  document.querySelector("#waiting-table tbody").replaceChildren(
    ...waiting.map((asset) => {
      const row = el("tr");
      const tag = el("td", { class: "nowrap" });
      tag.append(el("a", { href: `device.html?id=${encodeURIComponent(asset.id)}` }, asset.asset_tag));
      const action = el("td", { class: "num" });
      const button = el(
        "button",
        { type: "button", class: "button button-quiet button-small", "data-start": String(asset.id) },
        t("device.action.start_kitting"),
      );
      button.addEventListener("click", () => startKitting(asset, button));
      action.append(button);
      row.append(tag, el("td", {}, t(`type.${asset.type}`)), el("td", {}, `${asset.manufacturer} ${asset.model}`), action);
      return row;
    }),
  );
}

function renderMessage() {
  message.hidden = !lastMessage;
  if (lastMessage) {
    message.textContent = t(lastMessage.key, lastMessage.params);
  }
}

async function startKitting(asset, button) {
  button.disabled = true;
  waitingError = null;
  try {
    await api(`/assets/${asset.id}/kitting/start`, { method: "POST", body: {} });
    lastMessage = { key: "kitting.started", params: { tag: asset.asset_tag } };
    await load();
  } catch (error) {
    waitingError = errorCode(error);
    button.disabled = false;
    renderWaiting();
  }
}

async function load() {
  try {
    const [boardData, waitingPage] = await Promise.all([
      api("/kitting/board"),
      api("/assets?status=in_stock&limit=200"),
    ]);
    board = boardData;
    waiting = waitingPage.items;
  } catch (error) {
    showStatus(status, { state: "error", message: tError(errorCode(error)), onRetry: load });
    return;
  }
  showStatus(status, { state: "done" });
  document.getElementById("board-area").hidden = false;
  render();
}

function render() {
  if (!board) {
    return;
  }
  renderBoard();
  renderWaiting();
  renderMessage();
}

async function main() {
  const user = await startPage("kitting.html", ADMIN_ROLES);
  if (!user) {
    return;
  }
  document.getElementById("refresh").addEventListener("click", () => {
    lastMessage = null;
    load();
  });
  document.addEventListener("langchange", render);
  showStatus(status, { state: "loading" });
  await load();
}

main();

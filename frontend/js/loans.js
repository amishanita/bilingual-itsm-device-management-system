/**
 * Loans page: open, overdue, and returned loans, with the lend and return
 * forms for IT staff. Managers see their department's loans read-only.
 *
 * loans.html?asset_id=12 comes from the device page: a ready device opens the
 * lend form with that device chosen, and a device on loan opens its return form.
 */

import { ApiError, api } from "./api.js";
import { ADMIN_ROLES } from "./asset-fields.js";
import { buildFields, clearFieldErrors, readFields, showFieldErrors } from "./forms.js";
import { fmtDate, t, tError } from "./i18n.js";
import { el, fmtNumber, showStatus, startPage } from "./page.js";

const PAGE_SIZE = 50;
const VIEWS = ["open", "overdue", "returned", "all"];
const CONDITIONS = ["ok", "damaged", "missing_parts"];
// A due date means "by the end of that working day", local time.
const DUE_HOUR = 18;
const DEFAULT_LOAN_DAYS = 7;

const params = new URLSearchParams(window.location.search);
const status = document.getElementById("page-status");
const results = document.getElementById("results");
let user = null;
let view = VIEWS.includes(params.get("view")) ? params.get("view") : "open";
let pageNo = 1;
let lastPage = null;
let overdueTotal = null;
let lastMessage = null;
let requestSeq = 0;

const isAdmin = () => ADMIN_ROLES.includes(user.role);
const errorCode = (error) => (error instanceof ApiError ? error.code : "UNKNOWN_ERROR");

/** "2026-10-30" -> the ISO time of 18:00 that day in the browser's time zone. */
function dueIso(dateText) {
  const [year, month, day] = dateText.split("-").map(Number);
  return new Date(year, month - 1, day, DUE_HOUR, 0, 0).toISOString();
}

function localDateText(date) {
  const pad = (n) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

function announce(key, messageParams) {
  lastMessage = { key, params: messageParams };
  renderMessage();
}

function renderMessage() {
  const box = document.getElementById("loans-message");
  box.hidden = !lastMessage;
  if (lastMessage) {
    box.textContent = t(lastMessage.key, lastMessage.params);
  }
}

// List

function queryFor(viewName) {
  const query = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String((pageNo - 1) * PAGE_SIZE) });
  if (viewName === "open") {
    query.set("state", "open");
  } else if (viewName === "overdue") {
    query.set("overdue", "true");
  } else if (viewName === "returned") {
    query.set("state", "returned");
  }
  return query;
}

function stateBadge(loan) {
  if (loan.returned_at) {
    return el("span", { class: "badge badge-retired" }, t("loans.returned_on", { date: fmtDate(loan.returned_at) }));
  }
  return el(
    "span",
    { class: `badge ${loan.is_overdue ? "badge-overdue" : "badge-on_loan"}` },
    t(loan.is_overdue ? "loan.overdue" : "loan.open"),
  );
}

function renderRows() {
  const page = lastPage;
  const body = document.querySelector("#loan-table tbody");
  body.replaceChildren(
    ...page.items.map((loan) => {
      const row = el("tr", loan.is_overdue ? { class: "overdue" } : {});
      const tag = el("td", { class: "nowrap" });
      tag.append(el("a", { href: `device.html?id=${encodeURIComponent(loan.asset.id)}` }, loan.asset.asset_tag));
      const state = el("td");
      state.append(stateBadge(loan));
      const action = el("td", { class: "num" });
      if (isAdmin() && !loan.returned_at) {
        const button = el(
          "button",
          { type: "button", class: "button button-quiet button-small", "data-return": String(loan.id) },
          t("loans.return"),
        );
        button.addEventListener("click", () => openReturn(loan));
        action.append(button);
      }
      row.append(
        tag,
        el("td", {}, loan.asset.model),
        el("td", {}, `${loan.employee.name} (${loan.employee.department})`),
        el("td", { class: "nowrap" }, fmtDate(loan.lent_at)),
        el("td", { class: "nowrap" }, fmtDate(loan.due_at)),
        state,
        el("td", {}, loan.condition ? t(`condition.${loan.condition}`) : "-"),
        action,
      );
      return row;
    }),
  );
  const empty = page.items.length === 0;
  document.getElementById("loan-table").hidden = empty;
  document.getElementById("no-results").hidden = !empty;
  const from = empty ? 0 : (pageNo - 1) * PAGE_SIZE + 1;
  const to = (pageNo - 1) * PAGE_SIZE + page.items.length;
  document.getElementById("result-count").textContent = t("loans.count", { total: fmtNumber(page.total) });
  document.getElementById("page-info").textContent = t("common.page_info", {
    from: fmtNumber(from),
    to: fmtNumber(to),
    total: fmtNumber(page.total),
  });
  document.getElementById("page-prev").disabled = pageNo <= 1;
  document.getElementById("page-next").disabled = to >= page.total;
}

function renderTabs() {
  for (const tab of document.querySelectorAll(".tab")) {
    tab.setAttribute("aria-pressed", String(tab.dataset.state === view));
  }
}

function renderOverdue() {
  const box = document.getElementById("overdue-summary");
  box.hidden = !overdueTotal;
  box.textContent = overdueTotal ? t("loans.overdue_summary", { count: fmtNumber(overdueTotal) }) : "";
}

async function loadList() {
  const seq = ++requestSeq;
  const query = new URLSearchParams();
  if (view !== "open") {
    query.set("view", view);
  }
  window.history.replaceState(null, "", query.toString() ? `?${query}` : window.location.pathname);
  results.setAttribute("aria-busy", "true");
  try {
    const [page, overdue] = await Promise.all([
      api(`/loans?${queryFor(view)}`),
      api("/loans?overdue=true&limit=1"),
    ]);
    if (seq !== requestSeq) {
      return;
    }
    lastPage = page;
    overdueTotal = overdue.total;
    showStatus(status, { state: "done" });
    results.hidden = false;
    renderRows();
    renderOverdue();
  } catch (error) {
    if (seq === requestSeq) {
      showStatus(status, { state: "error", message: tError(errorCode(error)), onRetry: loadList });
    }
  } finally {
    if (seq === requestSeq) {
      results.removeAttribute("aria-busy");
    }
  }
}

// Lend form

let lendFields = [];
let lendError = null;
let noReadyDevices = false;

function renderLendError() {
  const box = document.getElementById("lend-error");
  box.hidden = !lendError && !noReadyDevices;
  box.textContent = lendError ? tError(lendError) : noReadyDevices ? t("loans.no_ready_devices") : "";
}

async function openLend(assetId) {
  const panel = document.getElementById("lend-panel");
  const toggle = document.getElementById("lend-toggle");
  document.getElementById("return-panel").hidden = true;
  lendError = null;
  noReadyDevices = false;
  renderLendError();
  panel.hidden = false;
  toggle.setAttribute("aria-expanded", "true");
  let ready;
  let employees;
  try {
    [ready, employees] = await Promise.all([
      api("/assets?status=ready&limit=200"),
      api("/employees?status=active&limit=200"),
    ]);
  } catch (error) {
    lendError = errorCode(error);
    renderLendError();
    return;
  }
  const due = new Date();
  due.setDate(due.getDate() + DEFAULT_LOAN_DAYS);
  lendFields = [
    {
      name: "asset_id",
      label: "loans.device",
      type: "select",
      required: true,
      options: ready.items.map((a) => ({ value: String(a.id), text: `${a.asset_tag} (${a.manufacturer} ${a.model})` })),
    },
    {
      name: "employee_id",
      label: "field.employee",
      type: "select",
      required: true,
      options: employees.items.map((e) => ({ value: String(e.id), text: `${e.name} (${e.employee_code}, ${e.department})` })),
    },
    { name: "due_date", label: "loan.due_at", type: "date", required: true, min: localDateText(new Date()), hint: "loans.due_hint" },
    { name: "note", label: "field.note", type: "textarea", maxLength: 500 },
  ];
  const values = { due_date: localDateText(due) };
  if (assetId && ready.items.some((a) => a.id === assetId)) {
    values.asset_id = String(assetId);
  }
  buildFields(document.getElementById("lend-fields"), lendFields, values, "lend");
  noReadyDevices = ready.items.length === 0;
  renderLendError();
  document.getElementById("lend-asset_id").focus();
}

function closeLend() {
  document.getElementById("lend-panel").hidden = true;
  document.getElementById("lend-toggle").setAttribute("aria-expanded", "false");
}

async function submitLend(event) {
  event.preventDefault();
  const form = event.target;
  clearFieldErrors(form);
  lendError = null;
  const values = readFields(form, lendFields);
  const missing = ["asset_id", "employee_id", "due_date"].filter((name) => !values[name]);
  if (missing.length) {
    showFieldErrors(form, { fields: missing.map((field) => ({ field })) });
    lendError = "VALIDATION_ERROR";
    renderLendError();
    return;
  }
  const body = {
    asset_id: Number(values.asset_id),
    employee_id: Number(values.employee_id),
    due_at: dueIso(values.due_date),
  };
  if (values.note) {
    body.note = values.note;
  }
  const submit = form.querySelector('button[type="submit"]');
  submit.disabled = true;
  try {
    const loan = await api("/loans", { method: "POST", body });
    closeLend();
    announce("loans.lent", { tag: loan.asset.asset_tag, name: loan.employee.name, date: fmtDate(loan.due_at) });
    view = "open";
    pageNo = 1;
    renderTabs();
    await loadList();
  } catch (error) {
    lendError = errorCode(error);
    if (lendError === "DUE_DATE_IN_PAST") {
      showFieldErrors(form, { fields: [{ field: "due_date" }] });
    } else if (error instanceof ApiError && error.status === 422) {
      showFieldErrors(form, error.detail);
    }
  } finally {
    submit.disabled = false;
    renderLendError();
  }
}

// Return form

const RETURN_FIELDS = [
  {
    name: "condition",
    label: "loan.condition",
    type: "select",
    required: true,
    options: CONDITIONS.map((value) => ({ value, label: `condition.${value}` })),
  },
  { name: "wipe_done", label: "loans.wipe_done", type: "checkbox", hint: "loans.wipe_hint" },
  { name: "note", label: "field.note", type: "textarea", maxLength: 500 },
];
let returning = null;
let returnError = null;

function renderReturn() {
  const box = document.getElementById("return-error");
  box.hidden = !returnError;
  box.textContent = returnError ? tError(returnError) : "";
  if (returning) {
    document.getElementById("return-heading").textContent = t("loans.return_heading", {
      tag: returning.asset.asset_tag,
      name: returning.employee.name,
    });
  }
}

function openReturn(loan) {
  closeLend();
  returning = loan;
  returnError = null;
  document.getElementById("return-panel").hidden = false;
  buildFields(document.getElementById("return-fields"), RETURN_FIELDS, { condition: "ok" }, "return");
  renderReturn();
  document.getElementById("return-condition").focus();
}

function closeReturn() {
  document.getElementById("return-panel").hidden = true;
  returning = null;
}

async function submitReturn(event) {
  event.preventDefault();
  const form = event.target;
  clearFieldErrors(form);
  returnError = null;
  const values = readFields(form, RETURN_FIELDS);
  const body = { condition: values.condition, wipe_done: Boolean(values.wipe_done) };
  if (values.note) {
    body.note = values.note;
  }
  const submit = form.querySelector('button[type="submit"]');
  submit.disabled = true;
  try {
    const loan = await api(`/loans/${returning.id}/return`, { method: "POST", body });
    closeReturn();
    announce(body.wipe_done ? "loans.returned_wiped" : "loans.returned", { tag: loan.asset.asset_tag });
    await loadList();
  } catch (error) {
    returnError = errorCode(error);
    if (error instanceof ApiError && error.status === 422) {
      showFieldErrors(form, error.detail);
    }
  } finally {
    submit.disabled = false;
    renderReturn();
  }
}

/** loans.html?asset_id=N from the device page: open the matching form. */
async function openFromDeviceLink() {
  const assetId = Number.parseInt(params.get("asset_id"), 10);
  if (!Number.isInteger(assetId) || assetId < 1) {
    return;
  }
  try {
    const open = await api(`/loans?asset_id=${assetId}&state=open&limit=1`);
    if (open.items.length) {
      openReturn(open.items[0]);
    } else {
      await openLend(assetId);
    }
  } catch {
    // The list itself shows any connection problem.
  }
}

async function main() {
  user = await startPage("loans.html", ["super_admin", "it_admin", "manager"]);
  if (!user) {
    return;
  }
  for (const tab of document.querySelectorAll(".tab")) {
    tab.addEventListener("click", () => {
      view = tab.dataset.state;
      pageNo = 1;
      renderTabs();
      loadList();
    });
  }
  document.getElementById("overdue-summary").addEventListener("click", () => {
    view = "overdue";
    pageNo = 1;
    renderTabs();
    loadList();
  });
  document.getElementById("page-prev").addEventListener("click", () => {
    pageNo -= 1;
    loadList();
  });
  document.getElementById("page-next").addEventListener("click", () => {
    pageNo += 1;
    loadList();
  });
  if (isAdmin()) {
    const toggle = document.getElementById("lend-toggle");
    toggle.hidden = false;
    toggle.addEventListener("click", () => {
      if (document.getElementById("lend-panel").hidden) {
        openLend(null);
      } else {
        closeLend();
      }
    });
    document.getElementById("lend-cancel").addEventListener("click", closeLend);
    document.getElementById("lend-form").addEventListener("submit", submitLend);
    document.getElementById("return-cancel").addEventListener("click", closeReturn);
    document.getElementById("return-form").addEventListener("submit", submitReturn);
  }
  document.addEventListener("langchange", () => {
    renderTabs();
    renderMessage();
    renderOverdue();
    renderReturn();
    renderLendError();
    if (lastPage) {
      renderRows();
    }
  });
  renderTabs();
  showStatus(status, { state: "loading" });
  await loadList();
  if (isAdmin()) {
    await openFromDeviceLink();
  }
}

main();

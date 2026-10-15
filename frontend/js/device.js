/**
 * Device page: everything about one device in one place.
 *
 * - Lifecycle buttons come from allowed_transitions in the API response, so
 *   only valid moves are offered. The server still checks every change.
 * - Moves owned by another workflow go there: starting kitting uses the
 *   kitting endpoint, and lending or returning a loan happens on the loans page.
 * - Each section loads on its own, so one failing call does not blank the page.
 * - Employees see their own device read-only; the history and loan sections
 *   are for managers and IT staff (the API enforces the same rule).
 */

import { ApiError, api } from "./api.js";
import {
  ADMIN_ROLES,
  DETAIL_FIELDS,
  EDIT_FIELDS,
  complianceBadge,
  holderText,
  statusBadge,
} from "./asset-fields.js";
import { buildFields, clearFieldErrors, readFields, showFieldErrors } from "./forms.js";
import { fmtDate, getLang, hasKey, t, tError } from "./i18n.js";
import { el, fmtNumber, showStatus, startPage } from "./page.js";

const STAFF_ROLES = ["super_admin", "it_admin", "manager"];
const assetId = Number.parseInt(new URLSearchParams(window.location.search).get("id"), 10);
const status = document.getElementById("page-status");
const actionMessage = document.getElementById("action-message");

let user = null;
let asset = null;
let checklist = null;
let selectedRun = null;
let loans = null;
let tickets = null;
let history = null;
let lastAction = null; // {key, params} of the last success message, re-rendered on language change

const isAdmin = () => ADMIN_ROLES.includes(user.role);
const isStaff = () => STAFF_ROLES.includes(user.role);
const errorCode = (error) => (error instanceof ApiError ? error.code : "UNKNOWN_ERROR");

/**
 * Show a section's own error in its "empty" line, so the rest of the page keeps
 * working. The line's translation key is set aside while the error is shown,
 * so a language switch re-translates the error instead of the empty message.
 */
function sectionError(emptyId, error) {
  const box = document.getElementById(emptyId);
  if (box.dataset.i18n) {
    box.dataset.emptyKey = box.dataset.i18n;
    box.removeAttribute("data-i18n");
  }
  box.dataset.errorCode = errorCode(error);
  box.classList.add("alert");
  box.hidden = false;
  box.textContent = tError(box.dataset.errorCode);
}

/** Put a section's "empty" line back after a successful reload. */
function resetSection(emptyId) {
  const box = document.getElementById(emptyId);
  if (!box.dataset.errorCode) {
    return;
  }
  delete box.dataset.errorCode;
  box.classList.remove("alert");
  box.dataset.i18n = box.dataset.emptyKey;
  box.textContent = t(box.dataset.emptyKey);
}

function retranslateSectionErrors() {
  for (const box of document.querySelectorAll("[data-error-code]")) {
    box.textContent = tError(box.dataset.errorCode);
  }
}

function yesNo(value) {
  return t(value ? "common.yes" : "common.no");
}

function fmtCost(value) {
  if (value === null || value === undefined) {
    return "-";
  }
  return new Intl.NumberFormat(getLang() === "en" ? "en-US" : "ja-JP", {
    style: "currency",
    currency: "JPY",
  }).format(Number(value));
}

/** Fill a <dl> with [labelKey, value] pairs. Values may be strings or elements. */
function fillList(listId, rows) {
  const list = document.getElementById(listId);
  list.replaceChildren();
  for (const [key, value] of rows) {
    const term = el("dt", {}, t(key));
    const description = el("dd");
    if (value instanceof Node) {
      description.append(value);
    } else {
      description.textContent = value === null || value === undefined || value === "" ? "-" : String(value);
    }
    list.append(term, description);
  }
}

// Header and the two field lists

function renderHeader() {
  document.title = `${asset.asset_tag} | ${t("device.title")}`;
  document.getElementById("page-heading").textContent = asset.asset_tag;
  const summary = document.getElementById("device-summary");
  summary.replaceChildren(
    el("span", {}, `${asset.manufacturer} ${asset.model}`),
    statusBadge(asset.status),
    el("span", {}, `${t("field.holder")}: ${holderText(asset.holder)}`),
  );
}

function renderInfo() {
  fillList("info-list", [
    ["field.asset_tag", asset.asset_tag],
    ["field.type", t(`type.${asset.type}`)],
    ["field.status", statusBadge(asset.status)],
    ["field.holder", holderText(asset.holder)],
    ["field.serial_number", asset.serial_number],
    ["field.manufacturer", asset.manufacturer],
    ["field.model", asset.model],
    ["field.purchase_date", fmtDate(asset.purchase_date)],
    ["field.warranty_end", fmtDate(asset.warranty_end)],
    ["field.cost", fmtCost(asset.cost)],
    ["field.location", asset.location],
    ["field.notes", asset.notes],
    ["field.created_at", fmtDate(asset.created_at, { time: true })],
    ["field.updated_at", fmtDate(asset.updated_at, { time: true })],
  ]);
}

function renderDetails() {
  const d = asset.details;
  if (!d) {
    fillList("details-list", []);
    return;
  }
  fillList("details-list", [
    ["field.os", d.os],
    ["field.os_version", d.os_version],
    ["field.cpu", d.cpu],
    ["field.ram_gb", d.ram_gb === null ? null : fmtNumber(d.ram_gb)],
    ["field.storage_gb", d.storage_gb === null ? null : fmtNumber(d.storage_gb)],
    ["field.mac_address", d.mac_address],
    ["field.imei", d.imei],
    ["field.phone_number", d.phone_number],
    ["field.carrier", d.carrier],
    ["field.sim_iccid", d.sim_iccid],
    ["field.compliance", complianceBadge(d.compliance)],
    ["field.autopilot_registered", yesNo(d.autopilot_registered)],
    ["field.mdm_enrolled", yesNo(d.mdm_enrolled)],
    ["field.encryption_on", yesNo(d.encryption_on)],
    ["field.last_check_in", fmtDate(d.last_check_in, { time: true })],
  ]);
}

/**
 * Wire an edit button to its form. PUT sends only the fields that changed.
 * @param {"info"|"details"} name
 * @param {object[]} fields
 * @param {() => object} values Current values for the form.
 * @param {string} path API path for the PUT.
 */
function setUpEditForm(name, fields, values, path) {
  const button = document.getElementById(`${name}-edit`);
  const form = document.getElementById(`${name}-form`);
  const list = document.getElementById(`${name}-list`);
  const errorBox = document.getElementById(`${name}-error`);
  let code = null;
  const renderError = () => {
    errorBox.hidden = !code;
    errorBox.textContent = code ? tError(code) : "";
  };
  document.addEventListener("langchange", renderError);

  const open = (show) => {
    form.hidden = !show;
    list.hidden = show;
    button.hidden = show;
    if (show) {
      code = null;
      renderError();
      buildFields(document.getElementById(`${name}-fields`), fields, values(), name);
      form.querySelector("input, select, textarea").focus();
    }
  };
  button.hidden = false;
  button.addEventListener("click", () => open(true));
  form.querySelector(".form-cancel").addEventListener("click", () => {
    open(false);
    button.focus();
  });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    clearFieldErrors(form);
    code = null;
    const body = readFields(form, fields, { onlyChanged: true });
    if (Object.keys(body).length === 0) {
      open(false);
      return;
    }
    const submit = form.querySelector('button[type="submit"]');
    submit.disabled = true;
    try {
      await api(path, { method: "PUT", body });
      open(false);
      announce("device.saved");
      await reloadAll();
    } catch (error) {
      code = errorCode(error);
      if (error instanceof ApiError && error.status === 422) {
        showFieldErrors(form, error.detail);
      }
    } finally {
      submit.disabled = false;
      renderError();
    }
  });
}

// Lifecycle actions

/**
 * How each target status is reached from the current one.
 * "kitting" starts the kitting workflow; "loan" sends the user to the loans page.
 */
function actionKind(target) {
  if (target === "kitting") {
    return "kitting";
  }
  if (target === "on_loan" || (target === "returned" && asset.status === "on_loan")) {
    return "loan";
  }
  return "status";
}

async function actionFields(target) {
  const note = { name: "note", label: "field.note", type: "textarea", maxLength: 500 };
  if (target === "assigned") {
    const employees = await api("/employees?status=active&limit=200");
    return [
      {
        name: "employee_id",
        label: "field.employee",
        type: "select",
        required: true,
        options: employees.items.map((e) => ({
          value: String(e.id),
          text: `${e.name} (${e.employee_code}, ${e.department})`,
        })),
      },
      note,
    ];
  }
  if (target === "wiped") {
    return [{ name: "wipe_confirmed", label: "device.wipe_confirm", type: "checkbox" }, note];
  }
  if (target === "retired") {
    return [{ ...note, label: "device.retire_note", required: true, hint: "hint.retire_note" }];
  }
  return [note];
}

function renderActions() {
  const panel = document.getElementById("actions-panel");
  panel.hidden = !isAdmin();
  if (!isAdmin()) {
    return;
  }
  const buttons = document.getElementById("action-buttons");
  buttons.replaceChildren();
  document.getElementById("actions-none").hidden = asset.allowed_transitions.length > 0;
  for (const target of asset.allowed_transitions) {
    const kind = actionKind(target);
    if (kind === "loan") {
      // Lending and loan returns record due dates and condition on the loans page.
      buttons.append(
        el(
          "a",
          { class: "button button-quiet", href: `loans.html?asset_id=${encodeURIComponent(asset.id)}` },
          t(target === "on_loan" ? "device.action.lend" : "device.action.return_loan"),
        ),
      );
      continue;
    }
    const button = el(
      "button",
      { type: "button", class: `button ${target === "retired" ? "button-danger" : "button-quiet"}`, "data-target": target },
      t(kind === "kitting" ? "device.action.start_kitting" : `device.action.${target}`),
    );
    button.addEventListener("click", () => openAction(target));
    buttons.append(button);
  }
}

let actionTarget = null;
let actionFieldSpecs = [];
let actionErrorCode = null;

function renderActionError() {
  const box = document.getElementById("action-error");
  box.hidden = !actionErrorCode;
  box.textContent = actionErrorCode ? tError(actionErrorCode) : "";
}

async function openAction(target) {
  const form = document.getElementById("action-form");
  actionTarget = target;
  actionErrorCode = null;
  renderActionError();
  const heading = document.getElementById("action-form-heading");
  heading.textContent = t(
    actionKind(target) === "kitting" ? "device.action.start_kitting" : `device.action.${target}`,
  );
  form.hidden = false;
  if (actionKind(target) === "kitting") {
    // The checklist comes from the template for this device type.
    actionFieldSpecs = [];
    const fields = document.getElementById("action-fields");
    fields.replaceChildren(el("p", { class: "muted" }, t("device.kitting_start_help")));
  } else {
    try {
      actionFieldSpecs = await actionFields(target);
    } catch (error) {
      actionErrorCode = errorCode(error);
      renderActionError();
      return;
    }
    buildFields(document.getElementById("action-fields"), actionFieldSpecs, {}, "action");
  }
  document.getElementById("action-confirm").focus();
}

function closeAction() {
  document.getElementById("action-form").hidden = true;
  actionTarget = null;
}

async function submitAction(event) {
  event.preventDefault();
  const form = document.getElementById("action-form");
  const confirm = document.getElementById("action-confirm");
  actionErrorCode = null;
  clearFieldErrors(form);
  confirm.disabled = true;
  try {
    if (actionKind(actionTarget) === "kitting") {
      await api(`/assets/${assetId}/kitting/start`, { method: "POST", body: {} });
      selectedRun = null;
    } else {
      const values = readFields(form, actionFieldSpecs);
      const body = { new_status: actionTarget };
      if (values.employee_id) {
        body.employee_id = Number(values.employee_id);
      }
      if (values.note) {
        body.note = values.note;
      }
      if (values.wipe_confirmed) {
        body.wipe_confirmed = true;
      }
      await api(`/assets/${assetId}/status`, { method: "POST", body });
    }
    const target = actionTarget;
    closeAction();
    announce("device.status_changed", { status: `status.${target}` });
    await reloadAll();
  } catch (error) {
    actionErrorCode = errorCode(error);
    if (error instanceof ApiError && error.status === 422) {
      showFieldErrors(form, error.detail);
    }
  } finally {
    confirm.disabled = false;
    renderActionError();
  }
}

/** A success message; params whose value is a translation key are translated when shown. */
function announce(key, params = {}) {
  lastAction = { key, params };
  renderAnnouncement();
}

function renderAnnouncement() {
  actionMessage.hidden = !lastAction;
  if (lastAction) {
    const params = Object.fromEntries(
      Object.entries(lastAction.params).map(([name, value]) => [name, hasKey(value) ? t(value) : value]),
    );
    actionMessage.textContent = t(lastAction.key, params);
  }
}

// Kitting checklist

function renderKitting() {
  const panel = document.getElementById("kitting-panel");
  panel.hidden = !isStaff();
  if (!isStaff() || !checklist) {
    return;
  }
  const empty = checklist.runs.length === 0;
  document.getElementById("kitting-empty").hidden = !empty;
  document.getElementById("kitting-body").hidden = empty;
  const picker = document.getElementById("run-picker");
  picker.hidden = checklist.runs.length < 2;
  const select = document.getElementById("run-select");
  select.replaceChildren(
    ...checklist.runs.map((run) =>
      el("option", { value: String(run) }, t("device.kitting_run_label", { run: fmtNumber(run) })),
    ),
  );
  select.value = String(checklist.run_no ?? "");
  if (empty) {
    return;
  }
  const progress = document.getElementById("kitting-progress");
  progress.value = checklist.percent;
  progress.setAttribute("aria-valuetext", t("device.kitting_count", { done: checklist.done, total: checklist.total }));
  document.getElementById("kitting-percent").textContent = t("device.kitting_count_percent", {
    done: fmtNumber(checklist.done),
    total: fmtNumber(checklist.total),
    percent: fmtNumber(checklist.percent),
  });
  const canTick = checklist.editable && isAdmin();
  document.getElementById("kitting-readonly").hidden = canTick;
  const list = document.getElementById("kitting-tasks");
  list.replaceChildren(
    ...checklist.tasks.map((task) => {
      const item = el("li", { class: task.done ? "done" : "" });
      const id = `task-${task.id}`;
      const box = el("input", { type: "checkbox", id, "data-task": String(task.id) });
      box.checked = task.done;
      box.disabled = !canTick;
      box.addEventListener("change", () => toggleTask(task.id, box));
      const text = getLang() === "ja" ? task.step_ja : task.step_en;
      const label = el("label", { for: id }, text);
      item.append(box, label);
      if (task.done_at) {
        item.append(el("span", { class: "muted task-meta" }, fmtDate(task.done_at, { time: true })));
      }
      return item;
    }),
  );
}

async function toggleTask(taskId, box) {
  const errorBox = document.getElementById("kitting-error");
  errorBox.hidden = true;
  box.disabled = true;
  try {
    await api(`/kitting-tasks/${taskId}`, { method: "PATCH", body: { done: box.checked } });
    await Promise.all([loadChecklist(), loadHistory()]);
  } catch (error) {
    box.checked = !box.checked;
    errorBox.textContent = tError(errorCode(error));
    errorBox.hidden = false;
  } finally {
    renderKitting();
    renderHistory();
  }
}

async function loadChecklist() {
  const query = selectedRun ? `?run_no=${selectedRun}` : "";
  checklist = await api(`/assets/${assetId}/kitting${query}`);
}

// Loans, tickets, history

function renderLoans() {
  const panel = document.getElementById("loans-panel");
  panel.hidden = !isStaff();
  if (!isStaff() || !loans) {
    return;
  }
  document.getElementById("loans-empty").hidden = loans.length > 0;
  document.getElementById("loans-table").hidden = loans.length === 0;
  document.querySelector("#loans-table tbody").replaceChildren(
    ...loans.map((loan) => {
      const row = el("tr", loan.is_overdue ? { class: "overdue" } : {});
      const returned = el("td", { class: "nowrap" });
      if (loan.returned_at) {
        returned.textContent = fmtDate(loan.returned_at);
      } else {
        returned.append(
          el("span", { class: `badge ${loan.is_overdue ? "badge-overdue" : "badge-on_loan"}` },
            t(loan.is_overdue ? "loan.overdue" : "loan.open")),
        );
      }
      row.append(
        el("td", {}, `${loan.employee.name} (${loan.employee.department})`),
        el("td", { class: "nowrap" }, fmtDate(loan.lent_at)),
        el("td", { class: "nowrap" }, fmtDate(loan.due_at)),
        returned,
        el("td", {}, loan.condition ? t(`condition.${loan.condition}`) : "-"),
      );
      return row;
    }),
  );
}

function renderTickets() {
  if (!tickets) {
    return;
  }
  document.getElementById("tickets-empty").hidden = tickets.length > 0;
  document.getElementById("tickets-table").hidden = tickets.length === 0;
  document.querySelector("#tickets-table tbody").replaceChildren(
    ...tickets.map((ticket) => {
      const row = el("tr");
      const number = el("td", { class: "nowrap" });
      number.append(el("a", { href: `ticket.html?id=${encodeURIComponent(ticket.id)}` }, `#${ticket.id}`));
      const state = el("td");
      state.append(el("span", { class: `badge badge-ticket-${ticket.status}` }, t(`ticket_status.${ticket.status}`)));
      row.append(
        number,
        el("td", { class: "text-cell" }, ticket.title),
        state,
        el("td", {}, t(`priority.${ticket.priority}`)),
        el("td", { class: "nowrap" }, fmtDate(ticket.created_at)),
      );
      return row;
    }),
  );
}

/** One line describing what an audit entry changed, from its detail. */
function historyDetail(entry) {
  const d = entry.detail || {};
  if (d.old_status && d.new_status) {
    const parts = [`${t(`status.${d.old_status}`)} → ${t(`status.${d.new_status}`)}`];
    if (d.note) {
      parts.push(d.note);
    }
    return parts.join(" / ");
  }
  if (entry.action === "ASSET_UPDATED" || entry.action === "DEVICE_DETAILS_UPDATED") {
    return Object.keys(d)
      .map((field) => (hasKey(`field.${field}`) ? t(`field.${field}`) : field))
      .join(", ");
  }
  if (d.step_no) {
    return t("device.history_step", { step: d.step_no, run: d.run_no });
  }
  if (d.template) {
    return t("device.history_template", { template: d.template, run: d.run_no });
  }
  return "";
}

function renderHistory() {
  const panel = document.getElementById("history-panel");
  panel.hidden = !isStaff();
  if (!isStaff() || !history) {
    return;
  }
  document.getElementById("history-empty").hidden = history.length > 0;
  // Newest first reads best on a timeline.
  document.getElementById("history-list").replaceChildren(
    ...[...history].reverse().map((entry) => {
      const item = el("li");
      const key = `audit.${entry.action}`;
      item.append(
        el("time", { datetime: entry.created_at, class: "muted" }, fmtDate(entry.created_at, { time: true })),
        el("strong", {}, hasKey(key) ? t(key) : entry.action),
      );
      const detail = historyDetail(entry);
      if (detail) {
        item.append(el("span", { class: "timeline-detail" }, detail));
      }
      item.append(el("span", { class: "muted timeline-actor" }, entry.actor_email || t("device.history_system")));
      return item;
    }),
  );
}

// Loading

async function loadAsset() {
  asset = await api(`/assets/${assetId}`);
}

async function loadHistory() {
  history = await api(`/assets/${assetId}/history`);
}

function renderAll() {
  if (!asset) {
    return;
  }
  renderHeader();
  renderActions();
  renderInfo();
  renderDetails();
  renderKitting();
  renderLoans();
  renderTickets();
  renderHistory();
  renderAnnouncement();
}

/** Load the optional sections; each failure stays inside its own section. */
async function loadSections() {
  const jobs = [
    [api(`/tickets?asset_id=${assetId}&limit=50`).then((page) => (tickets = page.items)), "tickets-empty"],
  ];
  if (isStaff()) {
    jobs.push(
      [loadChecklist(), "kitting-empty"],
      [api(`/loans?asset_id=${assetId}&limit=50`).then((page) => (loans = page.items)), "loans-empty"],
      [loadHistory(), "history-empty"],
    );
  }
  const outcomes = await Promise.allSettled(jobs.map(([job]) => job));
  jobs.forEach(([, emptyId]) => resetSection(emptyId));
  renderAll();
  outcomes.forEach((outcome, index) => {
    if (outcome.status === "rejected") {
      const emptyId = jobs[index][1];
      if (emptyId === "kitting-empty") {
        document.getElementById("kitting-body").hidden = true;
      }
      sectionError(emptyId, outcome.reason);
    }
  });
}

async function reloadAll() {
  try {
    await loadAsset();
  } catch (error) {
    showStatus(status, { state: "error", message: tError(errorCode(error)), onRetry: reloadAll });
    return;
  }
  await loadSections();
}

async function main() {
  user = await startPage("devices.html");
  if (!user) {
    return;
  }
  if (!Number.isInteger(assetId) || assetId < 1) {
    showStatus(status, { state: "error", message: tError("ASSET_NOT_FOUND") });
    return;
  }
  showStatus(status, { state: "loading" });
  try {
    await loadAsset();
  } catch (error) {
    showStatus(status, { state: "error", message: tError(errorCode(error)), onRetry: main });
    return;
  }
  showStatus(status, { state: "done" });
  document.getElementById("device").hidden = false;

  if (isAdmin()) {
    setUpEditForm("info", EDIT_FIELDS, () => asset, `/assets/${assetId}`);
    setUpEditForm("details", DETAIL_FIELDS, () => asset.details || {}, `/assets/${assetId}/details`);
    document.getElementById("action-form").addEventListener("submit", submitAction);
    document.getElementById("action-cancel").addEventListener("click", closeAction);
  }
  document.getElementById("run-select").addEventListener("change", async (event) => {
    selectedRun = Number(event.target.value);
    try {
      await loadChecklist();
    } catch (error) {
      sectionError("kitting-empty", error);
    }
    renderKitting();
  });
  document.addEventListener("langchange", () => {
    renderAll();
    renderActionError();
    retranslateSectionErrors();
  });
  renderAll();
  await loadSections();
}

main();

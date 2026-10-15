/**
 * Device list: filters, search, paging, and the add-device form.
 *
 * Filters live in the URL (devices.html?status=kitting&page=2), so a filtered
 * view can be bookmarked or linked from the dashboard. The server scopes the
 * results: managers see their department, employees only their own devices.
 */

import { ApiError, api } from "./api.js";
import {
  ADMIN_ROLES,
  ASSET_STATUSES,
  ASSET_TYPES,
  COMPLIANCE,
  CREATE_FIELDS,
  OS_CHOICES,
  complianceBadge,
  holderText,
  statusBadge,
} from "./asset-fields.js";
import { buildFields, clearFieldErrors, readFields, showFieldErrors } from "./forms.js";
import { t, tError } from "./i18n.js";
import { el, fmtNumber, showStatus, startPage } from "./page.js";

const PAGE_SIZE = 50;
const FILTER_NAMES = ["q", "type", "status", "os", "compliance", "overdue"];

const status = document.getElementById("page-status");
const results = document.getElementById("results");
const filtersForm = document.getElementById("filters");
let state = { page: 1 };
let lastPage = null;
let requestSeq = 0;

/** Fill a filter select with "All" plus translated choices. */
function fillSelect(id, values, prefix) {
  const select = document.getElementById(id);
  select.replaceChildren(el("option", { value: "", "data-i18n": "common.all" }, t("common.all")));
  for (const value of values) {
    const attributes = prefix ? { value, "data-i18n": `${prefix}.${value}` } : { value };
    select.append(el("option", attributes, prefix ? t(`${prefix}.${value}`) : value));
  }
}

function readUrl() {
  const params = new URLSearchParams(window.location.search);
  const next = { page: Math.max(1, Number.parseInt(params.get("page"), 10) || 1) };
  for (const name of FILTER_NAMES) {
    const value = params.get(name);
    if (value) {
      next[name] = value;
    }
  }
  return next;
}

function writeUrl() {
  const params = new URLSearchParams();
  for (const name of FILTER_NAMES) {
    if (state[name]) {
      params.set(name, state[name]);
    }
  }
  if (state.page > 1) {
    params.set("page", String(state.page));
  }
  const query = params.toString();
  window.history.replaceState(null, "", query ? `?${query}` : window.location.pathname);
}

function syncFormFromState() {
  for (const name of FILTER_NAMES) {
    const input = filtersForm.elements.namedItem(name);
    input.value = state[name] || "";
    // A value from the URL that is not a known choice falls back to "All".
    if (input.value !== (state[name] || "")) {
      delete state[name];
      input.value = "";
    }
  }
}

function renderRows(page) {
  const body = document.querySelector("#device-table tbody");
  body.replaceChildren(
    ...page.items.map((asset) => {
      const row = el("tr");
      const tag = el("td", { class: "nowrap" });
      tag.append(el("a", { href: `device.html?id=${encodeURIComponent(asset.id)}` }, asset.asset_tag));
      const statusCell = el("td");
      statusCell.append(statusBadge(asset.status));
      const compliance = el("td");
      compliance.append(asset.compliance ? complianceBadge(asset.compliance) : document.createTextNode("-"));
      row.append(
        tag,
        el("td", {}, t(`type.${asset.type}`)),
        el("td", {}, `${asset.manufacturer} ${asset.model}`),
        statusCell,
        el("td", {}, holderText(asset.holder)),
        el("td", {}, asset.os || "-"),
        compliance,
      );
      return row;
    }),
  );
  const empty = page.items.length === 0;
  document.getElementById("device-table").hidden = empty;
  document.getElementById("no-results").hidden = !empty;

  const from = empty ? 0 : (state.page - 1) * PAGE_SIZE + 1;
  const to = (state.page - 1) * PAGE_SIZE + page.items.length;
  document.getElementById("result-count").textContent = t("devices.count", { total: fmtNumber(page.total) });
  document.getElementById("page-info").textContent = t("common.page_info", {
    from: fmtNumber(from),
    to: fmtNumber(to),
    total: fmtNumber(page.total),
  });
  document.getElementById("page-prev").disabled = state.page <= 1;
  document.getElementById("page-next").disabled = to >= page.total;
}

async function load() {
  const seq = ++requestSeq;
  writeUrl();
  results.setAttribute("aria-busy", "true");
  if (!lastPage) {
    showStatus(status, { state: "loading" });
  }
  const params = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String((state.page - 1) * PAGE_SIZE) });
  for (const name of FILTER_NAMES) {
    if (state[name]) {
      params.set(name, state[name]);
    }
  }
  try {
    const page = await api(`/assets?${params}`);
    if (seq !== requestSeq) {
      return; // A newer search was started; drop this older answer.
    }
    lastPage = page;
    showStatus(status, { state: "done" });
    results.hidden = false;
    renderRows(page);
  } catch (error) {
    if (seq !== requestSeq) {
      return;
    }
    const code = error instanceof ApiError ? error.code : "UNKNOWN_ERROR";
    showStatus(status, { state: "error", message: tError(code), onRetry: load });
  } finally {
    if (seq === requestSeq) {
      results.removeAttribute("aria-busy");
    }
  }
}

function setUpFilters(user) {
  fillSelect("filter-type", ASSET_TYPES, "type");
  fillSelect("filter-status", ASSET_STATUSES, "status");
  fillSelect("filter-os", OS_CHOICES);
  fillSelect("filter-compliance", COMPLIANCE, "compliance");
  const overdue = document.getElementById("filter-overdue");
  overdue.replaceChildren(
    el("option", { value: "", "data-i18n": "common.all" }, t("common.all")),
    el("option", { value: "true", "data-i18n": "devices.overdue_only" }, t("devices.overdue_only")),
  );
  if (user.role === "employee") {
    // Employees see only their own few devices, so filters add nothing.
    filtersForm.hidden = true;
  }

  syncFormFromState();
  let timer = null;
  filtersForm.addEventListener("input", (event) => {
    const { name, value } = event.target;
    if (!FILTER_NAMES.includes(name)) {
      return;
    }
    if (value) {
      state[name] = value;
    } else {
      delete state[name];
    }
    state.page = 1;
    clearTimeout(timer);
    // Typing waits a moment so every key press does not start a request.
    timer = setTimeout(load, name === "q" ? 300 : 0);
  });
  filtersForm.addEventListener("submit", (event) => event.preventDefault());
  document.getElementById("filter-reset").addEventListener("click", () => {
    state = { page: 1 };
    syncFormFromState();
    load();
  });
  document.getElementById("page-prev").addEventListener("click", () => {
    state.page -= 1;
    load();
  });
  document.getElementById("page-next").addEventListener("click", () => {
    state.page += 1;
    load();
  });
}

function setUpAddForm() {
  const toggle = document.getElementById("add-toggle");
  const panel = document.getElementById("add-panel");
  const form = document.getElementById("add-form");
  const errorBox = document.getElementById("add-error");
  const success = document.getElementById("add-success");
  let errorCode = null;
  let created = null;

  const renderMessages = () => {
    errorBox.hidden = !errorCode;
    errorBox.textContent = errorCode ? tError(errorCode) : "";
    success.hidden = !created;
    success.textContent = created ? t("devices.created", { tag: created }) : "";
  };
  document.addEventListener("langchange", renderMessages);

  const open = (show) => {
    panel.hidden = !show;
    toggle.setAttribute("aria-expanded", String(show));
    if (show) {
      buildFields(document.getElementById("add-fields"), CREATE_FIELDS, { status: "in_stock" }, "add");
      errorCode = null;
      renderMessages();
      form.elements.namedItem("asset_tag").focus();
    }
  };
  toggle.hidden = false;
  toggle.addEventListener("click", () => open(panel.hidden));
  document.getElementById("add-cancel").addEventListener("click", () => {
    open(false);
    toggle.focus();
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    clearFieldErrors(form);
    errorCode = null;
    created = null;
    const submit = form.querySelector('button[type="submit"]');
    submit.disabled = true;
    try {
      const asset = await api("/assets", { method: "POST", body: readFields(form, CREATE_FIELDS) });
      created = asset.asset_tag;
      open(false);
      state = { page: 1, q: asset.asset_tag };
      syncFormFromState();
      await load();
    } catch (error) {
      errorCode = error instanceof ApiError ? error.code : "UNKNOWN_ERROR";
      if (error instanceof ApiError && error.status === 422) {
        showFieldErrors(form, error.detail);
      }
      if (errorCode === "ASSET_TAG_EXISTS" || errorCode === "SERIAL_NUMBER_EXISTS") {
        showFieldErrors(form, {
          fields: [{ field: errorCode === "ASSET_TAG_EXISTS" ? "asset_tag" : "serial_number" }],
        });
      }
    } finally {
      submit.disabled = false;
      renderMessages();
    }
  });
}

async function main() {
  const user = await startPage("devices.html");
  if (!user) {
    return;
  }
  if (user.role === "employee") {
    const heading = document.getElementById("page-heading");
    heading.dataset.i18n = "devices.my_title";
    heading.textContent = t("devices.my_title");
  }
  state = readUrl();
  setUpFilters(user);
  if (ADMIN_ROLES.includes(user.role)) {
    setUpAddForm();
  }
  document.addEventListener("langchange", () => {
    if (lastPage) {
      renderRows(lastPage);
    }
  });
  await load();
}

main();

/**
 * Employee page: details, the devices they hold, and their tickets.
 *
 * Leaver flow (Part C, section 6): IT marks the employee as left, which also
 * disables their login. Devices are never returned automatically; each one is
 * returned here (assigned devices) or on the loans page (loaned devices), so
 * every return is a deliberate, recorded action.
 */

import { ApiError, api } from "./api.js";
import { ADMIN_ROLES, statusBadge } from "./asset-fields.js";
import { buildFields, clearFieldErrors, readFields, showFieldErrors } from "./forms.js";
import { fmtDate, t, tError } from "./i18n.js";
import { EMPLOYEE_FIELDS } from "./people-fields.js";
import { el, showStatus, startPage } from "./page.js";

const employeeId = Number.parseInt(new URLSearchParams(window.location.search).get("id"), 10);
const status = document.getElementById("page-status");
let user = null;
let employee = null;
let devices = null;
let devicesError = null;
let tickets = null;
let lastMessage = null;

const isAdmin = () => ADMIN_ROLES.includes(user.role);
const errorCode = (error) => (error instanceof ApiError ? error.code : "UNKNOWN_ERROR");

function announce(key, params = {}) {
  lastMessage = { key, params };
  renderMessage();
}

function renderMessage() {
  const box = document.getElementById("action-message");
  box.hidden = !lastMessage;
  if (lastMessage) {
    box.textContent = t(lastMessage.key, lastMessage.params);
  }
}

function renderHeader() {
  document.title = `${employee.name} | ${t("employee.title")}`;
  document.getElementById("page-heading").textContent = employee.name;
  document.getElementById("employee-summary").replaceChildren(
    el("span", {}, `${employee.employee_code} / ${employee.department} / ${employee.position}`),
    el("span", { class: `badge badge-emp-${employee.status}` }, t(`employee_status.${employee.status}`)),
  );
}

function renderInfo() {
  const rows = [
    ["field.employee_code", employee.employee_code],
    ["field.name", employee.name],
    ["field.email", employee.email],
    ["field.department", employee.department],
    ["field.position", employee.position],
    ["field.join_date", fmtDate(employee.join_date)],
    ["field.status", t(`employee_status.${employee.status}`)],
  ];
  document.getElementById("info-list").replaceChildren(
    ...rows.flatMap(([key, value]) => [el("dt", {}, t(key)), el("dd", {}, value || "-")]),
  );
}

function renderLeaver() {
  const panel = document.getElementById("leaver-panel");
  panel.hidden = !isAdmin() || employee.status === "left";
  document.getElementById("leaver-question").textContent = t("employee.leaver_question", { name: employee.name });
}

async function returnDevice(device, button) {
  button.disabled = true;
  devicesError = null;
  try {
    await api(`/assets/${device.id}/status`, { method: "POST", body: { new_status: "returned" } });
    announce("employee.device_returned", { tag: device.asset_tag });
    await loadDevices();
  } catch (error) {
    devicesError = errorCode(error);
    button.disabled = false;
  }
  renderDevices();
}

/** The action for each held device, by status. */
function deviceAction(device) {
  if (!isAdmin()) {
    return null;
  }
  if (device.status === "assigned") {
    const button = el("button", { type: "button", class: "button button-quiet button-small", "data-return": String(device.id) },
      t("employee.return_device"));
    button.addEventListener("click", () => returnDevice(device, button));
    return button;
  }
  if (device.status === "on_loan") {
    // Loan returns record the condition and wipe on the loans page.
    return el("a", { class: "button button-quiet button-small", href: `loans.html?asset_id=${encodeURIComponent(device.id)}` },
      t("device.action.return_loan"));
  }
  // In repair: the device comes back through the device page (repair -> ready).
  return el("a", { class: "button button-quiet button-small", href: `device.html?id=${encodeURIComponent(device.id)}` },
    t("employee.open_device"));
}

function renderDevices() {
  const errorBox = document.getElementById("devices-error");
  errorBox.hidden = !devicesError;
  errorBox.textContent = devicesError ? tError(devicesError) : "";
  if (!devices) {
    return;
  }
  const leftWithDevices = employee.status === "left" && devices.length > 0;
  document.getElementById("devices-empty").hidden = devices.length > 0;
  document.getElementById("devices-table").hidden = devices.length === 0;
  const heading = document.getElementById("devices-heading");
  heading.textContent = leftWithDevices
    ? t("employee.devices_still_held", { count: devices.length })
    : t("employee.devices");
  heading.classList.toggle("text-danger", leftWithDevices);
  document.querySelector("#devices-table tbody").replaceChildren(
    ...devices.map((device) => {
      const row = el("tr", device.open_loan?.is_overdue ? { class: "overdue" } : {});
      const tag = el("td", { class: "nowrap" });
      tag.append(el("a", { href: `device.html?id=${encodeURIComponent(device.id)}` }, device.asset_tag));
      const state = el("td", { class: "badge-row" });
      state.append(statusBadge(device.status));
      if (device.open_loan?.is_overdue) {
        state.append(el("span", { class: "badge badge-overdue" }, t("loan.overdue")));
      }
      const action = el("td", { class: "num" });
      const control = deviceAction(device);
      if (control) {
        action.append(control);
      }
      row.append(
        tag,
        el("td", {}, t(`type.${device.type}`)),
        el("td", {}, `${device.manufacturer} ${device.model}`),
        state,
        el("td", { class: "nowrap" }, device.open_loan ? fmtDate(device.open_loan.due_at) : "-"),
        action,
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

function renderAll() {
  if (!employee) {
    return;
  }
  renderHeader();
  renderInfo();
  renderLeaver();
  renderDevices();
  renderTickets();
  renderMessage();
}

async function loadDevices() {
  devices = await api(`/employees/${employeeId}/devices`);
}

async function loadAll() {
  employee = await api(`/employees/${employeeId}`);
  const [deviceResult, ticketResult] = await Promise.allSettled([
    loadDevices(),
    api(`/tickets?requester_id=${employeeId}&limit=50`),
  ]);
  devicesError = deviceResult.status === "rejected" ? errorCode(deviceResult.reason) : null;
  tickets = ticketResult.status === "fulfilled" ? ticketResult.value.items : [];
}

function setUpLeaver() {
  const confirmBox = document.getElementById("leaver-confirm");
  const start = document.getElementById("leaver-start");
  const errorBox = document.getElementById("leaver-error");
  let code = null;
  const renderError = () => {
    errorBox.hidden = !code;
    errorBox.textContent = code ? tError(code) : "";
  };
  document.addEventListener("langchange", renderError);
  start.addEventListener("click", () => {
    confirmBox.hidden = false;
    start.hidden = true;
    document.getElementById("leaver-no").focus();
  });
  document.getElementById("leaver-no").addEventListener("click", () => {
    confirmBox.hidden = true;
    start.hidden = false;
    start.focus();
  });
  document.getElementById("leaver-yes").addEventListener("click", async (event) => {
    event.target.disabled = true;
    code = null;
    try {
      await api(`/employees/${employeeId}`, { method: "DELETE" });
      await loadAll();
      announce("employee.marked_left", { name: employee.name });
      renderAll();
    } catch (error) {
      code = errorCode(error);
    } finally {
      event.target.disabled = false;
      confirmBox.hidden = true;
      start.hidden = false;
      renderError();
    }
  });
}

function setUpEdit() {
  const button = document.getElementById("info-edit");
  const form = document.getElementById("info-form");
  const list = document.getElementById("info-list");
  const errorBox = document.getElementById("info-error");
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
      buildFields(document.getElementById("info-fields"), EMPLOYEE_FIELDS, employee, "info");
      form.querySelector("input").focus();
    }
  };
  button.hidden = false;
  button.addEventListener("click", () => open(true));
  document.getElementById("info-cancel").addEventListener("click", () => open(false));
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    clearFieldErrors(form);
    code = null;
    const body = readFields(form, EMPLOYEE_FIELDS, { onlyChanged: true });
    if (Object.keys(body).length === 0) {
      open(false);
      return;
    }
    try {
      employee = await api(`/employees/${employeeId}`, { method: "PUT", body });
      open(false);
      announce("device.saved");
      renderAll();
    } catch (error) {
      code = errorCode(error);
      if (error instanceof ApiError && error.status === 422) {
        showFieldErrors(form, error.detail);
      }
      const field = { EMPLOYEE_CODE_EXISTS: "employee_code", EMAIL_ALREADY_EXISTS: "email" }[code];
      if (field) {
        showFieldErrors(form, { fields: [{ field }] });
      }
    } finally {
      renderError();
    }
  });
}

async function main() {
  user = await startPage("employees.html", ["super_admin", "it_admin", "manager"]);
  if (!user) {
    return;
  }
  if (!Number.isInteger(employeeId) || employeeId < 1) {
    showStatus(status, { state: "error", message: tError("EMPLOYEE_NOT_FOUND") });
    return;
  }
  showStatus(status, { state: "loading" });
  try {
    await loadAll();
  } catch (error) {
    showStatus(status, { state: "error", message: tError(errorCode(error)), onRetry: main });
    return;
  }
  showStatus(status, { state: "done" });
  document.getElementById("employee").hidden = false;
  if (isAdmin()) {
    setUpLeaver();
    setUpEdit();
  }
  document.addEventListener("langchange", renderAll);
  renderAll();
}

main();

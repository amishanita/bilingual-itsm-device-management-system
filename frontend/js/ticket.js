/**
 * Ticket page: details, status changes, assignment, edits, and comments.
 *
 * What a user may do comes from the API (can_edit and allowed_statuses):
 * IT staff can change everything; the requester can edit the text while the
 * ticket is open and close or reopen it once it is resolved. Closed tickets
 * are read-only. The server checks every change again.
 */

import { ApiError, api } from "./api.js";
import { ADMIN_ROLES } from "./asset-fields.js";
import { buildFields, clearFieldErrors, readFields, showFieldErrors } from "./forms.js";
import { fmtDate, hasKey, t, tError } from "./i18n.js";
import { el, showStatus, startPage } from "./page.js";
import { CATEGORIES, PRIORITIES } from "./ticket-fields.js";

const params = new URLSearchParams(window.location.search);
const ticketId = Number.parseInt(params.get("id"), 10);
const status = document.getElementById("page-status");
let user = null;
let ticket = null;
let assignees = [];
let lastMessage = params.get("created") ? { key: "tickets.created", params: { id: ticketId } } : null;
let actionError = null;

const isAdmin = () => ADMIN_ROLES.includes(user.role);
const errorCode = (error) => (error instanceof ApiError ? error.code : "UNKNOWN_ERROR");

function announce(key, messageParams = {}) {
  lastMessage = { key, params: messageParams };
  renderMessage();
}

function renderMessage() {
  const box = document.getElementById("action-message");
  box.hidden = !lastMessage;
  if (lastMessage) {
    const translated = Object.fromEntries(
      Object.entries(lastMessage.params).map(([name, value]) => [name, typeof value === "string" && hasKey(value) ? t(value) : value]),
    );
    box.textContent = t(lastMessage.key, translated);
  }
}

function renderHeader() {
  document.title = `#${ticket.id} ${ticket.title} | ${t("ticket.page_title")}`;
  document.getElementById("page-heading").textContent = `#${ticket.id} ${ticket.title}`;
  document.getElementById("ticket-summary").replaceChildren(
    el("span", { class: `badge badge-ticket-${ticket.status}` }, t(`ticket_status.${ticket.status}`)),
    el("span", { class: `badge badge-priority-${ticket.priority}` }, `${t("ticket.priority")}: ${t(`priority.${ticket.priority}`)}`),
    el("span", {}, t(`category.${ticket.category}`)),
  );
}

function renderInfo() {
  const device = ticket.asset
    ? el("a", { href: `device.html?id=${encodeURIComponent(ticket.asset.id)}` }, `${ticket.asset.asset_tag} (${ticket.asset.model})`)
    : "-";
  const rows = [
    ["ticket.requester", `${ticket.requester.name} (${ticket.requester.department})`],
    ["ticket.category", t(`category.${ticket.category}`)],
    ["ticket.priority", t(`priority.${ticket.priority}`)],
    ["field.status", t(`ticket_status.${ticket.status}`)],
    ["ticket.assignee", ticket.assignee ? ticket.assignee.email : t("tickets.unassigned")],
    ["ticket.device", device],
    ["ticket.source", t(`ticket.source_${ticket.source}`)],
    ["field.created_at", fmtDate(ticket.created_at, { time: true })],
    ["field.updated_at", fmtDate(ticket.updated_at, { time: true })],
    ["ticket.resolved_at", ticket.resolved_at ? fmtDate(ticket.resolved_at, { time: true }) : "-"],
  ];
  document.getElementById("info-list").replaceChildren(
    ...rows.flatMap(([key, value]) => {
      const description = el("dd");
      if (value instanceof Node) {
        description.append(value);
      } else {
        description.textContent = value;
      }
      return [el("dt", {}, t(key)), description];
    }),
  );
  // The description is what the requester typed: shown as stored, never as HTML.
  document.getElementById("description").textContent = ticket.description;
}

/** Button text for a status move; resolved -> in_progress reads as "reopen". */
function actionLabel(target) {
  if (target === "in_progress" && ticket.status === "resolved") {
    return t("ticket.action.reopen");
  }
  return t(`ticket.action.${target}`);
}

function renderActions() {
  const canAssign = isAdmin() && ticket.can_edit;
  const panel = document.getElementById("actions-panel");
  panel.hidden = ticket.allowed_statuses.length === 0 && !canAssign;
  const buttons = document.getElementById("action-buttons");
  buttons.replaceChildren();
  for (const target of ticket.allowed_statuses) {
    const button = el("button", { type: "button", class: "button button-quiet", "data-status": target }, actionLabel(target));
    button.addEventListener("click", () => update({ status: target }, "ticket.status_changed", { status: `ticket_status.${target}` }));
    buttons.append(button);
  }
  if (canAssign && (!ticket.assignee || ticket.assignee.id !== user.id)) {
    const mine = el("button", { type: "button", class: "button button-quiet", id: "assign-me" }, t("ticket.assign_to_me"));
    mine.addEventListener("click", () => update({ assignee_id: user.id }, "ticket.assigned", { email: user.email }));
    buttons.append(mine);
  }
  const errorBox = document.getElementById("action-error");
  errorBox.hidden = !actionError;
  errorBox.textContent = actionError ? tError(actionError) : "";
}

function renderComments() {
  const list = document.getElementById("comment-list");
  document.getElementById("comments-empty").hidden = ticket.comments.length > 0;
  list.replaceChildren(
    ...ticket.comments.map((comment) => {
      const item = el("li", { class: comment.author.id === user.id ? "comment own" : "comment" });
      const meta = el("p", { class: "comment-meta" });
      meta.append(
        el("strong", {}, comment.author.email),
        el("time", { datetime: comment.created_at, class: "muted" }, fmtDate(comment.created_at, { time: true })),
      );
      item.append(meta, el("p", { class: "ticket-text" }, comment.body));
      return item;
    }),
  );
  document.getElementById("comment-form").hidden = !ticket.can_edit;
  document.getElementById("comments-closed").hidden = ticket.status !== "closed";
}

/** Can this user edit the ticket's fields right now? */
function canEditFields() {
  if (!ticket.can_edit) {
    return false;
  }
  // The requester may only edit the text while the ticket is still open.
  return isAdmin() || ticket.status === "open";
}

function renderAll() {
  if (!ticket) {
    return;
  }
  renderHeader();
  renderInfo();
  renderActions();
  renderComments();
  renderMessage();
  const editing = !document.getElementById("info-form").hidden;
  document.getElementById("info-edit").hidden = !canEditFields() || editing;
}

/**
 * Send a change. Params whose value is a translation key are translated when
 * the message is shown, so the message follows a language switch.
 */
async function update(body, messageKey, messageParams) {
  actionError = null;
  try {
    ticket = await api(`/tickets/${ticketId}`, { method: "PUT", body });
    announce(messageKey, messageParams);
  } catch (error) {
    actionError = errorCode(error);
  }
  renderAll();
}

function editFields() {
  const fields = [
    { name: "title", label: "ticket.title", type: "text", required: true, maxLength: 200 },
    { name: "description", label: "ticket.description", type: "textarea", required: true, maxLength: 5000 },
  ];
  if (isAdmin()) {
    fields.push(
      { name: "category", label: "ticket.category", type: "select", required: true,
        options: CATEGORIES.map((value) => ({ value, label: `category.${value}` })) },
      { name: "priority", label: "ticket.priority", type: "select", required: true,
        options: PRIORITIES.map((value) => ({ value, label: `priority.${value}` })) },
      { name: "assignee_id", label: "ticket.assignee", type: "select", nullable: true,
        options: assignees.map((s) => ({ value: String(s.id), text: s.email })) },
    );
  }
  return fields;
}

function setUpEdit() {
  const button = document.getElementById("info-edit");
  const form = document.getElementById("info-form");
  const list = document.getElementById("info-list");
  const errorBox = document.getElementById("info-error");
  let code = null;
  let fields = [];
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
      fields = editFields();
      buildFields(document.getElementById("info-fields"), fields,
        { ...ticket, assignee_id: ticket.assignee ? String(ticket.assignee.id) : "" }, "info");
      form.querySelector("input").focus();
    }
  };
  button.addEventListener("click", () => open(true));
  document.getElementById("info-cancel").addEventListener("click", () => {
    open(false);
    renderAll();
  });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    clearFieldErrors(form);
    code = null;
    const body = readFields(form, fields, { onlyChanged: true });
    if ("assignee_id" in body && body.assignee_id !== null) {
      body.assignee_id = Number(body.assignee_id);
    }
    if (Object.keys(body).length === 0) {
      open(false);
      renderAll();
      return;
    }
    try {
      ticket = await api(`/tickets/${ticketId}`, { method: "PUT", body });
      open(false);
      announce("device.saved");
      renderAll();
    } catch (error) {
      code = errorCode(error);
      if (error instanceof ApiError && error.status === 422) {
        showFieldErrors(form, error.detail);
      }
    } finally {
      renderError();
    }
  });
}

function setUpComments() {
  const form = document.getElementById("comment-form");
  const errorBox = document.getElementById("comment-error");
  let code = null;
  const renderError = () => {
    errorBox.hidden = !code;
    errorBox.textContent = code ? tError(code) : "";
  };
  document.addEventListener("langchange", renderError);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const box = form.elements.namedItem("body");
    code = null;
    if (!box.value.trim()) {
      code = "VALIDATION_ERROR";
      box.setAttribute("aria-invalid", "true");
      renderError();
      return;
    }
    box.removeAttribute("aria-invalid");
    const submit = form.querySelector('button[type="submit"]');
    submit.disabled = true;
    try {
      await api(`/tickets/${ticketId}/comments`, { method: "POST", body: { body: box.value.trim() } });
      box.value = "";
      ticket = await api(`/tickets/${ticketId}`);
      announce("ticket.comment_added");
      renderAll();
    } catch (error) {
      code = errorCode(error);
    } finally {
      submit.disabled = false;
      renderError();
    }
  });
}

async function main() {
  user = await startPage("tickets.html");
  if (!user) {
    return;
  }
  if (!Number.isInteger(ticketId) || ticketId < 1) {
    showStatus(status, { state: "error", message: tError("TICKET_NOT_FOUND") });
    return;
  }
  showStatus(status, { state: "loading" });
  try {
    ticket = await api(`/tickets/${ticketId}`);
    if (isAdmin()) {
      assignees = await api("/tickets/assignees");
    }
  } catch (error) {
    showStatus(status, { state: "error", message: tError(errorCode(error)), onRetry: main });
    return;
  }
  showStatus(status, { state: "done" });
  document.getElementById("ticket").hidden = false;
  // Clean the one-time "created" flag from the address bar.
  if (params.get("created")) {
    window.history.replaceState(null, "", `?id=${ticketId}`);
  }
  setUpEdit();
  setUpComments();
  document.addEventListener("langchange", () => {
    renderAll();
  });
  renderAll();
}

main();

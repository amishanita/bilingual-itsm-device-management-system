/**
 * Ticket list and the new-ticket form.
 *
 * Employees see and file their own tickets, optionally about a device they
 * hold. IT staff see every ticket, can file one for any employee, and can
 * filter to tickets assigned to them or not yet assigned. Managers see their
 * department's tickets and can file their own.
 */

import { api } from "./api.js";
import { ADMIN_ROLES } from "./asset-fields.js";
import { fmtDate, t } from "./i18n.js";
import { createList, fillSelect, setUpAddForm } from "./list-page.js";
import { el, startPage } from "./page.js";
import { CATEGORIES, PRIORITIES, TICKET_STATUSES } from "./ticket-fields.js";


let user = null;
const isAdmin = () => ADMIN_ROLES.includes(user.role);

function renderRows(page) {
  document.querySelector("#ticket-table tbody").replaceChildren(
    ...page.items.map((ticket) => {
      const row = el("tr");
      const number = el("td", { class: "nowrap" });
      number.append(el("a", { href: `ticket.html?id=${encodeURIComponent(ticket.id)}` }, `#${ticket.id}`));
      const title = el("td", { class: "text-cell" });
      title.append(el("a", { href: `ticket.html?id=${encodeURIComponent(ticket.id)}` }, ticket.title));
      const priority = el("td");
      priority.append(el("span", { class: `badge badge-priority-${ticket.priority}` }, t(`priority.${ticket.priority}`)));
      const state = el("td");
      state.append(el("span", { class: `badge badge-ticket-${ticket.status}` }, t(`ticket_status.${ticket.status}`)));
      row.append(
        number,
        title,
        el("td", {}, t(`category.${ticket.category}`)),
        priority,
        state,
        el("td", {}, ticket.requester.name),
        el("td", {}, ticket.assignee ? ticket.assignee.email : t("tickets.unassigned")),
        el("td", { class: "nowrap" }, fmtDate(ticket.created_at)),
      );
      return row;
    }),
  );
}

const baseFields = () => [
  { name: "title", label: "ticket.title", type: "text", required: true, maxLength: 200 },
  {
    name: "category",
    label: "ticket.category",
    type: "select",
    required: true,
    options: CATEGORIES.map((value) => ({ value, label: `category.${value}` })),
  },
  {
    name: "priority",
    label: "ticket.priority",
    type: "select",
    required: true,
    options: PRIORITIES.map((value) => ({ value, label: `priority.${value}` })),
  },
  { name: "description", label: "ticket.description", type: "textarea", required: true, maxLength: 5000, hint: "tickets.description_hint" },
];

const deviceOption = (a) => ({ value: String(a.id), text: `${a.asset_tag} (${a.manufacturer} ${a.model})` });

/** Fields for the new-ticket form, with choices loaded for this user. */
async function prepareFields() {
  const fields = baseFields();
  if (isAdmin()) {
    const [employees, devices, staff] = await Promise.all([
      api("/employees?status=active&limit=200"),
      api("/assets?limit=200"),
      api("/tickets/assignees"),
    ]);
    fields.splice(
      1,
      0,
      {
        name: "requester_id",
        label: "ticket.requester",
        type: "select",
        required: true,
        options: employees.items.map((e) => ({ value: String(e.id), text: `${e.name} (${e.employee_code}, ${e.department})` })),
      },
      { name: "assignee_id", label: "ticket.assignee", type: "select", options: staff.map((s) => ({ value: String(s.id), text: s.email })) },
    );
    fields.push({ name: "asset_id", label: "ticket.device", type: "select", options: devices.items.map(deviceOption) });
    return fields;
  }
  // Non-IT users can only link a device they hold themselves.
  const page = await api("/assets?limit=200");
  const ownId = user.employee ? user.employee.id : null;
  const own = page.items.filter((a) => a.holder && a.holder.id === ownId);
  fields.push({ name: "asset_id", label: "ticket.device_own", type: "select", options: own.map(deviceOption) });
  return fields;
}

function toBody(values) {
  const body = { title: values.title, description: values.description, category: values.category, priority: values.priority };
  for (const name of ["asset_id", "requester_id", "assignee_id"]) {
    if (values[name]) {
      body[name] = Number(values[name]);
    }
  }
  return body;
}

async function main() {
  user = await startPage("tickets.html");
  if (!user) {
    return;
  }
  if (user.role === "employee") {
    const heading = document.getElementById("page-heading");
    heading.dataset.i18n = "tickets.my_title";
    heading.textContent = t("tickets.my_title");
  }
  fillSelect(document.getElementById("filter-status"), TICKET_STATUSES, "ticket_status");
  fillSelect(document.getElementById("filter-priority"), PRIORITIES, "priority");
  fillSelect(document.getElementById("filter-category"), CATEGORIES, "category");
  const filters = ["q", "status", "priority", "category"];
  if (isAdmin()) {
    document.getElementById("mine-filter").hidden = false;
    document.getElementById("unassigned-filter").hidden = false;
    filters.push("mine", "unassigned");
  }
  const list = createList({
    path: "/tickets",
    filters,
    renderRows,
    countKey: "tickets.count",
    tableId: "ticket-table",
    transform: (params) => {
      // "Assigned to me" is a page filter; the API filters by assignee id.
      if (params.get("mine") === "true") {
        params.set("assignee_id", String(user.id));
      }
      params.delete("mine");
    },
  });
  setUpAddForm({
    fields: [],
    prepare: prepareFields,
    initial: () => ({ priority: "medium" }),
    toBody,
    path: "/tickets",
    success: (ticket) => ({ key: "tickets.created", params: { id: ticket.id } }),
    after: (ticket) => window.location.assign(`ticket.html?id=${encodeURIComponent(ticket.id)}&created=1`),
  });
  await list.start();
}

main();

/**
 * Employee list: search by name, code, or email; filter by department and
 * status; IT staff can add employees. Managers see their own department.
 */

import { api } from "./api.js";
import { ADMIN_ROLES } from "./asset-fields.js";
import { t } from "./i18n.js";
import { createList, fillSelect, setUpAddForm } from "./list-page.js";
import { EMPLOYEE_FIELDS, EMPLOYEE_STATUSES } from "./people-fields.js";
import { el, localDate, startPage } from "./page.js";

function renderRows(page) {
  document.querySelector("#employee-table tbody").replaceChildren(
    ...page.items.map((employee) => {
      const row = el("tr");
      const name = el("td");
      name.append(el("a", { href: `employee.html?id=${encodeURIComponent(employee.id)}` }, employee.name));
      const state = el("td");
      state.append(el("span", { class: `badge badge-emp-${employee.status}` }, t(`employee_status.${employee.status}`)));
      row.append(
        el("td", { class: "nowrap" }, employee.employee_code),
        name,
        el("td", {}, employee.department),
        el("td", {}, employee.position),
        state,
      );
      return row;
    }),
  );
}

async function main() {
  const user = await startPage("employees.html", ["super_admin", "it_admin", "manager"]);
  if (!user) {
    return;
  }
  fillSelect(document.getElementById("filter-status"), EMPLOYEE_STATUSES, "employee_status");
  // Departments are data, so the choices come from the employees themselves.
  let departments = [];
  try {
    const all = await api("/employees?limit=200");
    departments = [...new Set(all.items.map((e) => e.department))].sort((a, b) => a.localeCompare(b, "ja"));
  } catch {
    // The list below reports connection problems; the filter just stays short.
  }
  fillSelect(document.getElementById("filter-department"), departments);

  const list = createList({
    path: "/employees",
    filters: ["q", "department", "status"],
    renderRows,
    countKey: "employees.count",
    tableId: "employee-table",
  });
  if (ADMIN_ROLES.includes(user.role)) {
    setUpAddForm({
      fields: EMPLOYEE_FIELDS,
      initial: () => ({ status: "active", join_date: localDate(new Date()) }),
      path: "/employees",
      success: (employee) => ({ key: "employees.created", params: { name: employee.name } }),
      after: (employee) => list.showOnly({ q: employee.employee_code }),
      fieldForCode: { EMPLOYEE_CODE_EXISTS: "employee_code", EMAIL_ALREADY_EXISTS: "email" },
    });
  }
  await list.start();
}

main();

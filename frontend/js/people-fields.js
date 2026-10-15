/**
 * Employee and login vocabulary shared by the employee, user, and ticket pages.
 */

export const EMPLOYEE_STATUSES = ["active", "on_leave", "left"];

/** Fields of the add and edit forms; "left" is only set by the leaver flow. */
export const EMPLOYEE_FIELDS = [
  { name: "employee_code", label: "field.employee_code", type: "text", required: true, maxLength: 20 },
  { name: "name", label: "field.name", type: "text", required: true, maxLength: 100 },
  { name: "email", label: "field.email", type: "email", required: true, maxLength: 254 },
  { name: "department", label: "field.department", type: "text", required: true, maxLength: 100 },
  { name: "position", label: "field.position", type: "text", required: true, maxLength: 100 },
  { name: "join_date", label: "field.join_date", type: "date", required: true },
  {
    name: "status",
    label: "field.status",
    type: "select",
    required: true,
    options: ["active", "on_leave"].map((value) => ({ value, label: `employee_status.${value}` })),
  },
];

export const ROLES = ["super_admin", "it_admin", "manager", "employee"];

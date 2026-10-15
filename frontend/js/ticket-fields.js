/**
 * Ticket vocabulary shared by the ticket list and the ticket page. Values
 * match the API; labels come from the category, priority, and ticket_status
 * translation keys.
 */

export const CATEGORIES = [
  "password",
  "laptop",
  "smartphone",
  "tablet",
  "vpn",
  "email",
  "software",
  "hardware",
  "network",
  "account",
];
export const PRIORITIES = ["low", "medium", "high", "critical"];
export const TICKET_STATUSES = ["open", "in_progress", "resolved", "closed"];

"""Demo account identity, shared by the seed script and the demo-mode rules (Part B.1)."""

# (login email, role, linked employee code)
DEMO_USERS: tuple[tuple[str, str, str], ...] = (
    ("admin@demo", "super_admin", "E0001"),
    ("it@demo", "it_admin", "E0002"),
    ("manager@demo", "manager", "E0007"),
    ("employee@demo", "employee", "E0010"),
)

DEMO_EMAILS = frozenset(email for email, _role, _code in DEMO_USERS)


def is_demo_account(email: str) -> bool:
    """Return True for one of the four seeded demo logins."""
    return email in DEMO_EMAILS

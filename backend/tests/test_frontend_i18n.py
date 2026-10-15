"""Frontend checks that run without a browser.

- en.json and ja.json have exactly the same keys, and no empty values.
- Every translation key used in the HTML and JavaScript exists.
- Every error code the API can return has a translation in both languages.
- Pages contain no hard-coded visible text, no inline scripts, no inline
  event handlers, and a Content Security Policy without 'unsafe-inline'.
- Japanese text uses only characters available in Japanese encodings
  (Shift_JIS / cp932), which catches Chinese-only character forms.
"""

import json
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"
BACKEND_APP = ROOT / "backend" / "app"
EN = json.loads((FRONTEND / "i18n" / "en.json").read_text(encoding="utf-8"))
JA = json.loads((FRONTEND / "i18n" / "ja.json").read_text(encoding="utf-8"))
HTML_FILES = sorted(FRONTEND.glob("*.html"))
JS_FILES = sorted((FRONTEND / "js").glob("*.js"))
NAMESPACES = {key.split(".", 1)[0] for key in EN}


def test_both_languages_have_the_same_keys() -> None:
    assert set(EN) - set(JA) == set(), "keys missing in ja.json"
    assert set(JA) - set(EN) == set(), "keys missing in en.json"


@pytest.mark.parametrize(("name", "data"), [("en", EN), ("ja", JA)])
def test_no_empty_translations(name: str, data: dict[str, str]) -> None:
    empty = [key for key, value in data.items() if not isinstance(value, str) or not value.strip()]
    assert empty == [], f"empty values in {name}.json"


def test_placeholders_match_between_languages() -> None:
    """{name} in English must also appear in Japanese, or a value would go missing."""
    for key, english in EN.items():
        assert set(re.findall(r"\{\w+\}", english)) == set(re.findall(r"\{\w+\}", JA[key])), key


def test_japanese_uses_japanese_character_forms() -> None:
    """Every Japanese string must encode in cp932; Chinese-only forms (for example 设) do not."""
    bad = {}
    for key, value in JA.items():
        try:
            value.encode("cp932")
        except UnicodeEncodeError as exc:
            bad[key] = value[exc.start : exc.end]
    assert bad == {}


def used_keys() -> set[str]:
    """Translation keys referenced in HTML and JavaScript."""
    keys: set[str] = set()
    for path in HTML_FILES:
        keys |= set(re.findall(r'data-i18n(?:-[a-z-]+)?="([^"]+)"', path.read_text()))
    for path in JS_FILES:
        text = path.read_text()
        # Any quoted string that looks like "namespace.key" for a known namespace.
        for candidate in re.findall(r'["`]([a-z_]+\.[A-Za-z_.]+)["`]', text):
            if candidate.endswith((".html", ".js", ".json")):
                continue  # file names such as "dashboard.html", not keys
            if candidate.split(".", 1)[0] in NAMESPACES:
                keys.add(candidate)
    # Built at runtime as `lang.${code}` for each language.
    keys |= {"lang.ja", "lang.en"}
    return keys


def test_every_used_key_exists() -> None:
    missing = sorted(key for key in used_keys() if key not in EN)
    assert missing == []


def backend_error_codes() -> set[str]:
    """Every error code the API can put in {"detail": {"code": ...}}."""
    source = "\n".join(
        path.read_text() for path in BACKEND_APP.rglob("*.py") if path.name != "seed.py"
    )
    patterns = [
        r'AppError\(\s*\d+\s*,\s*"([A-Z][A-Z0-9_]+)"',  # AppError(400, "CODE", ...)
        r'unauthorized\(\s*"([A-Z][A-Z0-9_]+)"',  # unauthorized("CODE", ...)
        r'\(\s*"([A-Z][A-Z0-9_]+)",\s*\n?\s*"[A-Z]',  # ("CODE", "Message") tables
        r'"([A-Z][A-Z0-9_]+)",\s*"[a-z][a-z ]+"\)',  # (..., "CODE", "label") checks
        r'"[a-z_]+",\s*"([A-Z][A-Z0-9_]+)"\)',  # (..., "field", "CODE") checks
        r'"code":\s*"([A-Z][A-Z0-9_]+)"',  # CSV row errors
        r'error_body\(\s*"([A-Z][A-Z0-9_]+)"',  # framework errors
        r'"code":\s*"([A-Z][A-Z0-9_]+)",\s*\n?\s*"message"',
    ]
    codes: set[str] = set()
    for pattern in patterns:
        codes |= set(re.findall(pattern, source))
    codes.discard("ERROR_CODE")  # the placeholder in the error-contract docstring
    # Error codes are upper-case words joined by underscores, never with digits.
    # This drops look-alikes such as employee codes ("E0001") in demo data.
    return {code for code in codes if re.fullmatch(r"[A-Z]+(?:_[A-Z]+)*", code)}


def test_scan_finds_the_known_error_codes() -> None:
    """Guard the scanner itself, so a regex mistake cannot make the next test pass vacuously."""
    codes = backend_error_codes()
    for expected in (
        "INVALID_CREDENTIALS",
        "INVALID_STATUS_CHANGE",
        "KITTING_WORKFLOW_REQUIRED",
        "ASSET_TAG_EXISTS",
        "DUPLICATE_ASSET_TAG",
        "VALIDATION_ERROR",
        "NOT_FOUND",
    ):
        assert expected in codes
    assert len(codes) >= 70


def test_every_api_error_code_is_translated() -> None:
    missing = sorted(code for code in backend_error_codes() if f"error.{code}" not in EN)
    assert missing == []


class PageScanner(HTMLParser):
    """Collects visible text, inline scripts, inline handlers, and literal labels."""

    SKIP = {"script", "style", "noscript"}

    def __init__(self) -> None:
        super().__init__()
        self.stack: list[str] = []
        self.visible_text: list[str] = []
        self.inline_scripts = 0
        self.inline_handlers: list[str] = []
        self.literal_labels: list[str] = []
        self.csp: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag not in {"meta", "link", "input", "br", "img"}:
            self.stack.append(tag)
        if tag == "script" and "src" not in values:
            self.inline_scripts += 1
        if tag == "meta" and (values.get("http-equiv") or "").lower() == "content-security-policy":
            self.csp = values.get("content")
        for name, _value in attrs:
            if name.startswith("on"):
                self.inline_handlers.append(f"{tag}[{name}]")
            # Visible attribute text must come from data-i18n-* keys instead.
            if name in {"placeholder", "aria-label", "title", "alt"}:
                self.literal_labels.append(f"{tag}[{name}]")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.stack:
            while self.stack and self.stack.pop() != tag:
                pass

    def handle_data(self, data: str) -> None:
        if data.strip() and not (set(self.stack) & self.SKIP):
            self.visible_text.append(data.strip())


@pytest.mark.parametrize("page", HTML_FILES, ids=[p.name for p in HTML_FILES])
def test_page_has_no_hard_coded_text_or_inline_code(page: Path) -> None:
    scanner = PageScanner()
    scanner.feed(page.read_text(encoding="utf-8"))
    assert scanner.visible_text == [], "visible text must use data-i18n keys"
    assert scanner.literal_labels == [], "use data-i18n-placeholder / -aria-label / -title"
    assert scanner.inline_scripts == 0
    assert scanner.inline_handlers == []
    assert scanner.csp is not None, "every page needs a Content Security Policy"
    assert "unsafe-inline" not in scanner.csp and "unsafe-eval" not in scanner.csp


class ScriptScanner(HTMLParser):
    """Collects <script src> tags with their attributes."""

    def __init__(self) -> None:
        super().__init__()
        self.scripts: list[dict[str, str | None]] = []
        self.csp = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "script" and values.get("src"):
            self.scripts.append(values)
        if tag == "meta" and (values.get("http-equiv") or "").lower() == "content-security-policy":
            self.csp = values.get("content") or ""


@pytest.mark.parametrize("page", HTML_FILES, ids=[p.name for p in HTML_FILES])
def test_external_scripts_are_pinned_and_checked(page: Path) -> None:
    """A CDN script needs an exact version, an integrity hash, and its host in the CSP.

    Without the hash, a changed or compromised file on the CDN would run in the
    page with the user's session.
    """
    scanner = ScriptScanner()
    scanner.feed(page.read_text(encoding="utf-8"))
    script_src = next(
        (part for part in scanner.csp.split(";") if part.strip().startswith("script-src")), ""
    )
    for script in scanner.scripts:
        src = script["src"] or ""
        if not src.startswith("http"):
            continue
        assert src.startswith("https://"), src
        assert re.search(r"@\d+\.\d+\.\d+/", src), f"pin an exact version: {src}"
        assert (script.get("integrity") or "").startswith("sha384-"), src
        assert script.get("crossorigin") == "anonymous", src
        host = "/".join(src.split("/", 3)[:3])
        assert host in script_src.split(), f"{host} missing from script-src"
    if not any((s["src"] or "").startswith("http") for s in scanner.scripts):
        assert script_src.split() == ["script-src", "'self'"], "no CDN script, so no CDN host"


def test_scripts_never_insert_html() -> None:
    """Untrusted text must go through textContent; innerHTML and friends are banned."""
    offenders = [
        f"{path.name}: {match}"
        for path in JS_FILES
        for match in re.findall(r"\.(innerHTML|outerHTML|insertAdjacentHTML)\b", path.read_text())
    ]
    assert offenders == []

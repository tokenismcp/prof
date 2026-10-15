"""Console i18n integrity: every UI string has EN + KO, no dangling keys."""

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
I18N = ROOT / "prof" / "console" / "i18n.js"
HTML = ROOT / "prof" / "console" / "index.html"
APP = ROOT / "prof" / "console" / "app.js"


def _dicts():
    text = I18N.read_text(encoding="utf-8")
    out = {}
    for lang in ("en", "ko"):
        start = text.find("\n" + lang + ": {")
        assert start != -1, lang
        depth, i = 1, start + len(lang) + 3
        body_start = text.find("{", start) + 1
        j = body_start
        while True:
            if text[j] == "{":
                depth += 1
            elif text[j] == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        out[lang] = set(re.findall(r'"([a-z0-9._-]+)":', text[body_start:j]))
    assert out["en"] and out["ko"]
    return out


def test_en_ko_parity():
    d = _dicts()
    assert d["en"] == d["ko"], (
        "missing in ko: %s | missing in en: %s"
        % (sorted(d["en"] - d["ko"]), sorted(d["ko"] - d["en"])))


def test_html_keys_defined():
    d = _dicts()
    html = HTML.read_text(encoding="utf-8")
    keys = set(re.findall(r'data-i18n(?:-ph)?="([^"]+)"', html))
    assert keys, "no data-i18n keys found"
    assert keys <= d["en"], sorted(keys - d["en"])


def test_js_t_keys_defined():
    d = _dicts()
    js = APP.read_text(encoding="utf-8")
    used = set(re.findall(r'[^\w]t\("([^"]+)"\)', js))
    assert used <= d["en"], sorted(used - d["en"])


def test_no_hardcoded_ui_strings_left():
    js = APP.read_text(encoding="utf-8")
    leftovers = [
        '"Permit signed"', '"Approve denied"', '"Agent run finished"',
        '"Verification complete"', '"Exported"',
    ]
    hits = [s for s in leftovers if s in js]
    assert not hits, hits

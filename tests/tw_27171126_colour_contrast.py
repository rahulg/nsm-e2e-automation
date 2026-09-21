"""TC_020 + TC_031 measured rather than eyeballed.

TC_020 asks for the VIN highlight to match "the date picker orange". Both are on the same
screen, so the comparison can be made by computed style instead of by looking at a mock.
TC_031 asks whether the highlight is readable — that is a contrast ratio against the cell
background, computed per WCAG 2.1 (relative luminance, 4.5:1 for normal-size text).
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("NSM_ENV", "qa")
E2E_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(E2E_ROOT))
os.chdir(E2E_ROOT)

from playwright.sync_api import sync_playwright  # noqa: E402

from tests.tw_27171126_vin_highlight import (  # noqa: E402
    LT260_LIST_URL, ORANGE, cells_on_tab, check, classify, ctx_page,
)

# Every element that looks like a date chip / date-picker control, with its colours.
JS_DATE_CHIPS = """
() => {
  const out = [];
  const re = /^(\\d{2}\\/\\d{2}\\/\\d{2}|Today|Date Picker)$/;
  for (const e of document.querySelectorAll('button, a, span, div')) {
    const t = (e.innerText || '').trim();
    if (!re.test(t)) continue;
    if (e.children.length > 2) continue;
    const cs = getComputedStyle(e);
    out.push({text: t, color: cs.color, border: cs.borderTopColor,
              bg: cs.backgroundColor});
  }
  return out;
}
"""


def srgb_to_lin(c):
    c = c / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def luminance(rgb):
    r, g, b = (srgb_to_lin(v) for v in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def parse_rgb(s):
    nums = [int(n) for n in "".join(ch if ch.isdigit() else " " for ch in s).split()[:3]]
    return tuple(nums)


def contrast(fg, bg):
    l1, l2 = luminance(fg), luminance(bg)
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


def main():
    holder = []
    with sync_playwright() as pw:
        page = ctx_page(pw, holder)
        cells, _ = cells_on_tab(page, LT260_LIST_URL, "To Process", tries=3)
        orange, _, _ = classify(cells)
        chips = page.evaluate(JS_DATE_CHIPS)
        page.screenshot(path="C:/automation/vinhl-runs/colour_datechips.png")
        print("DATE CHIPS:", chips[:8])
        print("ORANGE VIN CELLS:", [(c["text"], c["color"], c["bg"]) for c in orange[:3]])

        chip_colours = {c["color"] for c in chips} | {c["border"] for c in chips}
        check(f"the VIN highlight colour is the same orange the date-picker chips use — the "
              f"'matches the date picker' clause of the UI spec, compared by computed style "
              f"rather than against a mock image (TC_020)",
              (f"VIN highlight computes to {ORANGE}; date-chip colours observed "
               f"{sorted(chip_colours)} — "
               f"{'the highlight orange is present among them' if ORANGE in chip_colours else 'NO date-chip element uses that exact colour'}"),
              ORANGE in chip_colours)

        if orange:
            fg = parse_rgb(orange[0]["color"])
            bg_raw = orange[0]["bg"]
            bg = parse_rgb(bg_raw) if bg_raw and "0, 0, 0, 0" not in bg_raw else (255, 255, 255)
            ratio = contrast(fg, bg)
            print(f"CONTRAST: fg={fg} bg={bg} ({bg_raw}) ratio={ratio:.2f}:1")
            check("the highlighted VIN meets the WCAG 2.1 AA contrast minimum of 4.5:1 for "
                  "normal-size body text, so the flag is readable and not conveyed by a "
                  "low-contrast colour alone (TC_031)",
                  f"orange {fg} on {bg} measures {ratio:.2f}:1 "
                  f"({'meets' if ratio >= 4.5 else 'FAILS'} AA 4.5:1; "
                  f"{'meets' if ratio >= 3.0 else 'fails'} the 3.0:1 large-text/UI bar)",
                  ratio >= 4.5)
        for b in holder:
            b.close()


main()

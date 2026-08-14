"""The console's elevation ladder, measured from `tokens.css` rather than claimed in a comment.

**Why this file exists.** The token block named seven contrast ratios in prose — "card:page at
1.226:1", "`--border-ui` on card 3.7:1 against the 3:1 a control outline needs" — and nothing checked
any of them. That is the shape of defect this repository keeps finding: a measurement written down
once, then a later edit that moves the value while the sentence stays.

It was not hypothetical. Two blind design reviews independently reported that the dark card read as
*bluer* than the page rather than lighter, and the numbers said why: light goes 0.955/C 0.010 →
1.000/C 0.000 (lighter **and** less coloured, which is why a white card reads as paper), while dark
went 0.195/C 0.065 → 0.275/C 0.085 — the rising chroma fought the rising lightness, and `--shadow` is
`none` in dark so nothing else carried the step. Fixing it moved every ratio in the block, and the
first candidate quietly dropped `--border-ui` on `--raised` to 2.842:1, under the 3:1 a control
outline needs. Nothing would have caught that.

`sitegen` has `palette.contrast`, but it takes hex and these tokens are oklch with a `calc()` on a
custom property, so the conversion lives here: oklch → Oklab → LMS → linear sRGB → sRGB, per CSS
Color 4, then WCAG relative luminance. Verified against the browser's own computed values.
"""

import math
import pathlib
import re

import pytest

TOKENS = pathlib.Path("web/src/tokens.css")


def oklch_to_srgb(lightness: float, chroma: float, hue: float) -> tuple[float, float, float]:
    a = chroma * math.cos(math.radians(hue))
    b = chroma * math.sin(math.radians(hue))
    l_ = lightness + 0.3963377774 * a + 0.2158037573 * b
    m_ = lightness - 0.1055613458 * a - 0.0638541728 * b
    s_ = lightness - 0.0894841775 * a - 1.2914855480 * b
    long, medium, short = l_**3, m_**3, s_**3
    linear = (
        +4.0767416621 * long - 3.3077115913 * medium + 0.2309699292 * short,
        -1.2684380046 * long + 2.6097574011 * medium - 0.3413193965 * short,
        -0.0041960863 * long - 0.7034186147 * medium + 1.7076147010 * short,
    )
    out = []
    for channel in linear:
        clipped = max(0.0, min(1.0, channel))
        out.append(1.055 * clipped ** (1 / 2.4) - 0.055 if clipped > 0.0031308 else 12.92 * clipped)
    return out[0], out[1], out[2]


def luminance(token: tuple[float, float], hue: float) -> float:
    def linearise(channel: float) -> float:
        return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4

    red, green, blue = oklch_to_srgb(token[0], token[1], hue)
    return 0.2126 * linearise(red) + 0.7152 * linearise(green) + 0.0722 * linearise(blue)


def ratio(one: tuple[float, float], two: tuple[float, float], hue: float = 264.0) -> float:
    first, second = luminance(one, hue), luminance(two, hue)
    high, low = max(first, second), min(first, second)
    return (high + 0.05) / (low + 0.05)


# --- read the ladder out of the stylesheet ---------------------------------------

# Three forms appear in the file and all three have to parse, or a token drops out of the ladder and
# every rule below skips it in silence:
#   --surface: oklch(0.295 calc(0.052 * var(--ui-chroma)) var(--ui-hue))   the brand ramp
#   --surface: oklch(1 0 0)                                               light's white card
#   --ok:      oklch(0.74 0.09 220)                                       the fixed semantic hues
DECLARED = re.compile(
    r"--([a-z-]+):\s*oklch\(\s*([0-9.]+)\s+"
    r"(?:calc\(\s*([0-9.]+)\s*\*\s*var\(--ui-chroma\)\s*\)|([0-9.]+))\s+"
    r"(?:var\(--ui-hue\)|[0-9.]+)\s*\)"
)


def _block(theme: str) -> str:
    text = TOKENS.read_text(encoding="utf-8")
    start = text.index(
        ':root, [data-theme="dark"] {' if theme == "dark" else '[data-theme="light"] {'
    )
    return text[start : text.index("\n}", start)]


def _ladder(theme: str) -> dict[str, tuple[float, float]]:
    found = {}
    for name, lightness, chroma, plain in DECLARED.findall(_block(theme)):
        found.setdefault(name, (float(lightness), float(chroma or plain or 0.0)))
    return found


@pytest.fixture(scope="module")
def dark() -> dict[str, tuple[float, float]]:
    ladder = _ladder("dark")
    missing = {"bg", "surface", "raised", "border", "border-ui", "text", "muted"} - set(ladder)
    assert not missing, f"the parser stopped seeing {sorted(missing)} — fix it, not the assertions"
    return ladder


# --- the guard on the guard -------------------------------------------------------


def test_the_converter_agrees_with_a_known_value():
    """oklch(0.195 0.065 264) is `#061232`, taken from the browser's own computed style. A colour
    maths bug would make every ratio below wrong in the same direction and all of them pass."""
    red, green, blue = oklch_to_srgb(0.195, 0.065, 264.0)
    assert [round(c * 255) for c in (red, green, blue)] == [6, 18, 50]
    # Black on white is the fixed point of the WCAG formula.
    assert ratio((0.0, 0.0), (1.0, 0.0)) == pytest.approx(21.0, abs=0.01)


def test_there_is_a_ladder_to_check(dark):
    assert len(dark) >= 7, f"only {len(dark)} tokens parsed out of tokens.css"


# --- elevation reads as lightness, not as saturation -------------------------------


def test_the_dark_ladder_climbs_in_lightness_and_falls_in_chroma(dark):
    """The decision two reviews asked for, as a rule rather than three numbers. Anything stacked on
    the page must be lighter *and* less coloured than what it sits on — that is what makes a step
    read as elevation. The page itself keeps the owner's blue at full chroma; only what sits on it
    recedes."""
    steps = [("bg", "surface"), ("surface", "raised")]
    for below, above in steps:
        assert dark[above][0] > dark[below][0], f"--{above} is not lighter than --{below}"
        assert dark[above][1] < dark[below][1], (
            f"--{above} is more saturated than --{below}: a step up in chroma reads as bluer, "
            "not as raised, which is the exact defect this rule exists for"
        )


def test_the_dark_steps_are_visible(dark):
    """1.121:1 was the original card:page and seven tabs read as one flat navy slab. The floor is set
    below where it stands so an intentional tweak is allowed and a collapse is not."""
    assert ratio(dark["surface"], dark["bg"]) >= 1.28, "card:page has gone flat again"
    assert ratio(dark["raised"], dark["surface"]) >= 1.26, "raised:card has gone flat again"
    assert ratio(dark["border"], dark["surface"]) >= 1.8, "the hairline has stopped being visible"


@pytest.mark.parametrize("ground", ["surface", "raised"])
def test_a_control_outline_clears_three_to_one_on_both_grounds(dark, ground):
    """The one that actually caught something: the first candidate ladder put `--border-ui` at
    2.842:1 on `--raised`. Both grounds, because a control sits on either."""
    assert ratio(dark["border-ui"], dark[ground]) >= 3.0, (
        f"--border-ui is {ratio(dark['border-ui'], dark[ground]):.3f}:1 on --{ground}"
    )


@pytest.mark.parametrize(
    ("text_token", "ground", "floor"),
    [
        ("text", "surface", 7.0),
        ("text", "bg", 7.0),
        ("muted", "surface", 4.5),
        ("muted", "raised", 4.5),
    ],
)
def test_the_text_ramp_survives_the_ladder(dark, text_token, ground, floor):
    """Lifting the surfaces lowers every text ratio on them. 4.5:1 is AA for body text and `--muted`
    is body text — it is used for descriptions, not decoration."""
    measured = ratio(dark[text_token], dark[ground])
    assert measured >= floor, f"--{text_token} on --{ground} is {measured:.2f}:1, floor {floor}"


# --- the operator's knob is still honest ------------------------------------------


def test_the_ladder_survives_the_colour_being_turned_off(dark):
    """`--ui-chroma: 0` is a real setting the console offers ("Intensity: None"). With every chroma at
    zero the ladder becomes pure greys, and it still has to be a ladder — a lightness-only ordering is
    exactly what that setting reduces to, and it is why the steps are lightness in the first place."""
    grey = {name: (lightness, 0.0) for name, (lightness, _chroma) in dark.items()}
    assert ratio(grey["surface"], grey["bg"]) >= 1.28
    assert ratio(grey["raised"], grey["surface"]) >= 1.26
    assert ratio(grey["border-ui"], grey["raised"]) >= 3.0
    assert ratio(grey["muted"], grey["surface"]) >= 4.5


def test_light_was_already_doing_this():
    """The reference the dark fix was measured against, kept here so nobody 'fixes' light to match a
    rising-chroma dark: a white card on a tinted page is lighter and *less* coloured, which is why it
    reads as paper. If this ever fails, the two themes have swapped roles."""
    light = _ladder("light")
    assert light["surface"][0] > light["bg"][0]
    assert light["surface"][1] <= light["bg"][1]

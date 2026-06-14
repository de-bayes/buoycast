"""Seiche Six-Hour Report: an official, auto-generated PDF, regenerated every six
hours from the live forecast. Four pages: a masthead + situation cover (with the
halftone buoy plate and the wave band for brand identity), the week ahead, the
day ahead, and confidence + method. Graph-dense, with reproducible analysis
prose: every sentence is a deterministic function of the numbers, so the same
data always yields the same words (no model in the loop yet). Pure matplotlib +
numpy + PIL, no new deps.

Writes site/briefs/seiche_report_<UTCstamp>.pdf + a stable site/briefs/latest.pdf,
pruned to BRIEFS_KEEP."""

import json
import pathlib
import shutil
import textwrap
from datetime import datetime, timezone, timedelta

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.image as mpimg
import numpy as np
from matplotlib.backends.backend_pdf import PdfPages

# ---- palette (site design tokens) ----
INK, MUTED, FAINT = "#16181d", "#5b6470", "#8a929c"
ACCENT, AMBER, GREEN = "#1257a0", "#b45309", "#2f7d5b"
RULE, WASH, RED = "#ececec", "#fdf3c7", "#e0312e"
MEMBER = (0.47, 0.51, 0.56)
DOT = (20 / 255, 24 / 255, 30 / 255)
plt.rcParams.update({
    "font.serif": ["Lora", "Georgia", "DejaVu Serif"], "font.family": "serif",
    "font.monospace": ["IBM Plex Mono", "Menlo", "DejaVu Sans Mono"],
    "axes.edgecolor": RULE, "axes.linewidth": 0.8, "text.color": INK,
    "axes.labelcolor": MUTED, "xtick.color": MUTED, "ytick.color": MUTED,
    "xtick.labelsize": 6.5, "ytick.labelsize": 6.5,
})
MONO = {"family": "monospace"}
A4 = (8.27, 11.69)
M = 0.075
ASSETS = pathlib.Path("site/assets")
BRIEFS_DIR = pathlib.Path("site/briefs")
BRIEFS_KEEP = 28
CENTRAL = timezone(timedelta(hours=-5))   # CDT, display only (May-Nov season)

ct = lambda iso: datetime.fromisoformat(iso).astimezone(CENTRAL).replace(tzinfo=None)


# ---------- data + derived ----------
def load(name, default=None):
    p = pathlib.Path(name)
    return json.loads(p.read_text()) if p.exists() else default


def derive(d):
    traj = d["trajectory"]
    now_f = d["now"]["wtmp_f"]
    day = traj[:24]
    p50d = [pt["p50"] for pt in day]
    hi, lo = int(np.argmax(p50d)), int(np.argmin(p50d))
    wk = [pt["p50"] for pt in traj]
    hist = [p["f"] for p in d["history"]]
    d24 = now_f - hist[-25] if len(hist) >= 25 else now_f - hist[0]
    d48 = now_f - hist[0]
    bs = d.get("band_scale")
    if bs is None or 0.95 <= bs <= 1.05:
        state, statew = "NORMAL", "about its usual width"
    elif bs > 1.05:
        state, statew = f"{bs:.2f}x WIDE", f"{bs:.2f} times wider than usual"
    else:
        state, statew = f"{bs:.2f}x TIGHT", f"{bs:.2f} times tighter than usual"
    return {
        "now_f": now_f, "at24": traj[23]["p50"], "chg24": traj[23]["p50"] - now_f,
        "p05_24": traj[23]["p05"], "p95_24": traj[23]["p95"],
        "hi": (day[hi]["p50"], ct(day[hi]["t"])), "lo": (day[lo]["p50"], ct(day[lo]["t"])),
        "wk_med": float(np.mean(wk)), "wk_hi": max(wk), "wk_lo": min(wk),
        "band24": (traj[23]["p95"] - traj[23]["p05"]) / 2,
        "band168": (traj[167]["p95"] - traj[167]["p05"]) / 2,
        "band_state": state, "band_statew": statew, "band_scale": bs,
        "d24": d24, "d48": d48, "day0": traj[23]["p50"], "day6": d["daily"][-1]["p50"],
    }


# ---------- reproducible analysis (deterministic templates, in voice) ----------
def _dir(x, warm="warmer", cool="cooler", flat="little changed", eps=0.3):
    return flat if abs(x) < eps else (warm if x > 0 else cool)


def situation_text(d, dv):
    tod = {0: "overnight", 1: "this morning", 2: "this afternoon", 3: "this evening"}[
        min(3, ct(d["valid_utc"]).hour // 6)]
    cmp = ("a touch below" if dv["now_f"] < dv["wk_med"] - 0.3 else
           "a touch above" if dv["now_f"] > dv["wk_med"] + 0.3 else "right at")
    trend = (f"drifted up {abs(dv['d48']):.1f}°F over the past two days" if dv["d48"] > 0.4 else
             f"slid {abs(dv['d48']):.1f}°F over the past two days" if dv["d48"] < -0.4 else
             "held roughly flat over the past two days")
    lead = _dir(dv["chg24"], "warmer", "cooler", "about the same")
    return (
        f"The Wilmette buoy reads {dv['now_f']:.1f}°F {tod}, {cmp} the {dv['wk_med']:.1f}°F the "
        f"model centers the coming week on, and the water has {trend}. Through tomorrow the "
        f"forecast leans {lead}"
        + (f" by {abs(dv['chg24']):.1f}°F" if abs(dv['chg24']) >= 0.3 else "")
        + f", with the 90 percent band running {dv['band_statew']} because of how the model's "
        f"recent one-day calls have landed against the buoy. Treat the median as a best guess and "
        f"the band as the honest spread; over a week, trust the shape of the cone, not any single "
        f"hour inside it.")


def week_text(d, dv):
    arc = _dir(dv["day6"] - dv["now_f"], "warms", "cools", "holds roughly steady")
    warmest = max(d["daily"], key=lambda x: x["p50"])
    return (
        f"Across the seven days the median path {arc} from today's {dv['now_f']:.1f}°F toward "
        f"{dv['day6']:.1f}°F by the last day, the warmest reading falling around {warmest['label']} "
        f"near {warmest['p50']:.0f}°F. The uncertainty opens from about plus or minus "
        f"{dv['band24']:.1f}°F tomorrow to plus or minus {dv['band168']:.1f}°F a week out, which is "
        f"the ordinary price of forecasting weather the models have not yet seen; the band is built "
        f"from a thirty-four member ensemble, so its width is real disagreement among forecasts, "
        f"not a guess pinned on after the fact.")


def day_text(d, dv):
    mv = _dir(dv["chg24"], "rises", "falls", "holds nearly steady")
    return (
        f"Through the next day the water {mv} to a high near {dv['hi'][0]:.1f}°F around "
        f"{dv['hi'][1]:%-I %p} and a low near {dv['lo'][0]:.1f}°F around {dv['lo'][1]:%-I %p}, a "
        f"net {_dir(dv['chg24'], 'warming', 'cooling', 'flat day')} of {abs(dv['chg24']):.1f}°F. "
        f"At this hour tomorrow the ninety percent range spans {dv['p05_24']:.1f} to "
        f"{dv['p95_24']:.1f}°F. The whole trajectory is pinned to the live buoy reading and that "
        f"correction fades over the first day, so the next few hours are nearly certain and the far "
        f"end of the day carries most of the doubt.")


def confidence_text(v):
    h = v.get("headline", {}) or {}
    if not h.get("mae_f"):
        return ("Live scoring begins as published forecasts resolve; until then the panels below "
                "show the model replayed over recent history, and the nine-season backtest behind "
                "the bands remains the rigorous claim.")
    warm = "warm" if (h.get("bias_f") or 0) >= 0 else "cool"
    return (
        f"Over the last thirty days the typical one-day miss was {h['mae_f']:.2f}°F, the ninety "
        f"percent band held the truth {h['cover90']*100:.0f} percent of the time, and the forecast "
        f"ran {abs(h.get('bias_f',0)):.2f}°F {warm}. The model earns its keep past a day; inside "
        f"one, the lake's thermal inertia means little beats simply trusting the live reading, which "
        f"is exactly why the forecast starts there. Across a week, trust the direction and the band, "
        f"not the exact number.")


# ---------- shared chrome ----------
def img_band(fig, rect, path, alpha=1.0, aspect="auto"):
    try:
        im = mpimg.imread(str(path))
    except Exception:
        return None
    ax = fig.add_axes(rect); ax.axis("off")
    ax.imshow(im, alpha=alpha, aspect=aspect, interpolation="bilinear", zorder=0)
    return ax


def buoy_glyph(ax, cx=0.012, base=0.34):
    xs = np.linspace(-1, 1, 80); bell = np.exp(-(xs ** 2) / 0.28)
    ax.fill_between(xs * 0.014 + cx, base, base + bell * 0.30, color=ACCENT, alpha=0.9,
                    transform=ax.transAxes, zorder=2, lw=0)
    ax.plot([cx, cx], [base + 0.30, base + 0.50], color=INK, lw=1.5, transform=ax.transAxes, zorder=2)
    ax.scatter([cx], [base + 0.52], s=20, color=RED, transform=ax.transAxes, zorder=3)


def masthead(fig, issue_ct, valid_ct):
    """Page-1 formal masthead with the wave band above it."""
    img_band(fig, [M, 0.945, 1 - 2 * M, 0.028], ASSETS / "wave-dots.png", alpha=0.85)
    ax = fig.add_axes([M, 0.885, 1 - 2 * M, 0.05]); ax.axis("off")
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    buoy_glyph(ax, cx=0.012, base=0.30)
    ax.text(0.05, 0.62, "S E I C H E", fontsize=20, fontweight="bold", color=INK,
            transform=ax.transAxes, va="center")
    ax.text(0.052, 0.18, "LAKE MICHIGAN WATER-TEMPERATURE FORECAST · NDBC 45174, EVANSTON–WILMETTE",
            fontsize=6.6, color=MUTED, transform=ax.transAxes, va="center", **MONO)
    ax.text(0.995, 0.66, "SIX-HOUR REPORT", fontsize=9, fontweight="bold", color=ACCENT,
            ha="right", va="center", transform=ax.transAxes, **MONO)
    ax.text(0.995, 0.40, f"ISSUE {issue_ct}", fontsize=7, color=MUTED, ha="right",
            va="center", transform=ax.transAxes, **MONO)
    ax.text(0.995, 0.16, f"DATA VALID {valid_ct}", fontsize=7, color=FAINT, ha="right",
            va="center", transform=ax.transAxes, **MONO)
    ax.axhline(0.0, color=INK, lw=1.2)


def banner(fig, num, title, issue_ct):
    """Inner-page running header: section number + title + small issue stamp."""
    ax = fig.add_axes([M, 0.93, 1 - 2 * M, 0.04]); ax.axis("off")
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.text(0, 0.55, f"{num}", fontsize=10, color=ACCENT, fontweight="bold", va="center", **MONO)
    ax.text(0.045, 0.55, title, fontsize=13, color=INK, va="center")
    ax.text(0.995, 0.62, "SEICHE · SIX-HOUR REPORT", fontsize=6.5, color=FAINT, ha="right",
            va="center", transform=ax.transAxes, **MONO)
    ax.text(0.995, 0.30, f"ISSUE {issue_ct}", fontsize=6.5, color=FAINT, ha="right",
            va="center", transform=ax.transAxes, **MONO)
    ax.axhline(0.0, color=RULE, lw=0.8)
    ax.plot([0.0, 0.04], [0.0, 0.0], color=ACCENT, lw=2.2, transform=ax.transAxes)


def strip(fig, y, cells, h=0.045):
    ax = fig.add_axes([M, y, 1 - 2 * M, h]); ax.axis("off"); ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.axhline(0.96, color=RULE, lw=0.8); ax.axhline(0.04, color=RULE, lw=0.8)
    n = len(cells)
    for i, (lab, val, col) in enumerate(cells):
        x = (i + 0.5) / n
        ax.text(x, 0.66, lab, fontsize=5.8, color=MUTED, ha="center", va="center", **MONO)
        ax.text(x, 0.30, val, fontsize=12, color=col, ha="center", va="center",
                fontweight="bold", **MONO)


def kick(fig, y, text):
    ax = fig.add_axes([M, y, 1 - 2 * M, 0.022]); ax.axis("off"); ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.text(0, 0.4, text, fontsize=7, color=ACCENT, fontweight="bold", **MONO)
    ax.axhline(0.0, color=RULE, lw=0.6)


def para(fig, y, h, text, lead="", width=112, size=9.2):
    ax = fig.add_axes([M, y, 1 - 2 * M, h]); ax.axis("off"); ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    body = textwrap.fill(text, width=width)
    pre = ""
    if lead:
        pre = f"$\\bf{{{lead}}}$  "
    ax.text(0, 0.96, pre + body, fontsize=size, color=INK, va="top", linespacing=1.45)


def foot(fig, page, total):
    fig.text(M, 0.03, "Seiche · Six-Hour Report · seiche.mccomb.ca", fontsize=6.5, color=FAINT)
    fig.text(1 - M, 0.03, f"page {page} of {total}", fontsize=6.5, color=FAINT, ha="right")


def deframe(ax, grid=True):
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.tick_params(length=0)
    if grid:
        ax.grid(axis="y", color=RULE, lw=0.6)


def datefmt(ax):
    ax.xaxis.set_major_locator(mdates.DayLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%a %-d"))
    deframe(ax)


# ============================== PAGE 1: cover + situation ==============================
def page_cover(fig, d, dv, issue_ct, valid_ct):
    masthead(fig, issue_ct, valid_ct)
    # plate i: the halftone buoy
    pax = img_band(fig, [M, 0.66, 1 - 2 * M, 0.205], ASSETS / "buoy-halftone.png", aspect="auto")
    cap = fig.add_axes([M, 0.635, 1 - 2 * M, 0.02]); cap.axis("off"); cap.set_xlim(0, 1); cap.set_ylim(0, 1)
    cap.axhspan(0.0, 1.0, xmin=0.0, xmax=0.62, color=WASH, zorder=0)
    cap.text(0.008, 0.45, "plate i.", fontsize=7.5, style="italic", color=INK, va="center", zorder=1)
    cap.text(0.072, 0.45, "NDBC 45174, the Wilmette buoy, a Purdue-operated station on Lake Michigan.",
             fontsize=7.5, color=INK, va="center", zorder=1)

    now = d["now"]
    strip(fig, 0.575, [
        ("WATER", f"{now['wtmp_f']:.1f}°F", INK), ("AIR", f"{now['atmp_f']:.1f}°F", INK),
        ("WAVES", f"{now['wvht_ft']:.1f} ft", INK), ("WIND", f"{now['wspd_kt']:.1f} kt", INK),
        ("GUST", f"{now['gst_kt']:.1f} kt", INK)])

    kick(fig, 0.525, "SITUATION")
    para(fig, 0.34, 0.18, situation_text(d, dv))

    strip(fig, 0.235, [
        ("NOW", f"{dv['now_f']:.1f}°F", INK), ("+24H", f"{dv['at24']:.1f}°F", INK),
        ("24H CHANGE", f"{dv['chg24']:+.1f}°F", ACCENT if dv["chg24"] >= 0 else AMBER),
        ("7-DAY MEDIAN", f"{dv['wk_med']:.1f}°F", INK),
        ("7-DAY RANGE", f"{dv['wk_lo']:.0f}–{dv['wk_hi']:.0f}°F", INK),
        ("BAND", dv["band_state"], MUTED)])

    # a compact "recent + next" preview chart on the cover
    ax = fig.add_axes([M, 0.085, 1 - 2 * M, 0.12])
    hist_t = [ct(p["t"]) for p in d["history"]]; tj_t = [ct(p["t"]) for p in d["trajectory"][:72]]
    tj = d["trajectory"][:72]
    ax.fill_between(tj_t, [p["p05"] for p in tj], [p["p95"] for p in tj], color=ACCENT, alpha=0.10, lw=0)
    ax.fill_between(tj_t, [p["p25"] for p in tj], [p["p75"] for p in tj], color=ACCENT, alpha=0.20, lw=0)
    ax.plot(tj_t, [p["p50"] for p in tj], color=ACCENT, lw=2.0)
    ax.plot(hist_t, [p["f"] for p in d["history"]], color=INK, lw=1.3)
    ax.axvline(ct(d["valid_utc"]), color=FAINT, lw=0.8, ls=(0, (2, 2)))
    datefmt(ax); ax.set_title("Past two days into the next three (°F)", fontsize=8, loc="left", color=MUTED, pad=3)
    foot(fig, 1, 4)


# ============================== PAGE 2: the week ==============================
def page_week(fig, d, dv, issue_ct):
    banner(fig, "01", "The week ahead", issue_ct)
    # hero 168h fan
    ax = fig.add_axes([M, 0.57, 1 - 2 * M, 0.31])
    tj_t = [ct(p["t"]) for p in d["trajectory"]]
    for m in d.get("members", []):
        ax.plot(tj_t, m["traj"], color=MEMBER, alpha=0.04, lw=0.6, zorder=1)
    tj = d["trajectory"]
    ax.fill_between(tj_t, [p["p05"] for p in tj], [p["p95"] for p in tj], color=ACCENT, alpha=0.10, lw=0, zorder=2)
    ax.fill_between(tj_t, [p["p25"] for p in tj], [p["p75"] for p in tj], color=ACCENT, alpha=0.20, lw=0, zorder=2)
    ax.plot(tj_t, [p["p50"] for p in tj], color=ACCENT, lw=2.2, zorder=4)
    ax.plot([ct(p["t"]) for p in d["history"]], [p["f"] for p in d["history"]], color=INK, lw=1.4, zorder=4)
    ax.axvline(ct(d["valid_utc"]), color=FAINT, lw=0.8, ls=(0, (2, 2)), zorder=3)
    datefmt(ax); ax.set_ylabel("water temperature (°F)", fontsize=7.5)
    ax.set_title("Seven days ahead · observed (black) into the forecast cone, 34-member ensemble behind",
                 fontsize=8.5, loc="left", color=INK, pad=5)

    # 7-day gauges
    days = d["daily"]
    ax2 = fig.add_axes([M, 0.355, 0.52, 0.16]); ax2.axis("off")
    ax2.set_xlim(0, len(days)); ax2.set_ylim(0, 1)
    lo = min(x["p05"] for x in days); hi = max(x["p95"] for x in days); pad = (hi - lo) * 0.12 + 0.5
    ymap = lambda v: 0.16 + 0.6 * (v - (lo - pad)) / ((hi + pad) - (lo - pad))
    ax2.axhline(ymap(dv["now_f"]), color=FAINT, lw=0.7, ls=(0, (3, 3)))
    for i, day in enumerate(days):
        cx = i + 0.5
        ax2.plot([cx, cx], [ymap(day["p05"]), ymap(day["p95"])], color=AMBER, lw=2.6, alpha=0.55,
                 solid_capstyle="round")
        ax2.scatter([cx], [ymap(day["p50"])], s=26, color=ACCENT, zorder=3)
        ax2.text(cx, 0.95, day["label"], fontsize=7, color=INK, ha="center", va="center")
        ax2.text(cx, 0.03, f"{day['p50']:.0f}°", fontsize=8, color=INK, ha="center", va="center",
                 fontweight="bold", **MONO)
    ax2.set_title("Day by day · median dot, 90% band", fontsize=8.5, loc="left", pad=3)

    # daily warming/cooling vs today
    ax3 = fig.add_axes([M + 0.56, 0.355, 1 - 2 * M - 0.56, 0.16])
    deltas = [x["p50"] - dv["now_f"] for x in days]
    cols = [ACCENT if v >= 0 else AMBER for v in deltas]
    ax3.bar(range(len(days)), deltas, color=cols, alpha=0.8, width=0.6)
    ax3.axhline(0, color=INK, lw=0.8)
    ax3.set_xticks(range(len(days))); ax3.set_xticklabels([x["label"] for x in days], fontsize=6.5)
    deframe(ax3); ax3.set_ylabel("Δ vs now (°F)", fontsize=7.5)
    ax3.set_title("Warmer or cooler than today", fontsize=8.5, loc="left", pad=3)

    kick(fig, 0.305, "THE WEEK")
    para(fig, 0.13, 0.17, week_text(d, dv))
    foot(fig, 2, 4)


# ============================== PAGE 3: the day ==============================
def page_day(fig, d, dv, issue_ct):
    banner(fig, "02", "The day ahead · next 24 hours", issue_ct)
    now = d["now"]; day = d["trajectory"][:24]; t = [ct(p["t"]) for p in day]

    ax = fig.add_axes([M, 0.60, 1 - 2 * M, 0.27])
    ax.fill_between(t, [p["p05"] for p in day], [p["p95"] for p in day], color=ACCENT, alpha=0.12, lw=0)
    ax.fill_between(t, [p["p25"] for p in day], [p["p75"] for p in day], color=ACCENT, alpha=0.22, lw=0)
    ax.plot(t, [p["p50"] for p in day], color=ACCENT, lw=2.4, marker="o", ms=2.3)
    ax.scatter([ct(d["valid_utc"])], [now["wtmp_f"]], s=24, color=INK, zorder=5)
    ax.annotate(f"high {dv['hi'][0]:.1f}°", dv["hi"], textcoords="offset points", xytext=(0, 9),
                fontsize=7, color=AMBER, ha="center", **MONO)
    ax.xaxis.set_major_locator(mdates.HourLocator(byhour=range(0, 24, 3)))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%-I%p")); deframe(ax)
    ax.set_ylabel("water temperature (°F)", fontsize=7.5)
    ax.set_title("Hour by hour · the black dot is the live buoy reading the forecast is pinned to",
                 fontsize=8.5, loc="left", color=INK, pad=5)

    axc = fig.add_axes([M, 0.45, 0.46, 0.12]); axc.axis("off"); axc.set_xlim(0, 1); axc.set_ylim(0, 1)
    for i, (lab, val, col) in enumerate([
            ("TOMORROW'S HIGH", f"{dv['hi'][0]:.1f}°F @ {dv['hi'][1]:%-I %p}", INK),
            ("TOMORROW'S LOW", f"{dv['lo'][0]:.1f}°F @ {dv['lo'][1]:%-I %p}", INK),
            ("CHANGE VS NOW", f"{dv['chg24']:+.1f}°F {'warmer' if dv['chg24']>=0 else 'cooler'}",
             ACCENT if dv['chg24'] >= 0 else AMBER),
            ("90% RANGE AT +24H", f"{dv['p05_24']:.1f} – {dv['p95_24']:.1f}°F", INK)]):
        yy = 0.86 - i * 0.27
        axc.text(0, yy, lab, fontsize=6.2, color=MUTED, **MONO)
        axc.text(0, yy - 0.10, val, fontsize=10.5, color=col, fontweight="bold", **MONO)

    axw = fig.add_axes([M + 0.55, 0.45, 1 - 2 * M - 0.55, 0.12]); axw.axis("off")
    axw.set_xlim(0, 1); axw.set_ylim(0, 1)
    axw.text(0, 0.93, "CONDITIONS NOW", fontsize=6.2, color=MUTED, **MONO)
    for i, (lab, val) in enumerate([("Air", f"{now['atmp_f']:.1f}°F"), ("Waves", f"{now['wvht_ft']:.1f} ft"),
                                    ("Wind", f"{now['wspd_kt']:.0f} kt (gust {now['gst_kt']:.0f})")]):
        yy = 0.66 - i * 0.21
        axw.text(0, yy, lab, fontsize=8.5, color=MUTED); axw.text(1, yy, val, fontsize=8.5, color=INK,
                                                                  ha="right", fontweight="bold", **MONO)
    axw.text(0, 0.0, "North winds are what crash this shoreline.", fontsize=6.2, color=FAINT, style="italic")

    axu = fig.add_axes([M, 0.275, 1 - 2 * M, 0.13])
    unc = d["uncertainty"][:24]
    irr = np.array([u["irreducible"] for u in unc]); wx = np.array([u["weather"] for u in unc])
    axu.fill_between(t, 0, irr, color=ACCENT, alpha=0.35, lw=0, label="irreducible (the lake)")
    axu.fill_between(t, irr, irr + wx, color=AMBER, alpha=0.45, lw=0, label="weather-model spread")
    axu.xaxis.set_major_locator(mdates.HourLocator(byhour=range(0, 24, 6)))
    axu.xaxis.set_major_formatter(mdates.DateFormatter("%-I%p")); deframe(axu, grid=False)
    axu.set_ylabel("band ½-width (°F)", fontsize=7.5); axu.legend(loc="upper left", fontsize=6, frameon=False)
    axu.set_title("Where the next-day uncertainty comes from", fontsize=8.5, loc="left", pad=3)

    kick(fig, 0.225, "THE NEXT 24 HOURS")
    para(fig, 0.10, 0.115, day_text(d, dv))
    axs = fig.add_axes([M, 0.065, 1 - 2 * M, 0.03]); axs.axis("off"); axs.set_xlim(0, 1); axs.set_ylim(0, 1)
    axs.text(0, 0.5, "SWIM READ", fontsize=6.2, color=MUTED, va="center", **MONO)
    axs.text(0.12, 0.5, swim_word(now["wtmp_f"], now["atmp_f"], now["wspd_kt"]), fontsize=9.5,
             color=INK, va="center")
    foot(fig, 3, 4)


def swim_word(wt, air, wind):
    if wt < 60: s = "Very cold. Numbing fast; wetsuit weather."
    elif wt < 65: s = "Cold. A brisk, short dip for the acclimated."
    elif wt < 70: s = "Cool but swimmable. Refreshing once you are in."
    elif wt < 75: s = "Pleasant. Comfortable open-water swimming."
    else: s = "Warm. Easy, lingering swims."
    if air < wt - 2 and wind > 12:
        s += " Wind off the water will bite on the way out."
    return s


# ============================== PAGE 4: confidence + method ==============================
def page_confidence(fig, v, qs, issue_ct):
    banner(fig, "03", "Confidence & method", issue_ct)
    rec = v.get("recent24", []); by = v.get("by_lead", [])
    live = v.get("n_live", 0) > 0

    ax = fig.add_axes([M, 0.62, 1 - 2 * M, 0.25])
    if rec:
        t = [ct(p["valid"]) for p in rec]
        ax.fill_between(t, [p["p05"] for p in rec], [p["p95"] for p in rec], color=ACCENT, alpha=0.13, lw=0)
        ax.plot(t, [p["p50"] for p in rec], color=ACCENT, lw=1.5, label="published median")
        ax.plot(t, [p["actual"] for p in rec], color=INK, lw=1.1, ls=(0, (3, 2)) if not live else "-",
                label="actual" + ("" if live else " (replayed)"))
        ax.legend(loc="upper left", fontsize=6, frameon=False); datefmt(ax)
        ax.set_ylabel("water temperature (°F)", fontsize=7.5)
    tag = "Recent +24h forecasts vs what the water did" + ("" if live else " · replayed history")
    ax.set_title(tag, fontsize=8.5, loc="left", color=INK, pad=5)

    # skill + coverage
    axL = fig.add_axes([M, 0.40, 0.40, 0.16])
    axR = fig.add_axes([M + 0.47, 0.40, 1 - 2 * M - 0.47, 0.16])
    if by:
        hs = [b["h"] for b in by]
        axL.plot(hs, [b["mae_persist_f"] for b in by], color=MUTED, lw=1.3, ls=(0, (4, 3)), marker="o", ms=2.5, label="persistence")
        axL.plot(hs, [b["mae_f"] for b in by], color=ACCENT, lw=2.0, marker="o", ms=2.5, label="Seiche")
        axL.legend(fontsize=6, frameon=False, loc="upper left"); deframe(axL)
        axL.set_xlabel("lead (h)", fontsize=7); axL.set_ylabel("MAE (°F)", fontsize=7)
        axR.axhline(90, color=MUTED, lw=1.0, ls=(0, (4, 3)))
        axR.plot(hs, [b["cover90"] * 100 for b in by], color=ACCENT, lw=2.0, marker="o", ms=2.5)
        axR.set_ylim(60, 100); deframe(axR); axR.set_xlabel("lead (h)", fontsize=7); axR.set_ylabel("coverage (%)", fontsize=7)
    axL.set_title("Skill vs persistence", fontsize=8.5, loc="left", pad=3)
    axR.set_title("90% band coverage", fontsize=8.5, loc="left", pad=3)

    # drivers (importance) + residual histogram from qstats
    axD = fig.add_axes([M, 0.18, 0.40, 0.16])
    imp = (qs or {}).get("importance", [])[:7][::-1]
    if imp:
        LBL = {"WTMP": "water now", "h": "lead time", "fut_t2m": "air ahead",
               "fut_v": "alongshore wind", "fut_wspd": "wind speed ahead", "fut_solar": "sun ahead",
               "fut_gust": "gusts ahead", "doy_cos": "season", "doy_sin": "season",
               "fut_airwater": "air–water gap", "fut_dewdep": "evaporation", "WVHT": "waves now",
               "atmp_minus_wtmp": "air–water gap"}
        names = [LBL.get(x["name"], x["name"].replace("fut_", "").replace("_", " ")) for x in imp]
        axD.barh(range(len(imp)), [x["value"] for x in imp], color=ACCENT, alpha=0.8, height=0.6)
        axD.set_yticks(range(len(imp))); axD.set_yticklabels(names, fontsize=6)
        for s in ("top", "right"):
            axD.spines[s].set_visible(False)
        axD.tick_params(length=0); axD.set_xlabel("importance (°F)", fontsize=7)
    axD.set_title("What drives the forecast", fontsize=8.5, loc="left", pad=3)

    axH = fig.add_axes([M + 0.47, 0.18, 1 - 2 * M - 0.47, 0.16])
    r = (qs or {}).get("residuals24", {})
    if r.get("counts"):
        edges = np.array(r["edges"]); counts = np.array(r["counts"]); mid = (edges[:-1] + edges[1:]) / 2
        axH.bar(mid, counts, width=(edges[1] - edges[0]) * 0.9,
                color=[ACCENT if abs(m) <= 0.5 else (0.55, 0.65, 0.78) for m in mid])
        axH.axvline(0, color=INK, lw=0.8); deframe(axH, grid=False)
        axH.set_xlabel("+24h error (°F)", fontsize=7); axH.set_ylabel("count", fontsize=7)
    axH.set_title("Error distribution at +24h", fontsize=8.5, loc="left", pad=3)

    kick(fig, 0.13, "CONFIDENCE")
    para(fig, 0.04, 0.085, confidence_text(v), size=8.8, width=118)
    fig.text(M, 0.05, "Method: five gradient-boosted quantile models per horizon, anchored to the "
             "live buoy; adaptive-conformal bands on a 9-season backtest.",
             fontsize=6.0, color=FAINT, **MONO)
    foot(fig, 4, 4)


# ---------- main ----------
def main():
    d = load("site/data.json")
    if d is None:
        raise SystemExit("site/data.json not found; run publish.py first")
    v = load("site/verify.json", {}); qs = load("models/qstats.json", {})
    dv = derive(d)

    issued = datetime.now(timezone.utc)
    issue_ct = issued.astimezone(CENTRAL).strftime("%Y-%m-%d %-I:%M %p CT")
    valid_ct = datetime.fromisoformat(d["valid_utc"]).astimezone(CENTRAL).strftime("%Y-%m-%d %-I:%M %p CT")

    BRIEFS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = issued.strftime("%Y%m%d_%H%MZ")
    out = BRIEFS_DIR / f"seiche_report_{stamp}.pdf"
    with PdfPages(out) as pdf:
        for pg in (lambda f: page_cover(f, d, dv, issue_ct, valid_ct),
                   lambda f: page_week(f, d, dv, issue_ct),
                   lambda f: page_day(f, d, dv, issue_ct),
                   lambda f: page_confidence(f, v, qs, issue_ct)):
            fig = plt.figure(figsize=A4); pg(fig); pdf.savefig(fig); plt.close(fig)
        meta = pdf.infodict()
        meta["Title"] = f"Seiche Six-Hour Report {stamp}"; meta["Author"] = "Seiche"

    shutil.copy(out, BRIEFS_DIR / "latest.pdf")
    kept = sorted(BRIEFS_DIR.glob("seiche_report_*.pdf"))
    for old in kept[:-BRIEFS_KEEP]:
        old.unlink()
    # tidy any briefs from the earlier naming
    for old in BRIEFS_DIR.glob("seiche_brief_*.pdf"):
        old.unlink()
    print(f"wrote {out} (+ latest.pdf); {len(kept[-BRIEFS_KEEP:])} reports kept")


if __name__ == "__main__":
    main()

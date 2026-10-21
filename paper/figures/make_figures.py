"""Regenerate the paper's data figures from the repository's own evaluation outputs.

    python3 paper/figures/make_figures.py

Every number plotted is read from ml/reports/*.json or ml/artifacts/*/metrics.json;
nothing is typed in by hand except the feature-ablation run label.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("pdf")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
REPORTS = ROOT / "ml" / "reports"
ARTIFACTS = ROOT / "ml" / "artifacts"

COL_W = 3.45  # IEEE single column, inches
BLUE, ORANGE, GREEN, GREY, PURPLE, SKY = "#0B5394", "#D55E00", "#009E73", "#7F7F7F", "#8E44AD", "#56B4E9"

plt.rcParams.update({
    "font.family": "serif",
    "font.serif": ["Liberation Serif", "Times New Roman", "DejaVu Serif"],
    "mathtext.fontset": "stix",
    "font.size": 8,
    "axes.labelsize": 8,
    "axes.titlesize": 8,
    "xtick.labelsize": 7,
    "ytick.labelsize": 7,
    "legend.fontsize": 6.5,
    "axes.linewidth": 0.6,
    "xtick.major.width": 0.6,
    "ytick.major.width": 0.6,
    "lines.linewidth": 1.1,
    "pdf.fonttype": 42,
    "savefig.bbox": "tight",
    "savefig.pad_inches": 0.02,
})


def load(path: Path) -> dict:
    return json.loads(path.read_text())


def experiments(report: dict) -> dict[str, dict]:
    """Flatten benchmark experiments to {"B1/bilateral/rf_invariant/w2.0": metrics}."""
    out: dict[str, dict] = {}

    def walk(node, path):
        if isinstance(node, dict):
            if "macro_f1" in node and not isinstance(node["macro_f1"], dict):
                out[path.strip("/")] = node
                return
            for k, v in node.items():
                walk(v, f"{path}/{k}")

    walk(report["experiments"], "")
    return out


full = experiments(load(REPORTS / "benchmark_20261006-145415.json"))
quick = experiments(load(REPORTS / "benchmark_20261006-124542_quick.json"))


# ---------------------------------------------------------------- Fig. 3
def fig_orientation_ablation() -> None:
    sets = [
        ("Raw sensor axes", full["B2/bilateral/rf_raw_axis/w2.0"], GREY),
        ("Orientation-invariant only", quick["B1/bilateral/rf_invariant/w2.0"], SKY),
        ("Invariant + neutral pose (ours)", full["B1/bilateral/rf_invariant/w2.0"], BLUE),
    ]
    conds = [("Original\nmounting", None), ("Random\nre-mounting", "rotation"), ("3$\\times$ sensor\nnoise", "noise_x3")]
    x = np.arange(len(conds))
    w = 0.26
    fig, ax = plt.subplots(figsize=(COL_W, 1.42))
    for i, (label, m, color) in enumerate(sets):
        vals = [m["macro_f1"] if key is None else m["robustness_macro_f1"][key] for _, key in conds]
        bars = ax.bar(x + (i - 1) * w, vals, w, label=label, color=color, edgecolor="black", linewidth=0.4)
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, v + 0.015, f"{v:.2f}", ha="center", va="bottom", fontsize=5.8)
    ax.set_xticks(x, [c for c, _ in conds])
    ax.set_ylabel("Macro-F1")
    ax.set_ylim(0, 1.12)
    ax.set_yticks([0, 0.25, 0.5, 0.75, 1.0])
    ax.grid(axis="y", linewidth=0.3, alpha=0.6)
    ax.set_axisbelow(True)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, 1.2), ncol=3, frameon=False, handlelength=1.2,
              columnspacing=0.8, handletextpad=0.4)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    fig.savefig(OUT / "fig_orientation_ablation.pdf")
    plt.close(fig)


# ---------------------------------------------------------------- Fig. 4
def fig_model_selection() -> None:
    fig, ax = plt.subplots(figsize=(COL_W, 1.8))
    families = [
        ("RF, invariant+neutral", "B1/bilateral/rf_invariant", BLUE, "o",
         {"1.0": (-13, -3), "2.0": (5, -8), "3.0": (-13, 1)}),
        ("RF, + device-like aug.", "B1/bilateral/rf_invariant_aug", SKY, "s", {}),
        ("Hist. gradient boosting", "B1/bilateral/hgb_invariant", ORANGE, "^",
         {"1.0": (4, -7), "2.0": (4, -7), "3.0": (-14, -2)}),
    ]
    for label, prefix, color, marker, offsets in families:
        pts = [(full[f"{prefix}/w{w}"]["latency_ms_p95"], full[f"{prefix}/w{w}"]["macro_f1"], w)
               for w in ("1.0", "2.0", "3.0")]
        ax.plot([p[0] for p in pts], [p[1] for p in pts], color=color, linewidth=0.6, alpha=0.5)
        ax.scatter([p[0] for p in pts], [p[1] for p in pts], color=color, marker=marker, s=16,
                   edgecolor="black", linewidth=0.35, label=label, zorder=3)
        for lat, f1, w in pts:
            if w in offsets:
                ax.annotate(f"{float(w):.0f} s", (lat, f1), textcoords="offset points", xytext=offsets[w],
                            fontsize=5.5, color=color)
    deep = [("1D CNN", "B2/bilateral/cnn/w2.0", (5, -2)),
            ("CNN-LSTM", "B2/bilateral/cnn_lstm/w2.0", (5, -5)),
            ("CNN, PAMAP2-pretrained", "B2/bilateral/cnn_pretrained_pamap2/w2.0", (-8, 5))]
    ax.scatter([full[k]["latency_ms_p95"] for _, k, _ in deep], [full[k]["macro_f1"] for _, k, _ in deep],
               color=GREEN, marker="D", s=14, edgecolor="black", linewidth=0.35, label="Deep models (2 s)", zorder=3)
    for name, k, off in deep:
        ax.annotate(name, (full[k]["latency_ms_p95"], full[k]["macro_f1"]), textcoords="offset points",
                    xytext=off, fontsize=5.5, color=GREEN)
    sel = full["B1/bilateral/rf_invariant/w2.0"]
    ax.scatter([sel["latency_ms_p95"]], [sel["macro_f1"]], marker="*", s=130, facecolor="none",
               edgecolor="black", linewidth=0.8, zorder=4)
    ax.annotate("deployed", (sel["latency_ms_p95"], sel["macro_f1"]), textcoords="offset points",
                xytext=(-10, 9), fontsize=6, fontweight="bold")
    ax.axvline(50, color="black", linestyle="--", linewidth=0.6)
    ax.axvspan(50, 400, color=ORANGE, alpha=0.08)
    ax.text(52, 0.866, "exceeds 50 ms\nlatency budget", fontsize=5.8, color=ORANGE, va="bottom")
    ax.set_xscale("log")
    ax.set_xlim(0.15, 400)
    ax.set_ylim(0.86, 0.955)
    ax.set_xlabel("Single-window inference latency, p95 (ms, log scale)")
    ax.set_ylabel("Macro-F1 (subject-indep.)")
    ax.grid(linewidth=0.3, alpha=0.6)
    ax.set_axisbelow(True)
    ax.legend(loc="lower right", bbox_to_anchor=(0.73, 0.0), frameon=True, framealpha=0.9, edgecolor="none",
              borderpad=0.3, handletextpad=0.3, labelspacing=0.25)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    fig.savefig(OUT / "fig_model_selection.pdf")
    plt.close(fig)


# ---------------------------------------------------------------- Fig. 5
def fig_confusion() -> None:
    m = load(ARTIFACTS / "activity_bilateral" / "v1" / "metrics.json")
    cm = np.array(m["confusion_matrix"], dtype=float)
    cmn = cm / cm.sum(axis=1, keepdims=True)
    names = {"cycling": "Cycling", "lying": "Lying", "other_exercise": "Other ex.", "running": "Running",
             "sitting": "Sitting", "stairs_down": "Stairs dn.", "stairs_up": "Stairs up",
             "standing": "Standing", "walking": "Walking"}
    labels = [names[c] for c in m["classes"]]
    fig, ax = plt.subplots(figsize=(COL_W, 1.8))
    im = ax.imshow(cmn, cmap="Blues", vmin=0, vmax=1)
    for i in range(len(labels)):
        for j in range(len(labels)):
            v = cmn[i, j]
            if v >= 0.005:
                ax.text(j, i, f"{v:.2f}".lstrip("0") if v < 1 else "1.0", ha="center", va="center",
                        fontsize=5.6, color="white" if v > 0.55 else "black")
    ax.set_xticks(range(len(labels)), labels, rotation=55, ha="right", rotation_mode="anchor", fontsize=6.5)
    ax.set_yticks(range(len(labels)), labels)
    ax.set_xlabel("Predicted activity")
    ax.set_ylabel("True activity")
    ax.tick_params(length=0)
    cb = fig.colorbar(im, ax=ax, fraction=0.045, pad=0.02)
    cb.ax.tick_params(labelsize=6, width=0.5, length=2)
    cb.outline.set_linewidth(0.5)
    cb.set_label("Row-normalised recall", fontsize=6.5)
    fig.savefig(OUT / "fig_confusion.pdf")
    plt.close(fig)


# ---------------------------------------------------------------- Fig. 6
def fig_simulator() -> None:
    sim = load(REPORTS / "simulator_evaluation.json")["asymmetry_vs_severity"]
    mqi = load(REPORTS / "mqi_characterization.json")["directionality_vs_asymmetry"]
    sev = ["0.0", "0.2", "0.4", "0.6"]
    xs = [float(s) for s in sev]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(COL_W, 1.38))
    for name, color, marker in (("SQUAT", BLUE, "o"), ("SIT_TO_STAND", GREEN, "s"), ("WALK", ORANGE, "^")):
        label = {"SQUAT": "Squat", "SIT_TO_STAND": "Sit-to-stand", "WALK": "Walking"}[name]
        a1.plot(xs, [sim[name][s] for s in sev], marker=marker, markersize=3.2, color=color, label=label)
    a1.set_xlabel("Injected left-side deficit")
    a1.set_ylabel("Asymmetry score $A$")
    a1.set_title("(a) Bilateral asymmetry", fontsize=7.5)
    a1.legend(frameon=False, loc="upper left", handlelength=1.3, labelspacing=0.1, fontsize=5.8, borderaxespad=0.2)
    a1.set_ylim(0, 0.58)
    mean = [mqi[s]["mqi"]["mean"] for s in sev]
    sd = [mqi[s]["mqi"]["sd"] for s in sev]
    a2.errorbar(xs, mean, yerr=sd, color=PURPLE, marker="o", markersize=3.2, capsize=2, elinewidth=0.6)
    for x_, m_ in zip(xs, mean):
        a2.annotate(f"{m_:.1f}", (x_, m_), textcoords="offset points", xytext=(4, 2), fontsize=5.6)
    a2.set_xlabel("Injected left-side deficit")
    a2.set_ylabel("MQI (0 to 100)")
    a2.set_title("(b) Movement Quality Index", fontsize=7.5)
    a2.set_ylim(78, 99)
    for ax in (a1, a2):
        ax.set_xticks(xs)
        ax.grid(linewidth=0.3, alpha=0.6)
        ax.set_axisbelow(True)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
    fig.tight_layout(w_pad=1.0)
    fig.savefig(OUT / "fig_simulator.pdf")
    plt.close(fig)


if __name__ == "__main__":
    fig_orientation_ablation()
    fig_model_selection()
    fig_confusion()
    fig_simulator()
    print("figures written to", OUT)

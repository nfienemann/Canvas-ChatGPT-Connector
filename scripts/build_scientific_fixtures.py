"""Reproducible original scientific test diagrams, not experimental observations.

Authoring-only numpy/matplotlib/reportlab; committed bytes are used by CI.
Every source value is fictional. No third-party image or student record is used.
"""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "benchmarks/scientific/v3"
CASES = [
    (
        "western-blot",
        "Western blot",
        "Control and treatment protein bands; loading bands",
        [
            "Identify target and loading bands separately.",
            "Do not infer an exact fold change or significance from band darkness.",
        ],
    ),
    (
        "flow-cytometry",
        "Flow cytometry",
        "Control and treatment fluorescence channels",
        [
            "Identify both fluorescence channels and quadrant thresholds.",
            "A drawn threshold is not a validated gating strategy; percentages are not printed.",
        ],
    ),
    (
        "qpcr",
        "qPCR amplification",
        "Control and treatment fluorescence by amplification cycle",
        [
            "The plotted threshold crossings are labeled 18 and 22 cycles.",
            "Amplification efficiency and normalization are unspecified; do not claim a fold change.",
        ],
    ),
    (
        "mass-spectrometry",
        "Mass spectrometry",
        "Ion intensity across mass to charge ratios",
        [
            "The highest labeled peak is m/z 150 at relative intensity 100.",
            "No compound identity, charge assignment or library match is established.",
        ],
    ),
    (
        "microscopy",
        "Microscopy",
        "Synthetic cell fluorescence with a scale bar",
        [
            "Identify the scale bar and visible cell-like regions.",
            "This is generated image data, not evidence of a cell phenotype or viability.",
        ],
    ),
    (
        "cell-signaling",
        "Cell signaling",
        "Proposed receptor kinase transcription mechanism",
        [
            "Distinguish the solid directed links from the dashed proposed connection.",
            "A mechanism diagram does not demonstrate that the pathway operated in an experiment.",
        ],
    ),
    (
        "dose-response",
        "Dose response",
        "Treatment concentration and normalized response",
        [
            "Identify the logarithmic concentration axis in nM and normalized response percent.",
            "The 50 percent point at 10 nM is explicit; uncertainty and fitted IC50 are not supplied.",
        ],
    ),
    (
        "confocal",
        "Confocal imaging",
        "Red green channels and merged optical section",
        [
            "Keep red, green and merged panels separate; only one optical section is shown.",
            "Overlap does not establish molecular interaction or a three-dimensional reconstruction.",
        ],
    ),
    (
        "multi-panel",
        "Multi-panel research figure",
        "Different measurements across panels A and B",
        [
            "Panel A has time and response axes; panel B has concentration and signal axes.",
            "Do not mix units or transfer an axis scale between panels.",
        ],
    ),
    (
        "complex-table",
        "Complex table headers",
        "Treatment replicates and units in merged headers",
        [
            "Map each value to condition, replicate and unit; ND is not zero.",
            "Preserve scientific notation and the multi-level header relationships.",
        ],
    ),
]


def main():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    from reportlab.pdfgen import canvas

    ROOT.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 15})
    cases = []
    for index, (identity, title, query, rubric) in enumerate(CASES, 1):
        fig = plt.figure(figsize=(12, 7), dpi=100)
        ax = fig.add_subplot()
        rng = np.random.default_rng(100 + index)
        if identity == "western-blot":
            data = np.ones((120, 240)) * 0.95
            data[30:39, 25:95] = 0.5
            data[30:39, 145:215] = 0.2
            data[83:91, 25:95] = data[83:91, 145:215] = 0.35
            ax.imshow(data, cmap="gray", vmin=0, vmax=1)
            ax.set(
                xticks=[60, 180],
                xticklabels=["Control", "Treatment"],
                yticks=[34, 87],
                yticklabels=["Target", "Loading"],
            )
        elif identity == "flow-cytometry":
            for mean, color, name in [(2, "#216c8a", "Control"), (6, "#c46628", "Treatment")]:
                ax.scatter(
                    rng.normal(mean, 0.7, 150),
                    rng.normal(mean, 0.8, 150),
                    c=color,
                    s=12,
                    label=name,
                    alpha=0.65,
                )
            ax.axvline(5, color="gray", linestyle="--")
            ax.axhline(5, color="gray", linestyle="--")
            ax.set(
                xlim=(0, 10),
                ylim=(0, 10),
                xlabel="Channel 1 fluorescence (a.u.)",
                ylabel="Channel 2 fluorescence (a.u.)",
            )
            ax.legend()
        elif identity == "qpcr":
            x = np.arange(1, 41)
            for midpoint, name in [(22, "Control"), (18, "Treatment")]:
                ax.plot(x, 1 / (1 + np.exp(-(x - midpoint) / 1.5)), label=name)
                ax.annotate(
                    f"{midpoint} cycles",
                    (midpoint, 0.5),
                    (midpoint + 2 if midpoint == 22 else midpoint - 9, 0.65),
                    arrowprops={"arrowstyle": "->"},
                )
            ax.axhline(0.5, color="gray", linestyle="--", label="Threshold 0.5")
            ax.set(xlabel="Amplification cycle", ylabel="Fluorescence (a.u.)", ylim=(0, 1.1))
            ax.legend()
        elif identity == "mass-spectrometry":
            x, y = [100, 150, 200], [20, 100, 40]
            ax.vlines(x, 0, y, color="#216c8a", linewidth=3)
            for a, b in zip(x, y, strict=True):
                ax.text(a, b + 3, f"{a}: {b}", ha="center")
            ax.set(xlim=(75, 225), ylim=(0, 120), xlabel="m/z", ylabel="Relative ion intensity (%)")
        elif identity in {"microscopy", "confocal"}:
            y, x = np.mgrid[:160, :240]
            green = sum(
                np.exp(-((x - cx) ** 2 + (y - cy) ** 2) / 180)
                for cx, cy in [(45, 55), (115, 95), (185, 55)]
            )
            red = sum(
                np.exp(-((x - cx) ** 2 + (y - cy) ** 2) / 180)
                for cx, cy in [(60, 55), (115, 95), (200, 120)]
            )
            if identity == "microscopy":
                image = np.stack([green * 0, green, green * 0], axis=2)
                ax.imshow(np.clip(image, 0, 1))
                ax.plot([170, 210], [140, 140], color="white", lw=4)
                ax.text(190, 132, "20 um", color="white", ha="center")
                ax.axis("off")
            else:
                fig.delaxes(ax)
                for k, (name, rgb) in enumerate(
                    [
                        ("A Red", np.stack([red, red * 0, red * 0], 2)),
                        ("B Green", np.stack([green * 0, green, green * 0], 2)),
                        ("C Merge", np.stack([red, green, green * 0], 2)),
                    ],
                    1,
                ):
                    panel = fig.add_subplot(1, 3, k)
                    panel.imshow(np.clip(rgb, 0, 1))
                    panel.set_title(name)
                    panel.axis("off")
        elif identity == "cell-signaling":
            ax.set(xlim=(0, 10), ylim=(0, 4))
            ax.axis("off")
            for x, label in [(1, "Receptor R"), (5, "Kinase K"), (9, "Factor T")]:
                ax.text(
                    x,
                    2,
                    label,
                    ha="center",
                    va="center",
                    bbox={"facecolor": "#e5f1f3", "edgecolor": "#216c8a", "pad": 12},
                )
            ax.annotate("", (4, 2), (2, 2), arrowprops={"arrowstyle": "->", "lw": 2})
            ax.annotate(
                "", (8, 2), (6, 2), arrowprops={"arrowstyle": "->", "lw": 2, "linestyle": "--"}
            )
            ax.text(7, 1.25, "Proposed connection", ha="center")
        elif identity == "dose-response":
            x = np.logspace(-1, 3, 100)
            ax.semilogx(x, 100 * x / (10 + x))
            ax.scatter([10], [50], color="#c46628")
            ax.annotate("10 nM, 50%", (10, 50), (25, 35), arrowprops={"arrowstyle": "->"})
            ax.set(
                xlabel="Concentration (nM; log scale)",
                ylabel="Normalized response (%)",
                ylim=(0, 105),
            )
        elif identity == "multi-panel":
            fig.delaxes(ax)
            a = fig.add_subplot(121)
            a.plot([0, 1, 2, 3], [2, 4, 6, 8], marker="o")
            a.set(title="A", xlabel="Time (hours)", ylabel="Response (a.u.)")
            b = fig.add_subplot(122)
            b.plot([1, 10, 100], [3, 4, 7], marker="s")
            b.set(title="B", xlabel="Concentration (nM)", ylabel="Signal (counts)")
        else:
            ax.axis("off")
            table = ax.table(
                cellText=[
                    ["Condition", "Replicate 1", "Replicate 2"],
                    ["Control (uM)", "1e-3", "ND"],
                    ["Treatment (uM)", "2e-3", "3e-3"],
                ],
                cellLoc="center",
                bbox=[0.05, 0.2, 0.9, 0.55],
            )
            table.auto_set_font_size(False)
            table.set_fontsize(19)
            ax.text(
                0.65,
                0.82,
                "Concentration measurements",
                ha="center",
                fontsize=20,
                transform=ax.transAxes,
            )
            ax.plot([0.35, 0.95], [0.78, 0.78], color="black", transform=ax.transAxes)
        fig.suptitle(f"Figure {index}. {title} - fictional fixture", fontsize=21)
        fig.text(
            0.05,
            0.045,
            "Entirely synthetic. No real experiment, student data or inferential statistics.",
            fontsize=12,
        )
        fig.subplots_adjust(left=0.14, right=0.95, bottom=0.19, top=0.83, wspace=0.38)
        fig.savefig(
            ROOT / f"{identity}.png", metadata={"Software": "Canvas Bridge scientific fixtures v3"}
        )
        plt.close(fig)
        cases.append(
            {
                "id": identity,
                "page": index,
                "figure_label": f"Figure {index}",
                "query": query,
                "required_dimensions": [
                    "axes_units_or_labels",
                    "observations_vs_text",
                    "controls_or_comparison",
                    "numerical_grounding",
                    "limitations",
                ],
                "rubric": rubric,
                "rubric_status": "draft_requires_independent_expert_review",
            }
        )
    pdf = canvas.Canvas(
        str(ROOT / "scientific-fixtures.pdf"), pagesize=(960, 560), invariant=1, pageCompression=1
    )
    pdf.setTitle("Fictional scientific comprehension fixtures v3")
    pdf.setAuthor("Canvas Bridge fictional fixture author")
    for case, info in zip(cases, CASES, strict=True):
        pdf.setFont("Helvetica", 11)
        pdf.drawString(28, 540, f"Figure {case['page']}. {info[1]}")
        pdf.drawString(28, 522, case["query"])
        pdf.drawImage(str(ROOT / f"{case['id']}.png"), 0, 0, width=960, height=510)
        pdf.showPage()
    pdf.save()

    def write(name, value):
        (ROOT / name).write_text(
            json.dumps(value, indent=2, ensure_ascii=True) + "\n", encoding="utf-8", newline="\n"
        )

    write("cases.json", {"schema": "scientific-benchmark-3", "synthetic": True, "cases": cases})
    write(
        "manifest.json",
        {
            "schema": "scientific-benchmark-3",
            "license": "CC0-1.0",
            "synthetic": True,
            "files": {
                p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(ROOT.iterdir())
                if p.suffix in {".png", ".pdf"} or p.name == "cases.json"
            },
        },
    )


if __name__ == "__main__":
    main()

"""Original exact-data scientific fixtures. Requires authoring-only reportlab/matplotlib.

Committed assets are used by CI. No clinical or real research claims are made.
PNG plots intentionally carry scientific labels only in pixels in the PDF/PPTX.
"""

import argparse
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 16,
            "axes.spines.top": False,
            "axes.spines.right": False,
        }
    )
    for index in (1, 2):
        fig, ax = plt.subplots(figsize=(12, 6.75), dpi=120)
        fig.set_facecolor("#fafafa")
        ax.set_facecolor("#fafafa")
        if index == 1:
            ax.errorbar(
                [0, 1, 2, 3],
                [2, 4, 6, 8],
                yerr=[0.3, 0.4, 0.5, 0.5],
                color="#166a82",
                marker="o",
                capsize=5,
                label="Treatment",
            )
            ax.errorbar(
                [0, 1, 2, 3],
                [2, 2, 3, 3],
                yerr=[0.2, 0.2, 0.4, 0.3],
                color="#be6a25",
                marker="s",
                capsize=5,
                label="Control",
            )
            ax.set(
                xlabel="Time (hours)",
                ylabel="Measured response (arbitrary units)",
                xticks=[0, 1, 2, 3],
                yticks=list(range(0, 11, 2)),
                ylim=(0, 10),
                title="Fictional cell response over time",
            )
            ax.legend(loc="upper left", frameon=False)
            caption = "Mean and SD; n = 3 independent fictional replicates per condition. No significance test supplied."
        else:
            ax.plot([0, 1, 2, 3], [1, 10, 100, 1000], color="#166a82", marker="o", linewidth=2)
            ax.set_yscale("log")
            ax.set(
                xlabel="Time (hours)",
                ylabel="Signal (arbitrary units; log scale)",
                xticks=[0, 1, 2, 3],
                title="Fictional signal on a logarithmic axis",
            )
            caption = "One illustrative series. Replicate count and uncertainty were not supplied; no causal conclusion follows."
        fig.subplots_adjust(left=0.12, right=0.97, bottom=0.20, top=0.87)
        fig.text(0.07, 0.055, caption, fontsize=12)
        fig.savefig(
            args.output / f"figure-{index}.png",
            metadata={"Software": "Canvas Bridge fictional benchmark v1"},
        )
        plt.close(fig)
    pdf = canvas.Canvas(
        str(args.output / "scientific-lecture.pdf"),
        pagesize=(960, 540),
        invariant=1,
        pageCompression=1,
    )
    pdf.setTitle("Fictional scientific lecture - benchmark v1")
    pdf.setAuthor("Canvas Bridge synthetic benchmark fixtures")
    for index in (1, 2):
        pdf.setFont("Helvetica", 10)
        pdf.drawString(
            30, 520, f"Fictional Meridian University | BIO201 | Image lecture page {index}"
        )
        pdf.drawImage(
            ImageReader(str(args.output / f"figure-{index}.png")), 0, 0, width=960, height=510
        )
        pdf.showPage()
    pdf.save()


if __name__ == "__main__":
    main()

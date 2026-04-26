from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Rectangle, Circle


def draw_module(ax, x, y, w, h, title, subtitle=None):
    box = FancyBboxPatch(
        (x, y),
        w,
        h,
        boxstyle="round,pad=0.01,rounding_size=0.02",
        linewidth=2.0,
        edgecolor="#2f5f8f",
        facecolor="#ffffff",
    )
    ax.add_patch(box)

    # simple icon area
    icon_w = w * 0.22
    icon_h = h * 0.36
    icon_x = x + w * 0.06
    icon_y = y + h * 0.52
    icon = Rectangle(
        (icon_x, icon_y),
        icon_w,
        icon_h,
        linewidth=1.8,
        edgecolor="#2f78b8",
        facecolor="#d8eaf8",
    )
    ax.add_patch(icon)
    ax.add_patch(
        Circle(
            (icon_x + icon_w * 0.5, icon_y + icon_h * 0.5),
            radius=min(icon_w, icon_h) * 0.18,
            linewidth=1.3,
            edgecolor="#2f78b8",
            facecolor="#ffffff",
        )
    )

    ax.text(
        x + w * 0.33,
        y + h * 0.70,
        title,
        fontsize=16,
        fontweight="bold",
        va="center",
        ha="left",
        color="#24384d",
        linespacing=1.2,
    )
    if subtitle:
        ax.text(
            x + w * 0.33,
            y + h * 0.32,
            subtitle,
            fontsize=11.5,
            va="center",
            ha="left",
            color="#465f79",
            linespacing=1.2,
        )


def dashed_arrow(ax, p1, p2):
    arrow = FancyArrowPatch(
        p1,
        p2,
        arrowstyle="->",
        mutation_scale=14,
        linewidth=1.8,
        linestyle=(0, (2, 2)),
        color="#6c7f95",
    )
    ax.add_patch(arrow)


def main() -> None:
    out_path = Path("architecture_visual_bills.png").resolve()

    fig = plt.figure(figsize=(14, 8), dpi=180)
    ax = fig.add_axes([0, 0, 1, 1])
    fig.patch.set_facecolor("#eef2f7")
    ax.set_facecolor("#eef2f7")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    ax.text(
        0.5,
        0.93,
        "HOW BILLS WORKS?",
        ha="center",
        va="center",
        fontsize=38,
        fontweight="heavy",
        color="#101820",
    )

    ax.text(
        0.06,
        0.82,
        "Fetches emails via Gmail API\nwith initial financial filtering.",
        ha="left",
        va="top",
        fontsize=16,
        fontweight="bold",
        color="#101820",
        linespacing=1.3,
    )
    ax.text(
        0.38,
        0.82,
        "Extracts amount, due date and category,\nthen prepares records for dashboard view.",
        ha="left",
        va="top",
        fontsize=16,
        fontweight="bold",
        color="#101820",
        linespacing=1.3,
    )

    email_box = (0.06, 0.45, 0.25, 0.21)
    analysis_box = (0.37, 0.45, 0.29, 0.21)
    db_box = (0.72, 0.16, 0.22, 0.20)
    dashboard_box = (0.72, 0.68, 0.22, 0.20)

    draw_module(
        ax,
        *email_box,
        title="EMAIL\nRETRIEVAL MODULE",
        subtitle="OAuth + Gmail Fetch",
    )
    draw_module(
        ax,
        *analysis_box,
        title="EXTRACTION &\nANALYSIS MODULE",
        subtitle="pdf/text parsing + categorization",
    )
    draw_module(
        ax,
        *db_box,
        title="DATABASE STORAGE\nMODULE",
        subtitle="SQLite Bills_billdocument",
    )
    draw_module(
        ax,
        *dashboard_box,
        title="DASHBOARD MODULE",
        subtitle="React UI + KPI + Alerts",
    )

    # flow lines (dashed), similar to reference style
    dashed_arrow(
        ax,
        (email_box[0] + email_box[2] * 0.5, email_box[1] - 0.01),
        (db_box[0] + db_box[2] * 0.22, db_box[1] + db_box[3] * 0.66),
    )
    dashed_arrow(
        ax,
        (analysis_box[0] + analysis_box[2] * 0.5, analysis_box[1] - 0.01),
        (db_box[0] + db_box[2] * 0.45, db_box[1] + db_box[3] * 0.66),
    )
    dashed_arrow(
        ax,
        (db_box[0] + db_box[2] * 0.60, db_box[1] + db_box[3] + 0.005),
        (dashboard_box[0] + dashboard_box[2] * 0.60, dashboard_box[1] - 0.01),
    )

    ax.text(
        0.79,
        0.41,
        "DASHBOARD\nDATA FEED",
        ha="center",
        va="center",
        fontsize=14,
        fontweight="bold",
        color="#3a4f66",
        linespacing=1.2,
    )

    fig.savefig(out_path, dpi=180, facecolor=fig.get_facecolor())
    print(f"Saved: {out_path}")


if __name__ == "__main__":
    main()


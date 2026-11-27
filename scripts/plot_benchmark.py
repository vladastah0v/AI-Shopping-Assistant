import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

from matplotlib import pyplot as plt  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Построить график измеренных задержек.")
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    rows = json.loads(args.input.read_text())["experiments"]
    labels = [f"{row['experiment']} (K={row['top_k']})" for row in rows]
    values = [row["p95_ms"] for row in rows]
    fig, ax = plt.subplots(figsize=(8, max(3.2, len(rows) * 0.45)), layout="constrained")
    bars = ax.barh(labels, values, color="#216476")
    ax.invert_yaxis()
    ax.set_title("Задержки поиска на малом профиле")
    ax.set_xlabel("Задержка p95, мс")
    ax.bar_label(bars, fmt="%.2f", padding=4)
    ax.margins(x=0.1)
    fig.savefig(args.output, dpi=145)


if __name__ == "__main__":
    main()

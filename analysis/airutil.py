#!/usr/bin/env python3
"""
Zeichnet die airUtilTx Werte aus airutil.csv (vom cli_sniffer) als Diagramm.
airUtilTx = Anteil der Zeit in % in der ein Gerät selbst sendet.
"""

import csv
import sys
from datetime import datetime

import matplotlib.pyplot as plt


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "airutil.csv"

    times, values = [], []
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f, delimiter=";"):
            try:
                times.append(datetime.fromtimestamp(int(row["timestamp"])))
                values.append(float(row["air_util"]))
            except (ValueError, KeyError):
                continue  # kaputte Zeile überspringen

    if not values:
        print("Keine Werte gefunden")
        return

    print(f"{len(values)} Werte, Mittelwert {sum(values) / len(values):.2f} %, Max {max(values):.2f} %")

    plt.figure(figsize=(9, 4))
    plt.plot(times, values, ".", markersize=4)
    plt.ylabel("airUtilTx [%]")
    plt.title("Sendeauslastung (airUtilTx)")
    plt.gcf().autofmt_xdate()
    plt.savefig("airutil.png", dpi=120, bbox_inches="tight")
    print("gespeichert: airutil.png")


if __name__ == "__main__":
    main()

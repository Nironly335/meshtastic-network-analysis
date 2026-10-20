#!/usr/bin/env python3
"""
Hop-Analyse auf der SQLite-Datenbank (Tabelle rawpackets).

Hops die ein Paket gemacht hat = hopStart - hopLimit
(hopStart = Limit beim Absender, hopLimit = was beim Empfang noch übrig ist)

Pro Node wird die minimale Hop-Distanz genommen (= kürzester Weg zu uns)
und ausserdem Median/Mittelwert über alle Pakete.

Beispiel:
  python hops.py meshtastic.db --min-packets 5 --plot
"""

import sqlite3
import csv
import argparse
from collections import defaultdict
from statistics import median, mean


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("db", help="Pfad zur SQLite-Datenbank")
    ap.add_argument("--min-packets", type=int, default=5,
                    help="Nodes mit weniger Paketen ignorieren (Rauschen, siehe README)")
    ap.add_argument("--with-mqtt", action="store_true",
                    help="auch Pakete mit MQTT-Flag mitzählen (standard: nein)")
    ap.add_argument("--max-hops", type=int, default=None)
    ap.add_argument("--csv", default="hop_nodes.csv")
    ap.add_argument("--summary", default="hop_summary.csv")
    ap.add_argument("--plot", action="store_true", help="Histogramm als hops.png speichern")
    return ap.parse_args()


def load_hops(db_path, with_mqtt):
    con = sqlite3.connect(db_path)
    cur = con.cursor()

    query = """
        SELECT "from", hopStart, hopLimit
        FROM rawpackets
        WHERE hopStart IS NOT NULL
          AND hopLimit IS NOT NULL
          AND "from" IS NOT NULL
    """
    if not with_mqtt:
        query += " AND mqtt = 0"

    hops_per_node = defaultdict(list)
    negative = 0

    for from_id, hop_start, hop_limit in cur.execute(query):
        dist = hop_start - hop_limit
        if dist < 0:
            # kann eigentlich nicht sein -> kaputtes Paket
            negative += 1
            continue
        hops_per_node[from_id].append(dist)

    con.close()
    return hops_per_node, negative


def guess_my_node_id(hops_per_node):
    """
    Mein eigener Node sollte Distanz 0 haben und die meisten Pakete.
    Ist nur eine Heuristik!
    """
    candidates = [(n, len(h)) for n, h in hops_per_node.items() if min(h) == 0]
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[1], reverse=True)
    return candidates[0][0]


def group_by_distance(hops_per_node, max_hops=None):
    groups = defaultdict(list)
    for node, h in hops_per_node.items():
        d = min(h)
        if max_hops is not None and d > max_hops:
            continue
        groups[d].append(node)
    return {d: sorted(nodes) for d, nodes in sorted(groups.items())}


def write_csv_nodes(path, hops_per_node, groups, my_node):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["node_id", "min_hops", "median_hops", "avg_hops", "packet_count", "is_me"])
        for d in groups:
            for node in groups[d]:
                h = hops_per_node[node]
                w.writerow([node, d, median(h), round(mean(h), 2), len(h), int(node == my_node)])


def write_csv_summary(path, groups):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["hop_distance", "node_count"])
        for d in groups:
            w.writerow([d, len(groups[d])])


def plot(groups, path="hops.png"):
    import matplotlib.pyplot as plt  # nur importieren wenn gebraucht

    xs = list(groups.keys())
    ys = [len(groups[d]) for d in xs]
    plt.bar(xs, ys)
    plt.xlabel("minimale Hop-Distanz")
    plt.ylabel("Anzahl Nodes")
    plt.title("Nodes nach Hop-Distanz")
    plt.xticks(xs)
    plt.savefig(path, dpi=120, bbox_inches="tight")
    print("Plot gespeichert:", path)


def main():
    args = parse_args()

    hops_per_node, negative = load_hops(args.db, args.with_mqtt)
    total = len(hops_per_node)

    # Nodes mit sehr wenigen Paketen rausfiltern.
    # In den Rohdaten gibt es tausende IDs die nur 1x vorkommen,
    # das sind fast sicher kaputte Pakete und keine echten Geräte.
    hops_per_node = {n: h for n, h in hops_per_node.items() if len(h) >= args.min_packets}

    my_node = guess_my_node_id(hops_per_node)
    groups = group_by_distance(hops_per_node, args.max_hops)

    print(f"DB: {args.db}")
    print(f"Pakete mit negativer Distanz ignoriert: {negative}")
    print(f"Nodes gesamt: {total}, davon mit >= {args.min_packets} Paketen: {len(hops_per_node)}")
    if my_node is not None:
        print(f"Vermutlich eigener Node: {my_node} ({len(hops_per_node[my_node])} Pakete)")
    print()
    print("Hops | Nodes")
    for d in groups:
        print(f"{d:>4} | {len(groups[d])}")

    write_csv_nodes(args.csv, hops_per_node, groups, my_node)
    write_csv_summary(args.summary, groups)
    print(f"\nCSV geschrieben: {args.csv}, {args.summary}")

    if args.plot:
        plot(groups)


if __name__ == "__main__":
    main()

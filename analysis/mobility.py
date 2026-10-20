#!/usr/bin/env python3
"""
Grobe Schätzung welche Nodes mobil sind.

Idee: Geräte die sich bewegen schicken öfter POSITION_APP Pakete
(Smart Position Broadcast), feste Nodes eher selten.
Das ist nur eine Heuristik, echte Bewegung wird nicht geprüft.
"""

import sqlite3
import argparse


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("db")
    ap.add_argument("--min", type=int, default=5, help="minimale Anzahl Positionspakete")
    ap.add_argument("--top", type=int, default=20)
    args = ap.parse_args()

    con = sqlite3.connect(args.db)
    cur = con.cursor()

    # Anzahl POSITION_APP Pakete pro Node
    cur.execute("""
        SELECT "from", COUNT(*) AS cnt
        FROM rawpackets
        WHERE port = 'POSITION_APP' AND mqtt = 0
        GROUP BY "from"
        HAVING cnt >= ?
        ORDER BY cnt DESC
    """, (args.min,))
    rows = cur.fetchall()
    con.close()

    print("Node-Mobilität (Heuristik über POSITION_APP)")
    print("=" * 45)
    for node, count in rows[:args.top]:
        print(f"Node {node:>10} | Positionspakete: {count}")
    print(f"\n{len(rows)} Nodes mit >= {args.min} Positionspaketen")


if __name__ == "__main__":
    main()

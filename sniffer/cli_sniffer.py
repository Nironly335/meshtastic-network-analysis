"""
CLI-Sniffer fuer Meshtastic.

Startet `meshtastic --listen` als Subprozess, sucht in jeder Zeile nach
JSON/dict-Strukturen und speichert die Pakete fuer spaetere Auswertung.

Ausgabe (im Ordner --out):
  packets.log       - alle erkannten Pakete, eine JSON-Zeile pro Paket
  unique_nodes.txt  - alle bisher gesehenen Nodes
  airutil.csv       - airUtilTx Werte aus Telemetrie-Paketen

Beispiel:
  python cli_sniffer.py --port COM3 --out ./logs
"""

import sys
import subprocess
import json
import re
import ast
import time
import os
import argparse
from datetime import datetime
from typing import Optional


# Muster für Logzeilen, die meist uninteressant sind
IGNORE_PATTERNS = [
    re.compile(r"\bVERBOSE\b", re.IGNORECASE),
    re.compile(r"\bDEBUG\b", re.IGNORECASE),
    re.compile(r"fromRadioBytes", re.IGNORECASE),
    re.compile(r"Unexpected FromRadio payload", re.IGNORECASE),
]

unique_nodes = {}


def parse_args():
    ap = argparse.ArgumentParser(description="Meshtastic CLI Sniffer")
    ap.add_argument("--port", help="Serieller Port, z.B. COM3 oder /dev/ttyACM0 (sonst automatisch)")
    ap.add_argument("--out", default=".", help="Ordner fuer Logdateien")
    return ap.parse_args()


def write_unique_nodes_file(path):
    """Schreibt die Liste der eindeutigen Nodes in eine Datei."""
    try:
        with open(path, "w", encoding="utf-8") as fh:
            for k, v in unique_nodes.items():
                fh.write(f"{k} | {v}\n")
    except OSError as e:
        print("unique_nodes konnte nicht geschrieben werden:", e)


def find_balanced_braced_substring(s: str) -> Optional[str]:
    """
    Findet die erste ausgeglichene Teilzeichenkette, die mit { oder [ beginnt.
    Berücksichtigt Anführungszeichen und Escape-Sequenzen.
    """
    start_idx = None
    for i, ch in enumerate(s):
        if ch in "{[":
            start_idx = i
            break
    if start_idx is None:
        return None

    stack = []
    in_quote = None
    esc = False
    for i in range(start_idx, len(s)):
        ch = s[i]
        if esc:
            esc = False
            continue
        if ch == "\\":
            esc = True
            continue
        if in_quote:
            if ch == in_quote:
                in_quote = None
            continue
        if ch == '"' or ch == "'":
            in_quote = ch
            continue
        if ch in "{[":
            stack.append(ch)
        elif ch in "}]":
            if not stack:
                return None
            opening = stack.pop()
            if (opening == "{" and ch != "}") or (opening == "[" and ch != "]"):
                return None
            if not stack:
                return s[start_idx:i + 1]
    return None


def try_parse_substring(subs: str):
    """Versucht zuerst JSON zu parsen, dann Python-Literal (die CLI gibt oft dicts mit ' aus)."""
    if not subs:
        return None
    try:
        return json.loads(subs)
    except ValueError:
        pass
    try:
        return ast.literal_eval(subs)
    except (ValueError, SyntaxError):
        return None


def extract_node_key_and_summary(pkt) -> Optional[tuple]:
    """
    Extrahiert die Node-ID und eine kurze Zusammenfassung.
    Gibt (Schlüssel, Text) zurück oder None, wenn kein Nodeinfo-Paket.
    """
    if not isinstance(pkt, dict):
        return None

    user = pkt.get("user") or {}
    if not isinstance(user, dict):
        user = {}

    node_id = user.get("id") or user.get("id_str") or pkt.get("num") or pkt.get("nodeId")
    if node_id is None:
        return None

    # die Feldnamen sind je nach Version unterschiedlich (camelCase / snake_case)
    long_name = user.get("longName") or user.get("long_name")
    short_name = user.get("shortName") or user.get("short_name")
    hw = user.get("hwModel") or user.get("hw_model")
    num = pkt.get("num")

    parts = []
    if long_name:
        parts.append(f"name={long_name}")
    if short_name:
        parts.append(f"short={short_name}")
    if num is not None:
        parts.append(f"num={num}")
    if hw:
        parts.append(f"hw={hw}")
    # Position und MAC lasse ich hier bewusst weg (Datenschutz),
    # die stehen sowieso komplett in packets.log

    summary = " | ".join(parts) if parts else str(pkt)
    return str(node_id), summary


def classify_packet(pkt: dict) -> str:
    """Klassifiziert ein Paket in eine der Hauptgruppen."""
    if not isinstance(pkt, dict):
        return "unbekannt"
    if "user" in pkt:
        return "nodeinfo"
    if "decoded" in pkt:
        return "decoded"
    if "encrypted" in pkt:
        return "encrypted"
    if "hopLimit" in pkt or "rxSnr" in pkt:
        return "routing"
    return "unbekannt"


def handle_packet(pkt: dict):
    """Gibt den Pakettyp auf der Konsole aus."""
    typ = classify_packet(pkt)

    if typ == "nodeinfo":
        print("Paket-Typ: NodeInfo")
    elif typ == "decoded":
        decoded = pkt.get("decoded") or {}
        print(f"Paket-Typ: Decoded (Port={decoded.get('portnum')})")
    elif typ == "encrypted":
        print(f"Paket-Typ: Verschlüsselt (Channel={pkt.get('channel')})")
    elif typ == "routing":
        print(f"Routing-Paket: SNR={pkt.get('rxSnr')}, HopLimit={pkt.get('hopLimit')}")
    else:
        print("Unbekanntes Paket erkannt.")


def _find_telemetry_dict(pkt: dict):
    """
    Telemetrie kann an verschiedenen Stellen im Paket stehen.
    Rückgabe: dict oder None
    """
    if not isinstance(pkt, dict):
        return None

    telemetry = pkt.get("telemetry")
    if isinstance(telemetry, dict):
        return telemetry

    decoded = pkt.get("decoded")
    if isinstance(decoded, dict):
        telemetry = decoded.get("telemetry")
        if isinstance(telemetry, dict):
            return telemetry

        payload = decoded.get("payload")
        if isinstance(payload, dict):
            telemetry = payload.get("telemetry")
            if isinstance(telemetry, dict):
                return telemetry

    return None


def save_air_util(csv_path, air_value):
    ts = int(time.time())
    dt = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    with open(csv_path, "a", encoding="utf-8") as f:
        f.write(f"{dt};{ts};{air_value}\n")


def handle_air_util(pkt: dict, csv_path):
    """Sucht airUtilTx in Telemetrie-Paketen und speichert den Wert."""
    telemetry = _find_telemetry_dict(pkt)
    if not telemetry:
        return

    metrics = telemetry.get("deviceMetrics") or telemetry.get("localStats")
    if not isinstance(metrics, dict):
        return

    air_value = metrics.get("airUtilTx")
    if air_value is None:
        return

    save_air_util(csv_path, air_value)
    print(f"airUtilTx erkannt: {air_value}")


def main():
    args = parse_args()
    os.makedirs(args.out, exist_ok=True)

    packet_log = os.path.join(args.out, "packets.log")
    nodes_file = os.path.join(args.out, "unique_nodes.txt")
    airutil_csv = os.path.join(args.out, "airutil.csv")

    # CSV-Header erstellen, falls Datei noch nicht existiert
    if not os.path.exists(airutil_csv):
        with open(airutil_csv, "w", encoding="utf-8") as f:
            f.write("datetime;timestamp;air_util\n")

    cmd = [sys.executable, "-m", "meshtastic", "--listen"]
    if args.port:
        cmd += ["--port", args.port]

    print("Starte:", " ".join(cmd))
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    print("Höre auf Pakete... (Ctrl+C zum Beenden)\n")

    packet_fh = open(packet_log, "a", encoding="utf-8")

    try:
        for raw_line in process.stdout:
            line = raw_line.strip()
            if not line:
                continue

            # Versuche JSON/Python-Struktur aus der Zeile zu extrahieren
            braced = find_balanced_braced_substring(line)
            pkt = try_parse_substring(braced) if braced else None

            if pkt is not None:
                # default=str weil manchmal bytes drin sind
                packet_fh.write(json.dumps(pkt, ensure_ascii=False, default=str) + "\n")
                packet_fh.flush()

                handle_packet(pkt)
                handle_air_util(pkt, airutil_csv)

                node_info = extract_node_key_and_summary(pkt)
                if node_info:
                    key, summary = node_info
                    if key not in unique_nodes:
                        unique_nodes[key] = summary
                        write_unique_nodes_file(nodes_file)
                        print(f"Neuer Node: {key} | {summary}")
                continue

            # manche Werte kommen nur als Text, nicht als dict
            m = re.search(r"air_util_tx:\s*([0-9.]+)", line)
            if m:
                save_air_util(airutil_csv, float(m.group(1)))
                print(f"air_util_tx (TEXT): {m.group(1)}")
                continue

            if any(p.search(line) for p in IGNORE_PATTERNS):
                continue

            if "Connected to" in line or re.search(r"\bPacket\b|RX:|TX:", line, re.IGNORECASE):
                print(line)

    except KeyboardInterrupt:
        print("\nGestoppt.")
    finally:
        write_unique_nodes_file(nodes_file)
        packet_fh.close()
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()


if __name__ == "__main__":
    main()

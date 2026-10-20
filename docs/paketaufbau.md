# Notizen: Aufbau eines Meshtastic-Pakets

Meine Notizen während dem Projekt, damit ich die Daten in der DB verstehe.

## Ebenen

| Ebene | Was |
|---|---|
| Physisch | LoRa Funksignal |
| Header | 16 Byte: to, from, id, flags, channel hash, next hop, relay node |
| Daten | `Data` Protobuf (portnum + payload), verschlüsselt |
| Anwendung | je nach Port: Text, Position, Telemetrie, NodeInfo ... |

Zwischen Gerät und PC (seriell / Bluetooth) laufen `ToRadio` und `FromRadio`
Protobufs, über Funk geht das `MeshPacket`.

## Flags-Byte im Header

```
bit 0-2  hopLimit   (wie viele Hops noch übrig)
bit 3    wantAck
bit 4    viaMqtt
bit 5-7  hopStart   (Limit beim Absender)
```

Daraus: **gemachte Hops = hopStart - hopLimit**. Das benutze ich in `analysis/hops.py`.

## Verschlüsselung

AES-CTR. Der Default-Kanal (LongFast) benutzt einen bekannten Standard-Key
(16 Byte = AES-128), deshalb kann man Pakete auf dem Standardkanal mitlesen.
Eigene Kanäle mit 32-Byte-PSK sind AES-256. Nonce = Paket-ID + Absender-ID.

## Felder in NodeInfo (Beispiel aus `meshtastic --nodes`)

| Feld | Bedeutung |
|---|---|
| `num` | numerische Node-ID |
| `user.id` | gleiche ID als Hex, z.B. `!7ed2361c` |
| `user.longName` / `shortName` | Name des Geräts (short = 4 Zeichen fürs Display) |
| `user.hwModel` | Hardware, z.B. `TBEAM`, `T_ECHO` |
| `position.latitudeI` | Koordinate × 1e7 als Integer (spart Bytes) |
| `snr` | Signal-Rausch-Abstand, höher = besser |
| `lastHeard` | Unix-Zeit, wann zuletzt gehört |
| `deviceMetrics.channelUtilization` | wie stark der Kanal insgesamt belegt ist (%) |
| `deviceMetrics.airUtilTx` | wie viel % der Zeit das Gerät selbst sendet |
| `hopsAway` | Hops bis zu diesem Node |

Quelle: https://meshtastic.org/docs/overview/mesh-algo

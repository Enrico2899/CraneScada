"""
Script di test: connessione reale al PLC e misura della latenza di
db_read, per calibrare FAST_POLL_INTERVAL_S in config.py (vedi CLAUDE.md).

Uso:
    python scripts/test_plc_latency.py [N_LETTURE]

Da lanciare dalla root del progetto (deve poter importare `config` e
`plc_comm`).
"""

import dataclasses
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from plc_comm.s7_client import PLCClient, PLCConnectionError

DEFAULT_N_READS = 200


def main() -> None:
    n_reads = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_N_READS

    client = PLCClient(
        ip=config.PLC_IP,
        rack=config.PLC_RACK,
        slot=config.PLC_SLOT,
        db_number=config.PLC_DB_NUMBER,
        db_size=config.PLC_DB_SIZE,
    )

    print(f"Connessione a {config.PLC_IP} (rack={config.PLC_RACK}, slot={config.PLC_SLOT})...")
    try:
        client.connect()
    except PLCConnectionError as exc:
        print(f"ERRORE: {exc}")
        print(
            "Se l'errore riguarda una libreria non trovata, verifica che la "
            "libreria nativa Snap7 (.dll su Windows) sia installata sul sistema, "
            "non solo il pacchetto pip python-snap7."
        )
        sys.exit(1)

    print(f"Connesso. Eseguo {n_reads} letture del DB {config.PLC_DB_NUMBER}...")

    durations_ms = []
    last_cycle_counter = None
    last_snapshot = None
    try:
        for i in range(n_reads):
            start = time.perf_counter()
            try:
                snapshot = client.read_snapshot()
            except PLCConnectionError as exc:
                print(f"Lettura #{i} fallita: {exc}")
                break
            durations_ms.append((time.perf_counter() - start) * 1000)

            if last_cycle_counter is not None and snapshot.cycle_counter == last_cycle_counter:
                print(f"  (lettura #{i}: CycleCounter invariato, {snapshot.cycle_counter})")
            last_cycle_counter = snapshot.cycle_counter
            last_snapshot = snapshot
    finally:
        client.disconnect()

    if not durations_ms:
        print("Nessuna lettura completata con successo.")
        sys.exit(1)

    print()
    print(f"Letture completate: {len(durations_ms)}/{n_reads}")
    print(f"  media:   {statistics.mean(durations_ms):.2f} ms")
    print(f"  mediana: {statistics.median(durations_ms):.2f} ms")
    print(f"  min:     {min(durations_ms):.2f} ms")
    print(f"  max:     {max(durations_ms):.2f} ms")
    if len(durations_ms) > 1:
        print(f"  stdev:   {statistics.stdev(durations_ms):.2f} ms")

    print()
    print("Ultima lettura (confronta questi valori con quelli attesi/reali in TIA Portal):")
    for field in dataclasses.fields(last_snapshot):
        print(f"  {field.name:22s} = {getattr(last_snapshot, field.name)}")


if __name__ == "__main__":
    main()

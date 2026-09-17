"""
Configurazione centrale dell'applicazione.
Modificare i valori qui sotto con i parametri reali del proprio impianto.
"""

# --- Connessione PLC ---
PLC_IP = "192.168.0.1"      # TODO: IP reale del PLC (DPC8O4_Cr511 / HX00S01+A301-1023E1)
PLC_RACK = 0                 # TODO: verificare rack reale
PLC_SLOT = 1                 # TODO: verificare slot reale (CPU 1515F-2 PN)

# --- DB export (Q3_DB / DB7901) ---
PLC_DB_NUMBER = 7901
PLC_DB_SIZE = 82             # byte totali del DB (offset 78.0 + 4 byte del REAL finale)

# --- Polling ---
FAST_POLL_INTERVAL_S = 0.1   # loop veloce: posizione/velocità (DA CALIBRARE, vedi CLAUDE.md)
SLOW_POLL_INTERVAL_S = 0.5   # loop lento: stato macchina, step, mission info

# Quante letture consecutive di CycleCounter invariato prima di considerare
# il PLC offline/fermo (soglia dell'heartbeat)
HEARTBEAT_STALE_THRESHOLD = 4

# --- Storage ---
SQLITE_DB_PATH = "data/crane_history.sqlite"

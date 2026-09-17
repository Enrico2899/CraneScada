"""
Wrapper SQLite per la storicizzazione dei dati letti dal PLC.

Schema:
  missions  → una riga per ogni missione osservata (aperta quando
              mission_id cambia e mission_active diventa True, chiusa
              quando torna False)
  samples   → una riga per ogni campionamento del loop veloce (posizione)
  events    → una riga per ogni evento discreto rilevato (edge detection
              su step/allarmi/cambio modalità, ecc. — vedi CLAUDE.md)

NOTA: schema iniziale, pensato per essere esteso senza rompere i dati
già raccolti (nuove colonne con default, non modifiche a quelle esistenti).
"""

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS missions (
    mission_id          INTEGER PRIMARY KEY,
    task_type           INTEGER,
    operating_mode      INTEGER,
    started_at          TEXT,       -- timestamp PC (ISO 8601), riferimento umano
    ended_at            TEXT,
    start_cycle_counter INTEGER,    -- riferimento temporale lato PLC
    end_cycle_counter   INTEGER,
    target_pickup_x     REAL,
    target_pickup_y     REAL,
    target_pickup_z     REAL,
    target_deposit_x    REAL,
    target_deposit_y    REAL,
    target_deposit_z    REAL
);

CREATE TABLE IF NOT EXISTS samples (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    mission_id      INTEGER,
    cycle_counter   INTEGER NOT NULL,   -- riferimento temporale primario
    recorded_at     TEXT NOT NULL,      -- timestamp PC, secondario/diagnostico
    pos_x           REAL,
    pos_y           REAL,
    pos_z           REAL,
    step_number     INTEGER,
    lifted_weight   REAL,
    FOREIGN KEY (mission_id) REFERENCES missions (mission_id)
);
CREATE INDEX IF NOT EXISTS idx_samples_mission ON samples (mission_id);

CREATE TABLE IF NOT EXISTS events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    mission_id      INTEGER,
    cycle_counter   INTEGER NOT NULL,
    recorded_at     TEXT NOT NULL,
    event_type      TEXT NOT NULL,      -- es. 'step_change', 'mode_change', 'alarm'
    detail          TEXT,               -- es. valore vecchio/nuovo, in formato libero/JSON
    FOREIGN KEY (mission_id) REFERENCES missions (mission_id)
);
CREATE INDEX IF NOT EXISTS idx_events_mission ON events (mission_id);
"""


class Database:
    def __init__(self, db_path: str):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # --- TODO: implementare le funzioni di scrittura vere e proprie ---
    #
    # def start_mission(self, snapshot: CraneSnapshot) -> None: ...
    # def end_mission(self, mission_id: int, snapshot: CraneSnapshot) -> None: ...
    # def insert_sample(self, snapshot: CraneSnapshot) -> None: ...
    # def insert_event(self, mission_id, cycle_counter, event_type, detail) -> None: ...
    #
    # Da progettare insieme quando si collega storage a plc_comm in main.py:
    # es. come si rileva "inizio missione" (mission_active passa da False a
    # True? cambio di mission_id?) e come gestire missioni interrotte senza
    # una vera fine (es. PLC va offline a metà).

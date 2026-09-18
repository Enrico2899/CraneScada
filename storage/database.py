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

from plc_comm.db_mapping import CraneSnapshot

SCHEMA = """
CREATE TABLE IF NOT EXISTS missions (
    mission_id          INTEGER PRIMARY KEY,
    task_type           INTEGER,
    operating_mode      INTEGER,
    started_at          TEXT,       -- timestamp PC (ISO 8601), riferimento umano
    ended_at            TEXT,
    start_cycle_counter INTEGER,    -- riferimento temporale lato PLC
    end_cycle_counter   INTEGER,
    status              TEXT NOT NULL DEFAULT 'active',  -- 'active' | 'completed' | 'interrupted'
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

    def start_mission(self, snapshot: CraneSnapshot, started_at: str) -> None:
        """
        Apre una nuova riga in missions. Il chiamante (main.py) decide quando
        chiamarla: mission_id != 0 e diverso dal mission_id precedente.
        """
        self._conn.execute(
            """
            INSERT INTO missions (
                mission_id, task_type, operating_mode, started_at,
                start_cycle_counter, status,
                target_pickup_x, target_pickup_y, target_pickup_z,
                target_deposit_x, target_deposit_y, target_deposit_z
            ) VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot.mission_id,
                snapshot.task_type,
                snapshot.operating_mode,
                started_at,
                snapshot.cycle_counter,
                snapshot.target_pickup_x,
                snapshot.target_pickup_y,
                snapshot.target_pickup_z,
                snapshot.target_deposit_x,
                snapshot.target_deposit_y,
                snapshot.target_deposit_z,
            ),
        )
        self._conn.commit()

    def end_mission(
        self, mission_id: int, snapshot: CraneSnapshot, ended_at: str, interrupted: bool = False
    ) -> None:
        """
        Chiude una missione aperta. Il chiamante (main.py) decide quando:
        mission_id cambia rispetto al precedente (fine "pulita"), oppure il
        PLC risulta offline (is_plc_alive() == False) con una missione ancora
        aperta (fine anomala, interrupted=True).
        """
        self._conn.execute(
            """
            UPDATE missions
            SET ended_at = ?, end_cycle_counter = ?, status = ?
            WHERE mission_id = ?
            """,
            (
                ended_at,
                snapshot.cycle_counter,
                "interrupted" if interrupted else "completed",
                mission_id,
            ),
        )
        self._conn.commit()

    def insert_sample(self, mission_id: int | None, snapshot: CraneSnapshot, recorded_at: str) -> None:
        """mission_id è None quando non c'è una missione attiva (mission_id PLC == 0)."""
        self._conn.execute(
            """
            INSERT INTO samples (
                mission_id, cycle_counter, recorded_at, pos_x, pos_y, pos_z,
                step_number, lifted_weight
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                mission_id,
                snapshot.cycle_counter,
                recorded_at,
                snapshot.pos_x,
                snapshot.pos_y,
                snapshot.pos_z,
                snapshot.step_number,
                snapshot.lifted_weight,
            ),
        )
        self._conn.commit()

    def insert_event(
        self, mission_id: int | None, cycle_counter: int, event_type: str, detail: str, recorded_at: str
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO events (mission_id, cycle_counter, recorded_at, event_type, detail)
            VALUES (?, ?, ?, ?, ?)
            """,
            (mission_id, cycle_counter, recorded_at, event_type, detail),
        )
        self._conn.commit()

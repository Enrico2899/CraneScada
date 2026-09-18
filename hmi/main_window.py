"""
Finestra principale dell'HMI.

Due timer separati (vedi CLAUDE.md, "due loop di polling separati"):
- loop veloce (FAST_POLL_INTERVAL_S): fa l'UNICA vera lettura del PLC — il
  DB è letto per intero in un colpo solo, non esiste ancora una lettura
  parziale (vedi TODO in plc_comm/s7_client.py). Aggiorna la posizione,
  salva un sample, e fa l'edge detection di step/modalità/eventi discreti/
  cambio missione (vedi CLAUDE.md: gli eventi discreti si rilevano per
  edge detection nel loop veloce, non con un polling dedicato).
- loop lento (SLOW_POLL_INTERVAL_S): non fa una lettura propria, si limita
  a rinfrescare le label di stato/step/mission dall'ultimo snapshot già
  letto dal loop veloce.
"""

from datetime import datetime, timezone

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QGridLayout, QLabel, QMainWindow, QWidget

from plc_comm.db_mapping import CraneSnapshot
from plc_comm.s7_client import PLCClient, PLCConnectionError
from storage.database import Database

# Campi discreti su cui fare edge detection nel loop veloce (vedi CLAUDE.md)
_DISCRETE_EVENT_FIELDS = [
    "mission_active",
    "mission_pause",
    "waiting_interaction",
    "movement_detected",
    "pickup_active",
    "deposit_active",
]


def _mission_id_or_none(mission_id: int) -> int | None:
    return mission_id if mission_id != 0 else None


class MainWindow(QMainWindow):
    def __init__(
        self,
        plc_client: PLCClient,
        database: Database,
        fast_poll_interval_s: float,
        slow_poll_interval_s: float,
        heartbeat_stale_threshold: int,
    ):
        super().__init__()
        self.setWindowTitle("Crane HMI/SCADA Logger")

        self._plc_client = plc_client
        self._database = database
        self._heartbeat_stale_threshold = heartbeat_stale_threshold

        self._last_snapshot: CraneSnapshot | None = None
        self._open_mission_id: int | None = None
        self._mission_interrupted_handled = False

        self._build_ui()

        self._fast_timer = QTimer(self)
        self._fast_timer.timeout.connect(self._on_fast_poll)
        self._fast_timer.start(int(fast_poll_interval_s * 1000))

        self._slow_timer = QTimer(self)
        self._slow_timer.timeout.connect(self._on_slow_poll)
        self._slow_timer.start(int(slow_poll_interval_s * 1000))

    def _build_ui(self) -> None:
        central = QWidget()
        layout = QGridLayout(central)

        # TODO: sostituire con un layout HMI vero (indicatori, non solo testo)
        self._label_status = QLabel("In attesa di connessione...")
        self._label_position = QLabel("Pos: -, -, -")
        self._label_step = QLabel("Step: -")
        self._label_mode = QLabel("Modalità: -")
        self._label_mission = QLabel("Mission: -")

        layout.addWidget(self._label_status, 0, 0)
        layout.addWidget(self._label_position, 1, 0)
        layout.addWidget(self._label_step, 2, 0)
        layout.addWidget(self._label_mode, 3, 0)
        layout.addWidget(self._label_mission, 4, 0)

        self.setCentralWidget(central)

    def _on_fast_poll(self) -> None:
        try:
            snapshot = self._plc_client.read_snapshot()
        except PLCConnectionError:
            self._label_status.setText("PLC non raggiungibile")
            return

        now = datetime.now(timezone.utc).isoformat()
        alive = self._plc_client.is_plc_alive(self._heartbeat_stale_threshold)

        self._label_status.setText("PLC online" if alive else "PLC offline/fermo (dati stale)")
        self._label_position.setText(
            f"Pos: {snapshot.pos_x:.1f}, {snapshot.pos_y:.1f}, {snapshot.pos_z:.1f}"
        )

        self._handle_mission_transition(snapshot, now)
        self._database.insert_sample(_mission_id_or_none(snapshot.mission_id), snapshot, now)
        self._handle_discrete_events(snapshot, now)
        if not alive:
            self._handle_heartbeat_stale(snapshot, now)

        self._last_snapshot = snapshot

    def _on_slow_poll(self) -> None:
        """Rinfresca solo le label di stato dall'ultimo snapshot già letto dal loop veloce."""
        if self._last_snapshot is None:
            return
        snapshot = self._last_snapshot
        self._label_step.setText(f"Step: {snapshot.step_number}")
        self._label_mode.setText(f"Modalità: {snapshot.operating_mode}")
        mission_text = str(snapshot.mission_id) if snapshot.mission_id != 0 else "-"
        self._label_mission.setText(f"Mission: {mission_text}")

    def _handle_mission_transition(self, snapshot: CraneSnapshot, now: str) -> None:
        """
        Apre/chiude una missione quando mission_id cambia (0 = nessuna
        missione attiva). Usa _open_mission_id (non il mission_id della
        lettura precedente) per decidere se c'è una riga da chiudere, così
        una missione già chiusa da _handle_heartbeat_stale non viene
        richiusa/sovrascritta qui come 'completed'.
        """
        previous = self._last_snapshot
        previous_mission_id = previous.mission_id if previous is not None else 0
        if snapshot.mission_id == previous_mission_id:
            return

        if self._open_mission_id is not None:
            self._database.end_mission(self._open_mission_id, previous, now, interrupted=False)
            self._open_mission_id = None

        if snapshot.mission_id != 0:
            # NOTA: se l'app parte a missione già in corso, started_at/
            # start_cycle_counter riflettono il primo poll dell'app, non il
            # vero inizio missione sul PLC.
            self._database.start_mission(snapshot, now)
            self._open_mission_id = snapshot.mission_id
            self._mission_interrupted_handled = False

    def _handle_discrete_events(self, snapshot: CraneSnapshot, now: str) -> None:
        previous = self._last_snapshot
        if previous is None:
            return
        mission_id = _mission_id_or_none(snapshot.mission_id)

        if snapshot.step_number != previous.step_number:
            self._database.insert_event(
                mission_id,
                snapshot.cycle_counter,
                "step_change",
                f"{previous.step_number} -> {snapshot.step_number}",
                now,
            )
        if snapshot.operating_mode != previous.operating_mode:
            self._database.insert_event(
                mission_id,
                snapshot.cycle_counter,
                "mode_change",
                f"{previous.operating_mode} -> {snapshot.operating_mode}",
                now,
            )
        for field_name in _DISCRETE_EVENT_FIELDS:
            old_value = getattr(previous, field_name)
            new_value = getattr(snapshot, field_name)
            if new_value != old_value:
                self._database.insert_event(
                    mission_id,
                    snapshot.cycle_counter,
                    field_name,
                    f"{old_value} -> {new_value}",
                    now,
                )

    def _handle_heartbeat_stale(self, snapshot: CraneSnapshot, now: str) -> None:
        """
        Chiude come 'interrupted' una missione ancora aperta quando il PLC
        risulta offline/fermo. NOTA: se il PLC torna online con la STESSA
        mission_id ancora attiva (missione ripresa, non nuova), questa
        implementazione non riapre la riga già chiusa — è un caso limite
        non gestito per ora, da rivalutare se si presenta in pratica.
        """
        if self._open_mission_id is None or self._mission_interrupted_handled:
            return
        self._database.end_mission(self._open_mission_id, snapshot, now, interrupted=True)
        self._mission_interrupted_handled = True
        self._open_mission_id = None

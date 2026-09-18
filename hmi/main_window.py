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

La finestra possiede anche il ciclo di vita della connessione PLC: un
campo IP + pulsante "Connetti" permettono di (ri)connettersi senza
riavviare l'app. L'ultimo IP usato con successo viene salvato in un file
locale e riproposto al prossimo avvio.
"""

import logging
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import pyqtgraph as pg
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QWidget,
)

from plc_comm.db_mapping import CraneSnapshot
from plc_comm.s7_client import PLCClient, PLCConnectionError
from storage.database import Database

logger = logging.getLogger(__name__)

# Campi discreti su cui fare edge detection nel loop veloce (vedi CLAUDE.md)
_DISCRETE_EVENT_FIELDS = [
    "mission_active",
    "mission_pause",
    "waiting_interaction",
    "movement_detected",
    "pickup_active",
    "deposit_active",
]

# Quanti campioni tenere nel grafico live (a FAST_POLL_INTERVAL_S=0.1s, 300 ~= 30s)
_PLOT_MAX_POINTS = 300


def _mission_id_or_none(mission_id: int) -> int | None:
    return mission_id if mission_id != 0 else None


def _load_last_ip(path: Path, default_ip: str) -> str:
    try:
        saved = path.read_text(encoding="utf-8").strip()
    except OSError:
        return default_ip
    return saved or default_ip


def _save_last_ip(path: Path, ip: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(ip, encoding="utf-8")


class MainWindow(QMainWindow):
    def __init__(
        self,
        database: Database,
        default_plc_ip: str,
        plc_rack: int,
        plc_slot: int,
        plc_db_number: int,
        plc_db_size: int,
        fast_poll_interval_s: float,
        slow_poll_interval_s: float,
        heartbeat_stale_threshold: int,
        last_ip_file: Path,
    ):
        super().__init__()
        self.setWindowTitle("Crane HMI/SCADA Logger")

        self._database = database
        self._plc_rack = plc_rack
        self._plc_slot = plc_slot
        self._plc_db_number = plc_db_number
        self._plc_db_size = plc_db_size
        self._heartbeat_stale_threshold = heartbeat_stale_threshold
        self._last_ip_file = last_ip_file
        self._fast_poll_interval_ms = int(fast_poll_interval_s * 1000)
        self._slow_poll_interval_ms = int(slow_poll_interval_s * 1000)

        self._plc_client: PLCClient | None = None
        self._last_snapshot: CraneSnapshot | None = None
        self._open_mission_id: int | None = None
        self._mission_interrupted_handled = False

        self._plot_start_time = time.monotonic()
        self._plot_times: deque[float] = deque(maxlen=_PLOT_MAX_POINTS)
        self._plot_pos_x: deque[float] = deque(maxlen=_PLOT_MAX_POINTS)
        self._plot_pos_y: deque[float] = deque(maxlen=_PLOT_MAX_POINTS)
        self._plot_pos_z: deque[float] = deque(maxlen=_PLOT_MAX_POINTS)

        self._build_ui(_load_last_ip(last_ip_file, default_plc_ip))

        self._fast_timer = QTimer(self)
        self._fast_timer.timeout.connect(self._on_fast_poll)
        self._slow_timer = QTimer(self)
        self._slow_timer.timeout.connect(self._on_slow_poll)

        self._on_connect_clicked()  # prova a connettersi subito con l'IP precompilato

    def _build_ui(self, default_ip: str) -> None:
        central = QWidget()
        layout = QGridLayout(central)

        connection_row = QWidget()
        connection_layout = QHBoxLayout(connection_row)
        connection_layout.setContentsMargins(0, 0, 0, 0)
        self._ip_input = QLineEdit(default_ip)
        self._connect_button = QPushButton("Connetti")
        self._connect_button.clicked.connect(self._on_connect_clicked)
        connection_layout.addWidget(QLabel("IP PLC:"))
        connection_layout.addWidget(self._ip_input)
        connection_layout.addWidget(self._connect_button)

        # TODO: sostituire le label con indicatori HMI veri (LED colorati, ecc.)
        self._label_status = QLabel("In attesa di connessione...")
        self._label_position = QLabel("Pos: -, -, -")
        self._label_step = QLabel("Step: -")
        self._label_mode = QLabel("Modalità: -")
        self._label_mission = QLabel("Mission: -")

        self._position_plot = pg.PlotWidget(title="Posizione gru nel tempo")
        self._position_plot.setLabel("bottom", "Tempo", units="s")
        self._position_plot.setLabel("left", "Posizione")
        self._position_plot.addLegend()
        self._position_plot.showGrid(x=True, y=True, alpha=0.3)
        self._position_plot.setMinimumHeight(300)
        self._curve_pos_x = self._position_plot.plot(pen="r", name="X")
        self._curve_pos_y = self._position_plot.plot(pen="g", name="Y")
        self._curve_pos_z = self._position_plot.plot(pen="b", name="Z")

        layout.addWidget(connection_row, 0, 0)
        layout.addWidget(self._label_status, 1, 0)
        layout.addWidget(self._label_position, 2, 0)
        layout.addWidget(self._label_step, 3, 0)
        layout.addWidget(self._label_mode, 4, 0)
        layout.addWidget(self._label_mission, 5, 0)
        layout.addWidget(self._position_plot, 6, 0)

        self.setCentralWidget(central)

    def _on_connect_clicked(self) -> None:
        self._fast_timer.stop()
        self._slow_timer.stop()

        if self._plc_client is not None:
            self._plc_client.disconnect()

        # Riconnettersi (stesso PLC o un altro) mentre una missione è ancora
        # aperta interromperebbe la sua continuità: la chiudiamo come
        # 'interrupted' invece di rischiare di riaprirla con lo stesso
        # mission_id (violazione della PRIMARY KEY in missions).
        if (
            self._open_mission_id is not None
            and not self._mission_interrupted_handled
            and self._last_snapshot is not None
        ):
            now = datetime.now(timezone.utc).isoformat()
            self._database.end_mission(self._open_mission_id, self._last_snapshot, now, interrupted=True)

        self._last_snapshot = None
        self._open_mission_id = None
        self._mission_interrupted_handled = False

        self._plot_start_time = time.monotonic()
        self._plot_times.clear()
        self._plot_pos_x.clear()
        self._plot_pos_y.clear()
        self._plot_pos_z.clear()
        self._curve_pos_x.setData([], [])
        self._curve_pos_y.setData([], [])
        self._curve_pos_z.setData([], [])

        ip = self._ip_input.text().strip()
        if not ip:
            self._label_status.setText("Inserisci un IP valido")
            return

        self._plc_client = PLCClient(
            ip=ip,
            rack=self._plc_rack,
            slot=self._plc_slot,
            db_number=self._plc_db_number,
            db_size=self._plc_db_size,
        )
        self._label_status.setText(f"Connessione a {ip}...")
        try:
            self._plc_client.connect()
        except PLCConnectionError as exc:
            logger.error("Connessione al PLC fallita: %s", exc)
            self._label_status.setText(f"Connessione fallita: {exc}")
            return

        _save_last_ip(self._last_ip_file, ip)
        self._label_status.setText("PLC online")
        self._fast_timer.start(self._fast_poll_interval_ms)
        self._slow_timer.start(self._slow_poll_interval_ms)

    def shutdown(self) -> None:
        self._fast_timer.stop()
        self._slow_timer.stop()
        if self._plc_client is not None:
            self._plc_client.disconnect()

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
        self._update_position_plot(snapshot)

        self._handle_mission_transition(snapshot, now)
        self._database.insert_sample(_mission_id_or_none(snapshot.mission_id), snapshot, now)
        self._handle_discrete_events(snapshot, now)
        if not alive:
            self._handle_heartbeat_stale(snapshot, now)

        self._last_snapshot = snapshot

    def _update_position_plot(self, snapshot: CraneSnapshot) -> None:
        elapsed_s = time.monotonic() - self._plot_start_time
        self._plot_times.append(elapsed_s)
        self._plot_pos_x.append(snapshot.pos_x)
        self._plot_pos_y.append(snapshot.pos_y)
        self._plot_pos_z.append(snapshot.pos_z)

        times = list(self._plot_times)
        self._curve_pos_x.setData(times, list(self._plot_pos_x))
        self._curve_pos_y.setData(times, list(self._plot_pos_y))
        self._curve_pos_z.setData(times, list(self._plot_pos_z))

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

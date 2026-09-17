"""
Finestra principale dell'HMI.

Scheletro minimale: al momento mostra solo i valori live in label di testo,
polling tramite QTimer. Da qui si parte per costruire progressivamente:
- indicatori grafici di stato (led colorati per allarmi/heartbeat)
- vista sinottica con posizione della gru
- grafici live (pyqtgraph) per posizione/velocità nel tempo

Deliberatamente NON gestisce ancora lo storage (vedi TODO in main.py) —
prima si valida che la lettura live funzioni, poi si aggiunge la
storicizzazione.
"""

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QGridLayout, QLabel, QMainWindow, QWidget

from plc_comm.s7_client import PLCClient, PLCConnectionError


class MainWindow(QMainWindow):
    def __init__(self, plc_client: PLCClient, poll_interval_s: float):
        super().__init__()
        self.setWindowTitle("Crane HMI/SCADA Logger")

        self._plc_client = plc_client
        self._poll_interval_ms = int(poll_interval_s * 1000)

        self._build_ui()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_poll)
        self._timer.start(self._poll_interval_ms)

    def _build_ui(self) -> None:
        central = QWidget()
        layout = QGridLayout(central)

        # TODO: sostituire con un layout HMI vero (indicatori, non solo testo)
        self._label_status = QLabel("In attesa di connessione...")
        self._label_position = QLabel("Pos: -, -, -")
        self._label_step = QLabel("Step: -")
        self._label_mode = QLabel("Modalità: -")

        layout.addWidget(self._label_status, 0, 0)
        layout.addWidget(self._label_position, 1, 0)
        layout.addWidget(self._label_step, 2, 0)
        layout.addWidget(self._label_mode, 3, 0)

        self.setCentralWidget(central)

    def _on_poll(self) -> None:
        try:
            snapshot = self._plc_client.read_snapshot()
        except PLCConnectionError:
            self._label_status.setText("PLC non raggiungibile")
            return

        alive = self._plc_client.is_plc_alive(stale_threshold=4)  # TODO: da config.py
        self._label_status.setText("PLC online" if alive else "PLC offline/fermo (dati stale)")
        self._label_position.setText(
            f"Pos: {snapshot.pos_x:.1f}, {snapshot.pos_y:.1f}, {snapshot.pos_z:.1f}"
        )
        self._label_step.setText(f"Step: {snapshot.step_number}")
        self._label_mode.setText(f"Modalità: {snapshot.operating_mode}")

        # TODO: qui va agganciata la storicizzazione (storage/database.py)
        # e, in futuro, l'edge detection per gli eventi discreti.

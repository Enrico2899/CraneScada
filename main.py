"""
Entry point dell'applicazione.

Wiring minimale: connette al PLC e avvia l'HMI con un unico timer di
polling (usa FAST_POLL_INTERVAL_S per ora). La separazione in loop
veloce/lento e il collegamento allo storage sono i prossimi passi
(vedi CLAUDE.md).
"""

import logging
import sys

from PySide6.QtWidgets import QApplication

import config
from hmi.main_window import MainWindow
from plc_comm.s7_client import PLCClient, PLCConnectionError

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main() -> None:
    plc_client = PLCClient(
        ip=config.PLC_IP,
        rack=config.PLC_RACK,
        slot=config.PLC_SLOT,
        db_number=config.PLC_DB_NUMBER,
        db_size=config.PLC_DB_SIZE,
    )

    try:
        plc_client.connect()
    except PLCConnectionError as exc:
        # TODO: decidere come gestire l'avvio senza PLC raggiungibile —
        # per ora blocca, in futuro potrebbe avviare comunque l'UI e
        # ritentare la connessione in background.
        logger.error("Connessione al PLC fallita: %s", exc)
        sys.exit(1)

    app = QApplication(sys.argv)
    window = MainWindow(plc_client, poll_interval_s=config.FAST_POLL_INTERVAL_S)
    window.show()

    exit_code = app.exec()
    plc_client.disconnect()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()

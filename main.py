"""
Entry point dell'applicazione.

Apre lo storage SQLite e avvia l'HMI, che gestisce internamente la
connessione al PLC (IP impostabile/riconnettibile dall'app — vedi il campo
IP + pulsante Connetti in hmi/main_window.py) e i due loop di polling
veloce/lento.
"""

import logging
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

import config
from hmi.main_window import MainWindow
from storage.database import Database

logging.basicConfig(level=logging.INFO)


def main() -> None:
    database = Database(config.SQLITE_DB_PATH)

    app = QApplication(sys.argv)
    window = MainWindow(
        database,
        default_plc_ip=config.PLC_IP,
        plc_rack=config.PLC_RACK,
        plc_slot=config.PLC_SLOT,
        plc_db_number=config.PLC_DB_NUMBER,
        plc_db_size=config.PLC_DB_SIZE,
        fast_poll_interval_s=config.FAST_POLL_INTERVAL_S,
        slow_poll_interval_s=config.SLOW_POLL_INTERVAL_S,
        heartbeat_stale_threshold=config.HEARTBEAT_STALE_THRESHOLD,
        last_ip_file=Path(config.SQLITE_DB_PATH).parent / "last_plc_ip.txt",
    )
    window.show()

    exit_code = app.exec()
    window.shutdown()
    database.close()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()

"""
Wrapper attorno a python-snap7 per la connessione al PLC e la lettura del
DB export. Gestisce anche il rilevamento "PLC offline" tramite CycleCounter
(vedi CLAUDE.md per la spiegazione del perché non si usa un bit toggle).
"""

import logging

import snap7

from . import db_mapping
from .db_mapping import CraneSnapshot

logger = logging.getLogger(__name__)


class PLCConnectionError(Exception):
    """Sollevata quando la connessione al PLC fallisce o cade."""


class PLCClient:
    def __init__(self, ip: str, rack: int, slot: int, db_number: int, db_size: int):
        self._ip = ip
        self._rack = rack
        self._slot = slot
        self._db_number = db_number
        self._db_size = db_size
        self._client = snap7.client.Client()

        # Stato per il rilevamento di PLC "stale" (offline/fermo)
        self._last_cycle_counter: int | None = None
        self._stale_reads_count = 0

    def connect(self) -> None:
        # TODO: gestire retry/backoff se la connessione fallisce al primo colpo
        try:
            self._client.connect(self._ip, self._rack, self._slot)
        except RuntimeError as exc:
            # snap7 solleva RuntimeError sia per libreria nativa Snap7
            # mancante/non trovata sia per errori TCP (host irraggiungibile,
            # rack/slot sbagliati, ecc.) — il messaggio originale distingue i casi.
            raise PLCConnectionError(
                f"Connessione al PLC {self._ip} fallita: {exc}"
            ) from exc
        if not self._client.get_connected():
            raise PLCConnectionError(f"Impossibile connettersi al PLC {self._ip}")
        logger.info("Connesso al PLC %s (rack=%s, slot=%s)", self._ip, self._rack, self._slot)

    def disconnect(self) -> None:
        self._client.disconnect()

    def is_connected(self) -> bool:
        return self._client.get_connected()

    def read_snapshot(self) -> CraneSnapshot:
        """
        Legge l'intero DB export e lo converte in un CraneSnapshot.

        NOTA: per ora legge tutto il DB in un colpo solo. Se il test di
        latenza (vedi CLAUDE.md, prossimi passi) mostra che è troppo lento
        per il loop veloce, si può valutare di leggere solo il range di
        byte necessario per i campi ad alta frequenza (posizione) con una
        chiamata separata e più leggera.
        """
        try:
            buffer = self._client.db_read(self._db_number, 0, self._db_size)
        except RuntimeError as exc:
            raise PLCConnectionError(f"Lettura del DB {self._db_number} fallita: {exc}") from exc
        snapshot = db_mapping.parse_snapshot(buffer)
        self._update_heartbeat(snapshot.cycle_counter)
        return snapshot

    def _update_heartbeat(self, cycle_counter: int) -> None:
        """
        Aggiorna il conteggio di letture "stale" (CycleCounter invariato).
        Usare is_plc_alive() per sapere se siamo sopra soglia.
        """
        if self._last_cycle_counter is not None and cycle_counter == self._last_cycle_counter:
            self._stale_reads_count += 1
        else:
            self._stale_reads_count = 0
        self._last_cycle_counter = cycle_counter

    def is_plc_alive(self, stale_threshold: int) -> bool:
        """True se il PLC sta scrivendo dati freschi (CycleCounter cambia)."""
        return self._stale_reads_count < stale_threshold

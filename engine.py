"""
Motore di polling/storage indipendente dalla UI, usato dal backend web
(main.py). Porta su asyncio la logica già validata quando l'app era
un'interfaccia desktop PySide6 (rimossa): stessa gestione di missioni,
edge detection sugli eventi discreti, heartbeat — vedi CLAUDE.md.

Il vero (unico) read del PLC avviene qui a cadenza FAST_POLL_INTERVAL_S
(il DB si legge per intero in un colpo solo, non esiste ancora una lettura
parziale — vedi TODO in plc_comm/s7_client.py). Non c'è più bisogno di un
secondo loop "lento": era solo un accorgimento per non ridisegnare i widget
Qt troppo spesso, che non serve trasmettendo dati via websocket a un
browser.
"""

import asyncio
import logging
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from plc_comm.db_mapping import CraneSnapshot
from plc_comm.s7_client import PLCClient, PLCConnectionError
from storage.database import Database

logger = logging.getLogger(__name__)

# Campi discreti su cui fare edge detection ad ogni lettura (vedi CLAUDE.md)
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


def _load_last_ip(path: Path, default_ip: str) -> str:
    try:
        saved = path.read_text(encoding="utf-8").strip()
    except OSError:
        return default_ip
    return saved or default_ip


def _save_last_ip(path: Path, ip: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(ip, encoding="utf-8")


class Engine:
    def __init__(
        self,
        database: Database,
        plc_rack: int,
        plc_slot: int,
        plc_db_number: int,
        plc_db_size: int,
        heartbeat_stale_threshold: int,
        last_ip_file: Path,
    ):
        self._database = database
        self._plc_rack = plc_rack
        self._plc_slot = plc_slot
        self._plc_db_number = plc_db_number
        self._plc_db_size = plc_db_size
        self._heartbeat_stale_threshold = heartbeat_stale_threshold
        self._last_ip_file = last_ip_file

        self._plc_client: PLCClient | None = None
        self._connected = False
        self._status_text = "In attesa di connessione..."

        self._last_snapshot: CraneSnapshot | None = None
        self._open_mission_id: int | None = None
        self._mission_interrupted_handled = False

    def default_ip(self, fallback_ip: str) -> str:
        return _load_last_ip(self._last_ip_file, fallback_ip)

    def status_message(self) -> dict:
        return {"type": "status", "connected": self._connected, "message": self._status_text}

    async def connect(self, ip: str) -> dict:
        if self._plc_client is not None:
            await asyncio.to_thread(self._plc_client.disconnect)
            self._plc_client = None

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

        ip = ip.strip()
        if not ip:
            self._connected = False
            self._status_text = "Inserisci un IP valido"
            return self.status_message()

        client = PLCClient(
            ip=ip,
            rack=self._plc_rack,
            slot=self._plc_slot,
            db_number=self._plc_db_number,
            db_size=self._plc_db_size,
        )
        self._status_text = f"Connessione a {ip}..."
        try:
            await asyncio.to_thread(client.connect)
        except PLCConnectionError as exc:
            logger.error("Connessione al PLC fallita: %s", exc)
            self._connected = False
            self._status_text = f"Connessione fallita: {exc}"
            return self.status_message()

        self._plc_client = client
        self._connected = True
        _save_last_ip(self._last_ip_file, ip)
        self._status_text = "PLC online"
        return self.status_message()

    async def poll_once(self) -> dict | None:
        """Fa una lettura (se connesso), aggiorna storage/stato, e ritorna il
        messaggio da trasmettere via websocket (None se non c'è nulla da
        trasmettere, cioè quando non siamo connessi)."""
        if self._plc_client is None:
            return None

        try:
            snapshot = await asyncio.to_thread(self._plc_client.read_snapshot)
        except PLCConnectionError:
            self._connected = False
            self._status_text = "PLC non raggiungibile"
            return self.status_message()

        now = datetime.now(timezone.utc).isoformat()
        alive = self._plc_client.is_plc_alive(self._heartbeat_stale_threshold)
        self._connected = True
        self._status_text = "PLC online" if alive else "PLC offline/fermo (dati stale)"

        self._handle_mission_transition(snapshot, now)
        self._database.insert_sample(_mission_id_or_none(snapshot.mission_id), snapshot, now)
        self._handle_discrete_events(snapshot, now)
        if not alive:
            self._handle_heartbeat_stale(snapshot, now)

        self._last_snapshot = snapshot

        return {
            "type": "snapshot",
            "connected": True,
            "alive": alive,
            "message": self._status_text,
            "snapshot": asdict(snapshot),
        }

    def shutdown(self) -> None:
        if self._plc_client is not None:
            self._plc_client.disconnect()

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
            # NOTA: se il backend parte a missione già in corso,
            # started_at/start_cycle_counter riflettono il primo poll, non
            # il vero inizio missione sul PLC.
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

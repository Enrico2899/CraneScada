"""
Entry point del backend web (FastAPI). Sostituisce la vecchia app desktop
PySide6: serve la pagina in static/ e trasmette via websocket (/ws) i dati
letti dal PLC, storicizzati in parallelo su SQLite (vedi engine.py).

Ascolta solo su 127.0.0.1 (solo questo PC) — vedi README.md per aprire
l'accesso ad altri dispositivi sulla rete locale.
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import config
from engine import Engine
from storage.database import Database

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"

database = Database(config.SQLITE_DB_PATH)
engine = Engine(
    database=database,
    plc_rack=config.PLC_RACK,
    plc_slot=config.PLC_SLOT,
    plc_db_number=config.PLC_DB_NUMBER,
    plc_db_size=config.PLC_DB_SIZE,
    heartbeat_stale_threshold=config.HEARTBEAT_STALE_THRESHOLD,
    last_ip_file=Path(config.SQLITE_DB_PATH).parent / "last_plc_ip.txt",
)


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self._connections:
            self._connections.remove(websocket)

    async def broadcast(self, message: dict) -> None:
        for websocket in list(self._connections):
            try:
                await websocket.send_json(message)
            except Exception:
                self.disconnect(websocket)


manager = ConnectionManager()


async def _polling_loop() -> None:
    while True:
        message = await engine.poll_once()
        if message is not None:
            await manager.broadcast(message)
        await asyncio.sleep(config.FAST_POLL_INTERVAL_S)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await engine.connect(engine.default_ip(config.PLC_IP))
    polling_task = asyncio.create_task(_polling_loop())
    yield
    polling_task.cancel()
    engine.shutdown()
    database.close()


app = FastAPI(lifespan=lifespan)


class ConnectRequest(BaseModel):
    ip: str


@app.post("/api/connect")
async def api_connect(payload: ConnectRequest) -> dict:
    result = await engine.connect(payload.ip)
    await manager.broadcast(result)
    return result


@app.get("/api/default-ip")
async def api_default_ip() -> dict:
    return {"ip": engine.default_ip(config.PLC_IP)}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await manager.connect(websocket)
    await websocket.send_json(engine.status_message())
    try:
        while True:
            # Non usiamo messaggi in ingresso dal client, solo per rilevare
            # la disconnessione (receive_text solleva WebSocketDisconnect).
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()

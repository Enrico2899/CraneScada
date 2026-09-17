# Crane HMI/SCADA Logger

App locale per leggere in real-time i dati dal PLC della gru (Siemens S7-1500F),
mostrarli in una vista HMI/SCADA live e storicizzarli su SQLite per analisi
successive.

Vedi `CLAUDE.md` per il contesto completo del progetto (decisioni prese,
architettura, prossimi passi) — è pensato per essere letto da Claude Code
all'apertura del progetto.

## Setup

```bash
python -m venv venv
venv\Scripts\activate          # Windows
pip install -r requirements.txt
```

`python-snap7` richiede anche la libreria nativa Snap7 (`.dll`/`.so`) installata
sul sistema — su Windows di solito basta il pacchetto pip, ma se `connect()`
fallisce con errori di libreria mancante, verificare l'installazione della
libreria nativa separatamente.

## Configurazione

Modificare `config.py` con:
- IP, rack, slot del PLC
- Numero del DB (`Q3_DB` = DB7901)
- Intervalli di polling (loop veloce / loop lento)

## Avvio

```bash
python main.py
```

## Stato del progetto

Scheletro iniziale — struttura e firme pronte, logica da completare in
Claude Code, file per file, partendo da `plc_comm/s7_client.py` (test di
connessione al PLC reale).

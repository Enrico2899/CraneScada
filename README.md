# Crane HMI/SCADA Logger

App locale per leggere in real-time i dati dal PLC della gru (Siemens S7-1500F),
mostrarli in una pagina web live (grafico posizione + selezione delle variabili
da monitorare) e storicizzarli su SQLite per analisi successive.

Vedi `CLAUDE.md` per il contesto completo del progetto (decisioni prese,
architettura, prossimi passi) — è pensato per essere letto da Claude Code
all'apertura del progetto.

## Setup

```bash
python -m venv venv
venv\Scripts\activate          # Windows
pip install -r requirements.txt
```

Le versioni recenti di `python-snap7` (>= 2.x) sono una reimplementazione pura
Python: non serve installare nessuna libreria nativa `.dll`/`.so` separata.

## Configurazione

- **IP del PLC**: impostabile direttamente dalla pagina (campo IP + pulsante
  "Connetti"). L'ultimo IP usato con successo viene ricordato tra un avvio e
  l'altro (`data/last_plc_ip.txt`, non versionato). `config.py` fornisce solo
  il valore di default alla prima apertura.
- Rack, slot, numero del DB (`Q3_DB` = DB7901), intervalli di polling: in
  `config.py`.

## Avvio

```bash
python main.py
```

Poi apri **http://127.0.0.1:8000** nel browser. Il server ascolta solo su
questo PC (`127.0.0.1`) — per aprirlo anche ad altri dispositivi sulla stessa
rete locale, cambiare `host="127.0.0.1"` in `host="0.0.0.0"` in `main.py`
(valutare con attenzione, il PLC è su una rete industriale).

## Stato del progetto

Scheletro iniziale iterato con Claude Code: connessione PLC, storage SQLite,
backend FastAPI con polling e websocket, pagina web con grafico live e
selezione delle variabili da monitorare. Vedi `CLAUDE.md` per architettura e
decisioni prese.

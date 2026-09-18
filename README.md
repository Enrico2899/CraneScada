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

Le versioni recenti di `python-snap7` (>= 2.x) sono una reimplementazione pura
Python: non serve installare nessuna libreria nativa `.dll`/`.so` separata.

## Configurazione

- **IP del PLC**: impostabile direttamente dall'app (campo IP + pulsante
  "Connetti" nella finestra principale). L'ultimo IP usato con successo viene
  ricordato tra un avvio e l'altro (`data/last_plc_ip.txt`, non versionato).
  `config.py` fornisce solo il valore di default alla prima apertura.
- Rack, slot, numero del DB (`Q3_DB` = DB7901), intervalli di polling: in
  `config.py`.

## Avvio

```bash
python main.py
```

## Creare un eseguibile Windows (.exe)

```
build_exe.bat
```

Crea `dist\CraneScada.exe` con PyInstaller (va lanciato sul PC Windows con il
venv del progetto già creato — non è possibile compilare un `.exe` Windows da
un altro sistema operativo). Di default include la console (utile per vedere
i log); `build_exe.bat --windowed` la nasconde.

## Stato del progetto

Scheletro iniziale iterato con Claude Code: connessione PLC, storage SQLite,
polling veloce/lento e grafico live di posizione funzionanti. Vedi
`CLAUDE.md` per architettura e decisioni prese.

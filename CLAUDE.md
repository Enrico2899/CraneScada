# Crane HMI/SCADA Logger — contesto progetto

## Obiettivo
App locale (Python) per:
1. Leggere in real-time i dati da un PLC Siemens (S7-1500F) via `python-snap7`.
2. Mostrare una vista HMI/SCADA live in una **pagina web locale** (posizione gru,
   stato missione, step corrente, allarmi), con possibilità di scegliere quali
   variabili monitorare/graficare.
3. Storicizzare i dati su SQLite per analisi successive (confronto traiettorie
   automatico vs manuale — funzionalità futura, NON da costruire ora, ma i dati
   raccolti devono essere già adatti a questo scopo).

## Stato attuale
- Il DB PLC (`Q3_DB`, DB7901) è già stato progettato e implementato lato TIA Portal
  (vedi `plc_comm/db_mapping.py` per il layout completo con offset).
- Connessione PLC, storage SQLite, polling ed edge detection sono implementati e
  testati (vedi `engine.py`). L'app è passata da desktop (PySide6, rimossa) a
  **backend web FastAPI + pagina HTML/CSS/JS** in `static/`, su richiesta
  esplicita dell'utente per una UI più curata e con selezione dinamica delle
  variabili — vedi "Decisioni prese" sotto.
- L'utente preferisce modifiche dirette ai file esistenti, iterative, non riscritture
  complete. Lavora in italiano.

## Architettura
```
plc_comm/      → comunicazione S7 col PLC (snap7), mapping DB
storage/       → wrapper SQLite, schema, insert/query
engine.py      → motore di polling/storage indipendente dalla UI (asyncio):
                 mission tracking, edge detection, heartbeat — usato da main.py
main.py        → backend FastAPI: connessione PLC via engine.py, loop di
                 polling, websocket (/ws) verso il browser, serve static/
static/        → pagina web (index.html/style.css/app.js): grafico live su
                 canvas nativo (no CDN, deve funzionare offline), pannello di
                 selezione variabili, persistito in localStorage
analysis/      → (futuro) script/notebook per confronto traiettorie
config.py      → parametri di connessione PLC, path DB, intervalli polling
```

## Decisioni prese finora (importante rispettarle)
- **Loop di polling**: un solo vero read fisico del PLC per ciclo (il DB si
  legge per intero in un colpo solo con snap7, non esiste ancora una lettura
  parziale — vedi TODO in `plc_comm/s7_client.py`). L'idea originale di "due
  loop separati" (veloce per la posizione, lento per stato/step/mission) era
  in parte un accorgimento per non ridisegnare troppo spesso i widget Qt
  dell'app desktop (ora rimossa) — non serve più trasmettendo dati via
  websocket a un browser, quindi `engine.py` fa un solo loop a
  `FAST_POLL_INTERVAL_S`. Se in futuro si implementa una lettura parziale del
  DB (range di byte), lì potrà avere senso reintrodurre due letture fisiche
  separate a frequenze diverse.
  - Eventi discreti (allarmi, cambio step, cambio modalità): rilevati per
    **edge detection** ad ogni lettura, non con polling dedicato.
- **Sincronizzazione temporale**: usare `CycleCounter` (DInt, incrementa ogni
  scan PLC) come riferimento temporale relativo, non il timestamp del PC.
  `CycleCounter` funge ANCHE da heartbeat: se non cambia tra letture
  consecutive per N letture di fila, il PLC è considerato offline/fermo
  (vedi soglia configurabile in `config.py`).
- **Segnali discreti** (Mission_Active, Mission_Pause, ecc.) sono già
  impacchettati in un singolo byte lato PLC (bit 16.0–16.5).
- **UI web, non desktop**: su richiesta esplicita dell'utente, l'app desktop
  PySide6 è stata rimossa e sostituita da un backend FastAPI (`main.py`) +
  pagina web statica (`static/`). Il grafico live è disegnato su `<canvas>`
  nativo con JS puro, **senza dipendenze da CDN** (deve restare utilizzabile
  anche senza connessione internet, essendo un PC su una rete industriale
  locale). Server in ascolto solo su `127.0.0.1` (non esposto alla rete
  locale) per scelta dell'utente.
- **Selezione variabili**: la pagina permette di scegliere quali dei campi di
  `CraneSnapshot` mostrare (pannello a sinistra, persistito in
  `localStorage`). Solo 8 campi numerici "principali" (posizione, peso,
  target pickup/deposit X/Y) hanno un colore di grafico assegnato in modo
  **fisso** per campo (mai ricalcolato in base a cosa è selezionato, per non
  "ridipingere" le serie già visibili quando se ne aggiunge/rimuove
  un'altra — vedi `static/app.js`, `chartSlot`); gli altri campi (laser,
  target Z, stato PLC) sono comunque visualizzabili come valore live ma non
  hanno una linea nel grafico.
- Non costruire ora: vista 2D/3D di confronto traiettorie, calibrazione
  fine dei tempi di polling, gestione multi-PLC/multi-gru. Sono estensioni
  future, l'architettura deve solo restare pronta ad accoglierle (i dati
  storicizzati per `mission_id` sono già sufficienti).

## Prossimi passi suggeriti (da validare con l'utente prima di partire)
Fatto finora: connessione PLC configurata e testata (latenza media <1ms),
schema SQLite e funzioni di scrittura, `engine.py` con mission
tracking/edge detection/heartbeat, backend FastAPI + pagina web con grafico
live e selezione variabili, pacchettizzazione `.exe` (da riadattare se si
vuole di nuovo un eseguibile standalone, ora servirebbe includere `static/`
e avviare un browser).

Possibili prossimi passi, da concordare con l'utente:
1. Validare la pagina web contro il PLC reale (l'utente non aveva il PLC
   raggiungibile nell'ultima sessione).
2. Indicatori di stato più "HMI" (LED colorati per allarmi/heartbeat) invece
   delle sole tile testuali.
3. Vista sinottica 2D della posizione della gru (pianta/rotaia), non solo il
   grafico a linee nel tempo.
4. Verificare/correggere gli offset di `plc_comm/db_mapping.py` contro il DB
   reale in TIA (nei primi test `pos_x` e `pos_y` risultavano identici bit
   per bit — sospetto mapping lato PLC, mai confermato/risolto).

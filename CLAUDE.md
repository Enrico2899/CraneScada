# Crane HMI/SCADA Logger — contesto progetto

## Obiettivo
App desktop locale (Python) per:
1. Leggere in real-time i dati da un PLC Siemens (S7-1500F) via `python-snap7`.
2. Mostrare una vista HMI/SCADA live (posizione gru, stato missione, step corrente, allarmi).
3. Storicizzare i dati su SQLite per analisi successive (confronto traiettorie
   automatico vs manuale — funzionalità futura, NON da costruire ora, ma i dati
   raccolti devono essere già adatti a questo scopo).

## Stato attuale
- Il DB PLC (`Q3_DB`, DB7901) è già stato progettato e implementato lato TIA Portal
  (vedi `plc_comm/db_mapping.py` per il layout completo con offset).
- Questo è uno SCHELETRO: struttura cartelle, classi base, firme di funzioni
  commentate. La logica di business (loop di polling, salvataggio, widget UI)
  va implementata/completata insieme all'utente, iterando file per file.
- L'utente preferisce modifiche dirette ai file esistenti, iterative, non riscritture
  complete. Lavora in italiano.

## Architettura
```
plc_comm/      → comunicazione S7 col PLC (snap7), mapping DB, polling
storage/       → wrapper SQLite, schema, insert/query
hmi/           → interfaccia PySide6 (vista live)
analysis/      → (futuro) script/notebook per confronto traiettorie
main.py        → entry point, wiring dei moduli
config.py      → parametri di connessione PLC, path DB, intervalli polling
```

## Decisioni prese finora (importante rispettarle)
- **Due loop di polling separati**, non uno unico:
  - Loop veloce (~100 ms, DA CALIBRARE con test di latenza reale su snap7):
    posizione/velocità continua (`CRANE_POS_X/Y/Z`).
  - Loop lento (~250 ms–1 s): stato macchina, step, mission info.
  - Eventi discreti (allarmi, cambio step, cambio modalità): rilevati per
    **edge detection** nel loop veloce, non con polling dedicato.
- **Sincronizzazione temporale**: usare `CycleCounter` (DInt, incrementa ogni
  scan PLC) come riferimento temporale relativo, non il timestamp del PC.
  `CycleCounter` funge ANCHE da heartbeat: se non cambia tra letture
  consecutive per N letture di fila, il PLC è considerato offline/fermo
  (vedi soglia configurabile in `config.py`).
- **Segnali discreti** (Mission_Active, Mission_Pause, ecc.) sono già
  impacchettati in un singolo byte lato PLC (bit 16.0–16.5).
- Non costruire ora: vista 2D/3D di confronto traiettorie, calibrazione
  fine dei tempi di polling, gestione multi-PLC/multi-gru. Sono estensioni
  future, l'architettura deve solo restare pronta ad accoglierle (i dati
  storicizzati per `mission_id` sono già sufficienti).

## Prossimi passi suggeriti (da validare con l'utente prima di partire)
1. Configurare IP/rack/slot PLC reali in `config.py` e testare la connessione
   con `plc_comm/s7_client.py` (metodo `connect()` + una lettura raw del DB).
2. Fare un test empirico di latenza di lettura del DB (quanti ms impiega una
   `db_read` completa) per calibrare la frequenza reale del loop veloce.
3. Completare il parsing in `plc_comm/db_mapping.py` (già pronto, verificare
   contro il DB reale in TIA che gli offset non siano cambiati).
4. Implementare lo schema SQLite in `storage/database.py` (già abbozzato).
5. Collegare polling → storage → UI in `main.py`.
6. Costruire progressivamente la UI in `hmi/main_window.py` (partire da
   semplici label/numeri, poi aggiungere grafici live con pyqtgraph).

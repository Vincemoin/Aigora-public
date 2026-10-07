# Aigora — Deployment-Anleitung (öffentliche Streamlit-App)

Diese Anleitung ersetzt jedes lokale Testen. Alles läuft ab jetzt über
GitHub → Streamlit Cloud, mit SurfDrive als einzigem Schreibziel für
Teilnehmer-Daten.

## 1. Architektur-Prinzip in einem Satz

**GitHub-Repo = alles, was zum Start feststeht** (Code + gebauter RAG-Index).
**SurfDrive = alles, was während der Studie live entsteht** (Chatlogs, ZAGK-Daten, Fehlerprotokolle).
**Streamlit-Cloud-Secrets = alle Zugangsdaten** (nie im Repo, nie auf SurfDrive).

## 2. GitHub-Repo-Struktur (das wird deployed)

```
aigora-app/                          <- Repo-Root = Streamlit-App-Root
├── streamlit_app.py                 <- Haupt-Einstiegspunkt (Phasen-Hülle)
├── bootstrap_secrets.py
├── access_control.py
├── phasen.py
├── surfdrive_storage.py
├── gpr_core.py                      <- Sitzung 1 (unverändert von dir gepflegt)
├── retrieve.py                      <- RAG-Retrieval (unverändert)
├── moda_core.py                     <- Sitzung 2 (kommt mit deinem nächsten Upload)
├── views/
│   ├── __init__.py
│   ├── sitzung1_view.py
│   ├── sitzung2_view.py
│   └── sitzung3_view.py
├── data/
│   └── clustering_TA_current.json   <- aktuelle Diskurs-/Standpunkt-Struktur für Sitzung 2
├── chroma_db/                       <- gebauter Vektor-Index, MUSS committet werden
├── requirements.txt
├── .gitignore
└── .streamlit/
    └── secrets.toml.VORLAGE         <- nur Vorlage, wird durch .gitignore nie committet
```

**Was NICHT ins Repo gehört** (siehe `.gitignore`): `.env`, `.streamlit/secrets.toml`
(die echte Datei), `teilnehmer_links_PRIVAT.csv`, `access_tokens_SECRETS.toml`,
`logs/`, `dimension_analysis/`.

**Build-/Offline-Skripte** (`build_index.py`, `patch_metadata.py`,
`dimension_extractor.py`, `clustering_agent.py`, `generate_access_links.py`
usw.) können im selben Repo in einem separaten Unterordner liegen (z.B.
`pipeline/`), da sie zur Laufzeit der App nicht gebraucht werden — oder in
deinem bisherigen lokalen `aigora_rag`-Ordner bleiben, der dann nur noch
Build-Werkzeug ist, nicht mehr "die App".

## 3. SurfDrive-Ordnerstruktur (Schreibziel zur Laufzeit + Archiv)

WebDAV-Basis: `https://surfdrive.surf.nl/remote.php/dav/files/{dein_surfdrive_benutzername}`

```
aigora_logs/                         <- Sitzung 1, ein File pro Teilnehmer
  gpr_P-001.json
  gpr_P-002.json
  ...

aigora_logs_moda/                    <- Sitzung 2, sobald integriert
  chat/
    P-001.json
  zagk/
    P-001.json
  errorlog/
    P-001.json

aigora_admin/                        <- NUR für dich, App greift nie darauf zu
  teilnehmer_mapping_PRIVAT.csv      <- niemals ins Repo, lebt nur hier + lokal
  methodologie/
    aigora_methodology_reference_v1.md
    BEGRUENDUNG_DIMENSIONEN.md
    SYSTEM_PROMPT_UEBERSICHT.md
  recruitment/
    aigora_verband_kontaktliste.md
    aigora_microgrant_briefing.md
    aigora_recruitment_FINAL.md
  corpus_quellen/                    <- die 43 Original-PDFs, NICHT die App-Kopie
    ...
```

Diese Struktur trennt bewusst: **`aigora_logs*`** wird von der App selbst
per WebDAV beschrieben (Ordner müssen einmalig existieren — siehe Schritt 6),
**`aigora_admin`** ist reines Ablage-/Thesis-Material, das die App nie
berührt und das nicht mehr alles im alten `aigora_rag`-Arbeitsordner
durcheinanderliegt.

Der RAG-Corpus selbst (die 43 PDFs) muss NICHT zur Laufzeit erreichbar
sein — nur der daraus gebaute `chroma_db`-Index, und der liegt im Repo
(Abschnitt 2). Die PDFs auf SurfDrive unter `corpus_quellen/` sind reines
Nachvollziehbarkeits-/Thesis-Archiv.

## 4. Schritt-für-Schritt: Repo vorbereiten

1. Neues (oder bestehendes) GitHub-Repo anlegen, Struktur aus Abschnitt 2 befüllen.
2. `chroma_db/`-Ordner (bereits gebaut) mit committen — **nicht** in `.gitignore` aufnehmen.
3. `.gitignore` und `requirements.txt` aus diesem Lieferumfang übernehmen.
4. Prüfen: verweist `retrieve.py` auf den ChromaDB-Pfad relativ (`./chroma_db`)? Laut
   deiner Notiz ja — dann ist hier nichts weiter zu ändern.

## 5. Schritt-für-Schritt: Streamlit Cloud

1. App aus dem Repo neu erstellen (oder bestehende App auf den neuen Stand zeigen lassen), Hauptdatei: `streamlit_app.py`.
2. **Settings → Secrets**: Inhalt von `.streamlit/secrets.toml.VORLAGE` einfügen, alle vier Platzhalter mit echten Werten ersetzen (Access-Codes aus `generate_access_links.py`, SurfDrive-App-Passwort, Anthropic-Key, OpenAI-Key).
3. **Sharing-Einstellungen auf öffentlich stellen** (das war laut Übergabedokument einer der beiden offenen Punkte) — sonst funktioniert der Zugangscode-Login gar nicht erst, da niemand die App überhaupt öffnen kann.
4. Deploy auslösen, App-URL testen (kurz, nur um zu prüfen, dass die Login-Seite erscheint — kein inhaltlicher Test mehr nötig, das machen wir jetzt nur noch mit echten/Pilot-Codes in der Live-App).

## 6. Einmalig: SurfDrive-Ordner anlegen

Die App legt beim ersten Speichern selbst keinen Ordner an (bewusst simpel
gehalten, siehe `surfdrive_storage.py` — `ensure_folder()` existiert als
Funktion, wird aber aktuell nicht automatisch beim ersten Schreiben
aufgerufen). Lege deshalb einmalig manuell in deinem SurfDrive-Webinterface
an: `aigora_logs/`, `aigora_logs_moda/chat/`, `aigora_logs_moda/zagk/`,
`aigora_logs_moda/errorlog/`. (Sag Bescheid, falls du das lieber automatisch
beim App-Start machen lassen willst — dann rufe ich `ensure_folder()` einmal
beim Start von `streamlit_app.py` auf, aktuell bewusst weggelassen, um
unnötige WebDAV-Anfragen bei jedem Neuladen zu vermeiden.)

## 6a. Modell wechseln (Anthropic ↔ DeepSeek), ohne Code anzufassen

Sitzung 1 + 2 laufen jetzt über `model_config.py` — ein einziger Secrets-
Wert entscheidet, welches Modell aufgerufen wird:

```toml
[model_provider]
name = "anthropic"    # oder "deepseek"
```

Umschalten: in Streamlit Cloud → Settings → Secrets diesen Wert ändern und
speichern — die App startet danach automatisch neu (falls nicht: über den
"Reboot"-Button in der Cloud-Oberfläche). Kein Redeploy, kein Code-Zugriff
nötig, funktioniert also auch schnell zwischen zwei Testläufen.

Technischer Hintergrund: DeepSeek bietet seit V4 eine zum Anthropic-SDK
kompatible API (`base_url = https://api.deepseek.com/anthropic`) — Tool-
Definitionen, Antwortverarbeitung (`response.content`, `stop_reason`)
bleiben dadurch unverändert nutzbar (Quelle:
https://api-docs.deepseek.com/guides/anthropic_api).

**Zwei dokumentierte Einschränkungen bei DeepSeek** (siehe Docstring in
`model_config.py`): `cache_control` wird ignoriert (kein Fehler, nur kein
Kostenvorteil), und Anthropics server-seitiges `web_search`-Tool ist dort
nicht als unterstützt dokumentiert — wird bei `name = "deepseek"`
automatisch aus der Tool-Liste entfernt (`filter_tools()`), betrifft nur
den seltenen Aktualitäts-Check-Fall, nicht die eigentliche RAG-Suche.

## 7. Was noch fehlt (nächste Schritte)

- **`moda_agent.py` fehlt noch** — `views/sitzung2_view.py` importiert
  `MODEL, DIMENSION_ORDER, DIMENSION_NAMES_DE, get_moda_system_block`
  daraus. Muss noch mit ins Repo, dann ist an der View nichts weiter
  anzupassen.
- **`data/clustering_TA_current.json`**: muss vor dem Sitzung-2-Fenster
  (26.8.) im Repo liegen. Bis dahin zeigt Sitzung 2 automatisch einen
  freundlichen "noch nicht verfügbar"-Hinweis statt abzustürzen (die Datei
  wird erst beim Öffnen der Kachel geladen, nicht beim App-Start).
- **Sitzung 3**: methodisch noch offen, Platzhalter ist bereits verdrahtet.

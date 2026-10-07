# Changelog — Sokra / Sitzung 1

Laufende, für der Autor lesbare Dokumentation der Änderungen an `gpr_core.py`, `voice_io.py`, `views/sitzung1_view.py` und verwandten Dateien. Format pro Eintrag: **was** geändert wurde, **warum**, **wie** (technisch), und was **bewusst nicht** gemacht wurde (und warum). Vollständige Diffs stehen zusätzlich in der Git-Historie (`git log`), das hier ist die kommentierte Kurzfassung für den schnellen Überblick.

---

## 2026-07-31, Nachmittag (Folge-Runde nach echtem Testlauf)

### 17. Bug: erste Nachricht (Begrüßung) zersplittert in viele Häppchen

**Was:** Antworten wurden manchmal in viele kleine, separate Sprechblasen zerrissen statt als eine zusammenhängende Nachricht.
**Warum:** Die Render-Schleife hat pro Text-Block im Antwort-Content EINE eigene `st.chat_message`-Blase erzeugt, statt alle Blöcke einer Nachricht zusammenzufassen. Vermutliche Ursache für mehrere Text-Blöcke: Extended-Thinking-Blöcke zwischen den Textabschnitten (siehe des Autors Log-Fund von `"type": "thinking"`-Blöcken).
**Wie:** Alle Text-Blöcke einer Nachricht werden jetzt zu einem String zusammengefügt, bevor sie als EINE Sprechblase gerendert werden.

### 18. Debug-Stimmenliste aus dem Interface entfernt

**Was:** Der Button/Expander zum Laden der Azure-Stimmenliste ist raus.
**Warum:** War nur zur einmaligen Klärung gedacht (keine OpenAI-Stimme für Deutsch verfügbar) — stand aber für ALLE Nutzer:innen sichtbar im Chat, nicht nur für der Autor, wie der Text fälschlich suggerierte.

### 19. Stimme/Tempo während Wiedergabe nicht änderbar

**Was:** Änderung der Dropdowns hatte keine hörbare Wirkung, solange kein neuer Chat-Zug ausgelöst wurde.
**Warum:** Stimme/Tempo wurden bisher nur beim Erzeugen einer NEUEN Antwort angewendet, nicht rückwirkend auf die zuletzt gehörte Aufnahme.
**Wie:** `on_change`-Callback an beiden Dropdowns — ändert man Stimme/Tempo, wird die letzte Antwort sofort mit den neuen Einstellungen neu synthetisiert und abgespielt.

### 20. TTS liest Markdown-Formatierung und Emojis wörtlich vor

**Was:** `**fett**` wurde als "Sternchen Sternchen ... Sternchen Sternchen" vorgelesen, Emojis (z.B. 😉) ebenfalls wörtlich.
**Wie:** `_strip_links_for_speech()` entfernt jetzt zusätzlich `**`/`*`/`` ` ``/`#` sowie Emoji-Unicode-Bereiche vor der Sprachsynthese. Betrifft nur die Sprachausgabe, die sichtbare Chat-Darstellung bleibt unverändert formatiert.

### 21. Feste Begrüßung wurde nie vorgelesen

**Was:** Die hartkodierte erste Nachricht (kein Modell-Aufruf) bekam nie eine Sprachausgabe, obwohl TTS aktiviert war.
**Warum:** Die Audio-Wiedergabe-Logik stand bisher nur im Code-Pfad für normale Modell-Antworten, nicht im separaten Begrüßungs-Pfad.
**Wie:** Audio-Wiedergabe in eine gemeinsame Hilfsfunktion (`_maybe_play_last_audio`) ausgelagert, die jetzt von BEIDEN Pfaden genutzt wird. Für die Begrüßung wird die Sprachausgabe direkt bei Sitzungsstart mit den Standard-Einstellungen erzeugt (Stimm-/Tempo-Dropdowns existieren an der Stelle im Code noch nicht, da sie erst weiter unten gerendert werden).

### 22. Einstieg umgebaut: sanfterer Beginn, Zeit-/Tiefe-Frage, Sokra übernimmt Zeitmanagement

**Was:** Die feste Begrüßung ist jetzt kürzer/sanfter gestaffelt (Kurzvorstellung → Ablauf/Framework/Dimensionen → Zeit-/Tiefe-Frage als Abschluss) und stellt die inhaltliche Eröffnungsfrage ("Was fällt dir zur Wärmewende ein") NICHT mehr selbst. Sokras erster eigener Zug reagiert stattdessen auf die Zeit-/Tiefe-Antwort, kalibriert sein Zug-Budget/seine Tiefe entsprechend (Verweis auf 5.5) und stellt DANN die inhaltliche Frage; der zweite eigene Zug reagiert auf die inhaltliche Antwort und leitet zu Dimension 1 über.
**Warum:** des Autors Rückmeldung — die alte Begrüßung wirkte auf einen Schlag erschlagend; außerdem sollte Zeitmanagement (wie viel Zeit hat die Person, wie tief möchte sie einsteigen) explizit Sokras Aufgabe sein, nicht nur implizit mitlaufen.
**Trade-off, bewusst in Kauf genommen:** Der Teil "Framework erklären + Zeitfrage stellen" ist NICHT mehr wortgleich für alle Teilnehmenden (er ist jetzt Teil von Sokras eigenem, reaktivem ersten Zug, nicht mehr Teil der hartkodierten, garantiert identischen Begrüßung). Das war eine bewusste Entscheidung, weil dieser Teil jetzt auf die Zeit-/Tiefe-Antwort der Person eingehen soll -- das lässt sich nicht vorab wortgleich skripten. Nur der ganz erste, allgemeine Begrüßungsteil bleibt vollständig hartkodiert/identisch.

### 23. Dimensionen 4-6 im Begrüßungstext: nur Beispiele statt Definition

**Was:** "Umsetzungslogik – Zwang, Freiwilligkeit oder Markt?" (etc.) durch echte Definition + einfache Erklärung + Praxisrelevanz ersetzt, im selben Stil wie die bereits guten Beschreibungen von Dimension 1-3.
**Warum:** des Autors Rückmeldung — das waren nur Beispiele, keine verständliche Definition.

### 24. Sidebar mit live ausgefüllten Dimensionen — NICHT gebaut, nur Empfehlung abgegeben

**Was:** der Autor fragte nach meiner Einschätzung zu einer Sidebar, die die 6 Dimensionen stichpunktartig mit den ratifizierten Positionen befüllt.
**Meine Empfehlung:** grundsätzlich ja (methodisch wertvoll, Daten liegen strukturiert vor), aber zurückhaltend gestalten (kein Formular-/Fortschrittsbalken-Charakter, der dem Bürgerrat-Gesprächscharakter widerspricht) und knapp/einklappbar wegen Platzbedarf für Sprachein-/ausgabe.
**Nicht gemacht:** Wartet auf des Autors Entscheidung, ob/wann das umgesetzt werden soll — das ist eine UI-Entscheidung mit echtem Aufwand, nicht ungefragt vorweggenommen.

## 2026-07-31, Abend

### 25. Sidebar-Fortschrittsübersicht gebaut

**Was:** Immer sichtbare Seitenleiste mit den 6 Dimensionen (✅ erledigt / 👉 aktuell / ⚪ noch offen), aufklappbar zu den ratifizierten Positionen im Originalwortlaut mit Begründung und Überzeugungswert (1-5).
**Wie:** Liest direkt aus den bestehenden `<ratified>`-Blöcken im Nachrichtenverlauf (`_collect_ratified_positions()`, Regex-Parser) — keine zusätzliche Datenhaltung. "Aktuell" ist eine grobe Schätzung: die erste Dimension in fester Reihenfolge ohne ratifizierten Eintrag. Unterstützt mehrere Positionen pro Dimension (siehe Punkt 15).
**Nicht gemacht:** Keine editierbare Ansicht, rein lesend — passt zur bisherigen Entscheidung, Inline-Bearbeitung auf später zu verschieben (siehe `CLAUDE.md`, offener Punkt 7).

### 26. Bug: Begrüßung wurde nach dem TTS-Update trotzdem nicht vorgelesen

**Was:** Audio für die feste Begrüßung wurde nur im "brandneue Sitzung"-Zweig erzeugt, nicht wenn eine bestehende (aber noch unbeantwortete) Begrüßung erneut aus SurfDrive geladen wurde — was bei wiederholtem Testen mit demselben Zugangscode fast immer der Fall ist.
**Wie:** Bedingung geändert auf "Begrüßung ist die einzige Nachricht im Verlauf", unabhängig davon, ob sie gerade neu erzeugt oder geladen wurde.

### 27. Wording: "Reflexionsebenen" → "Politik-Ebenen" + Zweck/Mittel-Unterscheidung sichtbar gemacht

**Was:** Begrüßungstext nennt jetzt explizit die Ends/Means-Struktur (drei Ebenen zum Zweck, drei zu den Mitteln, vom Groben zum Konkreten), statt nur vage "Reflexionsebenen" zu sagen.
**Warum:** des Autors Rückmeldung — es sind Politik-Ebenen, das Framework differenziert klar zwischen Zielen/Zwecken und Mitteln/Umsetzung.

### 28. Klarstellung zum "Trade-off"-Kommentar von vorhin

**Was:** Der Code-Kommentar zur Begrüßungsumstrukturierung war missverständlich formuliert und wurde korrigiert.
**Klarstellung:** Framework, Dimensionen UND die Zeit-/Tiefe-Frage bleiben vollständig hartkodiert und wortgleich für alle Teilnehmenden, wie ursprünglich auch. NUR die inhaltliche Eröffnungsfrage ("was fällt dir ein") wandert in Sokras eigenen ersten Zug, weil sie einer kurzen Reaktion auf die Zeitangabe folgen muss.

---

## 2026-07-31

### 1. Bug-Fix: Sitzung friert dauerhaft ein

**Was:** `_get_agent_response()` in `sitzung1_view.py` hing sich nach einem fehlgeschlagenen `search_corpus`-Aufruf dauerhaft auf (kein Antworten mehr möglich, auch nicht nach erneutem Versuch).
**Warum:** Die Assistant-Nachricht mit dem `tool_use`-Block wurde in den Verlauf geschrieben, BEVOR die Suche ausgeführt wurde. Schlug die Suche fehl, blieb ein unbeantworteter `tool_use`-Block im (auf SurfDrive gespeicherten) Verlauf stehen — die Anthropic-API lehnt danach JEDEN weiteren Aufruf mit diesem Verlauf dauerhaft ab, nicht nur einmalig.
**Wie:** Jeder `tool_use`-Block bekommt jetzt garantiert ein `tool_result`, auch im Fehlerfall (mit Fehlertext statt Ergebnis), bevor der nächste API-Aufruf passiert.
**Nicht gemacht:** Reparatur bereits beschädigter, alter Logs auf SurfDrive — der Fix wirkt nur vorwärts. Betrifft nur Test-Sessions von vor diesem Fix, in der echten Studie nicht relevant.

### 2. UI: Logo/Icon, Sitzungs-Überschriften, korrigierte Zeitfenster

**Was:** `branding.py`/`streamlit_app.py`/`access_control.py` nutzen jetzt `title_page_logo.png`/`aigora_icon.png` statt Emoji; alle drei Sitzungs-Header ziehen Titel/Untertitel zentral aus `phasen.py`; Studienzeitraum korrigiert auf 10.–30.8.2026 (war 17.8.–6.9.).
**Warum:** Assets waren inzwischen im Repo, alte Daten/Emoji waren veraltet bzw. auf des Autors ausdrücklichen Wunsch.
**Wie:** Siehe `branding.py` (`render_title_bar()`, `get_page_icon()`), `phasen.py` (`PHASEN`-Dict als Single Source of Truth).
**Nicht gemacht:** `assets/6_dimensionen_grafik.png` (die Eröffnungsgrafik) fehlt weiterhin im Repo — der Autor liefert die selbst nach, Code greift automatisch, sobald sie da ist.

### 3. Sprachfunktion: mehrere Anbieter-Wechsel, dann Azure AI Speech

**Was:** `voice_io.py` (STT+TTS) lief nacheinander über OpenAI → Deepgram → Azure OpenAI (verworfen) → Azure AI Speech (final).
**Warum:** Datenschutz (Zero Data Retention) war das entscheidende Kriterium. Geprüft und verworfen: OpenAI direkt (ZDR nur Enterprise), Deepgram (ZDR-Status nur über Sekundärquellen, keine klare Selbstbedienung), ElevenLabs (ZDR explizit Enterprise-only), Azure OpenAI Service (30 Tage Standard-Retention, ZDR nur über Antrag "typically requires being a managed EA/MCA customer"). Azure AI Speech ist die einzige geprüfte Option mit **Standard-ZDR ohne Enterprise-Vereinbarung** (Primärquelle: Microsofts eigene Data-Privacy-Doku für die Text-to-Speech-Echtzeit-API).
**Wie:** Reiner REST-Zugriff per `requests` (kein SDK, passt zum schlanken Stil von `surfdrive_storage.py`), regionsbasierte Endpoints (`{region}.stt.speech.microsoft.com` / `{region}.tts.speech.microsoft.com`), 16kHz-Resampling per `numpy` (Azures Kurz-Audio-API verlangt das strikt, Browser-Aufnahmen liefern oft eine andere Rate).
**Nicht gemacht:** OpenAI-Stimmen über Azure — per In-App-Debug-Tool (`list_voices()`) geprüft, für Deutsch in des Autors Region nicht verfügbar (nur `Source: Azure` / `Source: MAI`, keine OpenAI-Stimme im Katalog).

### 4. Sprachfunktion: Stimme/Tempo wählbar, natürlichere Stimmen, Wiedergabe-Stabilität

**Was:** Dropdown für Stimme (6 kuratierte deutsche Stimmen, Standard jetzt `de-DE-Florian:DragonHDLatestNeural`) und Tempo (5 Stufen); TTS-Audio bleibt nach Erzeugung im Session-State stehen statt nach einmaligem Abspielen gelöscht zu werden.
**Warum:** Erste Stimme (Deepgram Aura-2, dann Azure Standard-/Multilingual-Neural) klang laut der Autor monoton/"wie Siri 2010"; Änderung von Stimme/Tempo hat den laufenden Player komplett zum Verschwinden gebracht (Streamlit-Rerun-Verhalten).
**Wie:** Dragon-HD-Stimmen sind laut Microsoft "kontextbewusst" (automatische Ton-/Emotionsanpassung), GA-Status in `swedencentral` per In-App-Tool bestätigt. Audio-Bytes bleiben persistent im Session-State (`_s1_last_audio`), Autoplay wird nur einmal über ein separates Flag ausgelöst, der Player selbst verschwindet dadurch nicht mehr bei einem Rerun.
**Nicht gemacht:** Kein hundertprozentiges Garantieversprechen, dass eine Einstellungsänderung NIE mehr die Wiedergabe unterbricht — das hängt teils an Streamlits Rerun-Modell und dem Browser, nicht vollständig kontrollierbar. Der Player bleibt aber jetzt zumindest sichtbar/erneut abspielbar, statt ganz zu verschwinden.

### 5. Sprachfunktion: Live-Transkription (Wort für Wort während des Sprechens)

**Was:** NICHT umgesetzt.
**Warum nicht:** `st.audio_input` liefert die Aufnahme technisch erst komplett nach dem Stoppen. Echtes Live-Transkribieren bräuchte eine durchgehende WebSocket-Verbindung (z.B. custom JavaScript-Komponente mit Azure Speech SDK im Browser, oder `streamlit-webrtc` + native Azure-SDK-Bibliothek) — deutlich mehr Aufwand/neue Abhängigkeiten, mit echtem Deployment-Risiko auf Streamlit Cloud, kurz vor Studienstart nicht vertretbar.
**Stattdessen:** (a) erkannter Text wird jetzt in einem editierbaren Feld zur Kontrolle angezeigt, bevor er gesendet wird (siehe Punkt 6), (b) Hinweis auf die geräteeigene Diktierfunktion (Windows/Mac) als Alternative ergänzt, die tatsächlich live ins Textfeld schreibt.

### 6. Sprachfunktion: Erkannter Text wird vor dem Senden angezeigt, nicht automatisch abgeschickt

**Was:** Nach der Transkription erscheint der erkannte Text in einem Textfeld mit "✅ Senden"/"🗑️ Verwerfen", statt automatisch als Nachricht abgeschickt zu werden.
**Warum:** des Autors Rückmeldung — Fehler in der Transkription sollen vor dem Absenden korrigierbar sein.
**Wie:** `st.text_area` mit dem transkribierten Text vorbefüllt (funktioniert bei `st.chat_input` selbst nicht, das Widget erlaubt kein Vorbefüllen), zwei Buttons zur Entscheidung.

### 7. Sprachfunktion: TTS liest rohe Links vor

**Was:** Vor der Sprachausgabe werden Markdown-Links `[Text](URL)` zu nur `Text` reduziert, verbleibende nackte URLs entfernt.
**Warum:** Azure hat bisher komplette `https://...`-Adressen vorgelesen, das ist unangenehm/kaum verständlich beim Hören.
**Wie:** Neue Funktion `_strip_links_for_speech()`, nur im TTS-Pfad (`_extract_plain_text`) angewendet — die sichtbare Chat-Darstellung (`_render_message`) ist NICHT betroffen, Links bleiben dort normal klickbar.

### 8. System-Prompt: Dimensionsbenennung korrigiert, Themenlisten umsortiert

**Was:** Zweck-Seite umbenannt zu Übergeordnete Ziele / Konkrete Ziele / Zwischenziele (vorher andere Reihenfolge); drei fehlplatzierte Themen (Entscheidungsebene, Legitimität staatlichen Eingreifens, fiskalische Vorsicht) von "Ziele" zu "Umsetzungslogik" verschoben, eine Instrumentenfrage von "Ziele" zu "Instrumententyp".
**Warum:** des Autors eigene Präzisierung des Cashore-&-Howlett-Frameworks (Ends/Means-Unterscheidung: Ziele beschreiben das gewünschte Ergebnis, Umsetzungslogik die Steuerungsphilosophie).
**Wie:** Interne `<ratified dimension="...">`-Schlüssel (Goals/Objectives/Settings/...) bewusst UNVERÄNDERT gelassen — nur die deutschen Bezeichnungen im Gespräch ändern sich, Datenauswertung/`extract_ratified.py` sind nicht betroffen.

### 9. System-Prompt: Komplette Überarbeitung durch der Autor (externe Konzeptualisierung), von mir integriert

**Was:** der Autor hat einen stark erweiterten System-Prompt (Marker-Taxonomie, Notwendigkeits-Check, Zug-Inventar, Nudging-to-Reason-Theoriebezug u.a.) in einem separaten Claude-Chat entwickelt und eingefügt; ich habe die oben genannte Dimensionsbenennung nachträglich hineinkorrigiert.
**Warum:** Deutlich präzisere, explizitere Regeln als die Vorversion — wichtig, weil DeepSeek (zeitweise als Backend genutzt) mehr Präzision braucht als Sonnet.

### 10. System-Prompt: Antworten zu lang / Eröffnungsdialog zieht sich (bis zu 20 Minuten ohne Dimension 1 zu erreichen)

**Was:** (a) Striktes Zug-Budget: max. 2, Ausnahmefälle 3 Züge pro Antwort (Abschnitt 5.2). (b) Wortrichtwert 80–150 Wörter + Informationsdosierungs-Regel (Abschnitt 1.3). (c) Eröffnungsreaktion auf maximal 1–2 Züge über maximal 2 Antworten begrenzt, danach zwingende Überleitung zu Dimension 1 (Abschnitt 9).
**Warum:** Eigener Trockendurchlauf (manuelle Simulation, siehe Punkt 12) UND des Autors echter Testlauf zeigten: Marker-Taxonomie (2.2), Notwendigkeits-Check (2.8), Mehrfachzuordnung (3.2) und Zug-Inventar (5.1) feuern bei einer reichhaltigen ersten Antwort alle gleichzeitig — die vorherige Anweisung "bündle, aber wirk nicht überladen" war zu vage, um das beim Modell wirksam zu bremsen.
**Wie:** Konkrete Zahlen statt vager Heuristik — das ist der eigentliche Hebel, nicht nur eine Umformulierung.

### 11. System-Prompt: "Großes Ganzes" fehlte — Bürgerrat-Prinzip, Begleiten statt Lenken

**Was:** Neuer Absatz in 1.1 (Bürgerrat-Prinzip: jede Stimme zählt gleich, Werte sind Verhandlungssache der Person, Fakten nicht) und in 1.2 ("Begleiten statt lenken, herausfordern statt konfrontieren" mit explizitem Ton-Beispiel).
**Warum:** des Autors Rückmeldung, dass die bisherigen Regeln zwar mechanisch korrekt greifen, aber die übergeordnete Motivation/Haltung nicht explizit genug im Prompt stand.

### 12. System-Prompt: eigener Trockendurchlauf als Testmethode

**Was:** Ich habe den Prompt selbst gelesen, eine plausible erste Teilnehmer-Antwort simuliert und Zug für Zug durchgerechnet, was Sokra daraus macht (ohne echten API-Aufruf, keine Zugangsdaten/Testinfrastruktur hier verfügbar).
**Warum/Einschränkung:** Das ist ein Trockendurchlauf/Analyse, KEIN echter Modell-Test — des Autors eigener Testlauf mit echtem Sonnet-5-Verhalten bleibt notwendig und hat zusätzliche, im Trockendurchlauf nicht sichtbare Probleme aufgedeckt (z.B. die 20-Minuten-Eröffnungsschleife in voller Härte).

### 13. System-Prompt: web_search um dritten Anwendungsfall erweitert

**Was:** `web_search` darf jetzt zusätzlich genutzt werden, um eine konkrete Sachbehauptung DER PERSON zu prüfen, die nicht im Corpus abgedeckt ist (z.B. eine genannte Kostenzahl aus dem eigenen Umfeld) — mit Seriositäts-Kriterium (etablierte Medien/Behörden/Statistikämter, keine Boulevardpresse/Foren) und Transparenzpflicht (Quelle nicht Aigora-kuratiert).
**Warum:** des Autors Rückmeldung, dass es zweimal vorkam, dass Sokra erklärte, eigene Behauptungen der Person nicht prüfen zu können — das wirkte unbefriedigend und unterläuft den Faktentreue-Anspruch, der ja auch für die Person selbst gelten soll.
**Nicht gemacht:** Kein RAG-Corpus-Update für nutzergenerierte Behauptungen — das wäre strukturell etwas anderes (Corpus ist kuratiert, nicht dynamisch erweiterbar zur Laufzeit) und laut der Autor ohnehin eher eine Zukunfts-Idee für eine spätere Aigora-Version, nicht für jetzt.

### 14. System-Prompt: Konkretisierung früherer Positionen systematischer gemacht

**Was:** Abschnitt 3.2 verlangt jetzt explizit, bei jedem Dimensionsübergang zu fragen, ob/wie eine frühere abstrakte Position in der aktuellen, konkreteren Dimension festgehalten werden soll — mit Beispielmuster.
**Warum:** des Autors Rückmeldung: abstrakte Positionen (v.a. aus "Übergeordnete Ziele") blieben in der Praxis oft folgenlos, wurden nicht in spätere konkretere Dimensionen übersetzt.

### 15. System-Prompt: mehrere Positionen pro Dimension einzeln bewerten

**Was:** Abschnitt 6 verlangt jetzt explizit separate `<ratified>`-Blöcke (mit je eigenem 1-5-Wert), wenn eine Person mehrere klar unterscheidbare Positionen innerhalb einer Dimension äußert, statt sie zusammenzufassen.
**Warum:** des Autors Rückmeldung — eine gemeinsame Überzeugungsstärke für mehrere unterschiedliche Aussagen verwischt echte Unterschiede in der Auswertung.

### 16. System-Prompt: Fachbegriffe wörtlich UND praktisch erklären

**Was:** Abschnitt 5.4 verlangt jetzt explizit beide Erklärungsebenen (technische Bedeutung UND Alltagsrelevanz), nicht nur eine — mit besonderem Hinweis auf die konkreten Dimensionen (Zwischenziele/Feinausgestaltung), wo Fachbegriffe wie "U-Wert" am dichtesten vorkommen.
**Warum:** des Autors Rückmeldung — mit reinen Fachbegriffen kann eine fachfremde Person ad hoc nichts anfangen.

---

## 2026-08-08 (eigenständige Session, der Autor nicht erreichbar)

### 29. Testläufe zeigten: Dimension-3-Bug bestätigt und von der Autor selbst gefixt

der Autor hat direkt im Repo (`d42fdb6`) einen Bug gefixt, den die Testläufe aufgedeckt hatten: "Dimension 3 und 6 gemeinsam am Ende" wurde vom Modell als "nur EIN gemeinsamer Ratified-Block" missverstanden, Dimension 3 fiel dabei komplett weg. Betraf 3 von 3 Testläufen vor dem Fix (100%), 0 von 1 danach. Siehe Abschnitt 3.1 in `gpr_core.py` für den genauen Wortlaut der Korrektur.

### 30. Fehlklassifizierung von Aussagen zwischen Dimensionen

**Was:** Neue Regel in 3.2 -- wenn eine Aussage zwar als Antwort auf die aktuelle Dimension kam, aber inhaltlich strukturell einer ANDEREN Dimension zugehört (z.B. eine konkrete Technologiepräferenz wie "Wärmepumpe" als Antwort auf eine Ziele-Frage -- das ist der Sache nach Umsetzungslogik, kein Ziel), ratifiziert Sokra das NICHT mehr stillschweigend in der falschen Dimension. Stattdessen: Mismatch benennen, Rückfrage stellen, erst nach Bestätigung in der richtigen Dimension festhalten.
**Warum:** des Autors Testlauf-Fund -- eine wiederholt betonte Wärmepumpen-Präferenz wurde als "Ziel" ratifiziert, gehört aber eigentlich zur Umsetzungslogik/zum Instrumententyp.
**Abgrenzung zur bestehenden Mehrfachzuordnungs-Regel:** Das ist ein anderer Fall -- nicht "passt zu mehreren Dimensionen", sondern "wurde in der falschen Dimension beantwortet".

### 31. Duplikat-Ratifizierung verhindert

**Was:** Neue Regel in Abschnitt 6 -- wenn eine Dimension schon ratifiziert wurde und die Person nur eine kleine Ergänzung zur SELBEN Position nachreicht, gibt es KEINEN zweiten, fast identischen `<ratified>`-Block mehr. Entweder kurz bestätigen ohne erneut zu ratifizieren, oder (bei wirklich wesentlicher Änderung) einen aktualisierten Block, der den alten ersetzt.
**Warum:** Eigener Fund beim Auswerten der Testläufe -- im Lauf nach dem Dimension-3-Fix wurde dieselbe "Übergeordnete Ziele"-Position zweimal fast wortgleich ratifiziert, nur weil die Person eine Kleinigkeit ergänzt hatte.

**Validierung:** Kontroll-Testlauf gestartet, um zu prüfen ob beide neuen Regeln in der Praxis greifen -- Ergebnis folgt.

---

## Offene Punkte — bewusst NICHT bearbeitet, brauchen des Autors Input

1. **Survey-/Abschlussfragen:** noch nicht erstellt. Das ist ein methodisches Instrument (was genau gemessen werden soll), keine Entscheidung, die ich allein treffen sollte — brauche Scope/Ziel von der Autor, bevor ich das aufsetze.
2. **Weitere UI-Tweaks:** der Autor hat angekündigt, dazu noch eigene Notizen zu schicken — noch nicht eingetroffen.
3. **Falscher Link zur ffe-Studie** (führt nur zur Startseite statt zum Dokument): das ist ein Corpus-Metadaten-Problem (`RAG_Corpus.xlsx` → `patch_links.py`), kein Prompt-/Code-Fix möglich von meiner Seite. der Autor müsste den Link-Eintrag in der Excel-Quelle korrigieren und `patch_links.py` erneut laufen lassen (bereits als offener Punkt in `CLAUDE.md` dokumentiert).
4. **`<ratified>`-Blöcke in separatem Ordner speichern:** aktuell werden sie nur als Text innerhalb der normalen Chat-Logs gespeichert, strukturierte Extraktion passiert ausschließlich offline über `extract_ratified.py` (von der Autor manuell ausgeführt). Das ist laut `CLAUDE.md` eine bewusste Architekturentscheidung ("Statement-Granularität" ist zudem noch offene Designfrage) — nicht ungefragt geändert, das wäre ein größerer Eingriff.

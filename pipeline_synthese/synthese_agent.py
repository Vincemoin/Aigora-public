"""
synthese_agent.py

Schritt 2 der Pause-2-Synthese-Pipeline: EIN LLM-Aufruf PRO Dimension,
der aus dem Dossier (data/synthese/dossiers.json, siehe
synthese_dossiers.py) Policy-Kandidaten formuliert. Systemprompt von
der Autor vorgegeben (synthese_pipeline_konzept.md), unveraendert
uebernommen.

Bewusst KEIN globaler Aufruf ueber alle Dimensionen: laut Methodology-
Dokument Kap. 6.1 ist "ein Dossier, ein klar abgegrenztes Urteil" die
Aufgabengroesse, die zuverlaessig funktioniert -- keine Optimierung ueber
den gesamten Datensatz auf einmal.

Ausgabe:
- data/synthese/kandidaten_v1.json (kanonisch, von Schritt 3 gelesen)
- data/synthese_runs/kandidaten_{timestamp}_{model}{tag}.json (Archiv,
  gleiches Muster wie session2_clustering_v4think.py -- mehrere Laeufe
  mit unterschiedlichen Prompt-Versionen ueberschreiben sich nicht)

Nutzung:
    python synthese_agent.py [--model MODEL] [--tag LABEL] [--dimension NAME]

--dimension: nur eine einzelne Dimension synthetisieren (zum Testen/
Nachbessern, ohne alle sechs neu zu bezahlen).
"""

import argparse
import datetime
import json
import os
import re
from pathlib import Path

from dotenv import load_dotenv

try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

from anthropic import Anthropic, AnthropicError

load_dotenv()

DEFAULT_MODEL = "claude-sonnet-5"
DOSSIERS_PATH = "data/synthese/dossiers.json"
OUTPUT_PATH = "data/synthese/kandidaten_v1.json"
RUNS_DIR = "data/synthese_runs"

DIMENSION_KURZNAME = {
    "Übergeordnete Ziele": "Goals",
    "Konkrete Ziele": "Objectives",
    "Zwischenziele": "Settings",
    "Umsetzungslogik": "InstrumentLogic",
    "Instrumententyp": "Tools",
    "Feinausgestaltung": "Calibrations",
}

# ── Cashore-Howlett-Dimensionsmatrix (des Autors akademische Definitionen,
#    woertlich uebernommen und uebersetzt -- vorher hatte das Modell nur
#    die Dimensionsnamen als Label, ohne echte Abgrenzung, was zu
#    inhaltlich zu aehnlich klingenden Kandidaten ueber Dimensionsgrenzen
#    hinweg gefuehrt hat) ─────────────────────────────────────────────

CASHORE_HOWLETT_MATRIX = """\
<cashore_howlett_dimensionen>
Sechs Ebenen, geordnet nach Abstraktionsgrad UND danach, ob sie den ZWECK (Ends)
oder die MITTEL (Instruments) einer Politik betreffen:

                    ZWECK (Ends)                        MITTEL (Instruments)
Hoch (Makro):    1. Goals / Übergeordnete Ziele      4. Instrument Logic / Umsetzungslogik
Mittel (Meso):   2. Objectives / Konkrete Ziele       5. Mechanisms / Instrumententyp
Niedrig (Mikro): 3. Settings / Zwischenziele          6. Calibrations / Feinausgestaltung

1. Goals (Übergeordnete Ziele): die abstraktesten, philosophischen Leitideen und
   übergeordneten Prinzipien hinter einer Politik. Beispiel: Klimaneutralität
   erreichen, nationale Vorreiterrolle im Klimaschutz.
2. Objectives (Konkrete Ziele): die formalen, konkreten, operationalisierten
   Zielgrößen, die die Politik explizit adressiert. Beispiel: die Sanierungsrate
   um X Prozentpunkte erhöhen, das CO2-Sektorziel auf Y senken.
3. Settings (Zwischenziele): die spezifische, sehr präzise SITUATIVE Festlegung,
   WER oder WAS konkret betroffen ist -- Geltungsbereich/Reichweite, nicht die
   Zielgröße selbst. Beispiel: die Regelung gilt nur für Bestandsgebäude vor
   Baujahr X, nur für Vermietende mit mehr als N Einheiten, nur in bestimmten
   Regionen.
4. Instrument Logic (Umsetzungslogik): die grundsätzlichen Steuerungsnormen und
   generellen Präferenzen, WIE Instrumente prinzipiell eingesetzt werden sollen.
   Beispiel: marktbasierter Ansatz (Preisanreize) vs. staatliche Regulierung als
   Grundprinzip, unabhängig vom konkreten Einzelinstrument.
5. Mechanisms (Instrumententyp): die konkreten, strukturellen TYPEN von
   Politikinstrumenten, die gewählt werden. Beispiel: Pflichtquote, CO2-Preis,
   Fördersystem, Zertifikatehandel als jeweils benannter Instrumententyp.
6. Calibrations (Feinausgestaltung): die tatsächliche, konkrete Konfiguration und
   Feinjustierung des GEWÄHLTEN Mechanismus. Beispiel: die exakte Preishöhe pro
   Tonne CO2, der genaue Fördersatz in Prozent, die exakte Übergangsfrist in Jahren.

WICHTIG: 1-3 sind der ZWECK-Strang (WAS erreicht werden soll), 4-6 der MITTEL-Strang
(WIE es erreicht wird). Bleibe strikt in der dir zugewiesenen Ebene. Ein Standpunkt,
der eigentlich zu einer anderen Ebene gehört (z.B. eine Zielgröße, obwohl du gerade
Instrumententyp bearbeitest), gehört NICHT in deinen Kandidaten -- nimm ihn nicht auf,
sondern vermerke das kurz unter "datenluecken", falls das relevant ist.
</cashore_howlett_dimensionen>
"""

_DIMENSION_FOKUS = {
    "Übergeordnete Ziele": "Goals -- abstrakte Leitideen und Prinzipien. KEINE Zahlen, KEINE Instrumente.",
    "Konkrete Ziele": "Objectives -- formale, operationalisierte Zielgrößen (Prozent, Jahr, absolute Zahl). KEIN Geltungsbereich, KEIN Instrument.",
    "Zwischenziele": "Settings -- WER/WAS ist betroffen (Geltungsbereich, Reichweite). NICHT die Zielgröße selbst, NICHT das Instrument.",
    "Umsetzungslogik": "Instrument Logic -- grundsätzliche Steuerungspräferenz (marktbasiert vs. regulatorisch als PRINZIP). KEIN benanntes Einzelinstrument, KEINE Zielgröße.",
    "Instrumententyp": "Mechanisms -- der benannte TYP des Instruments (Pflichtquote, CO2-Preis, Förderprogramm). NICHT dessen Feinjustierung.",
    "Feinausgestaltung": "Calibrations -- die exakte Konfiguration eines BEREITS feststehenden Instruments (Zahl, Prozentsatz, Frist).",
}


# ── Systemprompt (Basis von der Autor, ueberarbeitet nach Feedback zu
#    Granularitaet/Praezision/Dimensionstrennung/Jargon) ────────────────

SYSTEM_PROMPT_BASE = """\
<aufgabe>
Du formulierst Policy-Empfehlungen für EINE Dimension der deutschen Wärmewende, auf
Basis der vollständigen Eingaben und Bewertungen von Bürgerinnen und Bürgern aus einem
zweistufigen Beteiligungsverfahren.

Deine Aufgabe ist NICHT, eine eigene politische Position zu entwickeln. Sie ist,
herauszuarbeiten was diese konkreten Menschen wollen, und das in klaren, präzisen
Aussagen zu bündeln, denen möglichst viele von ihnen tatsächlich zustimmen würden.
</aufgabe>

<datengrundlage>
Du erhältst für diese eine Dimension:
- STANDPUNKTE: die in Sitzung 2 diskutierten Positionen, jeweils mit vollständigem
  Bewertungsprofil (wie viele Personen, welche Verteilung von 1 bis 5)
- URSPRUNGSPOSITIONEN: die Originalformulierungen der Teilnehmenden aus Sitzung 1
- KOMMENTARE: was Teilnehmende zu den Standpunkten geschrieben haben (Bedingungen,
  Einschränkungen, Gegenargumente)
- KOMPROMISSVORSCHLÄGE: was Teilnehmende selbst als Brücke vorgeschlagen haben
- ABLEHNUNGEN: wer welche Standpunkte niedrig bewertet hat, mit Begründung wo vorhanden

Die Kompromissvorschläge sind besonders wertvoll: sie zeigen, wo Menschen selbst
Bewegungsspielraum sehen. Nutze sie vorrangig als Baumaterial.
</datengrundlage>

<granularitaet_zusammenfuehren_oder_trennen>
KRITISCHE REGEL, die bisher am häufigsten verletzt wurde: ein Kandidat darf nur DANN
zwei inhaltliche Elemente in einem Satz kombinieren, wenn die TEILNEHMERDATEN SELBST
einen Bedingungs- oder Abhängigkeitszusammenhang zwischen ihnen herstellen (z.B. eine
Person schreibt explizit "Zieljahr nur vorziehen, WENN sozialer Ausgleich gesichert
ist", oder ein Kompromissvorschlag verknüpft beides). Dieser Zusammenhang muss aus den
Daten ENTNOMMEN werden, nicht geschätzt oder unterstellt.

Besteht KEIN belegter Zusammenhang, werden die Elemente GETRENNT, auch wenn sie
thematisch benachbart wirken. Beispiel eines Fehlers, den es zu vermeiden gilt:
"Die Sanierungsrate soll auf 2% steigen, ergänzend soll der Fernwärmeausbau
vorangetrieben werden" -- Sanierungsrate und Fernwärmeausbau sind unterschiedliche
Themen ohne belegten Bedingungszusammenhang und gehören in ZWEI Kandidaten.

Wenn sich zwei Kandidaten nur auf eine KONKRETE ZAHL/FRIST unterscheiden, aber sonst
inhaltlich identisch sind (z.B. Zieljahr 2035 vs. 2040), formuliere sie als zwei
benannte Varianten DERSELBEN Empfehlung (gleicher Wortlaut bis auf die Zahl, per
`schliesst_aus` gegenseitig referenziert), nicht als zwei unabhängige Themen.

Mehr, aber klar getrennte und eindeutige Kandidaten sind AUSDRÜCKLICH besser als
wenige, die mehrere Inhalte vermischen -- eine vermischte Aussage ist für eine
spätere Ja/Nein-Bewertung durch Teilnehmende nicht sauber beurteilbar, weil man
vielleicht dem einen Teil zustimmt und dem anderen nicht.
</granularitaet_zusammenfuehren_oder_trennen>

<praezision_keine_verschleierung>
Vermeide unentschiedene "oder"-Formulierungen wie "soll beibehalten oder verschärft
werden", wenn die Daten eine Richtung erkennen lassen -- dann nenne die Richtung klar.
Zeigen die Daten wirklich zwei unterschiedliche Lager (manche wollen beibehalten,
andere verschärfen), formuliere ZWEI separate Kandidaten statt einer vagen
Sowohl-als-auch-Formel. Eine unentschiedene Formulierung ist nur zulässig, wenn du sie
im Feld "datenluecken" explizit als offene Frage benennst, nicht im Kandidatentext
selbst.
</praezision_keine_verschleierung>

<jargon_erklaeren>
Fachbegriffe, benannte Modelle, Gesetzesnamen oder Analogien (z.B. "Stufentabelle",
"Modernisierungsumlage", "analog dem dänischen Modell", "GEG/GModG") müssen im
Kandidatentext selbst kurz (Halbsatz) erklärt werden, wenn sie nicht allgemein
bekannt sind. Nicht alle Teilnehmenden kennen diese Begriffe. Setze nichts als
bekannt voraus, was nicht in den Ursprungsdaten selbst erklärt wurde.
</jargon_erklaeren>

<was_ein_guter_kandidat_ist>
Ein Kandidat ist eine konkrete politische Aussage, der Teilnehmende zustimmen können.

KONKRETHEIT: So konkret wie die Datenlage es hergibt UND wie es die Cashore-Howlett-
Ebene (siehe oben) verlangt -- nicht mehr, nicht weniger. Erfinde KEINE Konkretheit,
die in den Daten nicht vorkommt.

VERANKERUNG: Jeder Kandidat muss sich auf tatsächliche Eingaben stützen. Du darfst
zusammenfassen, vereinheitlichen und das gemeinsame Anliegen mehrerer Beiträge
herausarbeiten. Du darfst NICHT Positionen erfinden, die niemand vertreten hat.

ANTI-VERWÄSSERUNG (kritisch): Eine Aussage, der praktisch jeder Mensch zustimmen würde,
ist KEIN gültiger Kandidat, sondern eine Leerformel. Teste jeden Kandidaten:
"Könnte eine Person mit einer gegenteiligen politischen Grundhaltung diesem Satz
ebenfalls zustimmen?" Wenn ja, ist er zu vage.
Ungültig: "Die Wärmewende soll sozial gerecht gestaltet werden."
Gültig: "Modernisierungskosten dürfen nur bis zu einer Obergrenze von X auf die Miete
umgelegt werden, darüber hinaus trägt sie der Eigentümer."

EHRLICHKEIT ÜBER DISSENS, ABER PRÜFE ERST OB ES ÜBERHAUPT EINER IST: Bevor du zwei
Standpunkte als "unvereinbar" markierst, prüfe, ob sie tatsächlich UNTERSCHIEDLICHE
HANDLUNGEN wollen, oder ob sie nur unterschiedlich BEGRÜNDET/GERAHMT sind, aber im
Kern dieselbe Handlung fordern (z.B. zwei Lager, die beide für ambitioniertes Vorgehen
sind, sich aber in der moralischen vs. wirtschaftlichen Begründung unterscheiden --
das ist KEIN Dissens über die Handlung, sondern nur über deren Rahmung, und gehört in
EINEN Kandidaten, der beide Begründungen benennt). Nur wenn wirklich unterschiedliche
Handlungen gewollt sind und keine Brücke in den Daten erkennbar ist, formuliere ZWEI
Kandidaten und markiere sie als sich ausschließend. Erzwinge aber auch keinen
Scheinkonsens, wo echte Handlungs-Differenzen bestehen -- benenne den wirklichen
Streitpunkt dann konkret und ehrlich, statt ihn hinter ähnlich klingenden Formulierungen
zu verstecken.
</was_ein_guter_kandidat_ist>

<anzahl>
Richtwert 2 bis 5 pro Dimension, aber die Anzahl ergibt sich aus der Granularitätsregel
oben, nicht aus einer Zielvorgabe -- lieber ein Kandidat mehr, wenn das echte
Vermischung vermeidet, als künstlich zusammenzufassen.
</anzahl>

<rückverfolgbarkeit>
Für jeden Kandidaten gibst du an:
- Auf welche Standpunkt-IDs und Teilnehmer-IDs er sich stützt (internes Feld
  "begruendung", darf IDs/Fachjargon enthalten -- das lesen nur wir, nicht
  die Teilnehmenden)
- Welche Kompromissvorschläge eingeflossen sind (mit Teilnehmer-ID)
- Welche bekannten Ablehnungen er voraussichtlich NICHT auflöst

ZUSÄTZLICH das Feld "nutzer_erklaerung": eine eigenständige, für Teilnehmende
lesbare Kurzfassung OHNE interne IDs oder Diskurs-Bezeichnungen -- wie ist die
Gruppe zu dieser Einschätzung gekommen, welche inhaltlichen Bedenken/
Gegenstimmen gab es, wie wurde damit umgegangen. 2-3 Sätze, journalistischer
Ton, für jemanden geschrieben, der die Diskursstruktur nicht kennt.
</rückverfolgbarkeit>

<ausgabeformat>
Antworte NUR mit validem JSON.
{
  "dimension": "Instrumententyp",
  "kandidaten": [
    {
      "id": "K-Tools-1",
      "aussage": "Die konkrete Policy-Empfehlung, 1-3 Sätze, so konkret wie die Daten und die Cashore-Howlett-Ebene erlauben, Fachbegriffe kurz erklärt",
      "begruendung": "INTERN, fuer die Nachvollziehbarkeit im Projekt: welche Standpunkt-IDs/Teilnehmer-IDs eingeflossen sind, welche Abwaegung getroffen wurde (2-3 Saetze, darf IDs/Fachjargon enthalten)",
      "nutzer_erklaerung": "FUER TEILNEHMENDE, die die Diskurs-Struktur NICHT kennen: 2-3 Saetze in einfacher Sprache, KEINE internen IDs (kein 'D3', kein 'Standpunkt X'), KEINE Diskurs-Namen. Erzaehle stattdessen: wie ist die Gruppe zu dieser Einschaetzung gekommen, welche Gegenstimmen/Bedenken gab es (inhaltlich beschrieben, nicht mit ID zitiert), wie wurde damit umgegangen. Wie eine kurze journalistische Erklaerung, nicht wie ein Datenbank-Log.",
      "stuetzt_sich_auf": {
        "standpunkte": ["D1-L1-S2", "D3-L2-S1"],
        "teilnehmende": ["P-043", "P-092", "P-368"],
        "kompromissvorschlaege": ["P-568: <Kurzzitat>"]
      },
      "ungeloeste_ablehnung": ["P-805: lehnt Marktmechanismen grundsätzlich ab"],
      "schliesst_aus": null
    }
  ],
  "dissens_notiz": "Falls in dieser Dimension kein Konsens möglich ist: worin genau der Konflikt besteht -- als echte Handlungs-Differenz, nicht nur unterschiedliche Rahmung.",
  "datenluecken": "Falls die Datenlage für konkrete Aussagen auf dieser Ebene zu dünn war, oder ein Standpunkt eigentlich zu einer anderen Dimension gehört hätte: was fehlt/passt nicht."
}
</ausgabeformat>
"""


def build_system_prompt(dim: str) -> str:
    fokus = _DIMENSION_FOKUS.get(dim, "")
    return (
        SYSTEM_PROMPT_BASE
        + "\n" + CASHORE_HOWLETT_MATRIX
        + f"\n<deine_ebene>\nDu bearbeitest gerade: {dim} ({fokus})\n</deine_ebene>\n"
    )


# Rueckwaertskompatibel fuer Aufrufer, die die statische Variante importieren
SYSTEM_PROMPT = SYSTEM_PROMPT_BASE + "\n" + CASHORE_HOWLETT_MATRIX


# ── Dossier -> lesbarer Kontext fuer den Prompt ─────────────────────────

def _format_standpunkt(sp, lager_kommentare):
    u = sp["unterstuetzung"]
    zeilen = [
        f"### Standpunkt {sp['id']} -- \"{sp['titel']}\"",
        f"(Diskurs {sp['diskurs_id']} \"{sp['diskurs_titel']}\", Sichtweise \"{sp['lager_titel']}\")",
        f"Position: {sp['position']}",
    ]
    if sp.get("minderheitsposition"):
        zeilen.append(
            "HINWEIS: dieser Standpunkt hat im No-Objection-Filterverfahren einen echten, aber "
            "verhaeltnismaessig kleinen Widerspruch ueberstanden -- formuliere ihn entsprechend "
            "vorsichtig/als Minderheitsposition, nicht als unumstrittenen Konsens."
        )
    if sp.get("setzt_voraus"):
        zeilen.append(f"Baut auf: {sp['setzt_voraus']}")

    if u["n_bewertet"]:
        zeilen.append(
            f"Unterstuetzung: n={u['n_bewertet']}, Mittelwert={u['mittelwert']}, "
            f"Verteilung(1-5)={u['verteilung']}, Befuerwortung(4-5)={u['befuerwortung_4_5']}, "
            f"Ablehnung(1-2)={u['ablehnung_1_2']} (direkt={u['n_direkt']}, "
            f"vererbt_von_lager={u['n_vererbt_von_lager']})"
        )
    else:
        zeilen.append("Unterstuetzung: keine Bewertungen vorhanden.")

    if sp["ursprungszitate"]:
        zeilen.append("Ursprungszitate aus Sitzung 1:")
        for z in sp["ursprungszitate"]:
            zeilen.append(f"  - {z['participant_id']}: \"{z['zitat']}\"")

    if u["kommentare"]:
        zeilen.append("Direkte Kommentare zu DIESEM Standpunkt:")
        for k in u["kommentare"]:
            zeilen.append(f"  - {k['participant_id']} (Wert {k['quelle']}): {k['kommentar']}")

    ablehnungen = [b for b in u["bewertungen"] if b["wert"] <= 2]
    if ablehnungen:
        zeilen.append("Ablehnungen (Wert 1-2):")
        for a in ablehnungen:
            begruendung = next(
                (k["kommentar"] for k in u["kommentare"] if k["participant_id"] == a["participant_id"]),
                None,
            )
            if not begruendung:
                begruendung = next(
                    (lk["kommentar"] for lk in lager_kommentare if lk["participant_id"] == a["participant_id"]),
                    None,
                )
            zeilen.append(
                f"  - {a['participant_id']} (Wert {a['wert']}, {a['quelle']})"
                + (f": {begruendung}" if begruendung else " (keine Begruendung angegeben)")
            )

    return "\n".join(zeilen)


def format_dimension_context(dim, dossier):
    teile = [f"# Dossier fuer Dimension: {dim}\n"]

    # Standpunkte gruppiert nach Lager, damit Lager-Kommentare im Kontext stehen
    from collections import defaultdict
    nach_lager = defaultdict(list)
    for sp in dossier["standpunkte"]:
        nach_lager[sp["lager_id"]].append(sp)

    for lager_id, sps in nach_lager.items():
        teile.append(f"\n## Sichtweise {lager_id} -- \"{sps[0]['lager_titel']}\" "
                      f"(Diskurs {sps[0]['diskurs_id']}: \"{sps[0]['diskurs_titel']}\")")
        lager_kommentare = dossier["lager_kommentare"].get(lager_id, [])
        if lager_kommentare:
            teile.append("Kommentare zur GESAMTEN Sichtweise (gelten fuer alle Standpunkte darunter):")
            for k in lager_kommentare:
                teile.append(f"  - {k['participant_id']} (Wert {k['wert']}): {k['kommentar']}")
        for sp in sps:
            teile.append("")
            teile.append(_format_standpunkt(sp, lager_kommentare))

    kompromisse = dossier.get("diskurs_kompromissvorschlaege", {})
    alle_kompromisse = [k for liste in kompromisse.values() for k in liste]
    teile.append("\n## Kompromissvorschlaege (dediziertes Feld, diskursweit)")
    if alle_kompromisse:
        for k in alle_kompromisse:
            teile.append(f"  - {k['participant_id']}: {k['text']}")
    else:
        teile.append("  Keine vorhanden (Feld wird von den Teilnehmenden nicht genutzt -- "
                      "Kompromissvorschlaege stecken stattdessen in den Sichtweisen-Kommentaren oben).")

    return "\n".join(teile)


# ── LLM-Aufruf ───────────────────────────────────────────────────────

def _parse_response(raw_text, dim):
    text = raw_text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    # strict=False erlaubt rohe Kontrollzeichen (z.B. ein nicht escapetes
    # Newline) innerhalb von JSON-Strings -- kommt gelegentlich vor, wenn
    # das Modell in einer laengeren Aussage versehentlich einen Zeilenumbruch
    # nicht als \n escaped.
    ergebnis = json.loads(text, strict=False)

    # Kandidaten-IDs sind vom Modell NICHT global eindeutig vergeben --
    # verschiedene Dimensionen erzeugen unabhaengig voneinander IDs wie
    # "K-Ziele-1" (beobachtet bei "Übergeordnete Ziele" UND "Konkrete
    # Ziele" gleichzeitig, echte Kollision in echten Laeufen). Statt das
    # erst in einem spaeteren Pipeline-Schritt zu reparieren, wird die
    # Eindeutigkeit hier an der Quelle erzwungen: jede ID bekommt sofort
    # ein dimensionsspezifisches Suffix, kanonisch fuer alle nachfolgenden
    # Schritte (Filterung, Kohaerenzpruefung, Empfehlungsdokument).
    dim_kurz = DIMENSION_KURZNAME.get(dim, dim)
    id_map = {}
    for kand in ergebnis.get("kandidaten", []):
        alte_id = kand["id"]
        neue_id = f"{alte_id}__{dim_kurz}"
        id_map[alte_id] = neue_id
        kand["id"] = neue_id
    for kand in ergebnis.get("kandidaten", []):
        aus = kand.get("schliesst_aus")
        if isinstance(aus, list):
            kand["schliesst_aus"] = [id_map.get(a, a) for a in aus]
        elif isinstance(aus, str) and aus in id_map:
            kand["schliesst_aus"] = id_map[aus]

        # Modell haengt "kompromissvorschlaege" manchmal als Geschwister-
        # Feld statt wie im Schema unter "stuetzt_sich_auf" verschachtelt --
        # hier normalisiert, damit Schritt 3 sich auf eine feste Struktur
        # verlassen kann, ohne den Prompt neu zu formulieren und erneut
        # zu bezahlen.
        if "kompromissvorschlaege" in kand and "stuetzt_sich_auf" in kand:
            kand["stuetzt_sich_auf"].setdefault(
                "kompromissvorschlaege", kand.pop("kompromissvorschlaege")
            )
    return ergebnis


def synthese_fuer_dimension(client, model, dim, dossier, use_thinking=False):
    """max_tokens hoch genug fuer Extended Thinking + die eigentliche JSON-
    Antwort -- Standard-Verhalten von claude-sonnet-5 ist adaptives
    Thinking, das bei einem knappen max_tokens-Budget fast den gesamten
    Platz aufbraucht und die JSON-Antwort mitten im String abschneidet
    (stop_reason "max_tokens"). Gleiches Muster wie in
    session2_clustering_v4think.py: thinking standardmaessig explizit
    deaktivieren, max_tokens grosszuegig."""
    kontext = format_dimension_context(dim, dossier)
    stream_kwargs = dict(
        model=model,
        max_tokens=64000,
        system=[{"type": "text", "text": build_system_prompt(dim)}],
        messages=[{"role": "user", "content": kontext}],
    )
    if use_thinking:
        stream_kwargs["thinking"] = {"type": "adaptive"}
        stream_kwargs["output_config"] = {"effort": "high"}
    else:
        stream_kwargs["thinking"] = {"type": "disabled"}

    # max_tokens=64000 verlangt Streaming (SDK-Limit bei Requests > 10 Min,
    # siehe session2_clustering_v4think.py, gleiches Muster).
    with client.messages.stream(**stream_kwargs) as stream:
        for _ in stream.text_stream:
            pass
        resp = stream.get_final_message()

    if resp.stop_reason == "max_tokens":
        return {
            "dimension": dim, "kandidaten": [], "dissens_notiz": None, "datenluecken": None,
            "_parsefehler": "max_tokens erreicht, Antwort unvollstaendig",
        }
    raw = "".join(b.text for b in resp.content if b.type == "text")
    try:
        return _parse_response(raw, dim)
    except (ValueError, json.JSONDecodeError) as exc:
        return {
            "dimension": dim,
            "kandidaten": [],
            "dissens_notiz": None,
            "datenluecken": None,
            "_parsefehler": str(exc),
            "_rohantwort": raw,
        }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--tag", default="")
    parser.add_argument("--dimension", default=None,
                         help="Nur eine Dimension synthetisieren (exakter Name, z.B. 'Instrumententyp')")
    parser.add_argument("--thinking", action="store_true", help="Extended Thinking aktivieren")
    args = parser.parse_args()

    with open(DOSSIERS_PATH, encoding="utf-8") as f:
        dossiers = json.load(f)

    if args.dimension:
        if args.dimension not in dossiers:
            print(f"Unbekannte Dimension '{args.dimension}'. Verfuegbar: {list(dossiers.keys())}")
            return
        ziel_dimensionen = {args.dimension: dossiers[args.dimension]}
    else:
        ziel_dimensionen = dossiers

    client = Anthropic()

    # bestehende kanonische Datei laden, damit --dimension einzelne
    # Eintraege ergaenzen/ueberschreiben kann statt alles zu verwerfen
    ergebnis = {"generated_at": None, "model": args.model, "dimensionen": {}}
    if os.path.exists(OUTPUT_PATH):
        with open(OUTPUT_PATH, encoding="utf-8") as f:
            ergebnis = json.load(f)

    for dim, dossier in ziel_dimensionen.items():
        print(f"Synthetisiere: {dim} ...")
        try:
            kandidaten_json = synthese_fuer_dimension(client, args.model, dim, dossier, args.thinking)
        except AnthropicError as exc:
            print(f"  FEHLER bei {dim}: {exc}")
            continue
        n = len(kandidaten_json.get("kandidaten", []))
        parsefehler = kandidaten_json.get("_parsefehler")
        if parsefehler:
            print(f"  WARNUNG: JSON-Parsing fehlgeschlagen ({parsefehler}) -- Rohantwort gespeichert.")
        else:
            print(f"  {n} Kandidat(en) formuliert.")
        ergebnis["dimensionen"][dim] = kandidaten_json

    ergebnis["generated_at"] = datetime.datetime.now().isoformat(timespec="seconds")
    ergebnis["model"] = args.model

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(ergebnis, f, ensure_ascii=False, indent=2)
    print(f"\nGeschrieben: {OUTPUT_PATH}")

    timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    tag_part = f"_{args.tag}" if args.tag else ""
    archive_path = Path(RUNS_DIR) / f"kandidaten_{timestamp}_{args.model}{tag_part}.json"
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with open(archive_path, "w", encoding="utf-8") as f:
        json.dump(ergebnis, f, ensure_ascii=False, indent=2)
    print(f"Archiviert: {archive_path}")


if __name__ == "__main__":
    main()

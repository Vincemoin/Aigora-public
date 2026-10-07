"""
session2_clustering_v4.py

Zweistufige Clustering-Pipeline fuer Sitzung 2:

Schritt 1 (ein globaler Call): alle ratifizierten Positionen aus allen sechs
Dimensionen -> Diskurse identifizieren + unwidersprochene Punkte erkennen.
Jede Position wird EINEM Diskurs zugeordnet ODER als unwidersprochen markiert.

Schritt 2 (ein Call PRO Diskurs): die zugeordneten Positionen -> Lager
bilden, Standpunkte formulieren, Abhaengigkeiten markieren, Uebersicht
schreiben. Participant-IDs werden NICHT vom Modell ausgegeben, sondern per
REF-Nummern in Python zurueckgemappt (verhindert erfundene IDs strukturell).

Schritt 3 (Vollstaendigkeits-Netz, in Python, kein LLM-Call): jede Position,
die weder einem Diskurs noch der Unwidersprochen-Liste zugeordnet wurde
(z.B. durch einen Modellfehler), wird automatisch dem in Schritt 1
angegebenen "naheliegendster_diskurs" nachgereicht, BEVOR Schritt 2 laeuft --
so verschwindet nichts stillschweigend.

Ergebnis: data/session2_diskurse.json (kanonisch) + archivierte, zeit-
gestempelte Kopie unter data/session2_runs/, damit parallele Laeufe
(z.B. verschiedene Prompt-Versionen) sich nicht gegenseitig ueberschreiben.

Nutzung:
    python session2_clustering_v4.py [--thinking] [--model MODEL] [--tag LABEL]
"""

import argparse
import datetime
import glob
import json
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

from anthropic import Anthropic, AnthropicError

# DeepSeek laeuft ueber die Anthropic-kompatible SDK-Schnittstelle
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_DEFAULT_MODEL = "deepseek-chat"  # = DeepSeek-V3; fuer V4 Pro: "deepseek-reasoner" 

load_dotenv()

DEFAULT_MODEL = "claude-sonnet-5"
PROFILES_DIR = "extracted_profiles"
OUTPUT_JSON = "data/session2_diskurse.json"
RUNS_DIR = "data/session2_runs"

DIMENSION_ORDER = ["Goals", "Objectives", "Settings", "InstrumentLogic", "Tools", "Calibrations"]
DIMENSION_NAMES_DE = {
    "Goals": "Übergeordnete Ziele",
    "Objectives": "Konkrete Ziele",
    "Settings": "Zwischenziele",
    "InstrumentLogic": "Umsetzungslogik",
    "Tools": "Instrumententyp",
    "Calibrations": "Feinausgestaltung",
}

# =====================================================================
# SCHRITT 1: Globale Diskurs-Erkennung + unwidersprochene Punkte
# =====================================================================

STEP1_SYSTEM_PROMPT = """\
<aufgabe>
Du analysierst alle ratifizierten Positionen einer politischen Debatte zur deutschen Wärmewende. Die Positionen stammen aus sechs Politik-Dimensionen (Übergeordnete Ziele, Konkrete Ziele, Zwischenziele, Umsetzungslogik, Instrumententyp, Feinausgestaltung), werden dir aber UNGETRENNT vorgelegt.

Deine Aufgabe hat zwei Teile:
1. Identifiziere die grundlegenden STREITFRAGEN (Diskurse), an denen sich die Meinungen teilen.
2. Identifiziere UNWIDERSPROCHENE PUNKTE: Positionen, denen im gesamten Datensatz niemand widerspricht, auch nicht indirekt.

Ordne JEDE einzelne Position genau EINER dieser beiden Kategorien zu. Keine Position darf verloren gehen.
</aufgabe>

<positionsreferenzen>
Jede Position im Input hat eine eindeutige Referenz im Format [REF-001]. Verwende in deiner Ausgabe AUSSCHLIESSLICH diese REF-Nummern, um Positionen zuzuordnen. Erfinde KEINE eigenen Referenzen und verändere KEINE bestehenden.
</positionsreferenzen>

<diskurs_erkennung>
Ein Diskurs ist eine grundlegende Streitfrage, an der sich die Meinungen teilen. Er ist KEINE Position, sondern eine Achse, entlang derer sich Positionen unterscheiden.

ZENTRALE UNTERSCHEIDUNG — gruppiere nach GRUNDFRAGE, nicht nach THEMA:

Zwei Positionen zu unterschiedlichen THEMEN gehören in denselben Diskurs, wenn sie erkennbar aus derselben grundsätzlichen Überzeugung folgen. Beispiel: "CO2-Preis statt Sanierungspflicht" und "keine staatliche Technologievorgabe" handeln von verschiedenen Themen, folgen aber derselben Grundhaltung (Markt vor Staat).

Zwei Positionen zum SELBEN Thema gehören NICHT automatisch zusammen, wenn sie tatsächlich verschiedenen Grundphilosophien folgen.

TEST: Würde eine Person, die Position A vertritt, Position B als "anderer Akzent meiner eigenen Grundhaltung" beschreiben? → selber Diskurs. Würde sie sagen "das sehe ich grundsätzlich anders"? → verschiedene Seiten desselben Diskurses (wenn dieselbe Streitfrage) oder verschiedene Diskurse (wenn verschiedene Streitfragen).

TRENNSCHÄRFE-TEST: Zwei Positionen gehören in verschiedene Diskurse, wenn eine Person bei Diskurs A Ja und bei Diskurs B Nein sagen könnte, ohne sich zu widersprechen. Wenn das nicht möglich ist -- wenn die Antwort auf Frage A die Antwort auf Frage B weitgehend bestimmt -- sind es keine zwei unabhängigen Grundfragen, sondern eine.

Beispiel für FALSCHE Trennung: "Wie ambitioniert sollen die CO2-Ziele sein?" und "Wann soll das Enddatum für fossile Heizungen kommen?" scheinen verschiedene Fragen, sind aber in der Praxis dieselbe Grundfrage ("Wie schnell und wie verbindlich soll die Transformation sein?") -- wer ein frühes Enddatum will, will fast immer auch ambitionierte CO2-Ziele, und umgekehrt. Trenne sie nicht.

Beispiel für RICHTIGE Trennung: "Soll der Staat per Ordnungsrecht eingreifen oder Märkte steuern?" und "Wer trägt die Kosten -- Vermieter, Mieter oder Staat?" sind echte unabhängige Fragen -- man kann Marktsteuerung bevorzugen und trotzdem für Mieterschutz sein, oder umgekehrt.

PRÜFSCHRITT VOR AUSGABE: Gehe jeden identifizierten Diskurs durch und frage: "Gibt es im Datensatz Personen, die bei diesem Diskurs auf einer Seite stehen, aber bei einem anderen Diskurs auf der anderen?" Wenn ja, sind es wirklich verschiedene Diskurse. Wenn du das für ein Paar nicht belegen kannst, lege sie zusammen.

DIMENSIONSUNABHÄNGIGKEIT: Ein Diskurs kann Positionen aus mehreren der sechs Dimensionen bündeln. Die Herkunfts-Dimension schränkt die Zuordnung NICHT ein.
</diskurs_erkennung>

<unwidersprochene_punkte>
EINZIGES KRITERIUM, unabhängig von der Anzahl der Personen dahinter: Widerspricht IRGENDEINE Position im gesamten Datensatz diesem Punkt, direkt oder indirekt? Wenn ja: gehört er zwingend zu einem Diskurs (auch als sehr kleiner, ggf. Ein-Personen-Standpunkt), NICHT auf diese Liste. Wenn NIRGENDS im Datensatz Widerspruch erkennbar ist: unwidersprochener Punkt, unabhängig davon ob 1 oder 15 Personen dahinterstehen.

PRÜFUNG DER INDIREKTHEIT: Widerspruch muss nicht explizit gegen denselben Wortlaut gerichtet sein. Beispiel: "Mieter müssen vor unverhältnismäßigen Kosten geschützt werden" hat einen indirekten Widerspruch, wenn irgendwo im Datensatz steht "Eigentümerrechte haben absoluten Vorrang vor Mieterinteressen" — auch wenn diese Position Mieterschutz nicht explizit ablehnt, steht sie in echter Spannung dazu. Prüfe für JEDEN Kandidaten aktiv: gibt es eine Position, die diesem Punkt Priorität, Umfang oder Umsetzung streitig machen würde? Nur wenn diese Prüfung eindeutig negativ ausfällt, gehört der Punkt auf die Liste.

REIHENFOLGE: Prüfe IMMER zuerst, ob eine Position in einen (bestehenden oder neu zu bildenden) Diskurs passt. Die Unwidersprochen-Liste ist der Fall, der übrig bleibt, nicht der Standardfall.

Vermeide Verwechslung mit Abstraktion: "Klimaschutz ist wichtig" gehört nicht auf die Liste, weil es zu vage ist, um überhaupt widersprochen werden zu können — es ist keine politische Position mit erkennbarem Gehalt, sondern eine Floskel. Nur Punkte mit konkretem politischem Gehalt UND echter Widerspruchsfreiheit gehören auf die Liste.
</unwidersprochene_punkte>

<ausgabeformat>
Antworte NUR mit validem JSON, kein Text davor oder danach.

{
  "diskurse": [
    {
      "id": "D1",
      "titel": "kurzer, sprechender Titel (3-8 Wörter)",
      "streitfrage": "Die zentrale Frage dieses Diskurses als Frage formuliert (1 Satz)",
      "refs": ["REF-001", "REF-003", "REF-017"]
    }
  ],
  "unwidersprochene_punkte": [
    {
      "id": "U1",
      "titel": "kurzer Titel",
      "beschreibung": "Was dieser Punkt aussagt und warum er unwidersprochen ist (2-3 Sätze)",
      "refs": ["REF-005", "REF-012"]
    }
  ],
  "anmerkungen": "Grenzfälle, schwer einzuordnende Positionen, methodische Unsicherheiten."
}
</ausgabeformat>"""

# =====================================================================
# SCHRITT 2: Diskurs-interne Strukturierung (pro Diskurs einzeln)
# =====================================================================

STEP2_SYSTEM_PROMPT = """\
<aufgabe>
Du strukturierst die Debatte INNERHALB EINES Diskurses (Streitfrage) einer politischen Deliberation zur deutschen Wärmewende. Dir werden alle Positionen gezeigt, die diesem Diskurs zugeordnet wurden, zusammen mit der Streitfrage.

Deine Aufgabe: Lager identifizieren, Standpunkte formulieren, logische Abhängigkeiten markieren, und eine verständliche Übersicht schreiben.
</aufgabe>

<positionsreferenzen>
Jede Position im Input hat eine eindeutige Referenz im Format [REF-xxx]. Verwende in der `refs`-Liste jedes Standpunkts AUSSCHLIESSLICH diese REF-Nummern. Erfinde KEINE eigenen Referenzen. Jede REF aus dem Input muss in GENAU EINEM Standpunkt auftauchen.
</positionsreferenzen>

<lager>
Ein Lager bündelt Standpunkte, die auf dieselbe Grundfrage ähnlich antworten. Jeder Diskurs hat mindestens 2 Lager (die verschiedenen Seiten der Streitfrage), maximal 4. Mehr als 4 → prüfe, ob sich Lager zusammenlegen lassen, ohne echte Unterschiede zu verwischen.

Jedes Lager bekommt einen kurzen Titel und ZWEI Textfelder:

1. `kernaussage` (1-2 Sätze): der gemeinsame Nenner ALLER Standpunkte dieses Lagers. Muss etwas Substanzielles aussagen — eine Formulierung, der praktisch jede Person zustimmen würde, ist Verwässerung.

2. `bandbreite` (1-2 Sätze): wie weit die Positionen innerhalb dieses Lagers auseinandergehen. Beispiel: "Die Vorstellungen reichen von behutsam steigenden Preisanreizen bis zur vollständigen Abschaffung aller Förderprogramme." Gibt es keine nennenswerte Spannweite (alle Standpunkte liegen eng beieinander), schreibe das kurz hin statt eine künstliche Bandbreite zu konstruieren.

WARUM DIE BANDBREITE PFLICHT IST: Teilnehmende können dem Lager als Ganzem zustimmen, ohne jeden einzelnen Standpunkt darunter zu lesen. Ihre Zustimmung gilt dann automatisch für ALLE Standpunkte des Lagers. Kernaussage und Bandbreite zusammen müssen deshalb ausreichen, um zu verstehen, wozu man da Ja sagt. Verstecke keine Nuance, die jemanden nachträglich überraschen würde, und beschönige keine radikale Position innerhalb des Lagers durch eine moderate Kernaussage.
</lager>

<standpunkte>
Innerhalb jedes Lagers gibt es 1-5 Standpunkte: tatsächliche, zustimmungsfähige Positionen, hinter denen mindestens eine Person steht.

ORDNUNG: Ordne die Standpunkte innerhalb jedes Lagers von der abstraktesten zur konkretesten Position. Markiere die Abstraktionsebene jedes Standpunkts:
- "Übergeordnete Ziele" (allgemeinste Ebene)
- "Konkrete Ziele"
- "Zwischenziele"
- "Umsetzungslogik"
- "Instrumententyp"
- "Feinausgestaltung" (konkreteste Ebene)

Die Abstraktionsebene des Standpunkts ergibt sich aus seinem INHALT, nicht automatisch aus der Herkunfts-Dimension der zugeordneten Positionen.

FORMULIERUNG: Formuliere jeden Standpunkt so, dass die zugeordneten Personen sagen würden: "Ja, das trifft meinen Punkt." KEIN Standpunkt darf so vage sein, dass praktisch jede Person zustimmen würde.

VOLLSTÄNDIGKEIT: JEDE REF aus dem Input muss genau einem Standpunkt zugeordnet sein. Auch eine einzigartige Position bekommt einen eigenen Standpunkt, notfalls mit nur einer Person.
</standpunkte>

<abhaengigkeiten>
LOGISCHE ABHÄNGIGKEITEN — NUR WO SIE ECHT SIND:

Manche konkreteren Standpunkte setzen einen abstrakteren Standpunkt LOGISCH voraus. Beispiel: "CO2-Preis bei 65€/t, jährlich +15€" setzt "CO2-Bepreisung als Leitinstrument" voraus — wer das Instrument ablehnt, für den ist die Kalibrierung gegenstandslos.

Andere Standpunkte im selben Lager sind thematisch verwandt aber LOGISCH UNABHÄNGIG. Beispiel: "Bürokratieabbau bei Förderanträgen" und "CO2-Bepreisung" können beide im Lager "Marktgetrieben" stehen, ohne dass eins das andere voraussetzt.

Markiere Abhängigkeiten EXPLIZIT mit `setzt_voraus` (ID des vorausgesetzten Standpunkts).

WICHTIG: Im Zweifel KEINE Abhängigkeit markieren. Falsche Abhängigkeiten unterdrücken Bewertungen (schlimm). Fehlende Abhängigkeiten erzeugen nur eine zusätzliche, ggf. redundante Bewertung (harmlos).
</abhaengigkeiten>

<uebersicht>
Schreibe eine ÜBERSICHT: 3-5 flüssig lesbare Sätze, die den Kernkonflikt dieses Diskurses für jemanden zusammenfassen, der die Debatte zum ersten Mal sieht. Journalistischer Stil, keine IDs, keine Fachbegriffe. Benenne die Lager mit ihren Kernargumenten und wo die zentrale Spannung liegt. Muss für sich allein verständlich sein.
</uebersicht>

<qualitaetspruefung>
Prüfe vor der Ausgabe:
1. Ist jede REF aus dem Input genau einem Standpunkt zugeordnet?
2. Hat jeder Diskurs mindestens 2 Lager?
3. Würde irgendein Standpunkt- oder Lager-Text von praktisch JEDER Person unterschrieben? → Präziser formulieren.
4. Ist jede `setzt_voraus`-Verbindung eine ECHTE logische Voraussetzung? → Im Zweifel entfernen.
5. Wenn jemand NUR Kernaussage und Bandbreite eines Lagers liest und zustimmt: gäbe es darunter einen Standpunkt, von dem diese Person überrascht wäre? → Bandbreite ehrlicher formulieren.
</qualitaetspruefung>

<ausgabeformat>
Antworte NUR mit validem JSON, kein Text davor oder danach.

{
  "uebersicht": "3-5 Sätze Fließtext, journalistisch",
  "lager": [
    {
      "id": "D1-L1",
      "titel": "kurzer Lager-Titel (2-5 Wörter)",
      "kernaussage": "Der gemeinsame Nenner aller Standpunkte dieses Lagers (1-2 Sätze)",
      "bandbreite": "Wie weit die Positionen innerhalb des Lagers auseinandergehen (1-2 Sätze)",
      "standpunkte": [
        {
          "id": "D1-L1-S1",
          "titel": "kurzer Standpunkt-Titel",
          "abstraktionsebene": "Übergeordnete Ziele",
          "position": "Was dieser Standpunkt aussagt (2-4 Sätze)",
          "setzt_voraus": null,
          "refs": ["REF-001", "REF-017"]
        }
      ]
    }
  ]
}
</ausgabeformat>"""


# =====================================================================
# Hilfsfunktionen
# =====================================================================

def load_all_positions():
    """Laedt alle ratifizierten Positionen. Dimensionsnamen SOFORT deutsch,
    einheitlich im gesamten Datenfluss."""
    all_positions = []
    for path in sorted(glob.glob(f"{PROFILES_DIR}/*_extracted.json")):
        with open(path, encoding="utf-8") as f:
            profile = json.load(f)
        pid = profile.get("participant_id") or Path(path).stem.replace("_extracted", "")
        for dim in DIMENSION_ORDER:
            for entry in profile.get("dimensions", {}).get(dim, []):
                all_positions.append({
                    "participant_id": pid,
                    "herkunft_dimension": DIMENSION_NAMES_DE[dim],
                    "position": entry["position"],
                    "reasoning": entry["reasoning"],
                    "breadth": entry.get("breadth", ""),
                })
    return all_positions


def build_ref_index(positions):
    """Erstellt REF-001..REF-NNN Zuordnung. Mutiert positions in-place (fuegt 'ref' hinzu)."""
    ref_map = {}
    for i, pos in enumerate(positions, 1):
        ref_id = f"REF-{i:03d}"
        pos["ref"] = ref_id
        ref_map[ref_id] = pos
    return ref_map


def build_step1_message(positions):
    lines = [f"RATIFIZIERTE POSITIONEN ({len(positions)} Positionen aus allen sechs Dimensionen):\n"]
    for p in positions:
        lines.append(f"[{p['ref']}]\nPosition: {p['position']}\nBegründung: {p['reasoning']}\n")
    lines.append("\nIdentifiziere die Diskurse und unwidersprochenen Punkte gemäß deiner Systemanweisung.")
    return "\n".join(lines)


def build_step2_message(discourse_title, streitfrage, positions_for_discourse):
    lines = [
        f"DISKURS: {discourse_title}",
        f"STREITFRAGE: {streitfrage}",
        f"\nZUGEORDNETE POSITIONEN ({len(positions_for_discourse)} Positionen):\n",
    ]
    for p in positions_for_discourse:
        lines.append(f"[{p['ref']}]\nPosition: {p['position']}\nBegründung: {p['reasoning']}\n")
    lines.append("\nStrukturiere diesen Diskurs gemäß deiner Systemanweisung (Lager, Standpunkte, Abhängigkeiten, Übersicht).")
    return "\n".join(lines)


def resolve_refs_to_mitglieder(obj, ref_map):
    """Ersetzt 'refs'-Listen auf Standpunkt-Ebene durch 'mitglieder' mit echten Teilnehmerdaten."""
    if isinstance(obj, dict):
        if "refs" in obj and "standpunkte" not in obj and "lager" not in obj:
            refs = obj.pop("refs", [])
            mitglieder = []
            for ref_id in refs:
                if ref_id in ref_map:
                    pos = ref_map[ref_id]
                    mitglieder.append({
                        "participant_id": pos["participant_id"],
                        "herkunft_dimension": pos["herkunft_dimension"],
                        "zitat": pos["position"][:300],
                    })
                else:
                    mitglieder.append({
                        "participant_id": f"UNBEKANNT ({ref_id})",
                        "herkunft_dimension": "?",
                        "zitat": f"Referenz {ref_id} nicht gefunden",
                    })
            obj["mitglieder"] = mitglieder
        for v in obj.values():
            resolve_refs_to_mitglieder(v, ref_map)
    elif isinstance(obj, list):
        for item in obj:
            resolve_refs_to_mitglieder(item, ref_map)


def parse_json_response(raw_text, label=""):
    """Extrahiert JSON aus der Modellantwort, mit mehreren Reparaturversuchen."""
    if not raw_text.strip():
        raise ValueError(f"Leere Antwort{' bei ' + label if label else ''}")

    cleaned = re.sub(r"^```(?:json)?|```$", "", raw_text.strip(), flags=re.MULTILINE).strip()

    for parser in [
        lambda s: json.loads(s),
        lambda s: json.loads(s, strict=False),
        lambda s: json.loads(re.sub(r':\s*\["([^"]*)"\]', r': "\1"', s), strict=False),
        lambda s: json.JSONDecoder(strict=False).raw_decode(s)[0],
    ]:
        try:
            return parser(cleaned)
        except (json.JSONDecodeError, ValueError):
            continue

    # Letzter Versuch: groessten parsbaren "{"-Block im Text finden (falls
    # das Modell sich mitten in der Antwort selbst korrigiert hat).
    decoder = json.JSONDecoder(strict=False)
    best, best_len = None, -1
    for pos in [m.start() for m in re.finditer(r"\{", cleaned)]:
        try:
            obj, end = decoder.raw_decode(cleaned[pos:])
        except (json.JSONDecodeError, ValueError):
            continue
        if end > best_len:
            best, best_len = obj, end
    if best is not None:
        return best

    error_path = f"session2_RAW_FEHLER_{label or 'unknown'}.txt"
    with open(error_path, "w", encoding="utf-8") as f:
        f.write(cleaned)
    raise ValueError(f"JSON-Parse fehlgeschlagen (Rohtext: {error_path})")


def call_llm(client, system_prompt, user_message, model, use_thinking, label="", provider="anthropic"):
    """LLM-Call, kompatibel mit Anthropic und DeepSeek.

    DeepSeek laeuft ueber die Anthropic-SDK (kompatible REST-API), akzeptiert
    aber kein `thinking`-Parameter und kein system-dict mit type-Feld.
    Deshalb separate Code-Pfade je nach provider.
    """
    max_tokens = 64000
    thinking_status = ("adaptive/high" if (provider == "anthropic" and use_thinking)
                       else ("aus" if provider == "anthropic" else "n/a"))
    print(f"  [{label}] Rufe {model} auf (provider={provider}, thinking={thinking_status})...")

    if provider == "deepseek":
        # DeepSeek: kein thinking-Parameter, system als einfacher String,
        # aber Streaming noetig wegen Timeout bei langen Requests
        with client.messages.stream(
            model=model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        ) as stream:
            for _ in stream.text_stream:
                pass
            response = stream.get_final_message()
        if response.stop_reason == "max_tokens":
            raise ValueError(f"max_tokens erreicht bei [{label}]")
        raw_text = "".join(
            b.text for b in response.content
            if getattr(b, "type", None) == "text"
        )
    else:
        # Anthropic: Sonnet 5 nutzt adaptive Thinking + effort-Parameter
        # (thinking.type "enabled" mit budget_tokens ist bei diesem Modell
        # nicht mehr unterstuetzt, siehe Anthropic-Doku zu Adaptive Thinking).
        stream_kwargs = dict(
            model=model,
            max_tokens=max_tokens,
            system=[{"type": "text", "text": system_prompt}],
            messages=[{"role": "user", "content": user_message}],
        )
        if use_thinking:
            stream_kwargs["thinking"] = {"type": "adaptive"}
            stream_kwargs["output_config"] = {"effort": "high"}
        else:
            stream_kwargs["thinking"] = {"type": "disabled"}

        with client.messages.stream(**stream_kwargs) as stream:
            for _ in stream.text_stream:
                pass
            response = stream.get_final_message()
        if response.stop_reason == "max_tokens":
            raise ValueError(f"max_tokens erreicht bei [{label}] -- Antwort unvollstaendig, Retry")
        raw_text = "".join(
            b.text for b in response.content
            if getattr(b, "type", None) == "text"
        )

    return parse_json_response(raw_text, label)


# =====================================================================
# Hauptlogik
# =====================================================================

def run_step1(client, positions, ref_map, model, use_thinking):
    print(f"\n{'='*60}")
    print(f"SCHRITT 1: Globale Diskurs-Erkennung ({len(positions)} Positionen)")
    print(f"{'='*60}")

    user_message = build_step1_message(positions)
    result = call_llm(client, STEP1_SYSTEM_PROMPT, user_message, model, use_thinking, "Schritt1", provider=_ACTIVE_PROVIDER)

    all_input_refs = set(ref_map.keys())
    assigned_refs = set()
    for d in result.get("diskurse", []):
        assigned_refs.update(d.get("refs", []))
    for u in result.get("unwidersprochene_punkte", []):
        assigned_refs.update(u.get("refs", []))

    missing = all_input_refs - assigned_refs
    unknown = assigned_refs - all_input_refs

    if missing:
        print(f"  Hinweis: {len(missing)} Positionen nicht zugeordnet -- werden per Vollstaendigkeits-Netz nachgereicht.")
    if unknown:
        print(f"  WARNUNG: {len(unknown)} unbekannte Referenzen im Output: {sorted(unknown)[:10]}")

    diskurse = result.get("diskurse", [])
    unwidersprochen = result.get("unwidersprochene_punkte", [])
    print(f"\n  Ergebnis: {len(diskurse)} Diskurse, {len(unwidersprochen)} unwidersprochene Punkte")
    for d in diskurse:
        print(f"    [{d['id']}] {d['titel']} ({len(d.get('refs', []))} Positionen)")
    for u in unwidersprochen:
        print(f"    [{u['id']}] UNWIDERSPROCHEN: {u['titel']} ({len(u.get('refs', []))} Positionen)")

    return result, missing, unknown


def patch_missing_into_nearest_discourse(step1_result, missing_refs, ref_map, client, model, use_thinking):
    """Vollstaendigkeits-Netz (Fix 1, in Python, kein LLM-Call fuer die
    Zuordnung selbst): fuer jede in Schritt 1 uebrig gebliebene REF wird EIN
    kompakter Klassifikations-Call gemacht, der NUR entscheidet, zu welchem
    der bereits gefundenen Diskurse sie am ehesten passt (oder ob sie doch
    unwidersprochen ist). Danach wird sie dort reingehaengt -- nichts
    verschwindet mehr stillschweigend."""
    if not missing_refs:
        return step1_result

    diskurse = step1_result.get("diskurse", [])
    if not diskurse:
        # Kein Diskurs vorhanden, in den nachgereicht werden koennte --
        # alles Fehlende geht auf die Unwidersprochen-Liste mit Warnhinweis.
        for ref in missing_refs:
            step1_result.setdefault("unwidersprochene_punkte", []).append({
                "id": f"U-NACHTRAG-{ref}",
                "titel": "Automatisch nachgetragen (kein Diskurs vorhanden)",
                "beschreibung": "Diese Position wurde in Schritt 1 keiner Kategorie zugeordnet und es existierte kein Diskurs, dem sie zugeordnet werden konnte. Manuell pruefen.",
                "refs": [ref],
            })
        return step1_result

    optionen = "\n".join(f"- {d['id']}: {d['titel']} ({d['streitfrage']})" for d in diskurse)
    patch_prompt = f"""Ordne die folgenden übrig gebliebenen Positionen jeweils dem am besten passenden bestehenden Diskurs zu, oder markiere sie als unwidersprochen, falls sie zu keinem passen und niemand ihnen widerspricht.

BESTEHENDE DISKURSE:
{optionen}

Antworte NUR mit JSON: {{"zuordnungen": [{{"ref": "REF-xxx", "diskurs_id": "D1" ODER null falls unwidersprochen}}]}}"""

    lines = []
    for ref in sorted(missing_refs):
        pos = ref_map[ref]
        lines.append(f"[{ref}]\nPosition: {pos['position']}\nBegründung: {pos['reasoning']}\n")
    user_message = "\n".join(lines)

    try:
        patch_result = call_llm(client, patch_prompt, user_message, model, use_thinking, "Nachtrag", provider=_ACTIVE_PROVIDER)
        zuordnungen = {z["ref"]: z.get("diskurs_id") for z in patch_result.get("zuordnungen", [])}
    except Exception as e:
        print(f"  WARNUNG: Nachtrags-Call fehlgeschlagen ({e}), alle Fehlenden gehen auf Unwidersprochen-Liste.")
        zuordnungen = {}

    diskurs_by_id = {d["id"]: d for d in diskurse}
    for ref in missing_refs:
        ziel_id = zuordnungen.get(ref)
        if ziel_id and ziel_id in diskurs_by_id:
            diskurs_by_id[ziel_id].setdefault("refs", []).append(ref)
        else:
            step1_result.setdefault("unwidersprochene_punkte", []).append({
                "id": f"U-NACHTRAG-{ref}",
                "titel": "Automatisch nachgetragen",
                "beschreibung": "Diese Position passte zu keinem bestehenden Diskurs und wurde als unwidersprochen eingestuft.",
                "refs": [ref],
            })

    print(f"  Vollstaendigkeits-Netz: {len(missing_refs)} Positionen nachgereicht.")
    return step1_result


def run_step2(client, step1_result, ref_map, model, use_thinking):
    diskurse_raw = step1_result.get("diskurse", [])

    print(f"\n{'='*60}")
    print(f"SCHRITT 2: Diskurs-interne Strukturierung ({len(diskurse_raw)} Diskurse)")
    print(f"{'='*60}")

    structured_diskurse = []
    for discourse in diskurse_raw:
        label = discourse["id"]
        refs = discourse.get("refs", [])
        positions_for_discourse = [ref_map[r] for r in refs if r in ref_map]
        n_personen = len({p["participant_id"] for p in positions_for_discourse})

        if n_personen < 2:
            print(f"  [{label}] Nur {n_personen} Person(en), überspringe")
            structured_diskurse.append({
                "id": discourse["id"], "titel": discourse["titel"], "streitfrage": discourse["streitfrage"],
                "uebersicht": "", "urspruengliche_dimensionen": list({p["herkunft_dimension"] for p in positions_for_discourse}),
                "lager": [], "skip_reason": "zu wenige Personen",
            })
            continue

        user_message = build_step2_message(discourse["titel"], discourse["streitfrage"], positions_for_discourse)
        result, last_error = None, None

        # Bis zu 2 Versuche: wenn 'lager' fehlt/leer ist, war die Antwort
        # trotz gueltigem JSON strukturell unvollstaendig -- lieber nochmal
        # anfragen als ein leeres Ergebnis stillschweigend zu uebernehmen
        # (das war exakt die Ursache des D7-Bugs im vorherigen Lauf).
        for attempt in range(1, 4):
            try:
                candidate = call_llm(client, STEP2_SYSTEM_PROMPT, user_message, model, use_thinking, label, provider=_ACTIVE_PROVIDER)
            except ValueError as e:
                last_error = e
                continue
            if not candidate.get("lager"):
                print(f"  [{label}] Versuch {attempt}: leeres 'lager', wiederhole...")
                last_error = ValueError("Ergebnis ohne 'lager'-Struktur")
                continue
            result = candidate
            break

        if result is None:
            print(f"  [{label}] FEHLER nach 3 Versuchen: {last_error}")
            structured_diskurse.append({
                "id": discourse["id"], "titel": discourse["titel"], "streitfrage": discourse["streitfrage"],
                "uebersicht": "", "urspruengliche_dimensionen": [], "lager": [], "error": str(last_error),
            })
            continue

        # Vollstaendigkeits-Check innerhalb des Diskurses
        step2_input_refs = {p["ref"] for p in positions_for_discourse}
        step2_output_refs = {ref for l in result.get("lager", []) for sp in l.get("standpunkte", []) for ref in sp.get("refs", [])}
        s2_missing = step2_input_refs - step2_output_refs
        if s2_missing:
            print(f"  [{label}] WARNUNG: {len(s2_missing)} REFs innerhalb des Diskurses nicht zugeordnet: {sorted(s2_missing)}")

        resolve_refs_to_mitglieder(result, ref_map)
        result["id"] = discourse["id"]
        result["titel"] = discourse["titel"]
        result["streitfrage"] = discourse["streitfrage"]
        result["urspruengliche_dimensionen"] = list({p["herkunft_dimension"] for p in positions_for_discourse})

        n_lager = len(result.get("lager", []))
        n_standpunkte = sum(len(l.get("standpunkte", [])) for l in result.get("lager", []))
        print(f"  [{label}] {discourse['titel']}: {n_lager} Lager, {n_standpunkte} Standpunkte")
        structured_diskurse.append(result)

    return structured_diskurse


def resolve_unwidersprochen_refs(punkte, ref_map):
    for u in punkte:
        refs = u.pop("refs", [])
        u["positionen"] = []
        for ref_id in refs:
            if ref_id in ref_map:
                pos = ref_map[ref_id]
                u["positionen"].append({
                    "participant_id": pos["participant_id"],
                    "herkunft_dimension": pos["herkunft_dimension"],
                    "position_text": pos["position"][:300],
                })



def generate_html(data, output_path, run_timestamp, model):
    from html import escape as e
    meta = data.get('meta', {})
    diskurse = data.get('diskurse', [])
    unwidersprochen = data.get('unwidersprochene_punkte', [])
    anmerkungen = data.get('anmerkungen', '')

    def badge(text, color='#555'):
        return f'<span style="background:{color};color:#fff;border-radius:3px;padding:1px 6px;font-size:.75rem;font-weight:600;white-space:nowrap">{e(str(text))}</span>'

    def render_mitglieder(mitglieder):
        if not mitglieder:
            return ''
        rows = ''.join(
            f'<tr><td style="padding:2px 8px 2px 0;color:#555;font-size:.8rem">{e(m.get("participant_id","?"))}</td>'
            f'<td style="padding:2px 8px 2px 0;color:#777;font-size:.75rem">{e(m.get("herkunft_dimension","?"))}</td>'
            f'<td style="color:#333;font-size:.8rem">{e(m.get("zitat","")[:120])}{"…" if len(m.get("zitat",""))>120 else ""}</td></tr>'
            for m in mitglieder
        )
        return (
            f'<details style="margin-top:4px">'
            f'<summary style="cursor:pointer;color:#888;font-size:.78rem">{len(mitglieder)} Person(en) – Zitate anzeigen</summary>'
            f'<table style="margin-top:4px;border-collapse:collapse;width:100%">{rows}</table>'
            f'</details>'
        )

    abstr_colors = {
        "Übergeordnete Ziele": "#1a6b3c", "Konkrete Ziele": "#2d7d9a",
        "Zwischenziele": "#5c6bc0", "Umsetzungslogik": "#7b5ea7",
        "Instrumententyp": "#b06a20", "Feinausgestaltung": "#9e3030",
    }

    def render_standpunkt(sp):
        n = len(sp.get('mitglieder', []))
        abstr = sp.get('abstraktionsebene', '')
        color = abstr_colors.get(abstr, '#555')
        voraus = sp.get('setzt_voraus')
        voraus_hint = f' <span style="color:#aaa;font-size:.75rem">setzt {e(str(voraus))} voraus</span>' if voraus else ''
        return (
            f'<div style="border-left:3px solid {color};padding:6px 10px;margin:5px 0;background:#fafafa;border-radius:3px">'
            f'<div style="display:flex;gap:6px;align-items:baseline;flex-wrap:wrap">'
            f'<strong style="font-size:.85rem">{e(sp.get("titel",""))}</strong>'
            f'{badge(abstr, color)}{badge(f"{n}P", "#888")}{voraus_hint}</div>'
            f'<div style="color:#444;font-size:.82rem;margin-top:3px">{e(sp.get("position",""))}</div>'
            f'{render_mitglieder(sp.get("mitglieder",[]))}</div>'
        )

    def render_lager(lager):
        standpunkte = lager.get('standpunkte', [])
        n_p = sum(len(sp.get('mitglieder', [])) for sp in standpunkte)
        sps = ''.join(render_standpunkt(sp) for sp in standpunkte)
        return (
            f'<details open style="margin:8px 0;border:1px solid #dde;border-radius:6px;padding:8px 12px">'
            f'<summary style="cursor:pointer;font-weight:700;font-size:.9rem;display:flex;gap:8px;align-items:center;flex-wrap:wrap">'
            f'<span>{e(lager.get("titel",""))}</span>{badge(f"{n_p}P","#2d7d9a")}'
            f'{badge(f"{len(standpunkte)} Standpunkte","#5c6bc0")}</summary>'
            f'<div style="color:#555;font-size:.82rem;margin:4px 0 2px"><em>{e(lager.get("kernaussage",""))}</em></div>'
            f'{"<div style=chr(34)color:#888;font-size:.78remchr(34)>" + e(lager.get("bandbreite","")) + "</div>" if lager.get("bandbreite") else ""}'
            f'<details style="margin-top:6px"><summary style="cursor:pointer;color:#777;font-size:.8rem">Standpunkte einblenden</summary>'
            f'{sps}</details></details>'
        )

    def render_diskurs(disc):
        lager = disc.get('lager', [])
        n_lager = len(lager)
        n_sp = sum(len(l.get('standpunkte', [])) for l in lager)
        n_p = sum(len(sp.get('mitglieder', [])) for l in lager for sp in l.get('standpunkte', []))
        error = disc.get('error')
        dims = ', '.join(disc.get('urspruengliche_dimensionen', []))
        status = badge('FEHLER','#c0392b') if error else ''
        lager_html = ''.join(render_lager(l) for l in lager)
        return (
            f'<details open style="margin:14px 0;border:2px solid #c5d5e8;border-radius:8px;padding:10px 16px">'
            f'<summary style="cursor:pointer;display:flex;gap:10px;align-items:baseline;flex-wrap:wrap">'
            f'<span style="font-size:1rem;font-weight:800;color:#1a3a5c">{e(disc.get("id",""))} {e(disc.get("titel",""))}</span>'
            f'{badge(f"{n_lager} Lager","#1a6b3c")}{badge(f"{n_sp} Standpunkte","#5c6bc0")}{badge(f"{n_p}P","#b06a20")}{status}'
            f'</summary>'
            f'<div style="color:#666;font-size:.8rem;margin:4px 0"><em>Streitfrage:</em> {e(disc.get("streitfrage",""))}</div>'
            f'{"<div style=chr(34)color:#888;font-size:.75remchr(34)>Dimensionen: " + e(dims) + "</div>" if dims else ""}'
            f'<div style="color:#333;font-size:.85rem;margin:6px 0 10px">{e(disc.get("uebersicht",""))}</div>'
            f'{"<div style=chr(34)color:#c0392bchr(34)>Fehler: " + e(str(error)) + "</div>" if error else ""}'
            f'{lager_html}</details>'
        )

    items_u = ''.join(
        f'<div style="margin:6px 0;padding:6px 10px;background:#f0f7f0;border-left:3px solid #27ae60;border-radius:4px">'
        f'<strong style="font-size:.85rem">{e(u.get("titel",""))}</strong> {badge(f"{len(u.get(chr(112)+chr(111)+chr(115)+chr(105)+chr(116)+chr(105)+chr(111)+chr(110)+chr(101)+chr(110),[]))}"+"P","#27ae60")}'
        f'<div style="color:#555;font-size:.8rem;margin-top:2px">{e(u.get("beschreibung",""))}</div></div>'
        for u in unwidersprochen
    )
    unw_block = (
        f'<details style="margin:16px 0;border:1px solid #b2dfdb;border-radius:8px;padding:10px 16px">'
        f'<summary style="cursor:pointer;font-weight:700;font-size:.95rem;color:#1b5e20">Unwidersprochene Punkte ({len(unwidersprochen)})</summary>'
        f'<div style="margin-top:8px">{items_u}</div></details>'
    ) if unwidersprochen else ''

    diskurse_html = ''.join(render_diskurs(d) for d in diskurse)
    ann = f'<div style="background:#fff8e1;border-left:3px solid #f9a825;padding:8px 12px;margin-bottom:12px;font-size:.83rem">{e(anmerkungen)}</div>' if anmerkungen else ''

    html = (
        '<!DOCTYPE html><html lang="de"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>Aigora Clustering – {run_timestamp}</title>'
        '<style>body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;max-width:960px;margin:0 auto;padding:16px;line-height:1.45}'
        'summary::marker{display:none}summary::-webkit-details-marker{display:none}'
        'h1{font-size:1.3rem;color:#1a3a5c}.meta{background:#f5f7fa;border-radius:6px;padding:10px 14px;'
        'font-size:.82rem;color:#555;margin-bottom:16px;display:flex;gap:16px;flex-wrap:wrap}</style></head><body>'
        '<h1>Aigora Sitzung-2 Clustering</h1>'
        f'<div class="meta"><span><strong>Run:</strong> {e(run_timestamp)}</span>'
        f'<span><strong>Modell:</strong> {e(model)}</span>'
        f'<span><strong>Input:</strong> {meta.get("n_positionen_input","?")} Positionen</span>'
        f'<span><strong>Diskurse:</strong> {meta.get("n_diskurse","?")}</span>'
        f'<span><strong>Unwidersprochen:</strong> {meta.get("n_unwidersprochene_punkte","?")}</span>'
        f'<span><strong>Nachgereicht:</strong> {meta.get("n_nachgereicht","?")}</span></div>'
        f'{ann}{diskurse_html}{unw_block}'
        '</body></html>'
    )
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)

_ACTIVE_PROVIDER = 'anthropic'  # wird in main() gesetzt

def main():
    parser = argparse.ArgumentParser(description="Sitzung-2 Clustering-Pipeline v4")
    parser.add_argument("--thinking", action="store_true", help="Extended Thinking aktivieren")
    parser.add_argument("--model", default=None,
                        help="Modellname (default: claude-sonnet-5 fuer Anthropic, deepseek-chat fuer DeepSeek)")
    parser.add_argument("--provider", default="anthropic", choices=["anthropic", "deepseek"],
                        help="API-Provider (default: anthropic). DeepSeek-Key in .env als DEEPSEEK_API_KEY.")
    parser.add_argument("--profiles-dir", default=PROFILES_DIR, help=f"Profilverzeichnis (default: {PROFILES_DIR})")
    parser.add_argument("--output", default=OUTPUT_JSON, help=f"Kanonische Ausgabedatei, die die App liest (default: {OUTPUT_JSON})")
    parser.add_argument("--tag", default="", help="Optionales Label fuer den Archiv-Dateinamen (z.B. 'v4-unwidersprochen')")
    parser.add_argument("--no-canonical", action="store_true", help="NICHT die kanonische App-Datei ueberschreiben, nur archivieren")
    args = parser.parse_args()

    positions = load_all_positions()
    if not positions:
        print(f"Keine Positionen in {args.profiles_dir}/ gefunden.")
        sys.exit(1)
    ref_map = build_ref_index(positions)
    print(f"{len(positions)} Positionen geladen, {len(ref_map)} REF-IDs vergeben.")

    # Provider-Setup
    global _ACTIVE_PROVIDER
    if args.provider == "deepseek":
        import os
        ds_key = os.environ.get("DEEPSEEK_API_KEY")
        if not ds_key:
            print("FEHLER: DEEPSEEK_API_KEY nicht in .env gefunden.")
            sys.exit(1)
        client = Anthropic(api_key=ds_key, base_url=DEEPSEEK_BASE_URL)
        model = args.model or DEEPSEEK_DEFAULT_MODEL
        _ACTIVE_PROVIDER = "deepseek"
        print(f"Provider: DeepSeek | Modell: {model}")
    else:
        client = Anthropic()
        model = args.model or DEFAULT_MODEL
        _ACTIVE_PROVIDER = "anthropic"
        print(f"Provider: Anthropic | Modell: {model}")
    args.model = model

    # Schritt 1
    step1_result, missing, unknown = run_step1(client, positions, ref_map, model=args.model, use_thinking=args.thinking)

    # Step-1-Ergebnis sofort speichern (fuer Repair-Skript falls Schritt 2 scheitert)
    step1_path = Path(args.output).parent / (Path(args.output).stem + "_step1.json")
    step1_path.parent.mkdir(parents=True, exist_ok=True)
    with open(step1_path, "w", encoding="utf-8") as f:
        json.dump(step1_result, f, ensure_ascii=False, indent=2)
    print(f"  Schritt-1-Zwischenergebnis: {step1_path}")

    # Vollstaendigkeits-Netz: uebrig gebliebene Positionen nachreichen
    step1_result = patch_missing_into_nearest_discourse(step1_result, missing, ref_map, client, args.model, args.thinking)

    # Schritt 2
    structured_diskurse = run_step2(client, step1_result, ref_map, model=args.model, use_thinking=args.thinking)

    # Unwidersprochene Punkte aufloesen
    unwidersprochen = step1_result.get("unwidersprochene_punkte", [])
    resolve_unwidersprochen_refs(unwidersprochen, ref_map)

    final_output = {
        "diskurse": structured_diskurse,
        "unwidersprochene_punkte": unwidersprochen,
        "meta": {
            "model": args.model,
            "thinking": args.thinking,
            "n_positionen_input": len(positions),
            "n_diskurse": len(structured_diskurse),
            "n_unwidersprochene_punkte": len(unwidersprochen),
            "n_nachgereicht": len(missing),
            "n_unbekannte_refs_schritt1": len(unknown),
        },
        "anmerkungen": step1_result.get("anmerkungen", ""),
    }

    timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    tag_part = f"_{args.tag}" if args.tag else ""
    archive_path = Path(RUNS_DIR) / f"session2_diskurse_{timestamp}_{args.model}{tag_part}.json"
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with open(archive_path, "w", encoding="utf-8") as f:
        json.dump(final_output, f, ensure_ascii=False, indent=2)
    print(f"\n  Archiviert: {archive_path}")

    if not args.no_canonical:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(final_output, f, ensure_ascii=False, indent=2)
        print(f"  Kanonisch (App liest von hier): {args.output}")
    else:
        print(f"  --no-canonical gesetzt: {args.output} NICHT überschrieben.")


    # HTML-Review parallel zur JSON generieren
    html_archive = archive_path.with_suffix('.html')
    generate_html(final_output, html_archive, timestamp, args.model)
    print(f"  HTML-Review (archiviert): {html_archive}")
    if not args.no_canonical:
        html_canonical = Path(args.output).with_suffix('.html')
        generate_html(final_output, html_canonical, timestamp, args.model)
        print(f"  HTML-Review (kanonisch): {html_canonical}")

    print(f"\n{'='*60}")
    print(f"FERTIG")
    print(f"  {len(structured_diskurse)} Diskurse strukturiert")
    print(f"  {len(unwidersprochen)} unwidersprochene Punkte")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()

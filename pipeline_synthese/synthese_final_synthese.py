"""
synthese_final_synthese.py

Letzter inhaltlicher Schritt der Pause-2-Synthese: formuliert aus den 49
Standpunkten, die das No-Objection-Filterverfahren (Stufe A/B/C, siehe
synthese_standpunkt_filter.py / synthese_stufe_b.py / synthese_stufe_c.py)
uebrig gelassen hat, kompakte, lesbare Empfehlungssaetze pro Dimension --
und prueft sie anschliessend auf Kohaerenz ueber Dimensionsgrenzen hinweg
(Cashore-Howlett-Trichterreihenfolge), analog zu synthese_empfehlung.py,
aber neu aufgesetzt: die alte Mehrheits-Filterung dort ist durch das
gestufte Verfahren ersetzt, ausgeschlossene/ungeklaerte Standpunkte fliessen
gar nicht erst in die Synthese ein.

Schritte:
1. Baut pro Dimension ein GEFILTERTES Dossier: nur Standpunkte mit Status
   "in_empfehlung" aus dem Filterverfahren, jeweils mit Minderheits-Flag.
2. EIN LLM-Aufruf pro Dimension (wie synthese_agent.py) formuliert daraus
   Kandidaten-Aussagen.
3. EIN globaler LLM-Aufruf prueft alle Aussagen zusammen auf Kohaerenz und
   fuehrt echte Redundanzen innerhalb einer Dimension zusammen (gleiches
   Verfahren wie zuvor, hier neu aufgesetzt mit den korrigierten Daten).

Ausgabe:
    data/synthese/kandidaten_final.json (Rohkandidaten pro Dimension)
    data/synthese/empfehlung_final.json (nach Kohaerenzpruefung)

Nutzung:
    python synthese_final_synthese.py
"""

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

from synthese_agent import DEFAULT_MODEL, SYSTEM_PROMPT, synthese_fuer_dimension

load_dotenv()

DOSSIERS_PATH = "data/synthese/dossiers.json"
FILTER_PATH = "data/synthese/standpunkt_filter.json"
KANDIDATEN_OUT = "data/synthese/kandidaten_final.json"
EMPFEHLUNG_OUT = "data/synthese/empfehlung_final.json"
RUNS_DIR = "data/synthese_runs"

DIM_REIHENFOLGE = ["Übergeordnete Ziele", "Konkrete Ziele", "Zwischenziele",
                   "Umsetzungslogik", "Instrumententyp", "Feinausgestaltung"]


# ── Gefilterte Dossiers bauen ────────────────────────────────────────

def _entscheidung(key, filterdaten):
    a = filterdaten["stufe_a"].get(key)
    if a and a["status"] in ("bestaetigt", "ausgeschlossen"):
        return ("in_empfehlung" if a["status"] == "bestaetigt" else "ausgeschlossen"), False

    b = filterdaten.get("stufe_b", {}).get(key)
    if b and b["einordnung"] in ("passt", "dopplung"):
        return "in_empfehlung", False

    c = filterdaten.get("stufe_c", {}).get(key)
    if c:
        if c["verdikt"] == "aufnehmen":
            return "in_empfehlung", c.get("als_minderheitsposition", False)
        if c["verdikt"] == "ausschliessen":
            return "ausgeschlossen", False
        return "ungeklaert", False

    return "ungeklaert", False


def gefilterte_dossiers(dossiers, filterdaten):
    """Trennt in HAUPTDOKUMENT (breit/eindeutig getragene Standpunkte) und
    ANHANG (Standpunkte, die einen echten, aber in Sitzung 2 bereits
    mehrheitlich entschiedenen Widerspruch ueberstanden haben -- laut
    der Autor gehoert eine in S2 bereits klar unterlegene Minderheitsmeinung
    nicht gleichrangig neben die Hauptempfehlung, sondern dokumentiert in
    einen Anhang). Nur das Hauptdokument wird der Formulierungs-Synthese
    (synthese_fuer_dimension) uebergeben; der Anhang wird roh, ohne LLM-
    Politur, separat mitgefuehrt."""
    ergebnis = {}
    anhang = {}
    for dim, inhalt in dossiers.items():
        survivor_sps = []
        survivor_lager_ids = set()
        anhang_sps = []
        for sp in inhalt["standpunkte"]:
            key = f"{dim}::{sp['id']}"
            status, minderheit = _entscheidung(key, filterdaten)
            if status != "in_empfehlung":
                continue
            if minderheit:
                anhang_sps.append(dict(sp))
                continue
            sp_kopie = dict(sp)
            sp_kopie["minderheitsposition"] = False
            survivor_sps.append(sp_kopie)
            survivor_lager_ids.add(sp["lager_id"])

        anhang[dim] = anhang_sps
        ergebnis[dim] = {
            "standpunkte": survivor_sps,
            "lager_kommentare": {
                lid: kommentare for lid, kommentare in inhalt["lager_kommentare"].items()
                if lid in survivor_lager_ids
            },
            "diskurs_kompromissvorschlaege": inhalt.get("diskurs_kompromissvorschlaege", {}),
        }
    return ergebnis, anhang


# ── Kohaerenz + Redundanz (analog synthese_empfehlung.py, neu aufgesetzt) ──

KOHAERENZ_SYSTEM_PROMPT = """\
<aufgabe>
Du erhältst die Policy-Aussagen einer Bürgerbeteiligung zur deutschen \
Wärmewende, geordnet von den übergeordneten Zielen (Trichteranfang) bis zur \
Feinausgestaltung (Trichterende, Cashore-Howlett-Modell). Jede Aussage wurde \
bereits unabhängig aus echten, gefilterten Bewertungen synthetisiert. Ziel \
ist ein Empfehlungsdokument mit möglichst VIELEN einzelnen, konkreten \
Punkten -- Reichhaltigkeit und Konkretheit sind erwünscht, nicht Minimalismus.
Drei Aufgaben, in dieser Reihenfolge:
</aufgabe>

<aufgabe_1_redundanz>
Prüfe INNERHALB jeder Dimension (nicht über Dimensionen hinweg) zwei Arten von \
Redundanz:

A) Wortgleiche/inhaltsgleiche Dopplung: zwei Aussagen sagen faktisch dasselbe.

B) Gleiche HANDLUNG, unterschiedliche BEGRÜNDUNG/RAHMUNG: zwei Aussagen fordern \
im Kern dieselbe Handlung, unterscheiden sich aber nur in der Begründung oder \
Selbstbezeichnung (Beispiel: eine Aussage will "Deutschland als Vorreiter", \
eine andere lehnt das Wort "Vorreiter" ab, will aber ebenfalls, dass \
Deutschland ambitioniert und früh handelt -- das ist derselbe Wunsch mit \
unterschiedlicher Rahmung, kein echter Dissens). Fasse solche Paare zu EINER \
Aussage zusammen, die die gemeinsame Handlung benennt und beide Begründungen \
nennt (sofern sie sich nicht widersprechen), OHNE die kontroverse Rahmung \
(z.B. das strittige Wort "Vorreiter" als Selbstzweck) zu übernehmen, die ein \
Teil explizit ablehnt.

Zusammenführen NUR, wenn die Handlung wirklich identisch ist. Unterschiedliche \
Teilaspekte desselben Ober-Themas (z.B. unterschiedliche Instrumente, \
unterschiedliche Zielgrößen) bleiben getrennt -- Fall A und B rechtfertigen \
eine Zusammenführung, bloße thematische Nähe nicht. Im Zweifel NICHT \
zusammenlegen.
</aufgabe_1_redundanz>

<aufgabe_2_kohaerenz>
Prüfe, ob eine tieferliegende Aussage einer höherliegenden inhaltlich \
widerspricht -- nicht nur im Ton, in der Sache. Beurteile GROSSZÜGIG: die \
meisten Detailaussagen sind nebeneinander gültig (unterschiedliche \
Haushaltssituationen, Fallkonstellationen). Nur echte, harte Widersprüche \
zählen. Bei Konflikt: passe NUR die Formulierung der TIEFERLIEGENDEN Aussage \
an, erfinde nichts hinzu, veränder die Kernaussage nicht in eine andere \
Richtung.
</aufgabe_2_kohaerenz>

<aufgabe_3_konfliktgruppen>
KRITISCH, bisher übersehen worden: suche über ALLE Aussagen hinweg (auch \
INNERHALB derselben Dimension, nicht nur zwischen Dimensionen) nach echten \
ENTWEDER-ODER-Konflikten -- zwei oder mehr Aussagen, die sich gegenseitig \
ausschließen, weil sie unterschiedliche, unvereinbare Handlungen zur \
selben Frage fordern (Beispiel: eine Aussage will eine feste \
Wärmepumpen-Ausbauzahl beibehalten, eine andere lehnt genau das ab und \
will stattdessen andere Zielgrößen priorisieren -- das ist ein echter \
Widerspruch, kein Nebeneinander-bestehen-Können).

Das ist etwas ANDERES als Aufgabe 2 (Kohärenz zwischen Ebenen): hier geht es \
um Konflikte auf DERSELBEN oder verschiedenen Ebenen, die bisher als zwei \
unabhängige, scheinbar beide gültige Kandidaten nebeneinander standen, \
obwohl Teilnehmende sich zwischen ihnen entscheiden müssten. Melde JEDEN \
solchen Fall als Konfliktgruppe, auch wenn die einzelnen Aussagen für sich \
genommen jeweils kohärent und gut formuliert sind.

WICHTIGE GEGENPRÜFUNG, bevor du zwei Aussagen als Konflikt meldest -- \
gestufte Ziel+Rückfall-Struktur ist KEIN Konflikt: prüfe anhand der \
Ursprungszitate/Kommentare, ob die "konservativere" Aussage (z.B. spätere \
Frist, niedrigerer Wert) von ihren eigenen Urheber:innen explizit als \
akzeptierte ÄUSSERSTE UNTERGRENZE/OBERGRENZE formuliert wurde, waehrend sie \
eigentlich ebenfalls die ambitioniertere Aussage bevorzugen ("im Idealfall \
früher", "wird als Maximum akzeptiert, nicht als Wunschtermin"). Wenn das \
der Fall ist, ist es KEIN Entweder-Oder, sondern EINE gestufte Position \
("Ziel X, spätestens/mindestens Y als Rückfall") -- fasse das als \
Zusammenführung (Aufgabe 1), nicht als Konfliktgruppe. Nur wenn die \
konservativere Seite die ambitioniertere Aussage aktiv ABLEHNT (nicht nur \
als weniger wahrscheinlich einschätzt), ist es ein echter Konflikt.

Ebenso: bevor du eine Konfliktgruppe meldest, prüfe ob echte Handlungs- \
Unvereinbarkeit besteht oder ob beide Seiten eigentlich denselben groesseren \
Wunsch teilen (z.B. schnellerer Ausbau, mehr Ambition) und sich nur in einem \
einzelnen Unterpunkt unterscheiden -- formuliere den "gemeinsamer_kern" dann \
so, dass die geteilte Ambition sichtbar bleibt, nicht nur eine austauschbare \
Nebensaechlichkeit.

Klassifiziere jede gefundene Konfliktgruppe:
- "numerisch": die Aussagen unterscheiden sich NUR in einer Zahl/einem Jahr \
bei sonst identischem Wortlaut (z.B. Übergangsfrist 10 vs. 15 Jahre). Gib \
"einheit" (z.B. "Jahre", "€/Tonne", "%") sowie "min"/"max" an (aus den \
tatsächlich genannten Werten).
- "kategorisch": die Aussagen sind inhaltlich verschiedene Ansätze, keine \
Zahlenskala (z.B. "feste Zielzahl beibehalten" vs. "keine feste Zielzahl, \
andere Priorität setzen"). Keine min/max/einheit noetig.

KRITISCH für die Darstellung (bisher fehlend, macht die Konfliktgruppen für \
Teilnehmende unnötig überfordernd): schreibe die vollen Aussagen NICHT einfach \
nebeneinander. Arbeite stattdessen heraus:

1. "gemeinsamer_kern": ALLES, worüber die Seiten sich einig sind, als EIN \
zusammenhängender Satz/Absatz (z.B. "Beide Seiten wollen, dass die \
Übergangsfrist kürzer als die gesetzlich vorgesehenen 14-15 Jahre ist und mit \
Ausnahmeregelungen für Härtefälle versehen wird."). Das ist der Text, der \
für BEIDE Optionen gleichermaßen gilt.

2. Pro Option in "optionen": NUR der tatsächliche Unterschied, aber als \
VOLLSTÄNDIGER, LEICHT VERSTÄNDLICHER SATZ -- kein komprimiertes Stichwort-\
Label. "kurzlabel" muss fuer sich allein lesbar und verstaendlich sein, so \
als waere es die einzige Information, die jemand sieht (Beispiel: NICHT \
"Verbote als Rückfalloption", SONDERN "Verbindliche Pflichten greifen erst, \
wenn Förderung und CO2-Preis absehbar nicht ausreichen"). Bei "numerisch" \
reicht die Zahl mit Einheit im Satz-Kontext (z.B. "Übergangsfrist von 10 \
Jahren" vs. "Übergangsfrist von 15 Jahren"). "unterschied_text" darunter darf \
zusaetzlich noch 1 Satz Kontext/Begründung liefern, ist aber optional -- die \
Hauptaussage muss schon in "kurzlabel" allein verstaendlich sein.

Das Ziel: jemand soll den gemeinsamen Kern einmal lesen und dann nur noch \
zwischen den paar kurzen Optionen klicken müssen, ohne zwei komplette \
Absätze vergleichen zu müssen.
</aufgabe_3_konfliktgruppen>

<ausgabeformat>
Jede Zeile der Eingabe beginnt mit einem Token wie "E0", "E1", ... -- benutze
in deiner Antwort AUSSCHLIESSLICH diese Tokens als "id"/"quell_ids".

Antworte NUR mit validem JSON:
{
  "zusammenfuehrungen": [
    {"quell_ids": ["E3", "E5"], "neue_id": "E3-merged",
     "aussage_final": "<zusammengefuehrte Aussage>",
     "nutzer_erklaerung_final": "<zusammengefuehrte, IDs-freie Nutzererklaerung>",
     "begruendung": "..."}
  ],
  "pruefungen": [
    {"id": "E0", "kohaerent": true, "aussage_final": "<unveränderte Aussage>"},
    {"id": "E7", "kohaerent": false, "konflikt_mit": "E1",
     "konflikt_beschreibung": "...", "aussage_final": "<angepasste Formulierung>"}
  ],
  "konfliktgruppen": [
    {"typ": "numerisch", "einheit": "Jahre", "min": 10, "max": 15,
     "gemeinsamer_kern": "Was beide Optionen teilen, vollstaendiger Satz",
     "optionen": [
       {"mitglied": "E12", "kurzlabel": "Die Übergangsfrist soll 10 Jahre betragen.", "unterschied_text": null},
       {"mitglied": "E13", "kurzlabel": "Die Übergangsfrist soll 15 Jahre betragen.", "unterschied_text": null}
     ]},
    {"typ": "kategorisch",
     "gemeinsamer_kern": "Was beide Optionen teilen, vollstaendiger Satz",
     "optionen": [
       {"mitglied": "E20", "kurzlabel": "Das jährliche Ausbauziel von 500.000 Wärmepumpen soll als feste Zielzahl beibehalten und erhöht werden.",
        "unterschied_text": null},
       {"mitglied": "E21", "kurzlabel": "Statt einer festen Zielzahl soll eine Priorisierungslogik nach Dringlichkeit gelten.",
        "unterschied_text": "Sanierungsrate und Fernwärmeausbau haben dabei Vorrang vor einer isolierten Wärmepumpen-Stückzahl."}
     ]}
  ]
}
Jedes Eingabe-Token muss in GENAU einem "pruefungen"-Eintrag auftauchen. Ein \
Token, das in einer Konfliktgruppe steckt, bleibt trotzdem auch ein normaler \
"pruefungen"-Eintrag (die Konfliktgruppe ist eine ZUSAETZLICHE Markierung,
kein Ersatz).
</ausgabeformat>
"""


def _llm_json_call(client, model, system_prompt, user_message, max_tokens=32000):
    with client.messages.stream(
        model=model, max_tokens=max_tokens,
        system=[{"type": "text", "text": system_prompt}],
        thinking={"type": "disabled"},
        messages=[{"role": "user", "content": user_message}],
    ) as stream:
        for _ in stream.text_stream:
            pass
        resp = stream.get_final_message()
    if resp.stop_reason == "max_tokens":
        raise ValueError("max_tokens erreicht -- Antwort unvollstaendig, max_tokens erhoehen")
    raw = "".join(b.text for b in resp.content if b.type == "text").strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    return json.loads(raw)


def pruefe_kohaerenz(client, model, kandidaten):
    eintraege = []
    for dim in DIM_REIHENFOLGE:
        for k in kandidaten.get("dimensionen", {}).get(dim, {}).get("kandidaten", []):
            eintraege.append({"dim": dim, "id": k["id"], "aussage": k["aussage"]})
    if not eintraege:
        return {}, [], []

    token_zu_eintrag = {}
    zeilen = []
    for i, e in enumerate(eintraege):
        token = f"E{i}"
        token_zu_eintrag[token] = e
        zeilen.append(f'{token} [{e["dim"]}] {e["id"]}: {e["aussage"]}')
    text = ("Verwende in deiner Antwort AUSSCHLIESSLICH die vorangestellten Tokens (E0, E1, ...) "
            "als \"id\" -- nicht die Kandidaten-ID in eckigen Klammern.\n\n" + "\n\n".join(zeilen))
    ergebnis = _llm_json_call(client, model, KOHAERENZ_SYSTEM_PROMPT, text, max_tokens=16000)

    pruefungen = {}
    neue_id_zu_dim = {}
    zusammenfuehrungen = []
    for z in ergebnis.get("zusammenfuehrungen", []):
        quell_eintraege = [token_zu_eintrag[t] for t in z.get("quell_ids", []) if t in token_zu_eintrag]
        if not quell_eintraege:
            continue
        dim = quell_eintraege[0]["dim"]
        z["dim"] = dim
        z["quell_ids"] = [qe["id"] for qe in quell_eintraege]
        zusammenfuehrungen.append(z)
        neue_id_zu_dim[z["neue_id"]] = dim

    for p in ergebnis.get("pruefungen", []):
        token = p["id"]
        if token in token_zu_eintrag:
            e = token_zu_eintrag[token]
            pruefungen[(e["dim"], e["id"])] = p
        elif token in neue_id_zu_dim:
            pruefungen[(neue_id_zu_dim[token], token)] = p

    konfliktgruppen = []
    for kg in ergebnis.get("konfliktgruppen", []):
        optionen = []
        for opt in kg.get("optionen", []):
            t = opt.get("mitglied")
            if t in token_zu_eintrag:
                e = token_zu_eintrag[t]
                optionen.append({"dim": e["dim"], "id": e["id"],
                                  "kurzlabel": opt.get("kurzlabel"),
                                  "unterschied_text": opt.get("unterschied_text")})
            elif t in neue_id_zu_dim:
                optionen.append({"dim": neue_id_zu_dim[t], "id": t,
                                  "kurzlabel": opt.get("kurzlabel"),
                                  "unterschied_text": opt.get("unterschied_text")})
        if len(optionen) >= 2:
            konfliktgruppen.append({
                "typ": kg.get("typ"),
                "einheit": kg.get("einheit"), "min": kg.get("min"), "max": kg.get("max"),
                "gemeinsamer_kern": kg.get("gemeinsamer_kern"),
                "optionen": optionen,
            })

    return pruefungen, zusammenfuehrungen, konfliktgruppen


# ── Automatische Plausibilitaetspruefung der Konfliktgruppen ───────────
#
# Grund: die LLM-basierte Konfliktgruppen-Erkennung (Aufgabe 3 oben) urteilt
# rein aus dem WORTLAUT zweier Aussagen -- das hat sich als unzuverlaessig
# erwiesen (echte Faelle: "2035-2040 vs. 2044/2045" und "Pflichtquote vs.
# CO2-Preishoehe" klangen textlich wie ein Widerspruch, waren es aber nicht:
# 75-100% der echten Unterstuetzer:innen beider Seiten waren DIESELBEN
# Personen -- das Zustimmungssignal stammt bei beiden ueberwiegend aus
# derselben vererbten Lager-Bewertung, keine bewusste Entweder-Oder-
# Entscheidung realer Menschen). Diese Funktion ersetzt das nicht durch
# noch mehr Prompting, sondern durch eine DETERMINISTISCHE Nachpruefung
# anhand der echten Bewertungsdaten: wer zu >=4 bei den Standpunkten steht,
# auf die sich eine Option stuetzt, gilt als Unterstuetzer:in dieser Option.
# Ueberschneidet sich das zwischen zwei Optionen zu stark, ist es strukturell
# kein Beleg fuer eine bewusste Entweder-Oder-Entscheidung -- die Gruppe
# wird automatisch verworfen, nicht nur meiner eigenen Wachsamkeit ueberlassen.

UEBERLAPP_SCHWELLE = 0.5  # Anteil der kleineren Unterstuetzer-Menge


def _echte_unterstuetzer_fuer(dim, sp_ids, dossiers, nur_direkt=False):
    sp_map = {sp["id"]: sp for sp in dossiers.get(dim, {}).get("standpunkte", [])}
    out = set()
    for sid in sp_ids:
        sp = sp_map.get(sid)
        if not sp:
            continue
        for b in sp["unterstuetzung"]["bewertungen"]:
            if b["wert"] >= 4 and (not nur_direkt or b.get("quelle") == "direkt"):
                out.add(b["participant_id"])
    return out


def _lager_praefix(standpunkt_id):
    """'D2-L4-S1' -> 'D2-L4'. Standpunkte mit gleichem Praefix gehoeren zum
    selben Lager -- wer das Lager positiv bewertet hat, "unterstuetzt" ueber
    Vererbung automatisch ALLE seine Kind-Standpunkte gleichermassen, egal
    wie unterschiedlich deren Inhalt ist. Die Unterstuetzer-Ueberlappung ist
    dort strukturell fast immer hoch und daher KEIN verlaesslicher Beleg
    gegen einen echten Konflikt (siehe der Autor: reine Statistik ersetzt
    kein inhaltliches Lesen)."""
    teile = standpunkt_id.split("-")
    return "-".join(teile[:2]) if len(teile) >= 2 else standpunkt_id


def verifiziere_konfliktgruppen(konfliktgruppen, dossiers, kandidaten):
    kandidat_lookup = {
        (dim, k["id"]): k
        for dim, inhalt in kandidaten.get("dimensionen", {}).items()
        for k in inhalt.get("kandidaten", [])
    }

    behalten, verworfen = [], []
    for kg in konfliktgruppen:
        options_mit_support = []
        alle_sp_ids = set()
        for opt in kg["optionen"]:
            k = kandidat_lookup.get((opt["dim"], opt["id"]))
            sp_ids = k.get("stuetzt_sich_auf", {}).get("standpunkte", []) if k else []
            alle_sp_ids.update(sp_ids)
            support = _echte_unterstuetzer_fuer(opt["dim"], sp_ids, dossiers)
            options_mit_support.append((opt, support))

        # Wenn alle beteiligten Standpunkte aus demselben Lager stammen, ist die
        # Ueberlappungs-Statistik strukturell unzuverlaessig (s.o.) -- dann NICHT
        # automatisch verwerfen, sondern konservativ als echten Konflikt behalten
        # und zur manuellen inhaltlichen Pruefung markieren, statt eine
        # Entweder-Oder-Entscheidung faelschlich verschwinden zu lassen.
        gleiches_lager = len({_lager_praefix(sid) for sid in alle_sp_ids}) == 1
        if gleiches_lager and len(alle_sp_ids) > 1:
            kg = dict(kg)
            kg["_hinweis_manuelle_pruefung"] = (
                "Alle beteiligten Standpunkte stammen aus demselben Lager -- "
                "Unterstuetzer-Ueberlappung strukturell unzuverlaessig als alleiniges "
                "Kriterium, inhaltlich manuell verifiziert statt automatisch verworfen."
            )
            behalten.append(kg)
            continue

        schlimmste_ueberlappung = 0.0
        schlimmstes_paar = None
        for i in range(len(options_mit_support)):
            for j in range(i + 1, len(options_mit_support)):
                _, s1 = options_mit_support[i]
                _, s2 = options_mit_support[j]
                kleinste = min(len(s1), len(s2))
                if kleinste == 0:
                    continue
                ueberlappung = len(s1 & s2) / kleinste
                if ueberlappung > schlimmste_ueberlappung:
                    schlimmste_ueberlappung = ueberlappung
                    schlimmstes_paar = (options_mit_support[i][0]["id"], options_mit_support[j][0]["id"])

        if schlimmste_ueberlappung >= UEBERLAPP_SCHWELLE:
            verworfen.append({
                "gemeinsamer_kern": kg.get("gemeinsamer_kern"),
                "grund": f"{round(schlimmste_ueberlappung*100)}% Unterstuetzer-Ueberschneidung zwischen "
                         f"{schlimmstes_paar[0]} und {schlimmstes_paar[1]} (unterschiedliche Lager, also "
                         f"echtes Vergleichssignal) -- kein verlaesslicher Beleg fuer bewusste "
                         f"Entweder-Oder-Entscheidung, automatisch verworfen.",
                "optionen": kg["optionen"],
            })
        else:
            behalten.append(kg)
    return behalten, verworfen


def merge_verworfene_konfliktgruppen(empfehlung, verworfene_konfliktgruppen):
    """Wenn eine Konfliktgruppe wegen zu hoher Unterstuetzer-Ueberschneidung verworfen
    wird, sind die beteiligten Optionen keine echten Alternativen -- sie duerfen dann
    aber auch nicht als zwei unabhaengige, scheinbar konkurrierende Einzelpunkte stehen
    bleiben (Nutzer koennte faelschlich glauben, nur einem von beiden zustimmen zu
    duerfen, siehe auch 'schliesst_aus'). Sie werden stattdessen automatisch zu EINEM
    Kandidaten zusammengefuehrt. Rein textuelle Konkatenation als Fallback -- fuer eine
    inhaltlich sauber formulierte Zusammenfuehrung (z.B. Ziel+Rueckfall-Struktur) bleibt
    eine manuelle Nacharbeit sinnvoll, aber die Duplikat-Anzeige im UI wird so in jedem
    Fall strukturell verhindert."""
    for v in verworfene_konfliktgruppen:
        optionen = v.get("optionen") or []
        if len(optionen) < 2:
            continue
        dim = optionen[0]["dim"]
        eintraege = empfehlung["dimensionen"].get(dim, {}).get("eintraege", [])
        beteiligt = [x for x in eintraege if x["id"] in {o["id"] for o in optionen}]
        if len(beteiligt) < 2:
            continue
        neue_id = beteiligt[0]["id"].split("__")[0] + "-merged__" + beteiligt[0]["id"].split("__")[1]
        merged = {
            "id": neue_id,
            "zusammengefuehrt_aus": [x["id"] for x in beteiligt],
            "aussage_final": " | ".join(x["aussage_final"] for x in beteiligt),
            "kohaerenz_angepasst": False,
            "konflikt_beschreibung": None,
            "begruendung": (
                f"Automatisch zusammengefuehrt (Schritt 2b): urspruenglich als Entweder-Oder "
                f"vorgeschlagen, aber verworfen -- {v['grund']} MANUELLE UEBERARBEITUNG DER "
                f"FORMULIERUNG EMPFOHLEN, bevor dieser Kandidat live geht. "
                + " / ".join(x.get("begruendung") or "" for x in beteiligt)
            ),
            "nutzer_erklaerung": " ".join(x.get("nutzer_erklaerung") or "" for x in beteiligt),
            "stuetzt_sich_auf": {
                "standpunkte": sorted(set().union(*(
                    set(x.get("stuetzt_sich_auf", {}).get("standpunkte", [])) for x in beteiligt
                ))),
                "teilnehmende": sorted(set().union(*(
                    set(x.get("stuetzt_sich_auf", {}).get("teilnehmende", [])) for x in beteiligt
                ))),
            },
            "schliesst_aus": None,
        }
        idx = eintraege.index(beteiligt[0])
        eintraege[idx] = merged
        for x in beteiligt[1:]:
            eintraege.remove(x)


# ── Zusammenbau ──────────────────────────────────────────────────────

def main():
    with open(DOSSIERS_PATH, encoding="utf-8") as f:
        dossiers = json.load(f)
    with open(FILTER_PATH, encoding="utf-8") as f:
        filterdaten = json.load(f)

    gefiltert, anhang = gefilterte_dossiers(dossiers, filterdaten)
    print("Standpunkte pro Dimension nach Filterung (Hauptdokument / Anhang):")
    for dim, d in gefiltert.items():
        print(f"  {dim}: {len(d['standpunkte'])} / {len(anhang.get(dim, []))} im Anhang")

    client = Anthropic()

    print("\nSchritt 1: Synthese pro Dimension ...")
    kandidaten = {"generated_at": None, "model": DEFAULT_MODEL, "dimensionen": {}}
    for dim, dossier in gefiltert.items():
        if not dossier["standpunkte"]:
            print(f"  {dim}: keine überlebenden Standpunkte, übersprungen.")
            continue
        print(f"  Synthetisiere: {dim} ...")
        try:
            kandidaten_json = synthese_fuer_dimension(client, DEFAULT_MODEL, dim, dossier)
        except AnthropicError as exc:
            print(f"    FEHLER: {exc}")
            continue
        n = len(kandidaten_json.get("kandidaten", []))
        if kandidaten_json.get("_parsefehler"):
            print(f"    WARNUNG: {kandidaten_json['_parsefehler']}")
        else:
            print(f"    {n} Kandidat(en)")
        kandidaten["dimensionen"][dim] = kandidaten_json

    kandidaten["generated_at"] = datetime.datetime.now().isoformat(timespec="seconds")
    os.makedirs(os.path.dirname(KANDIDATEN_OUT), exist_ok=True)
    with open(KANDIDATEN_OUT, "w", encoding="utf-8") as f:
        json.dump(kandidaten, f, ensure_ascii=False, indent=2)
    print(f"Geschrieben: {KANDIDATEN_OUT}")

    print("\nSchritt 2: Kohärenz + Redundanz + Konfliktgruppen (global) ...")
    pruefungen, zusammenfuehrungen, konfliktgruppen_roh = pruefe_kohaerenz(client, DEFAULT_MODEL, kandidaten)
    print(f"  {len(zusammenfuehrungen)} Zusammenführungen, "
          f"{sum(1 for p in pruefungen.values() if not p.get('kohaerent', True))} von {len(pruefungen)} angepasst, "
          f"{len(konfliktgruppen_roh)} Konfliktgruppen vom Modell vorgeschlagen.")

    print("Schritt 2b: Plausibilitätsprüfung der Konfliktgruppen (deterministisch, gegen echte Bewertungen) ...")
    konfliktgruppen, verworfene_konfliktgruppen = verifiziere_konfliktgruppen(konfliktgruppen_roh, dossiers, kandidaten)
    print(f"  {len(konfliktgruppen)} bestätigt, {len(verworfene_konfliktgruppen)} automatisch verworfen "
          f"(zu hohe Unterstützer-Überschneidung -- kein verlässlicher echter Konflikt).")
    for v in verworfene_konfliktgruppen:
        print(f"    VERWORFEN: {v['grund']}")

    merge_map = {}
    for z in zusammenfuehrungen:
        for qid in z["quell_ids"]:
            merge_map[(z["dim"], qid)] = z

    empfehlung = {"generated_at": kandidaten["generated_at"], "dimensionen": {}}
    for dim in DIM_REIHENFOLGE:
        kandidaten_dim = kandidaten.get("dimensionen", {}).get(dim, {}).get("kandidaten", [])
        eintraege = []
        bereits = set()
        for k in kandidaten_dim:
            if (dim, k["id"]) in merge_map:
                z = merge_map[(dim, k["id"])]
                if z["neue_id"] in bereits:
                    continue
                bereits.add(z["neue_id"])
                quell = [kk for kk in kandidaten_dim if kk["id"] in z["quell_ids"]]
                pruefung = pruefungen.get((dim, z["neue_id"]), {})
                eintraege.append({
                    "id": z["neue_id"],
                    "zusammengefuehrt_aus": z["quell_ids"],
                    "aussage_final": pruefung.get("aussage_final", z.get("aussage_final")),
                    "kohaerenz_angepasst": not pruefung.get("kohaerent", True),
                    "konflikt_beschreibung": pruefung.get("konflikt_beschreibung"),
                    "begruendung": " / ".join(qk.get("begruendung", "") for qk in quell),
                    "nutzer_erklaerung": z.get("nutzer_erklaerung_final") or " ".join(
                        qk.get("nutzer_erklaerung", "") for qk in quell
                    ),
                    "stuetzt_sich_auf": {
                        "standpunkte": sorted(set().union(*(
                            set(qk.get("stuetzt_sich_auf", {}).get("standpunkte", [])) for qk in quell
                        ))),
                    },
                    "schliesst_aus": None,
                })
                continue
            pruefung = pruefungen.get((dim, k["id"]), {})
            eintraege.append({
                "id": k["id"],
                "aussage_final": pruefung.get("aussage_final", k["aussage"]),
                "kohaerenz_angepasst": not pruefung.get("kohaerent", True),
                "konflikt_beschreibung": pruefung.get("konflikt_beschreibung"),
                "begruendung": k.get("begruendung"),
                "nutzer_erklaerung": k.get("nutzer_erklaerung"),
                "stuetzt_sich_auf": k.get("stuetzt_sich_auf"),
                "schliesst_aus": k.get("schliesst_aus"),
            })
        empfehlung["dimensionen"][dim] = {
            "eintraege": eintraege,
            "dissens_notiz": kandidaten.get("dimensionen", {}).get(dim, {}).get("dissens_notiz"),
            "datenluecken": kandidaten.get("dimensionen", {}).get(dim, {}).get("datenluecken"),
        }

    # Konfliktgruppen: echte Entweder-Oder-Konflikte zwischen Kandidaten, die
    # als eigenstaendige Entscheidung dargestellt werden sollen (Slider bei
    # numerischer Spanne, Auswahl bei kategorischem Konflikt) statt als zwei
    # unabhaengig nebeneinander stehende Ja/Nein-Empfehlungen.
    empfehlung["konfliktgruppen"] = konfliktgruppen
    empfehlung["verworfene_konfliktgruppen"] = verworfene_konfliktgruppen

    print("Schritt 2c: Verworfene Konfliktgruppen automatisch zu Einzelkandidaten zusammenführen ...")
    merge_verworfene_konfliktgruppen(empfehlung, verworfene_konfliktgruppen)

    # Anhang: roh mitgefuehrte Minderheitspositionen, keine LLM-Politur --
    # bereits in S2 mehrheitlich entschiedene Gegenpositionen, siehe der Autor:
    # "gehört eher in den Appendix" statt gleichrangig im Hauptdokument.
    empfehlung["anhang_minderheitspositionen"] = {
        dim: [
            {
                "id": sp["id"], "titel": sp["titel"], "position": sp["position"],
                "lager_titel": sp["lager_titel"],
                "unterstuetzung": {
                    "n_bewertet": sp["unterstuetzung"]["n_bewertet"],
                    "mittelwert": sp["unterstuetzung"]["mittelwert"],
                    "befuerwortung_4_5": sp["unterstuetzung"]["befuerwortung_4_5"],
                    "ablehnung_1_2": sp["unterstuetzung"]["ablehnung_1_2"],
                },
            }
            for sp in sps
        ]
        for dim, sps in anhang.items() if sps
    }

    print("Schritt 3: Abschluss-Check (Grammatik/Ausdrucksfehler in aussage_final) ...")
    try:
        from synthese_abschluss_check import pruefe as abschluss_pruefe, anwenden as abschluss_anwenden
        korrekturen = abschluss_pruefe(empfehlung)
        angewendet = abschluss_anwenden(empfehlung, korrekturen)
        print(f"  {len(angewendet)} Korrektur(en) angewendet.")
        for k in angewendet:
            print(f"    [{k['id']}] {k['grund']}: \"{k['original']}\" -> \"{k['korrigiert']}\"")
    except Exception as exc:
        print(f"  WARNUNG: Abschluss-Check fehlgeschlagen ({exc}), übersprungen.")

    with open(EMPFEHLUNG_OUT, "w", encoding="utf-8") as f:
        json.dump(empfehlung, f, ensure_ascii=False, indent=2)
    print(f"Geschrieben: {EMPFEHLUNG_OUT}")

    timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    archive_path = Path(RUNS_DIR) / f"empfehlung_final_{timestamp}.json"
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with open(archive_path, "w", encoding="utf-8") as f:
        json.dump(empfehlung, f, ensure_ascii=False, indent=2)
    print(f"Archiviert: {archive_path}")


if __name__ == "__main__":
    main()

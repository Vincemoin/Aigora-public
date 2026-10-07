# -*- coding: utf-8 -*-
"""
synthese_completeness_audit.py

Operationalisiert "Wie vollstaendig ist das finale Empfehlungspapier?" auf
drei Arten, die alle OHNE einen externen, per Definition unerreichbaren
"objektiv vollstaendige Politik"-Massstab auskommen:

  1. Dimensionsebene: wie viele finale Empfehlungen je der sechs Cashore-
     Howlett-Dimensionen (reiner Code, aus empfehlung_final.json).
  2. Pipeline-Attrition: vom rohen Sitzung-2-Standpunkt bis zur finalen
     Empfehlung -- wie viele Standpunkte wurden auf welcher Filterstufe
     ausgeschlossen, wie viele im letzten Schritt redundanzbereinigt/
     zusammengefuehrt (reiner Code, aus data/synthese/standpunkt_filter.json
     + session2_diskurse.json + empfehlung_final.json).
  3. Themenkatalog-Abdeckung: von den in gpr_core.py Abschnitt 4 curierten
     41 Unterthemen (der eigene, im System-Design bereits festgelegte
     Vollstaendigkeits-Massstab) -- wie viele sind im finalen Papier durch
     MINDESTENS eine Empfehlung inhaltlich abgedeckt, unabhaengig von der
     genauen inhaltlichen Ausrichtung (ein LLM-Call, da freie Sprache auf
     beiden Seiten -- Kandidaten-Formulierungen UND Katalog -- keinen
     Text-Match erlaubt).

Ausgabe:
    data/synthese/completeness_audit.json
    data/synthese/completeness_audit.md
"""
import json
import os
import re

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
THESISDATEN = os.path.join(REPO, "Thesisdaten")
EMPFEHLUNG_PATH = os.path.join(REPO, "data", "synthese", "empfehlung_final.json")
FILTER_PATH = os.path.join(REPO, "data", "synthese", "standpunkt_filter.json")
DISKURSE_PATH = os.path.join(REPO, "data", "session2_diskurse.json")
OUT_JSON = os.path.join(REPO, "data", "synthese", "completeness_audit.json")
OUT_MD = os.path.join(REPO, "data", "synthese", "completeness_audit.md")

DIM_ORDER_DE = ["Übergeordnete Ziele", "Konkrete Ziele", "Zwischenziele",
                "Umsetzungslogik", "Instrumententyp", "Feinausgestaltung"]
DIM_DE_TO_EN = {"Übergeordnete Ziele": "Goals", "Konkrete Ziele": "Objectives",
                "Zwischenziele": "Settings", "Umsetzungslogik": "InstrumentLogic",
                "Instrumententyp": "Tools", "Feinausgestaltung": "Calibrations"}

TOPIC_CATALOG = {
    "Goals": [
        ("G1", "Intergenerationelle Abwaegung (Diskontraten-Frage, nicht \"Klimaschutz vs. Wirtschaft\")"),
        ("G2", "Soziale Gerechtigkeit & Verteilung (wessen Interessen profitieren, wer zahlt)"),
        ("G3", "Wirtschaftliche Grundhaltung (Industrieschutz, Wachstum/Degrowth)"),
        ("G4", "Versorgungssicherheit und Resilienz"),
        ("G5", "Globale Klimagerechtigkeit"),
        ("G6", "Vorreiterrolle"),
        ("G7", "Optional: anthropozentrische vs. oekozentrische Grundhaltung"),
    ],
    "Objectives": [
        ("O1", "Sektorales THG-Ziel Gebaeude (KSG): 67 Mio. t CO2-Aeq. bis 2030"),
        ("O2", "Sanierungsrate: ca. 1%/Jahr, Zielkorridor 1,5-4,8%"),
        ("O3", "EE-Anteil bei neuen Heizungen: 65%-Vorgabe vs. gestuftes System"),
        ("O4", "Waermenetz-Dekarbonisierung (WPG-Stufenziele)"),
        ("O5", "Fernwaerme-Ausbau: 100.000 Neuanschluesse/Jahr"),
        ("O6", "Waermepumpen-Ausbauziel: 500.000/Jahr"),
        ("O7", "Gebaeude-Effizienzstandards (MEPS)"),
        ("O8", "Kommunale Waermeplanung: Fristen/Umsetzungsstand"),
    ],
    "Settings": [
        ("S1", "Bauteilanforderungen (U-Werte)"),
        ("S2", "Heizungsanforderungen: 65%-Pflicht vs. gestuftes Quotensystem"),
        ("S3", "Betriebsverbot fossiler Kessel: Enddatum 2044/2045"),
        ("S4", "Effizienzstandards Nichtwohngebaeude (MEPS)"),
        ("S5", "Mietrechtliche Kopplung: CO2-Kostenteilungs-Stufentabelle, JAZ-Effizienznachweis"),
    ],
    "InstrumentLogic": [
        ("L1", "Ordnungsrecht vs. Marktmechanismus (CO2-Preis)"),
        ("L2", "Technologieoffenheit als Norm"),
        ("L3", "Kosteneffizienz/Level Playing Field"),
        ("L4", "Planungssicherheit als Meta-Norm"),
        ("L5", "Subsidiaritaet/Buergerbeteiligung (welche Ebene entscheidet)"),
        ("L6", "Legitimitaet staatlichen Eingreifens"),
        ("L7", "Fiskalisches Vorgehen: Schuldenbremse vs. kreditfinanziertes Handeln"),
        ("L8", "Konkurrierende Verteilungsprinzipien"),
    ],
    "Tools": [
        ("T1", "Ausgleichsmechanismus-Ort: eigenes Instrument vs. allgemeines Steuersystem"),
        ("T2", "Ordnungsrechtliche/finanzielle/preisliche/planerische/informatorische Instrumente"),
        ("T3", "GEG/GModG als Kern-Ordnungsinstrument"),
        ("T4", "CO2-Bepreisung/Emissionshandel als Instrumentenwahl"),
        ("T5", "Foerderinstrumente (BEG)"),
        ("T6", "Kommunale Waermeplanung als planerisches Instrument"),
        ("T7", "Weisse-Zertifikate/Effizienzverpflichtung"),
        ("T8", "Fernwaerme-Lieferrecht"),
    ],
    "Calibrations": [
        ("C1", "BEG-Foerdersaetze und Boni"),
        ("C2", "Modernisierungsumlage: 8%/10% vs. 3-7%"),
        ("C3", "CO2-Preishoehe konkret"),
        ("C4", "CO2-Kostenteilung Mieter/Vermieter"),
        ("C5", "Fernwaerme-Bilanzierungsmethodik"),
    ],
}
ALL_CODES = {code for items in TOPIC_CATALOG.values() for code, _ in items}

empfehlung = json.load(open(EMPFEHLUNG_PATH, encoding="utf-8"))
filt = json.load(open(FILTER_PATH, encoding="utf-8"))
diskurse = json.load(open(DISKURSE_PATH, encoding="utf-8"))

# =====================================================================
# TEIL 1: Dimensions-Ebene -- finale Eintraege je Dimension
# =====================================================================
teil1 = {}
for dim in DIM_ORDER_DE:
    inhalt = empfehlung["dimensionen"].get(dim, {})
    teil1[dim] = {
        "n_final_eintraege": len(inhalt.get("eintraege", [])),
        "hat_datenluecken_notiz": bool(inhalt.get("datenluecken")),
    }

# =====================================================================
# TEIL 2: Pipeline-Attrition (roher S2-Standpunkt -> finale Empfehlung)
# =====================================================================
n_standpunkte_diskurs = sum(len(lager.get("standpunkte", [])) for di in diskurse["diskurse"] for lager in di["lager"])
n_unwidersprochen = len(diskurse.get("unwidersprochene_punkte", []))

def combined_status(key, sa, sb, sc):
    a = sa[key]["status"]
    if a in ("bestaetigt", "ausgeschlossen"):
        return "in_empfehlung" if a == "bestaetigt" else "ausgeschlossen"
    # a == "unklar" -> Stufe B
    b = sb.get(key)
    if b is None:
        return "unklar_ungeloest"
    if b["einordnung"] in ("passt", "dopplung"):
        return "in_empfehlung"
    # "widerspricht" oder "unklar" -> Stufe C
    c = sc.get(key)
    if c is None:
        return "unklar_ungeloest"
    if c["verdikt"] == "aufnehmen":
        return "in_empfehlung"
    if c["verdikt"] == "ausschliessen":
        return "ausgeschlossen"
    return "profil_check_noetig"  # ungeklaerter Sonderfall, siehe synthese_stufe_c.py

sa, sb, sc = filt["stufe_a"], filt["stufe_b"], filt["stufe_c"]
from collections import Counter
status_counts = Counter(combined_status(k, sa, sb, sc) for k in sa)

n_final_entries = sum(len(empfehlung["dimensionen"][d]["eintraege"]) for d in DIM_ORDER_DE)

teil2 = {
    "n_standpunkte_aus_diskursen": n_standpunkte_diskurs,
    "n_unwidersprochene_punkte": n_unwidersprochen,
    "n_standpunkte_im_filterverfahren": filt["zusammenfassung"]["n_gesamt"],
    "hinweis_differenz": (
        f"{n_standpunkte_diskurs} Standpunkte in den Diskursen gezaehlt, aber "
        f"{filt['zusammenfassung']['n_gesamt']} im Filterverfahren -- Differenz "
        f"vermutlich dadurch, dass ein Standpunkt aus einem dimensionsuebergreifenden "
        f"Diskurs (siehe 'urspruengliche_dimensionen') in mehr als ein Dimensions-Dossier "
        f"eingeht. Nicht abschliessend verifiziert, hier transparent als offene Frage "
        f"vermerkt statt glattgezogen."
    ),
    "kombinierter_filterstatus": dict(status_counts),
    "n_final_nach_redundanzbereinigung": n_final_entries,
    "konsolidierungs_hinweis": (
        f"{status_counts.get('in_empfehlung', 0)} Standpunkte erreichten Status "
        f"'in_empfehlung', aber nur {n_final_entries} eigenstaendige Empfehlungen stehen "
        f"im finalen Papier -- die Differenz ist erwartbare, im Pipeline-Design vorgesehene "
        f"Konsolidierung (mehrere inhaltlich naheliegende Standpunkte -> eine gemeinsame "
        f"Formulierung), keine zusaetzliche, unsichtbare Ablehnung."
    ),
}

# =====================================================================
# TEIL 3 Vorbereitung: Datenluecken-Notizen direkt uebernehmen
# =====================================================================
teil3_datenluecken = {
    dim: empfehlung["dimensionen"][dim].get("datenluecken")
    for dim in DIM_ORDER_DE
}

# =====================================================================
# TEIL 4: Themenkatalog-Abdeckung (ein globaler LLM-Call)
# =====================================================================
def alle_finalen_aussagen():
    out = []
    for dim in DIM_ORDER_DE:
        for e in empfehlung["dimensionen"][dim]["eintraege"]:
            out.append({"dim": DIM_DE_TO_EN[dim], "id": e["id"], "aussage": e["aussage_final"]})
    return out

CATALOG_TEXT = "\n\n".join(
    f"### {dim}\n" + "\n".join(f"- {code}: {label}" for code, label in items)
    for dim, items in TOPIC_CATALOG.items()
)

SYS = (
    "Dir liegt (a) ein fester Themenkatalog vor -- die im Systemdesign vorab curierten "
    "Unterthemen je Politik-Dimension einer Buergerbeteiligungsstudie zur deutschen "
    "Waermewende -- und (b) die Liste der finalen, tatsaechlich verabschiedeten "
    "Politik-Empfehlungen aus derselben Studie.\n\n"
    "AUFGABE: Bestimme fuer JEDES Katalog-Item (per Code), ob mindestens EINE finale "
    "Empfehlung dieses Thema INHALTLICH aufgreift -- UNABHAENGIG davon, welche konkrete "
    "Position/Richtung die Empfehlung dazu einnimmt (auch eine Empfehlung, die das Thema "
    "nur am Rande/impliziert behandelt, zaehlt als abgedeckt, wenn der inhaltliche Bezug "
    "erkennbar ist). Wenn kein finaler Eintrag das Thema in irgendeiner Form aufgreift, "
    "gilt es als NICHT abgedeckt.\n\n"
    "THEMENKATALOG:\n\n" + CATALOG_TEXT + "\n\n"
    "WICHTIG fuer gueltiges JSON: keine Anfuehrungszeichen in Begruendungstexten, kein "
    "Trailing-Komma. Antworte NUR mit JSON:\n"
    '{"G1": {"abgedeckt": true|false, "beleg_ids": ["<final-item-id>", ...], '
    '"begruendung": "<1 Satz>"}, "G2": {...}, ... fuer ALLE Codes aus dem Katalog}'
)


def run_llm_check():
    try:
        import truststore; truststore.inject_into_ssl()
    except ImportError:
        pass
    from dotenv import load_dotenv
    load_dotenv(os.path.join(REPO, ".env"))
    from anthropic import Anthropic
    client = Anthropic()

    payload = alle_finalen_aussagen()
    msg = "Finale Empfehlungen:\n\n" + json.dumps(payload, ensure_ascii=False, indent=1)

    def call():
        resp = client.messages.create(model="claude-sonnet-5", max_tokens=8000,
                                       system=SYS, messages=[{"role": "user", "content": msg}])
        raw = "".join(b.text for b in resp.content if b.type == "text").strip()
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw)
        raw = re.sub(r",\s*([}\]])", r"\1", raw)
        return raw

    raw = call()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        print("  !! JSON-Fehler, retry once")
        raw = call()
        return json.loads(raw)


katalog_ergebnis = run_llm_check()

# Validierung + fehlende Codes markieren statt stillschweigend ignorieren
missing_codes = ALL_CODES - set(katalog_ergebnis.keys())
if missing_codes:
    print(f"  !! Modell hat Codes ausgelassen: {sorted(missing_codes)} -- als 'nicht beurteilt' markiert")
    for c in missing_codes:
        katalog_ergebnis[c] = {"abgedeckt": None, "beleg_ids": [], "begruendung": "vom Modell ausgelassen"}

n_abgedeckt = sum(1 for v in katalog_ergebnis.values() if v.get("abgedeckt") is True)
n_katalog = len(ALL_CODES)

# =====================================================================
# Zusammenschreiben
# =====================================================================
out = {
    "teil1_dimensionsebene": teil1,
    "teil2_pipeline_attrition": teil2,
    "teil3_datenluecken_je_dimension": teil3_datenluecken,
    "teil4_themenkatalog_abdeckung": {
        "n_katalog_gesamt": n_katalog,
        "n_abgedeckt": n_abgedeckt,
        "abdeckungsquote": n_abgedeckt / n_katalog,
        "je_item": katalog_ergebnis,
    },
}
json.dump(out, open(OUT_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("geschrieben:", OUT_JSON)

# ---------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------
lines = ["# Aigora -- Vollstaendigkeits-Audit des finalen Empfehlungspapiers", ""]

lines += ["## 1. Dimensionsebene", "",
          "| Dimension | finale Empfehlungen | Datenluecken-Notiz vorhanden? |",
          "|---|--:|:--:|"]
for dim in DIM_ORDER_DE:
    t = teil1[dim]
    lines.append(f"| {dim} | {t['n_final_eintraege']} | {'ja' if t['hat_datenluecken_notiz'] else 'nein'} |")
lines.append("")

lines += ["## 2. Pipeline-Attrition (roher Standpunkt -> finale Empfehlung)", "",
          f"- Standpunkte aus den 6 Sitzung-2-Diskursen: **{teil2['n_standpunkte_aus_diskursen']}**, "
          f"plus {teil2['n_unwidersprochene_punkte']} von vornherein unwidersprochene Punkte.",
          f"- Im No-Objection-Filterverfahren bewertet: **{teil2['n_standpunkte_im_filterverfahren']}** "
          f"({teil2['hinweis_differenz']})",
          "- Kombinierter Endstatus je Standpunkt nach Stufe A/B/C:", ""]
for status, n in sorted(teil2["kombinierter_filterstatus"].items(), key=lambda x: -x[1]):
    lines.append(f"  - {status}: {n}")
lines += ["",
          f"- Finale, eigenstaendige Empfehlungen nach Redundanzbereinigung: **{teil2['n_final_nach_redundanzbereinigung']}**",
          f"- {teil2['konsolidierungs_hinweis']}", ""]

lines += ["## 3. Datenluecken je Dimension (direkt aus dem Pipeline-Output)", ""]
for dim, txt in teil3_datenluecken.items():
    lines.append(f"**{dim}:** {txt if txt else '(keine Notiz -- Pipeline hat hier keine Datenluecke vermerkt)'}")
    lines.append("")

t4 = out["teil4_themenkatalog_abdeckung"]
lines += ["## 4. Themenkatalog-Abdeckung", "",
          f"**{t4['n_abgedeckt']} von {t4['n_katalog_gesamt']} curierten Unterthemen "
          f"({t4['abdeckungsquote']:.0%}) sind im finalen Papier durch mindestens eine "
          f"Empfehlung inhaltlich abgedeckt.**", "",
          "| Code | Thema | Abgedeckt? | Beleg | Begründung |",
          "|---|---|:--:|---|---|"]
for dim, items in TOPIC_CATALOG.items():
    for code, label in items:
        v = katalog_ergebnis.get(code, {})
        status = {"True": "JA", "False": "NEIN", "None": "n/a"}[str(v.get("abgedeckt"))]
        beleg = ", ".join(v.get("beleg_ids", [])) or "--"
        begr = v.get("begruendung", "")
        lines.append(f"| {code} | {label} | {status} | {beleg} | {begr} |")

open(OUT_MD, "w", encoding="utf-8").write("\n".join(lines))
print("geschrieben:", OUT_MD)
print(f"\nThemenkatalog-Abdeckung: {n_abgedeckt}/{n_katalog} ({n_abgedeckt/n_katalog:.0%})")

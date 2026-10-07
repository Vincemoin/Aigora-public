"""
session2_bewertungen.py

Datenmodell fuer die Bewertungen aus Sitzung 2.

Kernlogik: Zustimmung zu einem Lager wird auf ALLE Standpunkte darunter
vererbt. Direkte Standpunkt-Bewertungen ueberschreiben die Vererbung. Jede
Bewertung traegt ein Herkunfts-Flag ("direkt" oder "vererbt"), damit spaeter
eine Sensitivitaetsanalyse moeglich ist (aendert sich das Ergebnis, wenn man
nur direkte Bewertungen zaehlt?) und damit messbar ist, wie tief die Gruppe
tatsaechlich eingestiegen ist.

Struktur pro Teilnehmenden (eine JSON-Datei):

{
  "participant_id": "P-017",
  "session": 2,
  "started_at": "2026-08-26T14:03:11",
  "completed_at": null,
  "diskurse": {
    "D1": {
      "stufe": 1,
      "uebersprungen": false,
      "bearbeitungszeit_sek": 412,
      "eigene_verortung": {
        "algorithmisch_lager": "D1-L1",
        "algorithmisch_standpunkte": ["D1-L1-S1", "D1-L1-S3"],
        "bestaetigt": true,
        "korrigiert_zu_lager": null,
        "kommentar": ""
      },
      "lager_bewertungen": {
        "D1-L1": {"wert": 5, "kommentar": ""},
        "D1-L2": {"wert": 2, "kommentar": "Verstehe das Anliegen, aber..."}
      },
      "standpunkt_bewertungen": {
        "D1-L1-S1": {"wert": 5, "quelle": "vererbt", "kommentar": ""},
        "D1-L1-S2": {"wert": 3, "quelle": "direkt", "kommentar": "hier gehe ich nicht ganz mit"}
      },
      "kompromissvorschlag": "Ich koennte mit einer Pflicht leben, wenn..."
    }
  }
}

ZA-Skala: 0 = kein Urteil, 1 = gar nicht, 2, 3, 4, 5 = voll zu.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

BEWERTUNGEN_DIR = "data/session2_bewertungen"

SKALA_MIN = 0
SKALA_MAX = 5
KEIN_URTEIL = 0

QUELLE_DIREKT = "direkt"
QUELLE_VERERBT = "vererbt"


# =====================================================================
# Anlegen und Laden
# =====================================================================

def neue_bewertung(participant_id):
    """Erzeugt einen leeren Bewertungsdatensatz."""
    return {
        "participant_id": participant_id,
        "session": 2,
        "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "completed_at": None,
        "hatte_s1_positionen": None,  # wird beim ersten Laden gesetzt (True/False)
        "diskurse": {},
    }


def markiere_s1_status(daten, hatte_positionen: bool):
    """Haelt fest, ob diese Person ueberhaupt eigene Sitzung-1-Positionen
    in der Diskursstruktur hatte. Einmalig gesetzt (aendert sich nicht mehr,
    auch wenn spaeter neu geclustert wird -- das Feld beschreibt den Stand
    beim ERSTEN Betreten von Sitzung 2, nicht den aktuellen). Erleichtert
    die spaetere Auswertung: Filterung nach S1+S2-vollstaendigen vs.
    S2-only-Teilnehmenden ohne manuellen Abgleich mit der Excel-Liste."""
    if daten.get("hatte_s1_positionen") is None:
        daten["hatte_s1_positionen"] = hatte_positionen
    return daten


def pfad_fuer(participant_id, basis_dir=BEWERTUNGEN_DIR):
    return Path(basis_dir) / f"{participant_id}_s2.json"


def laden(participant_id, basis_dir=BEWERTUNGEN_DIR):
    """Laedt bestehende Bewertungen oder legt einen neuen Datensatz an."""
    pfad = pfad_fuer(participant_id, basis_dir)
    if pfad.exists():
        with open(pfad, encoding="utf-8") as f:
            return json.load(f)
    return neue_bewertung(participant_id)


def speichern(daten, basis_dir=BEWERTUNGEN_DIR):
    """Speichert Bewertungen atomar (erst temp, dann umbenennen)."""
    pfad = pfad_fuer(daten["participant_id"], basis_dir)
    pfad.parent.mkdir(parents=True, exist_ok=True)
    temp = pfad.with_suffix(".tmp")
    with open(temp, "w", encoding="utf-8") as f:
        json.dump(daten, f, ensure_ascii=False, indent=2)
    temp.replace(pfad)
    return pfad


def _diskurs_block(daten, diskurs_id, stufe=1):
    """Holt oder erzeugt den Block fuer einen Diskurs."""
    if diskurs_id not in daten["diskurse"]:
        daten["diskurse"][diskurs_id] = {
            "stufe": stufe,
            "uebersprungen": False,
            "bearbeitungszeit_sek": 0,
            "eigene_verortung": None,
            "lager_bewertungen": {},
            "standpunkt_bewertungen": {},
            "kompromissvorschlag": "",
        }
    return daten["diskurse"][diskurs_id]


# =====================================================================
# Eigene Verortung
# =====================================================================

def verortung_setzen(daten, diskurs_id, algorithmisch_lager, algorithmisch_standpunkte, stufe=1):
    """Speichert die algorithmische Zuordnung (vor jeder Nutzerreaktion)."""
    block = _diskurs_block(daten, diskurs_id, stufe)
    block["eigene_verortung"] = {
        "algorithmisch_lager": algorithmisch_lager,
        "algorithmisch_standpunkte": list(algorithmisch_standpunkte or []),
        "bestaetigt": None,
        "korrigiert_zu_lager": None,
        "kommentar": "",
    }
    return daten


def verortung_bestaetigen(daten, diskurs_id, kommentar=""):
    """Person bestaetigt: die Zuordnung trifft zu."""
    block = _diskurs_block(daten, diskurs_id)
    if block["eigene_verortung"] is None:
        raise ValueError(f"Keine Verortung fuer {diskurs_id} gesetzt")
    block["eigene_verortung"]["bestaetigt"] = True
    block["eigene_verortung"]["korrigiert_zu_lager"] = None
    if kommentar:
        block["eigene_verortung"]["kommentar"] = kommentar
    return daten


def verortung_korrigieren(daten, diskurs_id, neues_lager, kommentar=""):
    """Person ordnet sich selbst einem anderen Lager zu.

    Das algorithmische Original bleibt erhalten -- die Differenz zwischen
    algorithmisch_lager und korrigiert_zu_lager ist die harte
    Repraesentationsqualitaets-Metrik fuer RQ1.
    """
    block = _diskurs_block(daten, diskurs_id)
    if block["eigene_verortung"] is None:
        raise ValueError(f"Keine Verortung fuer {diskurs_id} gesetzt")
    block["eigene_verortung"]["bestaetigt"] = False
    block["eigene_verortung"]["korrigiert_zu_lager"] = neues_lager
    if kommentar:
        block["eigene_verortung"]["kommentar"] = kommentar
    return daten


# =====================================================================
# Bewertungen mit Vererbungslogik
# =====================================================================

def lager_bewerten(daten, diskurs_id, lager_id, wert, standpunkt_ids, kommentar="", stufe=1):
    """Bewertet ein Lager. Der Wert wird auf alle Standpunkte darunter
    VERERBT, ausser auf solche, die bereits eine DIREKTE Bewertung haben.

    Args:
        standpunkt_ids: alle Standpunkt-IDs dieses Lagers (aus der
            Diskurs-Struktur, nicht aus den Bewertungen)
    """
    _pruefe_wert(wert)
    block = _diskurs_block(daten, diskurs_id, stufe)
    block["lager_bewertungen"][lager_id] = {"wert": wert, "kommentar": kommentar}

    for sp_id in standpunkt_ids:
        bestehend = block["standpunkt_bewertungen"].get(sp_id)
        # Direkte Bewertungen gewinnen immer gegen Vererbung
        if bestehend and bestehend.get("quelle") == QUELLE_DIREKT:
            continue
        block["standpunkt_bewertungen"][sp_id] = {
            "wert": wert,
            "quelle": QUELLE_VERERBT,
            "kommentar": bestehend.get("kommentar", "") if bestehend else "",
        }
    return daten


def standpunkt_bewerten(daten, diskurs_id, standpunkt_id, wert, kommentar="", stufe=1):
    """Bewertet einen einzelnen Standpunkt DIREKT. Ueberschreibt eine
    zuvor vererbte Bewertung und ist gegen spaetere Vererbung geschuetzt."""
    _pruefe_wert(wert)
    block = _diskurs_block(daten, diskurs_id, stufe)
    block["standpunkt_bewertungen"][standpunkt_id] = {
        "wert": wert,
        "quelle": QUELLE_DIREKT,
        "kommentar": kommentar,
    }
    return daten


def kompromiss_speichern(daten, diskurs_id, text, stufe=1):
    block = _diskurs_block(daten, diskurs_id, stufe)
    block["kompromissvorschlag"] = text
    return daten


def diskurs_ueberspringen(daten, diskurs_id, stufe=1):
    block = _diskurs_block(daten, diskurs_id, stufe)
    block["uebersprungen"] = True
    return daten


def zeit_addieren(daten, diskurs_id, sekunden, stufe=1):
    block = _diskurs_block(daten, diskurs_id, stufe)
    block["bearbeitungszeit_sek"] = block.get("bearbeitungszeit_sek", 0) + int(sekunden)
    return daten


def abschliessen(daten):
    daten["completed_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return daten


def _pruefe_wert(wert):
    if not isinstance(wert, int) or not (SKALA_MIN <= wert <= SKALA_MAX):
        raise ValueError(f"Bewertung muss ein Integer zwischen {SKALA_MIN} und {SKALA_MAX} sein, war: {wert!r}")


# =====================================================================
# Stufen-Zuweisung (welche Diskurse bekommt wer?)
# =====================================================================

def eigene_positionen_finden(diskurs, participant_id):
    """Zieht ALLE eigenen Positionen einer Person aus EINEM Diskurs, im
    Format, das build_s2_context() aus sokra_s2_prompt.py erwartet.

    Bindeglied zwischen der Diskursstruktur (data/session2_diskurse.json)
    und Sokras Kontext. Dedupliziert nicht: wenn dieselbe Person mit
    mehreren Positionen aus verschiedenen Dimensionen im selben Standpunkt
    steht, erscheinen alle, weil jedes Zitat eigenen Kontext liefert.

    Rueckgabe: Liste von dicts mit lager_id, lager_titel, standpunkt_id,
    standpunkt_titel, herkunft_dimension, zitat.
    """
    treffer = []
    for lager in diskurs.get("lager", []):
        for sp in lager.get("standpunkte", []):
            for m in sp.get("mitglieder", []):
                if m.get("participant_id") == participant_id:
                    treffer.append({
                        "lager_id": lager["id"],
                        "lager_titel": lager.get("titel", ""),
                        "standpunkt_id": sp["id"],
                        "standpunkt_titel": sp.get("titel", ""),
                        "herkunft_dimension": m.get("herkunft_dimension", "?"),
                        "zitat": m.get("zitat", ""),
                    })
    return treffer


def alle_standpunkt_ids(diskurs, lager_id=None):
    """Alle Standpunkt-IDs eines Diskurses, optional gefiltert auf ein Lager.
    Wird fuer lager_bewerten() gebraucht (Vererbungsziele)."""
    ids = []
    for lager in diskurs.get("lager", []):
        if lager_id and lager["id"] != lager_id:
            continue
        for sp in lager.get("standpunkte", []):
            ids.append(sp["id"])
    return ids


def pruefe_id_abdeckung(diskurse, bekannte_participant_ids):
    """Sanity-Check vor Studienstart: stimmen die participant_ids in der
    Diskursstruktur mit den erwarteten Teilnehmer-IDs ueberein?

    Faengt den haeufigsten Integrationsfehler ab: die IDs in
    extracted_profiles/ (und damit in session2_diskurse.json) muessen
    exakt dieselben Strings sein wie die, mit denen sich Teilnehmende in
    der App anmelden. Sonst findet stufe1_diskurse() nichts und jede
    Person landet faelschlich komplett in Stufe 2.
    """
    ids_in_daten = set()
    for d in diskurse:
        for lager in d.get("lager", []):
            for sp in lager.get("standpunkte", []):
                for m in sp.get("mitglieder", []):
                    ids_in_daten.add(m.get("participant_id"))

    bekannte = set(bekannte_participant_ids)
    return {
        "in_daten_nicht_erwartet": sorted(ids_in_daten - bekannte),
        "erwartet_ohne_positionen": sorted(bekannte - ids_in_daten),
        "n_in_daten": len(ids_in_daten),
        "n_erwartet": len(bekannte),
        "ok": not (ids_in_daten - bekannte),
    }


def stufe1_diskurse(diskurse, participant_id):
    """Diskurse, in denen diese Person eine eigene Position hat.
    Rueckgabe: Liste von (diskurs_id, lager_id, [standpunkt_ids])."""
    treffer = []
    for d in diskurse:
        lager_treffer = {}
        for lager in d.get("lager", []):
            for sp in lager.get("standpunkte", []):
                for m in sp.get("mitglieder", []):
                    if m.get("participant_id") == participant_id:
                        lager_treffer.setdefault(lager["id"], []).append(sp["id"])
        if lager_treffer:
            # Das Lager mit den meisten eigenen Standpunkten ist die Hauptverortung
            haupt_lager = max(lager_treffer.items(), key=lambda kv: len(kv[1]))
            treffer.append((d["id"], haupt_lager[0], haupt_lager[1]))
    return treffer


def stufe2_diskurse(diskurse, participant_id, anzahl=3):
    """Die groessten Diskurse (nach Personenzahl), in denen diese Person
    KEINE eigene Position hat. Schliesst die Legitimitaetsluecke bei den
    wichtigsten Streitfragen, ohne Nischendiskurse zu erzwingen."""
    eigene_ids = {d_id for d_id, _, _ in stufe1_diskurse(diskurse, participant_id)}
    kandidaten = []
    for d in diskurse:
        if d["id"] in eigene_ids or not d.get("lager"):
            continue
        personen = {
            m["participant_id"]
            for lager in d["lager"]
            for sp in lager.get("standpunkte", [])
            for m in sp.get("mitglieder", [])
        }
        kandidaten.append((len(personen), d["id"]))
    kandidaten.sort(reverse=True)
    return [d_id for _, d_id in kandidaten[:anzahl]]


# =====================================================================
# Aggregation fuer Pause 2
# =====================================================================

def s1_status_uebersicht(basis_dir=BEWERTUNGEN_DIR):
    """Liste aller Teilnehmenden, getrennt nach S1+S2-vollstaendig vs.
    S2-only-Einstieg. Ersetzt den manuellen Abgleich mit der Excel-Liste
    fuer die Sensitivitaetsanalyse in Pause 2 (siehe Methodology-Dokument:
    S2-only-Stimmen fliessen nicht ungefiltert in die primaere Synthese
    ein, sondern separat als Vergleich)."""
    vollstaendig, nur_s2, unbekannt = [], [], []
    for pfad in sorted(Path(basis_dir).glob("*_s2.json")):
        with open(pfad, encoding="utf-8") as f:
            daten = json.load(f)
        status = daten.get("hatte_s1_positionen")
        pid = daten.get("participant_id")
        if status is True:
            vollstaendig.append(pid)
        elif status is False:
            nur_s2.append(pid)
        else:
            unbekannt.append(pid)
    return {
        "vollstaendig_s1_s2": vollstaendig,
        "nur_s2": nur_s2,
        "status_unbekannt": unbekannt,
    }


def aggregieren(basis_dir=BEWERTUNGEN_DIR):
    """Fasst alle Teilnehmer-Bewertungen zu einer Matrix pro Standpunkt
    zusammen. Trennt direkte von vererbten Bewertungen, damit beide
    Auswertungen moeglich sind.

    Rueckgabe:
    {
      "D1-L1-S1": {
        "alle": [5, 4, 3, ...],
        "direkt": [4, 3],
        "vererbt": [5, ...],
        "kein_urteil": 2,
        "mittelwert_alle": 4.0,
        "mittelwert_direkt": 3.5,
        "n_alle": 12,
        "anteil_vererbt": 0.83
      }
    }
    """
    matrix = {}
    for pfad in sorted(Path(basis_dir).glob("*_s2.json")):
        with open(pfad, encoding="utf-8") as f:
            daten = json.load(f)
        for d_block in daten.get("diskurse", {}).values():
            if d_block.get("uebersprungen"):
                continue
            for sp_id, bew in d_block.get("standpunkt_bewertungen", {}).items():
                eintrag = matrix.setdefault(sp_id, {
                    "alle": [], "direkt": [], "vererbt": [], "kein_urteil": 0,
                })
                wert = bew.get("wert")
                if wert == KEIN_URTEIL:
                    eintrag["kein_urteil"] += 1
                    continue
                eintrag["alle"].append(wert)
                if bew.get("quelle") == QUELLE_DIREKT:
                    eintrag["direkt"].append(wert)
                else:
                    eintrag["vererbt"].append(wert)

    for sp_id, e in matrix.items():
        e["n_alle"] = len(e["alle"])
        e["mittelwert_alle"] = round(sum(e["alle"]) / len(e["alle"]), 2) if e["alle"] else None
        e["mittelwert_direkt"] = round(sum(e["direkt"]) / len(e["direkt"]), 2) if e["direkt"] else None
        e["anteil_vererbt"] = round(len(e["vererbt"]) / e["n_alle"], 2) if e["n_alle"] else None
    return matrix


def repraesentationsqualitaet(basis_dir=BEWERTUNGEN_DIR):
    """Harte RQ1-Metrik: wie oft wurde die algorithmische Lager-Zuordnung
    von den Teilnehmenden selbst korrigiert?"""
    bestaetigt, korrigiert, offen = 0, 0, 0
    korrekturen = []
    for pfad in sorted(Path(basis_dir).glob("*_s2.json")):
        with open(pfad, encoding="utf-8") as f:
            daten = json.load(f)
        for d_id, d_block in daten.get("diskurse", {}).items():
            v = d_block.get("eigene_verortung")
            if not v:
                continue
            if v.get("bestaetigt") is True:
                bestaetigt += 1
            elif v.get("korrigiert_zu_lager"):
                korrigiert += 1
                korrekturen.append({
                    "participant_id": daten["participant_id"],
                    "diskurs_id": d_id,
                    "algorithmisch": v.get("algorithmisch_lager"),
                    "korrigiert_zu": v.get("korrigiert_zu_lager"),
                    "kommentar": v.get("kommentar", ""),
                })
            else:
                offen += 1

    gesamt = bestaetigt + korrigiert
    return {
        "n_verortungen_beantwortet": gesamt,
        "n_bestaetigt": bestaetigt,
        "n_korrigiert": korrigiert,
        "n_offen": offen,
        "korrekturquote": round(korrigiert / gesamt, 3) if gesamt else None,
        "korrekturen": korrekturen,
    }


def fortschritt(daten, stufe1_ids, stufe2_ids):
    """Fortschrittsanzeige fuers UI."""
    def status(d_id):
        block = daten.get("diskurse", {}).get(d_id)
        if not block:
            return "offen"
        if block.get("uebersprungen"):
            return "uebersprungen"
        if block.get("lager_bewertungen") or block.get("standpunkt_bewertungen"):
            return "bearbeitet"
        return "offen"

    return {
        "stufe1": {d_id: status(d_id) for d_id in stufe1_ids},
        "stufe2": {d_id: status(d_id) for d_id in stufe2_ids},
        "stufe1_bearbeitet": sum(1 for d in stufe1_ids if status(d) == "bearbeitet"),
        "stufe1_gesamt": len(stufe1_ids),
        "stufe2_bearbeitet": sum(1 for d in stufe2_ids if status(d) == "bearbeitet"),
        "stufe2_gesamt": len(stufe2_ids),
    }

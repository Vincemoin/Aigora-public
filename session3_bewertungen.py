"""
session3_bewertungen.py

Datenmodell fuer Sitzung 3: pro Empfehlung (aus data/synthese/
empfehlung_final.json) eine Ja/Nein-Entscheidung plus optionaler Kommentar.
Deutlich einfacher als Sitzung 2 -- keine Vererbung, keine Sichtweisen-
Hierarchie, da hier nur noch die bereits gefilterten Endempfehlungen
bewertet werden.

Struktur pro Teilnehmenden (eine JSON-Datei):

{
  "participant_id": "P-017",
  "session": 3,
  "started_at": "...",
  "completed_at": null,
  "bewertungen": {
    "K-Ziele-1__Goals": {"wert": "ja", "kommentar": ""},
    "K-Fein-2__Calibrations": {"wert": "nein", "kommentar": "..."}
  },
  "konflikt_entscheidungen": {
    "0": {"gewaehlte_option": "K-Ziele-2a__Objectives", "kommentar": ""}
  }
}

wert: "ja" | "nein" | None (kein Urteil / noch nicht bearbeitet)

konflikt_entscheidungen: Schluessel ist der Index der Konfliktgruppe (siehe
empfehlung_final.json "konfliktgruppen") als String, Wert die ID der
gewaehlten Option -- eine echte Entweder-Oder-Wahl statt unabhaengiger
Ja/Nein-Bewertung pro Option (siehe der Autor: "man braucht nur auf das
eine oder andere zu klicken").
"""

import json
from datetime import datetime, timezone
from pathlib import Path

BEWERTUNGEN_DIR = "data/session3_bewertungen"


def neue_bewertung(participant_id):
    return {
        "participant_id": participant_id,
        "session": 3,
        "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "completed_at": None,
        "bewertungen": {},
        "konflikt_entscheidungen": {},
    }


def pfad_fuer(participant_id, basis_dir=BEWERTUNGEN_DIR):
    return Path(basis_dir) / f"{participant_id}_s3.json"


def laden(participant_id, basis_dir=BEWERTUNGEN_DIR):
    pfad = pfad_fuer(participant_id, basis_dir)
    if pfad.exists():
        with open(pfad, encoding="utf-8") as f:
            return json.load(f)
    return neue_bewertung(participant_id)


def speichern(daten, basis_dir=BEWERTUNGEN_DIR):
    pfad = pfad_fuer(daten["participant_id"], basis_dir)
    pfad.parent.mkdir(parents=True, exist_ok=True)
    temp = pfad.with_suffix(".tmp")
    with open(temp, "w", encoding="utf-8") as f:
        json.dump(daten, f, ensure_ascii=False, indent=2)
    temp.replace(pfad)
    return pfad


def bewerten(daten, kandidat_id, wert, kommentar=""):
    """wert: 'ja' oder 'nein'."""
    bestehend = daten["bewertungen"].get(kandidat_id, {})
    daten["bewertungen"][kandidat_id] = {
        "wert": wert,
        "kommentar": kommentar if kommentar else bestehend.get("kommentar", ""),
    }
    return daten


def kommentieren(daten, kandidat_id, kommentar):
    bestehend = daten["bewertungen"].get(kandidat_id, {})
    daten["bewertungen"][kandidat_id] = {
        "wert": bestehend.get("wert"),
        "kommentar": kommentar,
    }
    return daten


def konflikt_entscheiden(daten, gruppen_index, gewaehlte_option, kommentar=""):
    key = str(gruppen_index)
    bestehend = daten.setdefault("konflikt_entscheidungen", {}).get(key, {})
    daten["konflikt_entscheidungen"][key] = {
        "gewaehlte_option": gewaehlte_option,
        "kommentar": kommentar if kommentar else bestehend.get("kommentar", ""),
    }
    return daten


def abschliessen(daten):
    daten["completed_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return daten


def fortschritt(daten, alle_kandidat_ids, n_konfliktgruppen=0):
    bewertet = sum(1 for kid in alle_kandidat_ids if daten["bewertungen"].get(kid, {}).get("wert"))
    konflikt_entschieden = sum(
        1 for v in daten.get("konflikt_entscheidungen", {}).values() if v.get("gewaehlte_option")
    )
    return {
        "bewertet": bewertet + konflikt_entschieden,
        "gesamt": len(alle_kandidat_ids) + n_konfliktgruppen,
    }

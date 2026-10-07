"""
synthese_abschluss_check.py

Abschluss-QA-Pass ueber data/synthese/empfehlung_final.json: sucht
gezielt nach Grammatik-/Ausdrucksfehlern (fehlende Verben, abgebrochene
Satzkonstruktionen, doppelte Woerter) in den `aussage_final`-Texten, die
den Teilnehmenden in Sitzung 3 angezeigt werden -- OHNE Inhalt, Zahlen
oder Bedeutung zu veraendern. Reiner Korrektur-Pass, keine Politur/
Umformulierung aus Stilgruenden (siehe der Autor: "ich fordere einen
Abschluss-Check der solche Grammatik- und Formulierungsfehler erkennt
und behebt, sowas darf nicht passieren").

Kann eigenstaendig laufen (patcht die bestehende Datei) oder als
Funktion `pruefe(empfehlung)` in synthese_final_synthese.py eingebunden
werden.
"""

import json
import os

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

EMPFEHLUNG_PATH = "data/synthese/empfehlung_final.json"
MODEL = "claude-sonnet-5"

SYSTEM_PROMPT = """Du prüfst Formulierungen aus einem Bürgerbeteiligungs-Empfehlungsdokument
auf reine GRAMMATIK- und AUSDRUCKSFEHLER -- keine inhaltliche oder stilistische
Überarbeitung.

Suche NUR nach:
- fehlenden oder falschen Verben (z.B. "soll gesteigert werden, von vielen Teilnehmenden
  konkret auf 2 Prozent" -- Verb zum zweiten Halbsatz fehlt)
- abgebrochenen oder grammatisch unvollständigen Satzkonstruktionen
- doppelten oder widersprüchlichen Wörtern
- offensichtlichen Tippfehlern

Du darfst NICHT:
- Inhalt, Zahlen, Bedingungen oder Bedeutung verändern
- Formulierungen aus stilistischen Gründen umschreiben, wenn sie grammatisch korrekt sind
- Fachbegriffe oder Eigennamen anfassen

Gib NUR JSON zurück, ohne Fließtext davor/danach:
{
  "korrekturen": [
    {"id": "<kandidat-id>", "original": "<fehlerhafter satz>", "korrigiert": "<korrigierte version>", "grund": "<kurz, z.b. 'Verb fehlt'>"}
  ]
}
Wenn keine Fehler gefunden werden, gib {"korrekturen": []} zurück."""


def pruefe(empfehlung):
    client = Anthropic()
    eintraege = [
        {"id": x["id"], "dim": dim, "aussage": x["aussage_final"]}
        for dim, inhalt in empfehlung["dimensionen"].items()
        for x in inhalt["eintraege"]
    ]
    payload = json.dumps(eintraege, ensure_ascii=False, indent=2)

    resp = client.messages.create(
        model=MODEL,
        max_tokens=8192,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": payload}],
    )
    raw = "".join(b.text for b in resp.content if b.type == "text").strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
    try:
        result = json.loads(raw, strict=False)
    except ValueError as exc:
        print(f"  WARNUNG: Antwort nicht parsbar ({exc}), keine Korrekturen angewendet.")
        return []
    return result.get("korrekturen", [])


def anwenden(empfehlung, korrekturen):
    lookup = {
        x["id"]: x
        for inhalt in empfehlung["dimensionen"].values()
        for x in inhalt["eintraege"]
    }
    angewendet = []
    for k in korrekturen:
        x = lookup.get(k["id"])
        if not x:
            continue
        if x["aussage_final"].strip() != k["original"].strip():
            # Text hat sich seit dem Check schon geaendert -- nicht blind ueberschreiben
            continue
        x["aussage_final"] = k["korrigiert"]
        angewendet.append(k)
    return angewendet


if __name__ == "__main__":
    with open(EMPFEHLUNG_PATH, encoding="utf-8") as f:
        empfehlung = json.load(f)

    print("Prüfe aussage_final-Texte auf Grammatik-/Ausdrucksfehler ...")
    korrekturen = pruefe(empfehlung)
    print(f"  {len(korrekturen)} Korrektur(en) vorgeschlagen.")

    angewendet = anwenden(empfehlung, korrekturen)
    for k in angewendet:
        print(f"  [{k['id']}] {k['grund']}")
        print(f"    VORHER : {k['original']}")
        print(f"    NACHHER: {k['korrigiert']}")

    if angewendet:
        with open(EMPFEHLUNG_PATH, "w", encoding="utf-8") as f:
            json.dump(empfehlung, f, ensure_ascii=False, indent=2)
        print(f"Geschrieben: {EMPFEHLUNG_PATH} ({len(angewendet)} Korrektur(en) angewendet)")
    else:
        print("Keine Änderungen nötig.")

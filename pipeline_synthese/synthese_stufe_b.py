"""
synthese_stufe_b.py

Stufe B des No-Objection-Filterverfahrens (siehe synthese_standpunkt_filter.py
fuer Stufe A). Nur fuer Standpunkte, die Stufe A nicht eindeutig entscheiden
konnte (gemischtes Bild aus Zustimmung/Ablehnung).

Vorgehen pro Diskurs:
1. Ermittelt den "Diskursgewinner" -- die Sichtweise (Lager) mit der
   staerksten Gesamtzustimmung im Diskurs, reiner Code aus den echten
   Bewertungen.
2. EIN LLM-Aufruf pro Diskurs (nicht pro Standpunkt) prueft fuer jeden
   unklaren Standpunkt dieses Diskurses: passt er inhaltlich zur
   Gewinner-Sichtweise UND zu deren bestehenden Standpunkten -- also weder
   Widerspruch noch Dopplung? Wenn ja: wird der Empfehlung zugeordnet
   (ggf. der Gewinner-Sichtweise zugerechnet statt seiner urspruenglichen,
   schwaecher unterstuetzten Sichtweise). Wenn nein/unklar: geht weiter zu
   Stufe C.

Nutzung:
    python synthese_stufe_b.py
Ausgabe: aktualisiert data/synthese/standpunkt_filter.json um "stufe_b"
"""

import json
import os
import re
from collections import defaultdict

from dotenv import load_dotenv

try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

from anthropic import Anthropic

from synthese_dossiers import _fix_id, _load_bewertungen, _load_struktur

load_dotenv()

DEFAULT_MODEL = "claude-sonnet-5"
DOSSIERS_PATH = "data/synthese/dossiers.json"
FILTER_PATH = "data/synthese/standpunkt_filter.json"

SYSTEM_PROMPT = """\
<aufgabe>
In einem Diskurs einer Buergerbeteiligung zur deutschen Waermewende gibt es \
mehrere "Sichtweisen" (Lager). Eine davon hat im Diskurs den staerksten \
Rueckhalt ("Diskursgewinner"). Du bekommst deren Kernaussage und alle ihre \
bereits bestaetigten Standpunkte, sowie eine Liste WEITERER Standpunkte aus \
demselben Diskurs, deren eigene Zustimmungslage unklar ist (weder klar \
angenommen noch klar abgelehnt).
</aufgabe>

<pruefung>
Fuer jeden unklaren Standpunkt: passt er inhaltlich zur Gewinner-Sichtweise?
- "passt": widerspricht der Gewinner-Kernaussage NICHT und ist NICHT bereits \
durch einen ihrer bestehenden Standpunkte abgedeckt (keine Dopplung). Er \
wird dann in die Empfehlung uebernommen, zugeordnet zur Gewinner-Sichtweise.
- "widerspricht": steht inhaltlich im Widerspruch zur Gewinner-Kernaussage \
oder einem ihrer Standpunkte.
- "dopplung": sagt im Kern dasselbe wie ein bereits bestehender Standpunkt \
der Gewinner-Sichtweise (nenne welcher).
- "unklar": laesst sich nicht eindeutig entscheiden, braucht eine tiefere \
Pruefung der Wortlaut-Kommentare.

Sei GROSSZUEGIG bei "passt" -- die meisten konkreten Vorschlaege, die nicht \
aktiv widersprechen, sollten uebernommen werden. Nur echte inhaltliche \
Konflikte zaehlen als "widerspricht".
</pruefung>

<ausgabeformat>
Jede Zeile der zu pruefenden Standpunkte beginnt mit einem Token wie "E0",
"E1", ... -- benutze in deiner Antwort AUSSCHLIESSLICH dieses Token als
"standpunkt_id", NIEMALS die Kandidaten-ID in eckigen Klammern (kann bei
mehreren Dimensionen mehrfach vorkommen und ist nicht eindeutig).

Antworte NUR mit validem JSON:
{
  "pruefungen": [
    {"standpunkt_id": "<Token, z.B. E0>", "einordnung": "passt|widerspricht|dopplung|unklar",
     "begruendung": "1-2 Saetze", "dopplung_mit": "<Standpunkt-ID>" oder null}
  ]
}
</ausgabeformat>
"""


def _llm_json_call(client, model, system_prompt, user_message, max_tokens=16000):
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


def _lager_gesamtwert(bewertungen, d_id, l_raw):
    """Mittelwert aller direkten Lager-Bewertungen (nicht vererbt-adjustiert,
    reine Sichtweisen-Beurteilung als Ganzes) -- Basis fuer die Diskursgewinner-
    Ermittlung."""
    werte = []
    for person in bewertungen:
        block = person.get("diskurse", {}).get(d_id)
        if not block or block.get("uebersprungen"):
            continue
        lb = block.get("lager_bewertungen", {}).get(l_raw) or {}
        wert = lb.get("wert") or 0
        if wert > 0:
            werte.append(wert)
    return (round(sum(werte) / len(werte), 2), len(werte)) if werte else (None, 0)


def diskursgewinner(struktur, bewertungen):
    """Pro Diskurs: die Sichtweise mit dem hoechsten Mittelwert (bei
    Gleichstand: mehr Bewertende gewinnt). Gibt (d_id -> (l_id, lager_dict,
    mittelwert)) zurueck."""
    gewinner = {}
    for d in struktur.get("diskurse", []):
        if not d.get("lager") or d.get("error"):
            continue
        d_id = d["id"]
        beste = None
        for lager in d["lager"]:
            mw, n = _lager_gesamtwert(bewertungen, d_id, lager["id"])
            if mw is None:
                continue
            if beste is None or (mw, n) > (beste[2], beste[3]):
                beste = (lager["id"], lager, mw, n)
        if beste:
            gewinner[d_id] = beste
    return gewinner


def main():
    struktur = _load_struktur()
    bewertungen = _load_bewertungen()
    with open(DOSSIERS_PATH, encoding="utf-8") as f:
        dossiers = json.load(f)
    with open(FILTER_PATH, encoding="utf-8") as f:
        filterdaten = json.load(f)

    gewinner = diskursgewinner(struktur, bewertungen)
    print("Diskursgewinner:")
    for d_id, (l_raw, lager, mw, n) in gewinner.items():
        print(f"  {d_id}: {lager['titel']} (Ø{mw}, n={n})")

    # Standpunkt-Lookup (korrigierte IDs) fuer Positionstexte
    sp_lookup = {}
    for d in struktur.get("diskurse", []):
        if not d.get("lager"):
            continue
        for lager in d.get("lager", []):
            for sp in lager.get("standpunkte", []):
                sp_lookup[_fix_id(sp["id"], d["id"])] = {
                    "sp": sp, "lager_id": _fix_id(lager["id"], d["id"]), "lager": lager,
                }

    # unklare Standpunkte aus Stufe A, gruppiert nach Diskurs
    unklar_je_diskurs = defaultdict(list)
    for key, v in filterdaten["stufe_a"].items():
        if v["status"] != "unklar":
            continue
        dim, sp_id = key.split("::")
        d_id = sp_id.split("-")[0]
        unklar_je_diskurs[d_id].append((dim, sp_id))

    client = Anthropic()
    stufe_b_ergebnisse = {}

    for d_id, eintraege in unklar_je_diskurs.items():
        if d_id not in gewinner:
            continue
        gewinner_l_raw, gewinner_lager, mw, n = gewinner[d_id]
        gewinner_l_id = _fix_id(gewinner_l_raw, d_id)

        text = [f"Diskursgewinner in {d_id}: Sichtweise \"{gewinner_lager['titel']}\""]
        text.append(f"Kernaussage: {gewinner_lager.get('kernaussage','')}")
        text.append("Bereits bestehende Standpunkte dieser Sichtweise:")
        for sp in gewinner_lager.get("standpunkte", []):
            sp_id_fixed = _fix_id(sp["id"], d_id)
            text.append(f"  - {sp_id_fixed}: {sp.get('titel','')} — {sp.get('position','')}")

        text.append("\nZu pruefende unklare Standpunkte aus demselben Diskurs:")
        token_zu_eintrag = {}
        for i, (dim, sp_id) in enumerate(eintraege):
            info = sp_lookup.get(sp_id)
            if not info:
                continue
            sp = info["sp"]
            token = f"E{i}"
            token_zu_eintrag[token] = (dim, sp_id)
            text.append(f"  {token} [{dim}] {sp_id}: {sp.get('titel','')} — {sp.get('position','')}")

        if not token_zu_eintrag:
            continue

        ergebnis = _llm_json_call(client, DEFAULT_MODEL, SYSTEM_PROMPT, "\n".join(text))
        for p in ergebnis.get("pruefungen", []):
            token = p["standpunkt_id"]
            if token not in token_zu_eintrag:
                continue  # Modellfehler -- unbekanntes Token, wird uebersprungen
            dim, sp_id = token_zu_eintrag[token]
            stufe_b_ergebnisse[f"{dim}::{sp_id}"] = p

    n_passt = sum(1 for v in stufe_b_ergebnisse.values() if v["einordnung"] == "passt")
    n_widerspricht = sum(1 for v in stufe_b_ergebnisse.values() if v["einordnung"] == "widerspricht")
    n_dopplung = sum(1 for v in stufe_b_ergebnisse.values() if v["einordnung"] == "dopplung")
    n_unklar = sum(1 for v in stufe_b_ergebnisse.values() if v["einordnung"] == "unklar")
    print(f"\nStufe B: {len(stufe_b_ergebnisse)} geprüft -- "
          f"{n_passt} passt, {n_widerspricht} widerspricht, {n_dopplung} Dopplung, {n_unklar} unklar (-> Stufe C)")

    filterdaten["stufe_b"] = stufe_b_ergebnisse
    filterdaten["diskursgewinner"] = {
        d_id: {"lager_id": _fix_id(l_raw, d_id), "titel": lager["titel"], "mittelwert": mw, "n": n}
        for d_id, (l_raw, lager, mw, n) in gewinner.items()
    }
    with open(FILTER_PATH, "w", encoding="utf-8") as f:
        json.dump(filterdaten, f, ensure_ascii=False, indent=2)
    print(f"Aktualisiert: {FILTER_PATH}")


if __name__ == "__main__":
    main()

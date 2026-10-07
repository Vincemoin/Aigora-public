"""
synthese_vererbung_check.py

Nachtraeglicher Legitimitaets-Check der Lager->Standpunkt-Vererbung aus
Sitzung 2 -- haette laut der Autor idealerweise schon beim S2-Clustering
selbst geprueft werden muessen (passen die Standpunkte, die einem Lager
zugeordnet wurden, wirklich zu dessen Kernaussage?), wird hier aber
retrospektiv nachgeholt, weil die Antwort direkt beeinflusst, wie viel
Gewicht eine VERERBTE Lager-Zustimmung fuer einen einzelnen Standpunkt
tragen darf (siehe direkt-vs-vererbt-Transparenz in synthese_empfehlung.py).

EIN LLM-Call (17 Lager insgesamt, ueberschaubar) prueft pro Lager zwei
Dinge:

1. LEGITIMITAET DER VERERBUNG: ist jeder Standpunkt darunter eine faire
   Spezifizierung der Lager-Kernaussage, sodass eine pauschale Zustimmung/
   Ablehnung zum Lager plausibel auch fuer DIESEN Standpunkt gilt? Oder
   fuegt der Standpunkt etwas hinzu (Konkretisierung, Bedingung, Instrument),
   das die Kernaussage nicht abdeckt und wo eine Vererbung riskant waere?

2. RELEVANZ DER LAGER-KOMMENTARE: bezieht sich ein Kommentar, den jemand
   zum GESAMTEN Lager geschrieben hat, wirklich auf ALLE Standpunkte
   darunter, oder erkennbar nur auf einen bestimmten Teilaspekt (dann
   sollte er nicht unkommentiert bei allen anderen Standpunkten als
   Kontext auftauchen)?

Ausgabe: data/synthese/vererbung_check.json -- wird von
synthese_empfehlung_review.py zusaetzlich zur direkt/vererbt-Zahl
angezeigt (Legitimitaets-Warnung bei "eingeschraenkt"/"fraglich").

Nutzung:
    python synthese_vererbung_check.py
"""

import json
import os
import re

from dotenv import load_dotenv

try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

from anthropic import Anthropic

from synthese_dossiers import _fix_id, _lager_kommentare_liste, _load_bewertungen

load_dotenv()

DEFAULT_MODEL = "claude-sonnet-5"
STRUCTURE_PATH = "data/session2_diskurse.json"
OUTPUT_PATH = "data/synthese/vererbung_check.json"

SYSTEM_PROMPT = """\
<aufgabe>
Du prüfst die Struktur eines Clustering-Ergebnisses aus einer Bürgerbeteiligung \
zur deutschen Wärmewende. Innerhalb eines Diskurses wurden Positionen zu \
"Sichtweisen" (Lager) gruppiert; jedes Lager hat eine Kernaussage, und darunter \
mehrere konkretere "Standpunkte". WICHTIG für den Kontext: in der App bewerten \
Teilnehmende oft NUR die Kernaussage des Lagers (nicht jeden Standpunkt einzeln) \
-- diese pauschale Bewertung wird automatisch auf ALLE Standpunkte darunter \
VERERBT. Das ist so gewollt, aber nur legitim, wenn ein Standpunkt tatsächlich \
eine faire Spezifizierung der Kernaussage ist.
</aufgabe>

<teil_1_standpunkte>
Prüfe für jeden Standpunkt: würde jemand, der der Kernaussage des Lagers \
zustimmt (bzw. sie ablehnt), plausibel auch diesem KONKRETEN Standpunkt \
zustimmen (bzw. ihn ablehnen)? Bewerte mit:
- "hoch": der Standpunkt ist eine direkte, naheliegende Konkretisierung der \
Kernaussage -- Vererbung ist unproblematisch.
- "eingeschränkt": der Standpunkt fügt eine zusätzliche Bedingung, ein \
konkretes Instrument oder eine Nuance hinzu, die in der Kernaussage NICHT \
zwingend enthalten ist -- jemand könnte der Kernaussage zustimmen und diesem \
Standpunkt trotzdem widersprechen. Vererbung ist ein grobes Signal, kein \
verlässlicher Beleg für diesen spezifischen Punkt.
- "fraglich": der Standpunkt geht inhaltlich über das hinaus, was die \
Kernaussage abdeckt, oder widerspricht ihr sogar in einem Detail -- Vererbung \
hierher ist methodisch fragwürdig.
</teil_1_standpunkte>

<teil_2_kommentare>
Prüfe für jeden Lager-Kommentar (den jemand zur GESAMTEN Sichtweise \
geschrieben hat, nicht zu einem einzelnen Standpunkt): bezieht er sich \
erkennbar auf einen SPEZIFISCHEN Teilaspekt (z.B. nur auf ein bestimmtes \
Instrument, eine bestimmte Zahl), oder ist er allgemein genug, um sinnvoll \
als Kontext für ALLE Standpunkte des Lagers zu gelten?
- "allgemein": passt als Kontext zu allen Standpunkten.
- "spezifisch": bezieht sich erkennbar nur auf bestimmte Standpunkte -- \
nenne welche (per ID) er plausibel betrifft.
</teil_2_kommentare>

Sei nicht überkritisch -- die meisten Standpunkte sind vermutlich "hoch", die \
meisten Kommentare "allgemein". Melde nur, was wirklich auffällt.
</aufgabe>

<ausgabeformat>
Antworte NUR mit validem JSON:
{
  "lager_pruefungen": {
    "<lager_id>": {
      "standpunkte": [
        {"id": "<Standpunkt-ID>", "legitimitaet": "hoch|eingeschränkt|fraglich", "begruendung": "1 Satz"}
      ],
      "kommentare": [
        {"participant_id": "<ID>", "einordnung": "allgemein|spezifisch",
         "betrifft_standpunkte": ["<Standpunkt-ID>", ...] oder null falls allgemein,
         "begruendung": "1 Satz"}
      ]
    }
  }
}
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


def _format_lager(d, lager, bewertungen):
    d_id = d["id"]
    l_raw = lager["id"]
    l_id = _fix_id(l_raw, d_id)
    zeilen = [
        f"\n## Lager {l_id} -- \"{lager.get('titel','')}\" (Diskurs {d_id}: \"{d.get('titel','')}\")",
        f"Kernaussage: {lager.get('kernaussage','')}",
    ]
    if lager.get("bandbreite"):
        zeilen.append(f"Bandbreite: {lager['bandbreite']}")
    zeilen.append("Standpunkte darunter:")
    for sp in lager.get("standpunkte", []):
        sp_id = _fix_id(sp["id"], d_id)
        zeilen.append(f"  - {sp_id}: \"{sp.get('titel','')}\" — {sp.get('position','')}")
    kommentare = _lager_kommentare_liste(bewertungen, d_id, l_raw)
    if kommentare:
        zeilen.append("Lager-Kommentare (an die GESAMTE Sichtweise, nicht an einen Standpunkt):")
        for k in kommentare:
            zeilen.append(f"  - {k['participant_id']}: {k['kommentar']}")
    return l_id, "\n".join(zeilen)


def main():
    with open(STRUCTURE_PATH, encoding="utf-8") as f:
        struktur = json.load(f)
    bewertungen = _load_bewertungen()
    diskurse = [d for d in struktur.get("diskurse", []) if d.get("lager") and not d.get("error")]

    bloecke = []
    for d in diskurse:
        for lager in d.get("lager", []):
            _, block = _format_lager(d, lager, bewertungen)
            bloecke.append(block)
    text = "\n".join(bloecke)

    client = Anthropic()
    print(f"Pruefe {sum(len(d.get('lager', [])) for d in diskurse)} Lager (ein Aufruf) ...")
    ergebnis = _llm_json_call(client, DEFAULT_MODEL, SYSTEM_PROMPT, text, max_tokens=32000)

    pruefungen = ergebnis.get("lager_pruefungen", {})
    n_eingeschraenkt = sum(
        1 for l in pruefungen.values() for s in l.get("standpunkte", [])
        if s.get("legitimitaet") == "eingeschränkt"
    )
    n_fraglich = sum(
        1 for l in pruefungen.values() for s in l.get("standpunkte", [])
        if s.get("legitimitaet") == "fraglich"
    )
    n_spezifisch = sum(
        1 for l in pruefungen.values() for k in l.get("kommentare", [])
        if k.get("einordnung") == "spezifisch"
    )
    print(f"  Standpunkte: {n_eingeschraenkt} eingeschränkt, {n_fraglich} fraglich legitim.")
    print(f"  Kommentare: {n_spezifisch} als thematisch spezifisch (nicht allgemeingültig) markiert.")

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(ergebnis, f, ensure_ascii=False, indent=2)
    print(f"\nGeschrieben: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()

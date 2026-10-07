"""
synthese_stufe_c.py

Stufe C des No-Objection-Filterverfahrens -- der "denkende" Schritt.
Prueft alle Standpunkte, die aus Stufe B als "widerspricht" (der
Diskursgewinner-Sichtweise) oder "unklar" hervorgingen: haben sie trotzdem
eine eigene, tragfaehige (ggf. Minderheits-)Position, oder gibt es echten,
verhaeltnismaessigen Widerspruch, der sie ausschliesst?

WICHTIG (des Autors Vorgabe): eine einzelne Gegenstimme darf NIE allein
entscheiden. Die Pruefung gewichtet sowohl die Menge der Gegenstimmen
(im Verhaeltnis zu allen, die sich zu diesem Thema ueberhaupt geaeussert
haben) als auch die Substanz ihrer Argumente (echtes Gegenargument vs.
vage Ablehnung).

Primär werden die S2-Bewertungen und Kommentare im Wortlaut herangezogen.
Nur wenn das Modell selbst angibt, dass die Lage anhand der S2-Daten nicht
zu beurteilen ist (z.B. sehr duenne Beteiligung zu diesem Punkt), wird der
Fall fuer einen S1+S2-Profil-basierten Nachschlag markiert (spaetere
Ausbaustufe, wird hier nur erkannt/geflaggt, noch nicht ausgefuehrt).

Nutzung:
    python synthese_stufe_c.py
Ausgabe: aktualisiert data/synthese/standpunkt_filter.json um "stufe_c"
"""

import json
import re

from dotenv import load_dotenv

try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

from anthropic import Anthropic

load_dotenv()

DEFAULT_MODEL = "claude-sonnet-5"
DOSSIERS_PATH = "data/synthese/dossiers.json"
FILTER_PATH = "data/synthese/standpunkt_filter.json"

SYSTEM_PROMPT = """\
<aufgabe>
Du beurteilst, ob ein konkreter Standpunkt aus einer Buergerbeteiligung zur \
deutschen Waermewende trotz Gegenstimmen als tragfaehige Position (ggf. als \
dokumentierte Minderheitsposition) in ein Empfehlungsdokument aufgenommen \
werden sollte, oder ob der Widerspruch dagegen zu stark ist.

Du bist ein politisch gebildeter, kritischer, abwaegungsfaehiger Beobachter \
-- keine reine Zaehlmaschine. Bewerte sowohl die MENGE als auch die SUBSTANZ \
der Gegenstimmen.
</aufgabe>

<kriterien>
EINE EINZELNE Gegenstimme darf NIEMALS allein einen Standpunkt ausschliessen \
-- unabhaengig davon, wie gut ihr Argument ist. Schliesse einen Standpunkt \
nur aus, wenn MINDESTENS EINE der folgenden Bedingungen erfuellt ist:
- Mehrere Personen (nicht nur eine) lehnen explizit und mit nachvollziehbarem \
Grund ab, UND diese Ablehnung macht einen spuerbaren Anteil aller aus, die \
sich zu diesem Thema ueberhaupt geaeussert haben (nicht im Verhaeltnis zur \
Gesamt-Teilnehmerzahl -- wer nie zu diesem Thema Stellung bezogen hat, zaehlt \
weder dafuer noch dagegen).
- ODER: ein einzelnes Gegenargument ist inhaltlich so grundsaetzlich (trifft \
einen Kernpunkt, den auch Befuerwortende kaum von der Hand weisen koennten), \
dass es plausibel eine Mehrheit zum Nachdenken bringen wuerde -- das muss \
explizit begruendet werden, nicht nur behauptet.

Fehlende Aeusserung (Schweigen) zaehlt NIE als Ablehnung. Vage, unspezifische \
Ablehnung ("passt nicht zu mir") ohne inhaltliches Argument zaehlt wenig.

Wenn du anhand der vorliegenden S2-Bewertungen/Kommentare nicht sicher \
entscheiden kannst (z.B. sehr wenige Personen haben sich zu diesem konkreten \
Punkt geaeussert), markiere das explizit als "profil_check_noetig" statt zu \
raten.
</kriterien>

<ausgabeformat>
Antworte NUR mit validem JSON:
{
  "pruefungen": [
    {
      "id": "<Token, z.B. E0>",
      "verdikt": "aufnehmen|ausschliessen|profil_check_noetig",
      "begruendung": "2-3 Saetze: warum, mit Bezug auf Menge UND Substanz der Gegenstimmen",
      "als_minderheitsposition": true/false
    }
  ]
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


def _sammle_faelle(dossiers, filterdaten):
    """Alle Standpunkte, die aus Stufe B als 'widerspricht' oder 'unklar'
    hervorgingen -- die eigentliche Zielgruppe von Stufe C."""
    faelle = []
    for key, v in filterdaten.get("stufe_b", {}).items():
        if v["einordnung"] not in ("widerspricht", "unklar"):
            continue
        dim, sp_id = key.split("::")
        dossier_dim = dossiers.get(dim, {})
        sp = next((s for s in dossier_dim.get("standpunkte", []) if s["id"] == sp_id), None)
        if not sp:
            continue
        faelle.append({"dim": dim, "sp_id": sp_id, "sp": sp, "stufe_b": v})
    return faelle


def _format_fall(token, fall, dossiers):
    sp = fall["sp"]
    u = sp["unterstuetzung"]
    zeilen = [
        f"{token} [{fall['dim']}] {sp['id']}: \"{sp['titel']}\" — {sp['position']}",
        f"  Stufe B (Vergleich mit Diskursgewinner): {fall['stufe_b']['einordnung']} — {fall['stufe_b']['begruendung']}",
    ]
    if u["n_bewertet"]:
        zeilen.append(
            f"  Bewertungslage: n={u['n_bewertet']}, Ø={u['mittelwert']}, "
            f"Befürwortung(4-5)={u['befuerwortung_4_5']}, Ablehnung(1-2)={u['ablehnung_1_2']}"
        )
    else:
        zeilen.append("  Bewertungslage: keine Bewertungen vorhanden.")
    if u["kommentare"]:
        zeilen.append("  Kommentare (Wortlaut):")
        for k in u["kommentare"]:
            zeilen.append(f"    - {k['participant_id']} ({k['quelle']}): {k['kommentar']}")
    lager_kommentare = dossiers.get(fall["dim"], {}).get("lager_kommentare", {}).get(sp["lager_id"], [])
    if lager_kommentare:
        zeilen.append("  Kommentare zur gesamten Sichtweise (gelten indirekt auch hier):")
        for k in lager_kommentare:
            zeilen.append(f"    - {k['participant_id']} (Wert {k['wert']}): {k['kommentar']}")
    return "\n".join(zeilen)


def main():
    with open(DOSSIERS_PATH, encoding="utf-8") as f:
        dossiers = json.load(f)
    with open(FILTER_PATH, encoding="utf-8") as f:
        filterdaten = json.load(f)

    faelle = _sammle_faelle(dossiers, filterdaten)
    print(f"Stufe C: {len(faelle)} Fälle zu prüfen (aus Stufe B: 'widerspricht' oder 'unklar').")

    token_zu_fall = {f"E{i}": fall for i, fall in enumerate(faelle)}
    text = "\n\n".join(_format_fall(token, fall, dossiers) for token, fall in token_zu_fall.items())

    client = Anthropic()
    ergebnis = _llm_json_call(client, DEFAULT_MODEL, SYSTEM_PROMPT, text)

    stufe_c_ergebnisse = {}
    for p in ergebnis.get("pruefungen", []):
        token = p["id"]
        if token not in token_zu_fall:
            continue
        fall = token_zu_fall[token]
        key = f"{fall['dim']}::{fall['sp_id']}"
        stufe_c_ergebnisse[key] = p

    n_auf = sum(1 for v in stufe_c_ergebnisse.values() if v["verdikt"] == "aufnehmen")
    n_aus = sum(1 for v in stufe_c_ergebnisse.values() if v["verdikt"] == "ausschliessen")
    n_profil = sum(1 for v in stufe_c_ergebnisse.values() if v["verdikt"] == "profil_check_noetig")
    n_minderheit = sum(1 for v in stufe_c_ergebnisse.values()
                        if v["verdikt"] == "aufnehmen" and v.get("als_minderheitsposition"))
    print(f"  aufnehmen: {n_auf} (davon als Minderheitsposition markiert: {n_minderheit})")
    print(f"  ausschliessen: {n_aus}")
    print(f"  profil_check_noetig: {n_profil}")

    filterdaten["stufe_c"] = stufe_c_ergebnisse
    with open(FILTER_PATH, "w", encoding="utf-8") as f:
        json.dump(filterdaten, f, ensure_ascii=False, indent=2)
    print(f"\nAktualisiert: {FILTER_PATH}")


if __name__ == "__main__":
    main()

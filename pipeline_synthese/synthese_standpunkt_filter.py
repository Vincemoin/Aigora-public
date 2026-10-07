"""
synthese_standpunkt_filter.py

Ersetzt die alte Kandidaten-nachtraegliche-Mehrheitsfilterung
(synthese_empfehlung.py) durch das mit der Autor abgestimmte gestufte
"No-Objection"-Verfahren: ein konkreter Standpunkt bleibt in der finalen
Synthese, solange es KEINEN echten, verhaeltnismaessigen Widerspruch dagegen
gibt -- Schweigen/fehlende Aeusserung zaehlt NICHT als Ablehnung, und eine
einzelne Gegenstimme kippt nie automatisch einen Punkt.

Das Verfahren laeuft in Stufen, von guenstig/eindeutig zu teuer/aufwendig,
damit nur die wirklich strittigen Faelle den teuren letzten Schritt
erreichen:

STUFE A (reiner Code, kostenlos): Wie fiel die GESAMTBEWERTUNG der
Sichtweise (Lager) aus, der dieser Standpunkt angehoert -- direkte UND
vererbte Bewertungen zusammen? Klar positiv, keine nennenswerte direkte
Ablehnung GENAU dieses Standpunkts -> bestaetigt, fertig. Klar negativ,
keine nennenswerte direkte Zustimmung GENAU dieses Standpunkts -> raus,
fertig. Alles dazwischen -> weiter zu Stufe B.

STUFE B (LLM, nur fuer die nach A unklaren Faelle): passt der Standpunkt
inhaltlich zur Sichtweise, die in seinem Diskurs den meisten Rueckhalt hat
(dem "Diskursgewinner") -- widerspruchsfrei UND nicht bereits durch einen
dortigen Standpunkt abgedeckt (keine Dopplung)? Wenn ja: uebernommen,
zugeordnet zum Diskursgewinner statt zu seiner urspruenglichen (schwaecher
unterstuetzten) Sichtweise.

STUFE C (LLM, nur fuer die nach A+B weiterhin unklaren Restfaelle): direkte
Pruefung der Wortlaut-Kommentare der Gegenstimmen auf Substanz UND
Verhaeltnismaessigkeit -- nie eine einzelne Person allein entscheidend.
Nur wenn WIRKLICH unklar (z.B. kaum jemand hat sich zu dem Thema geaeussert,
Stimmenlage duenn): ein zusaetzlicher, S1+S2-Profil-basierter Check pro
Person (im Habermas-Machine-Stil) -- kommt erst in einer spaeteren Ausbaustufe,
falls Stufe A+B+C(Kommentare) nicht genug uebrig laesst.

Nutzung:
    python synthese_standpunkt_filter.py
Ausgabe: data/synthese/standpunkt_filter.json
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

load_dotenv()

DEFAULT_MODEL = "claude-sonnet-5"
DOSSIERS_PATH = "data/synthese/dossiers.json"
OUTPUT_PATH = "data/synthese/standpunkt_filter.json"

# Schwellenwerte fuer Stufe A -- bewusst als Verhaeltnis, nicht als absolute
# Mindestanzahl (des Autors Vorgabe: auch wenige, aber unwidersprochene
# Stimmen zaehlen; das war der Unterschied zur alten MIN_UNTERSTUETZER-Regel).
STUFE_A_POSITIV_MITTELWERT = 3.5
STUFE_A_NEGATIV_MITTELWERT = 2.5


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


# ── Stufe A ──────────────────────────────────────────────────────────

def stufe_a(dossiers):
    """Nutzt die bereits in den Dossiers berechnete Unterstuetzung
    (direkt+vererbt zusammengefuehrt) pro Standpunkt. Klare Faelle werden
    hier entschieden, alles andere geht an Stufe B weiter."""
    ergebnisse = {}
    for dim, inhalt in dossiers.items():
        for sp in inhalt["standpunkte"]:
            u = sp["unterstuetzung"]
            key = (dim, sp["id"])
            if u["n_bewertet"] == 0:
                ergebnisse[key] = {"status": "unklar", "grund": "keine Bewertungen vorhanden"}
                continue

            mittelwert = u["mittelwert"]
            n_pro = u["befuerwortung_4_5"]
            n_contra = u["ablehnung_1_2"]

            if mittelwert >= STUFE_A_POSITIV_MITTELWERT and n_contra <= max(1, n_pro // 4):
                ergebnisse[key] = {
                    "status": "bestaetigt",
                    "grund": f"Sichtweise/Standpunkt insgesamt klar positiv aufgenommen "
                             f"(Ø{mittelwert}, {n_pro} Befürwortung vs. {n_contra} Ablehnung)",
                }
            elif mittelwert <= STUFE_A_NEGATIV_MITTELWERT and n_pro <= max(1, n_contra // 4):
                ergebnisse[key] = {
                    "status": "ausgeschlossen",
                    "grund": f"Sichtweise/Standpunkt insgesamt klar negativ aufgenommen "
                             f"(Ø{mittelwert}, {n_contra} Ablehnung vs. {n_pro} Befürwortung)",
                }
            else:
                ergebnisse[key] = {
                    "status": "unklar",
                    "grund": f"Gemischtes Bild (Ø{mittelwert}, {n_pro} vs. {n_contra}) -- braucht Stufe B/C",
                }
    return ergebnisse


def main():
    with open(DOSSIERS_PATH, encoding="utf-8") as f:
        dossiers = json.load(f)

    ergebnisse = stufe_a(dossiers)

    n_bestaetigt = sum(1 for v in ergebnisse.values() if v["status"] == "bestaetigt")
    n_ausgeschlossen = sum(1 for v in ergebnisse.values() if v["status"] == "ausgeschlossen")
    n_unklar = sum(1 for v in ergebnisse.values() if v["status"] == "unklar")
    n_gesamt = len(ergebnisse)

    print(f"Stufe A: {n_gesamt} Standpunkt-Einträge geprüft (Dimensionen einzeln gezählt, "
          f"6 Standpunkte tauchen in 2 Dimensionen auf)")
    print(f"  bestätigt (klar positiv):    {n_bestaetigt}")
    print(f"  ausgeschlossen (klar negativ): {n_ausgeschlossen}")
    print(f"  unklar (-> Stufe B):          {n_unklar}")

    ausgabe = {
        "stufe_a": {f"{dim}::{sp_id}": v for (dim, sp_id), v in ergebnisse.items()},
        "zusammenfassung": {
            "n_gesamt": n_gesamt, "n_bestaetigt": n_bestaetigt,
            "n_ausgeschlossen": n_ausgeschlossen, "n_unklar": n_unklar,
        },
    }
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(ausgabe, f, ensure_ascii=False, indent=2)
    print(f"\nGeschrieben: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()

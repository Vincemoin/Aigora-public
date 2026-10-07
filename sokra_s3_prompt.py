"""
sokra_s3_prompt.py

Sokra-Systemprompt fuer Sitzung 3 (Ergebnisse & Abstimmung). Gleiche
Stimme wie S1/S2, aber andere Aufgabe: nicht mehr Debatte moderieren,
sondern das fertige Empfehlungsdokument erklaeren und bei der
Ja/Nein-Entscheidung pro Empfehlung unterstuetzen, ohne selbst eine
Richtung vorzugeben.
"""

from typing import Optional

try:
    from retrieve import retrieve
    _RAG_OK = True
except ImportError:
    _RAG_OK = False

SOKRA_S3_SYSTEM_PROMPT = """\
<rolle>
Du bist Sokra, ein KI-Moderator in einem Buergerbeteiligungsverfahren zur \
deutschen Waermewende. Sitzung 3 ist die letzte Sitzung: aus den Bewertungen \
und Kommentaren aller Teilnehmenden in Sitzung 2 wurde ein Empfehlungsdokument \
synthetisiert. Diese Person soll nun zu jeder Empfehlung Ja oder Nein sagen -- \
ob sie so in den Abschlussbericht an die Politik aufgenommen werden sollte.

Du duzt, bist sachlich und zugewandt, direkt. Maximal 3-4 Saetze, eine Frage \
pro Antwort.
</rolle>

<wie_die_empfehlungen_entstanden_sind>
Falls jemand fragt, wie eine Empfehlung zustande kam, erklaere in einfachen \
Worten: aus den Bewertungen (Zustimmungswerte 1-5) und Kommentaren aus \
Sitzung 2 wurde jeder Einzelpunkt darauf geprueft, ob es echten, ernsthaften \
Widerspruch dagegen gab. Kein Widerspruch oder nur eine vereinzelte, nicht \
mehrheitsfaehige Gegenstimme: Punkt bleibt drin. Deutlicher, begruendeter \
Widerspruch mehrerer Personen: Punkt fliegt raus. Manche Punkte sind als \
"Minderheitsposition" gekennzeichnet: sie haben einen echten, aber kleineren \
Widerspruch ueberstanden. Wo zwei Seiten unvereinbar blieben, stehen ggf. \
beide nebeneinander.
</wie_die_empfehlungen_entstanden_sind>

<deine_aufgaben>
1. ERKLAEREN: Wenn eine Formulierung unklar ist oder jemand nach dem Hintergrund \
fragt, erklaere in Alltagssprache, was die Empfehlung konkret bedeutet.

2. HERKUNFT ZEIGEN: Wenn jemand fragt, ob eine Empfehlung mit der eigenen \
Sitzung-1/2-Position zu tun hat, nutze den mitgelieferten Kontext (eigene \
Positionen, eigene Bewertungen) um das ehrlich einzuordnen -- auch wenn die \
Antwort "nein, das war nicht deine Position" lautet.

3. ENTSCHEIDUNGSHILFE: Du gibst KEINE eigene Meinung und drängst nicht zu Ja \
oder Nein. Du kannst aber helfen, Fuer und Wider zu sortieren, wenn jemand \
unsicher ist: "Was genau macht dich unsicher: der Inhalt selbst, oder wie \
konkret/vage er formuliert ist?"

4. FAKTEN: Bei Sachfragen (Zahlen, Gesetze, Studien) nutze den RAG-Corpus wie \
in S1/S2. Zitiere die Quelle. Wertaussagen sind keine Fakten, korrigiere sie nicht.
</deine_aufgaben>

<grenzen>
Keine eigene politische Meinung. Kein Druck zum Weitermachen oder zu einer \
bestimmten Entscheidung. Wenn jemand alle Empfehlungen pauschal ablehnen oder \
annehmen will, ohne sie gelesen zu haben: kurz nachfragen, ob das wirklich \
gewollt ist, dann respektieren.
</grenzen>

<stil>
KRITISCH: Verwende NIEMALS Halbgeviertstriche (–). Ersetze durch Komma, \
Doppelpunkt, Punkt oder Umformulierung. Maximal 3-4 Saetze, eine Frage pro \
Antwort. Echte Umlaute (ae als ä, oe als ö, ue als ü, ss als ß in echten Woertern).
</stil>"""


def build_global_context(empfehlung, eigene_pos_je_kandidat, aktuelle_bewertungen):
    """eigene_pos_je_kandidat: {kandidat_id: [{participant_id, zitat, sp_id}, ...]}
    -- nur Eintraege, bei denen DIESE Person unter den urspruenglichen
    Standpunkten war, die diese Empfehlung stuetzen."""
    lines = ["<sitzung3_kontext>"]

    n_gesamt = sum(len(inhalt["eintraege"]) for inhalt in empfehlung["dimensionen"].values())
    n_bewertet = sum(1 for v in aktuelle_bewertungen.values() if v.get("wert"))
    lines.append(f"\nFortschritt: {n_bewertet}/{n_gesamt} Empfehlungen bewertet.")

    for dim, inhalt in empfehlung["dimensionen"].items():
        lines.append(f"\n[{dim}]")
        for x in inhalt["eintraege"]:
            eigene = eigene_pos_je_kandidat.get(x["id"], [])
            eigene_hinweis = ""
            if eigene:
                zitate = "; ".join(f'"{e["zitat"][:100]}"' for e in eigene[:2])
                eigene_hinweis = f" [BASIERT U.A. AUF EIGENER S1-POSITION: {zitate}]"
            bew = aktuelle_bewertungen.get(x["id"], {})
            status = f" (bisher: {bew['wert']})" if bew.get("wert") else " (noch offen)"
            lines.append(f"  {x['id']}: {x['aussage_final']}{eigene_hinweis}{status}")

    lines.append("\n</sitzung3_kontext>")
    return "\n".join(lines)


def build_frage_msg(kandidat_id: str, aussage: str, frage: str,
                    eigene_zitate: Optional[list] = None) -> str:
    lines = [f"KONTEXT: Empfehlung {kandidat_id}", f"Aussage: {aussage}"]
    if eigene_zitate:
        lines.append("Eigene Position(en) dazu aus Sitzung 1: " +
                     "; ".join(f'"{z[:150]}"' for z in eigene_zitate))
    lines.append(f"Frage: {frage}")
    return "\n".join(lines)


def get_rag_context(query: str, n_results: int = 3) -> str:
    if not _RAG_OK:
        return ""
    try:
        results = retrieve(query, n_results=n_results)
        if not results:
            return ""
        lines = ["<rag_kontext>"]
        for r in results:
            src = r.get("source", "unbekannte Quelle")
            text = r.get("text", "")[:300]
            lines.append(f"[{src}]: {text}")
        lines.append("</rag_kontext>")
        return "\n".join(lines)
    except Exception:
        return ""

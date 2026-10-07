"""
sokra_s2_prompt.py  (v5)
- RAG-Corpus-Zugriff via retrieve.py (gleiche Funktion wie S1)
- Websearch als Fallback
- Halbgeviertstrich-Verbot mit explizitem Negativbeispiel
"""

from typing import Optional

# RAG-Retrieval wie in Sitzung 1
try:
    from retrieve import retrieve
    _RAG_OK = True
except ImportError:
    _RAG_OK = False

SOKRA_S2_SYSTEM_PROMPT = """\
<rolle>
Du bist Sokra, ein KI-Moderator in einem Bürgerbeteiligungsverfahren zur deutschen Wärmewende. Du sitzt in einer Seitenleiste und begleitest diese Person aktiv durch Sitzung 2 -- die Auseinandersetzung mit der Meinungslandschaft aller Teilnehmenden.

Du moderierst proaktiv: du wartest nicht auf Fragen, sondern gibst Orientierung, erklärst, fragst nach und bietest Hilfe an. Gleichzeitig respektierst du die Autonomie der Person.

Du bist dieselbe Stimme wie in Sitzung 1: sachlich, zugewandt, direkt. Du duzt. Maximal 3-4 Sätze, eine Frage pro Antwort.
</rolle>

<fakten_und_quellen>
Du hast Zugriff auf denselben RAG-Corpus wie in Sitzung 1 (GModG, Studien, Gutachten zur deutschen Wärmewende). Wenn jemand nach Fakten, Zahlen oder Quellen fragt, nutze diesen Corpus. Wenn der Corpus keine ausreichende Antwort liefert, darfst du mit Websearch recherchieren.

Zitiere immer die Quelle. Trenne klar: "Laut [Quelle]..." für belegte Fakten, "Das ist umstritten..." für Expertendissens, "Das weiß ich hier nicht sicher..." wenn keine verlässliche Quelle verfügbar ist.

Wertaussagen sind KEINE Fakten. Korrigiere nur überprüfbare Tatsachenbehauptungen, niemals Wertungen oder Prioritäten.
</fakten_und_quellen>

<deine_aufgaben>
1. ORIENTIERUNG: Erkläre wo die Person gerade steht und was als nächstes kommt. Bei Phasenwechseln aktiv informieren. Fortschritt kommentieren.

2. SACHERKLÄRUNG: Wenn ein Begriff oder Zusammenhang unklar wirkt, erkläre konkret mit Alltagsbeispiel. Biete es proaktiv an: "Soll ich kurz erklären was das konkret bedeutet?" Nie abstrakt, immer: was bedeutet das für mich persönlich?

3. VERORTUNG: Zeige wo die eigene Sitzung-1-Position steht. "Du hast damals gesagt: [Zitat]. Das wurde der Sichtweise X zugeordnet. Passt das?" Wenn nicht: erklären wie umsortiert werden kann.

4. GEGENPOSITION: Erkläre die andere Seite in ihrer stärksten Form. "Leute, die das anders sehen, argumentieren vor allem so: [echtes Zitat aus dem Kontext]"

5. KOMPROMISS ERKUNDEN (gestuft):
   Stufe 1: Konflikt benennen. "Du hast X genannt, andere sagen Y."
   Stufe 2: Zum Nachdenken nudgen. "Was wäre deine Bedingung um einen Schritt in Richtung der anderen Position zu gehen?"
   Stufe 3: Wenn Offenheit signalisiert: "Soll ich einen möglichen Kompromissansatz skizzieren?" -- erst nach Zustimmung formulieren, klar als "KI-Vorschlag, keine Empfehlung" markieren.

6. SPANNUNG AUFZEIGEN: Wenn jemand widersprüchliche Positionen hoch bewertet, einmal ruhig darauf hinweisen. Danach loslassen.
</deine_aufgaben>

<mit_sokra_besprechen>
Wenn eine Nachricht mit "KONTEXT:" beginnt, hat die Person das "Frage an Sokra"-Feld bei einer Sichtweise oder Position genutzt. Reagiere mit:
1. Was diese Position aussagt (1-2 Sätze, Alltagssprache)
2. Wo die eigene Position der Person dazu steht
3. Einer einzigen offenen Frage
Maximal 4 Sätze.
</mit_sokra_besprechen>

<grenzen>
Keine eigene politische Meinung. Fakten nur aus RAG-Corpus oder Websearch, nie aus dem Gedächtnis wenn Überprüfung möglich ist. Kein Druck zum Weitermachen oder Zustimmen.
</grenzen>

<stil>
KRITISCH: Verwende NIEMALS Halbgeviertstriche (–). Das ist ein absolutes Verbot ohne Ausnahme.
Falsch: "Das ist wichtig – und zwar sehr."
Richtig: "Das ist wichtig, und zwar sehr." oder "Das ist wichtig: sehr sogar."
Ersetze jeden Gedankenstrich durch ein Komma, einen Doppelpunkt, einen Punkt oder eine Umformulierung.

Maximal 3-4 Sätze. Eine Frage pro Antwort. Echte Umlaute (ä, ö, ü, ß -- aber Achtung: das "–" hier ist ein Beispiel für das VERBOTENE Zeichen). Biete Erklärungen als Angebote an.
</stil>"""


def build_global_context(
    alle_diskurse, unwidersprochen, eigene_diskurs_ids,
    aktuelle_bewertungen, participant_eigene_positionen,
    aktueller_diskurs_id=None
):
    lines = ["<sitzung2_kontext>"]

    if participant_eigene_positionen:
        lines.append("\nEIGENE POSITIONEN AUS SITZUNG 1:")
        for d_id, pos_list in participant_eigene_positionen.items():
            d = next((d for d in alle_diskurse if d["id"] == d_id), None)
            d_titel = d["titel"] if d else d_id
            lines.append(f"\n[{d_id}] {d_titel}:")
            for p in pos_list:
                lines.append(
                    f"  Sichtweise {p.get('lager_id','?')} / "
                    f"Position {p.get('standpunkt_id','?')} "
                    f"[{p.get('herkunft_dimension','?')}]: "
                    f"\"{p.get('zitat','')[:300]}\""
                )
    else:
        lines.append("\nKeine eigenen Positionen aus Sitzung 1 gefunden.")

    lines.append("\n\nAKTUELLE BEWERTUNGEN (0=kein Urteil, 1=gar nicht, 5=voll zu):")
    if aktuelle_bewertungen:
        for d_id, bew in aktuelle_bewertungen.items():
            d = next((d for d in alle_diskurse if d["id"] == d_id), None)
            lines.append(f"\n[{d_id}] {d['titel'] if d else d_id}:")
            for key, wert in bew.items():
                if wert > 0:
                    lines.append(f"  {key}: {wert}/5")
    else:
        lines.append("  Noch keine Bewertungen.")

    bearbeitet = [d_id for d_id, bew in aktuelle_bewertungen.items()
                  if any(v > 0 for v in bew.values())]
    lines.append(f"\n\nFORTSCHRITT:")
    lines.append(
        f"  Eigene Debatten bearbeitet: "
        f"{len([d for d in eigene_diskurs_ids if d in bearbeitet])}"
        f"/{len(eigene_diskurs_ids)}"
    )
    lines.append(f"  Gesamt: {len(bearbeitet)}/{len(alle_diskurse)}")

    if aktueller_diskurs_id:
        d = next((d for d in alle_diskurse if d["id"] == aktueller_diskurs_id), None)
        if d:
            lines.append(f"\n\nGERADE GEÖFFNET: [{d['id']}] {d['titel']}")
            lines.append(f"Streitfrage: {d.get('streitfrage','')}")
            lines.append(f"Übersicht: {d.get('uebersicht','')}")
            lines.append("\nSichtweisen:")
            for lager in d.get("lager", []):
                n_p = sum(len(sp.get("mitglieder", []))
                          for sp in lager.get("standpunkte", []))
                lines.append(
                    f"  [{lager['id']}] {lager.get('titel','')} ({n_p}P): "
                    f"{lager.get('kernaussage','')}"
                )
                for sp in lager.get("standpunkte", []):
                    n = len(sp.get("mitglieder", []))
                    lines.append(
                        f"    [{sp['id']}] {sp.get('titel','')} ({n}P, "
                        f"{sp.get('abstraktionsebene','')}): "
                        f"{sp.get('position','')[:150]}"
                    )
                    for m in sp.get("mitglieder", [])[:2]:
                        lines.append(f"      Zitat: \"{m.get('zitat','')[:150]}\"")

    lines.append("\n</sitzung2_kontext>")
    return "\n".join(lines)


def build_diskutieren_msg(titel: str, position_text: str,
                          eigenes_zitat: Optional[str] = None) -> str:
    lines = [f"KONTEXT: {titel}", f"Inhalt: {position_text}"]
    if eigenes_zitat:
        lines.append(
            f"Meine eigene Position dazu (Sitzung 1): \"{eigenes_zitat}\""
        )
    return "\n".join(lines)


def get_rag_context(query: str, n_results: int = 3) -> str:
    """Holt RAG-Kontext aus dem S1-Corpus für Sokra-Antworten."""
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

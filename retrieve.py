"""
retrieve.py

Retrieval-Funktion mit Quellenstreuungs-Filter (Schicht 2 aus unserer
Architektur-Diskussion): verhindert, dass eine einzelne grosse Quelle
die Ergebnisse dominiert.

Kann direkt zum Testen ausgefuehrt werden (siehe unten, interaktive
Testschleife) oder als Modul in chat.py importiert werden:

    from retrieve import retrieve_chunks
    results = retrieve_chunks("Was kostet eine Waermepumpe im Altbau?")
"""

import chromadb
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

DB_DIR = "./chroma_db"
COLLECTION_NAME = "aigora_corpus"
EMBED_MODEL = "text-embedding-3-large"

client_openai = OpenAI()
chroma_client = chromadb.PersistentClient(path=DB_DIR)

_known_sources_cache = None


def get_known_documents():
    """
    Holt einmalig alle Dokumente (Dateiname, Quelle, Titel) aus der DB,
    fuer die Namenserkennung in Fix B. Gecacht fuer die Sitzung.
    """
    global _known_sources_cache
    if _known_sources_cache is not None:
        return _known_sources_cache

    collection = chroma_client.get_collection(COLLECTION_NAME)
    existing = collection.get(include=["metadatas"])
    docs = {}
    for m in existing["metadatas"]:
        docs[m["dateiname"]] = {"quelle": m["quelle"], "titel": m["titel"], "dateiname": m["dateiname"]}
    result = list(docs.values())
    _known_sources_cache = result
    return result


# Woerter, die trotz Grossschreibung/Laenge NICHT als Namenserkennung zaehlen,
# weil sie generische Fachbegriffe sind, keine Eigennamen (verhindert
# Fehlalarme wie "kommunale Waermewende" -> irrtuemlich als Quellenname erkannt)
# Woerter, die trotz Vorkommen in Organisationsnamen NICHT als Namenserkennung
# zaehlen -- rein zur Effizienz (verhindert dass praktisch jede Wärmewende-Frage
# eine zusaetzliche DB-Abfrage ausloest, weil "Wärmewende" in vielen
# Herausgebernamen steckt). KEIN Bias-Schutz mehr noetig, seit Fix B "weich"
# ist: Fehlalarme verlieren einfach im fairen Ranking, verzerren nichts mehr.
DOMAIN_STOPWORDS = {
    "wärmewende", "energiewende", "energie", "wärme", "gebäude",
}

STOPWORDS = {"der", "die", "das", "und", "für", "e.v.", "&", "von", "des", "im", "in", "zur", "zum"}


def detect_mentioned_document(query, known_docs, min_word_len=4):
    """
    Prueft, ob die Anfrage einen konkreten, eigennamenartigen Bestandteil
    eines bekannten Herausgebers ODER Dokumenttitels enthaelt (z.B. "CDU",
    "Vonovia", "Haus & Grund"). Domain-generische Woerter (siehe
    DOMAIN_STOPWORDS) zaehlen bewusst NICHT.

    Ausnahme: komplett grossgeschriebene Woerter (Akronyme wie "VKU", "DIW",
    "BDEW") zaehlen bereits ab 2 Zeichen -- im Deutschen fast nie ein
    Zufallstreffer, unabhaengig von der Laenge. Normale Woerter brauchen
    weiterhin min_word_len, um Zufallsueberschneidungen zu vermeiden.

    Gibt den Dateinamen des best-passenden Dokuments zurueck, oder None.
    """
    # Original-Grossschreibung der Anfrage-Woerter separat pruefen, BEVOR
    # alles kleingeschrieben wird (fuer die Akronym-Erkennung)
    raw_query_tokens = [w.strip(".,!?") for w in query.split()]
    uppercase_query_words = set(
        w.lower() for w in raw_query_tokens if len(w) >= 2 and w.isupper()
    )

    query_words = set(w.lower() for w in raw_query_tokens)
    query_words -= STOPWORDS
    query_words -= DOMAIN_STOPWORDS

    if not query_words and not uppercase_query_words:
        return None

    best_match = None
    best_overlap = 0

    for doc in known_docs:
        combined_text = f"{doc['quelle']} {doc['titel']}"
        raw_doc_tokens = [w.strip(".,!?()\"'") for w in combined_text.split()]
        uppercase_doc_words = set(
            w.lower() for w in raw_doc_tokens if len(w) >= 2 and w.isupper()
        )
        doc_words = set(w.lower() for w in raw_doc_tokens)
        doc_words -= STOPWORDS
        doc_words -= DOMAIN_STOPWORDS

        # normale Wortueberlappung (min_word_len Pflicht)
        meaningful_overlap = [w for w in (query_words & doc_words) if len(w) >= min_word_len]
        # Akronym-Ueberlappung (schon ab 2 Zeichen, wenn in BEIDEN grossgeschrieben)
        acronym_overlap = uppercase_query_words & uppercase_doc_words

        total_overlap = len(meaningful_overlap) + len(acronym_overlap)
        if total_overlap > best_overlap:
            best_overlap = total_overlap
            best_match = doc["dateiname"]

    return best_match if best_overlap >= 1 else None


def get_targeted_candidates(query_embedding, dateiname, n=3):
    """
    Sucht INNERHALB eines erkannten Dokuments nach den tatsaechlich
    relevantesten Chunks zur Anfrage (per echter Aehnlichkeitssuche,
    nur gefiltert auf dieses eine Dokument). Liefert diese als normale
    Kandidaten zurueck -- sie werden NICHT erzwungen, sondern konkurrieren
    im regulaeren Ranking mit. Wenn nichts im Dokument thematisch passt,
    fallen sie im finalen Ranking natuerlich hinten runter/raus.
    """
    collection = chroma_client.get_collection(COLLECTION_NAME)
    try:
        results = collection.query(
            query_embeddings=[query_embedding],
            where={"dateiname": dateiname},
            n_results=n,
        )
    except Exception:
        return []

    if not results["documents"] or not results["documents"][0]:
        return []

    return [
        {"text": doc, "meta": meta, "distance": dist, "boosted": False}
        for doc, meta, dist in zip(
            results["documents"][0], results["metadatas"][0], results["distances"][0]
        )
    ]


def embed_query(query):
    response = client_openai.embeddings.create(model=EMBED_MODEL, input=[query])
    return response.data[0].embedding


def retrieve_chunks(query, n_results=5, max_per_source=2, fetch_multiplier=4):
    """
    Sucht relevante Chunks zu einer Anfrage.

    max_per_source: verhindert Dominanz einer einzelnen Quelle in den
    Ergebnissen (Schicht 2).

    fetch_multiplier: wie viele Kandidaten initial geholt werden.

    Fix B (soft): wenn die Anfrage einen eigennamenartigen Bestandteil
    eines bekannten Dokuments enthaelt (Herausgeber ODER Titel, generische
    Fachbegriffe ausgeschlossen), wird zusaetzlich GEZIELT innerhalb dieses
    Dokuments nach den relevantesten Chunks gesucht. Diese werden aber NICHT
    erzwungen -- sie konkurrieren ganz normal im Ranking mit den breiten
    Suchergebnissen. Passt nichts im erkannten Dokument zur Frage, fallen
    sie von selbst raus, statt die Ergebnisse zu verfaelschen.
    """
    collection = chroma_client.get_collection(COLLECTION_NAME)
    query_embedding = embed_query(query)

    raw_results = collection.query(
        query_embeddings=[query_embedding],
        n_results=n_results * fetch_multiplier,
    )

    candidates = []
    seen_texts = set()
    for doc, meta, dist in zip(
        raw_results["documents"][0],
        raw_results["metadatas"][0],
        raw_results["distances"][0],
    ):
        candidates.append({"text": doc, "meta": meta, "distance": dist, "boosted": False})
        seen_texts.add(doc)

    # Fix B: erkanntes Dokument gezielt durchsuchen, Ergebnisse als
    # zusaetzliche Kandidaten einspeisen (nicht erzwingen)
    known_docs = get_known_documents()
    mentioned_doc = detect_mentioned_document(query, known_docs)
    if mentioned_doc:
        print(f"  [Hinweis: '{mentioned_doc}' erkannt, durchsuche gezielt zusaetzlich]")
        targeted = get_targeted_candidates(query_embedding, mentioned_doc, n=4)
        for cand in targeted:
            if cand["text"] not in seen_texts:
                candidates.append(cand)
                seen_texts.add(cand["text"])

    # nach Distanz sortieren (kleiner = aehnlicher), damit die targeted
    # Kandidaten sich fair einreihen statt automatisch vorne zu stehen
    candidates.sort(key=lambda c: c["distance"])

    final_results = []
    source_counts = {}
    for cand in candidates:
        src = cand["meta"]["quelle"]
        count = source_counts.get(src, 0)
        if count < max_per_source:
            final_results.append(cand)
            source_counts[src] = count + 1
        if len(final_results) >= n_results:
            break

    return final_results


def format_for_agent(results):
    """
    Formatiert die Ergebnisse mit Quellenangabe, damit der GPR-Agent
    korrekt attribuieren kann (z.B. "Laut Agora Energiewende...").
    Zeigt zusaetzlich den Foerderer/Auftraggeber an, falls in den Metadaten
    vorhanden -- wichtig fuer Transparenz bei Studien, die von einer
    Interessengruppe finanziert wurden (z.B. Frondel-Aufsatz, gefoerdert
    vom Wirtschaftsrat der CDU), damit der Agent das im Dialog offenlegen
    kann statt die Quelle als neutral erscheinen zu lassen.

    Zeigt AUSSERDEM den Dokument-Link an, falls in den Metadaten vorhanden
    (Feld "link", ergaenzt via patch_links.py aus RAG_Corpus.xlsx) -- fehlt
    das Feld noch (z.B. weil patch_links.py fuer dieses Dokument noch nicht
    lief), wird einfach nichts angezeigt, kein Fehler.
    """
    formatted = []
    for r in results:
        m = r["meta"]
        foerderer = m.get("foerderer", "")
        foerderer_hinweis = f", gefoerdert/beauftragt von: {foerderer}" if foerderer else ""
        link = m.get("link", "")
        link_hinweis = f", Link: {link}" if link else ""
        formatted.append(
            f"[Quelle: {m['quelle']}{foerderer_hinweis}, {m['jahr']}, \"{m['titel']}\"{link_hinweis}]\n{r['text']}"
        )
    return "\n\n---\n\n".join(formatted)


if __name__ == "__main__":
    print("Retrieval-Test. Frage eingeben (oder 'quit' zum Beenden).\n")
    while True:
        query = input("Frage: ").strip()
        if query.lower() in ("quit", "exit", "q"):
            break
        if not query:
            continue

        results = retrieve_chunks(query)
        print(f"\n{len(results)} Chunks gefunden:\n")
        for i, r in enumerate(results, 1):
            m = r["meta"]
            preview = r["text"][:200].replace("\n", " ")
            print(f"{i}. [{m['quelle']}, {m['jahr']}] (Distanz: {r['distance']:.3f})")
            print(f"   {preview}...\n")

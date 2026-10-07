# -*- coding: utf-8 -*-
"""
synthese_s3_ergebnis.py

Letzter Schritt der Pipeline, bisher fehlend: tallied die echten Sitzung-3-
Abstimmungen (Ja/Nein pro Empfehlung, gewaehlte Option pro Konfliktgruppe)
gegen data/synthese/empfehlung_final.json und erzeugt das eigentliche
Endergebnis-Dokument -- was der bisherige policy_brief.html NICHT enthaelt
(der zeigt nur die VOR der Abstimmung gestellten Kandidaten, keine
Ergebnisse).

Datenquelle: Thesisdaten/SurfDrive/aigora_logs_s3/s3_bewertungen/P-*.json
(echte Teilnehmenden-Abstimmungen, ein Ja/Nein-Werte-Dict pro Person plus
konflikt_entscheidungen). Ballot-Item-IDs entsprechen exakt den "id"-Feldern
in empfehlung_final.json (siehe views/sitzung3_view.py, Zeile ~302/482 --
gleiche ID wird fuer Anzeige UND Abstimmung verwendet, kein Remapping).

Kohorte: Thesisdaten/cohort_final.txt (21 PIDs). Stimmdateien, die NICHT in
dieser Liste stehen (z.B. P-428 -- gefunden, aber nicht Teil der finalen
Kohorte), werden separat gemeldet, nicht stillschweigend mitgezaehlt oder
verworfen.

Ausgabe:
    data/synthese/s3_ergebnis_final.json  (volle Tally-Daten, maschinenlesbar)
    data/synthese/s3_ergebnis_final.md    (lesbare Liste je Dimension: Aussage
                                            + Ja/Nein/n + Quote + traegt/nicht)
"""
import json
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
THESISDATEN = os.path.join(REPO, "Thesisdaten")
S3_DIR = os.path.join(THESISDATEN, "SurfDrive", "aigora_logs_s3", "s3_bewertungen")
EMPFEHLUNG_PATH = os.path.join(REPO, "data", "synthese", "empfehlung_final.json")
OUT_JSON = os.path.join(REPO, "data", "synthese", "s3_ergebnis_final.json")
OUT_MD = os.path.join(REPO, "data", "synthese", "s3_ergebnis_final.md")

MEHRHEITSSCHWELLE = 0.5  # >50%, siehe Thesisdaten-Draft §3.6 ("FUER NOW; JUST %=5 WAS CHOSEN")

# P-428 (Quereinstieg ab Sitzung 2, kein S1-Log) steht seit 2026-09-26 direkt in
# cohort_final.txt (des Autors Entscheidung) -- kein Extra-Override mehr noetig.
cohort_final = [l.strip() for l in open(os.path.join(THESISDATEN, "cohort_final.txt"), encoding="utf-8")
                if l.strip() and not l.startswith("#")]
cohort_set = set(cohort_final)

empfehlung = json.load(open(EMPFEHLUNG_PATH, encoding="utf-8"))

# ---------------------------------------------------------------------
# Stimmdateien einlesen, Kohorte vs. Nicht-Kohorte trennen
# ---------------------------------------------------------------------
votes = {}          # pid -> parsed json
out_of_cohort = []  # pids gefunden, aber nicht in cohort_final.txt
skipped_test = []

for fn in sorted(os.listdir(S3_DIR)):
    if not fn.endswith(".json"):
        continue
    pid = fn[:-5]
    if pid.upper().startswith("P-ADMIN-TEST") or pid.lower().startswith("synth_"):
        skipped_test.append(pid)
        continue
    data = json.load(open(os.path.join(S3_DIR, fn), encoding="utf-8"))
    if pid not in cohort_set:
        out_of_cohort.append(pid)
        continue
    votes[pid] = data

print(f"{len(votes)} Stimmdateien aus der finalen Kohorte ({len(cohort_final)} PIDs gesamt).")
if out_of_cohort:
    print(f"  ACHTUNG -- gefunden, aber NICHT in cohort_final.txt, daher NICHT mitgezaehlt: {out_of_cohort}")
if skipped_test:
    print(f"  Test-/Synth-Accounts uebersprungen: {skipped_test}")
missing_cohort = sorted(cohort_set - set(votes.keys()))
if missing_cohort:
    print(f"  Kohorten-Mitglieder OHNE S3-Stimmdatei (kein Log gefunden): {missing_cohort}")

# ---------------------------------------------------------------------
# Konfliktgruppen-Items ausschliessen (die werden separat als Wahl gezaehlt,
# nicht als unabhaengiges Ja/Nein -- gleiche Logik wie views/sitzung3_view.py)
# ---------------------------------------------------------------------
konfliktgruppen = empfehlung.get("konfliktgruppen", [])
konflikt_ids = {(opt["dim"], opt["id"]) for kg in konfliktgruppen for opt in kg["optionen"]}

# ---------------------------------------------------------------------
# Ja/Nein-Tally je normalem Empfehlungs-Item
# ---------------------------------------------------------------------
ergebnis_dimensionen = {}
for dim, inhalt in empfehlung["dimensionen"].items():
    items_out = []
    for e in inhalt["eintraege"]:
        if (dim, e["id"]) in konflikt_ids:
            continue  # gehoert zu einer Konfliktgruppe, siehe unten
        ja = nein = kein_urteil = 0
        kommentare = []
        for pid, v in votes.items():
            b = v.get("bewertungen", {}).get(e["id"])
            wert = (b or {}).get("wert")
            if wert == "ja":
                ja += 1
            elif wert == "nein":
                nein += 1
            else:
                kein_urteil += 1
            if b and b.get("kommentar"):
                kommentare.append({"pid": pid, "kommentar": b["kommentar"]})
        entschieden = ja + nein
        quote = (ja / entschieden) if entschieden else None
        items_out.append({
            "id": e["id"],
            "aussage_final": e["aussage_final"],
            "minderheitsposition": bool(e.get("minderheitsposition", False)) if "minderheitsposition" in e else None,
            "ja": ja, "nein": nein, "kein_urteil": kein_urteil,
            "n_entschieden": entschieden,
            "zustimmungsquote": quote,
            "traegt": (quote is not None and quote > MEHRHEITSSCHWELLE),
            "kommentare": kommentare,
        })
    ergebnis_dimensionen[dim] = {"items": items_out, "datenluecken": inhalt.get("datenluecken")}

# ---------------------------------------------------------------------
# Konfliktgruppen: Verteilung der gewaehlten Option
# ---------------------------------------------------------------------
konflikt_ergebnis = []
for i, kg in enumerate(konfliktgruppen):
    idx = str(i)
    counts = {opt["id"]: 0 for opt in kg["optionen"]}
    kommentare = []
    kein_urteil = 0
    for pid, v in votes.items():
        entscheidung = v.get("konflikt_entscheidungen", {}).get(idx)
        if entscheidung and entscheidung.get("gewaehlte_option") in counts:
            counts[entscheidung["gewaehlte_option"]] += 1
            if entscheidung.get("kommentar"):
                kommentare.append({"pid": pid, "kommentar": entscheidung["kommentar"]})
        else:
            kein_urteil += 1
    total_entschieden = sum(counts.values())
    konflikt_ergebnis.append({
        "index": i,
        "gemeinsamer_kern": kg.get("gemeinsamer_kern"),
        "optionen": [
            {"id": opt["id"], "kurzlabel": opt["kurzlabel"], "stimmen": counts[opt["id"]],
             "anteil": (counts[opt["id"]] / total_entschieden) if total_entschieden else None}
            for opt in kg["optionen"]
        ],
        "n_entschieden": total_entschieden,
        "kein_urteil": kein_urteil,
        "kommentare": kommentare,
    })

# ---------------------------------------------------------------------
# JSON schreiben
# ---------------------------------------------------------------------
out = {
    "quelle_empfehlung": os.path.basename(EMPFEHLUNG_PATH),
    "kohorte_n": len(cohort_final),
    "stimmen_gezaehlt_n": len(votes),
    "stimmen_ausserhalb_kohorte_uebersprungen": out_of_cohort,
    "kohorte_ohne_stimmdatei": missing_cohort,
    "mehrheitsschwelle": MEHRHEITSSCHWELLE,
    "dimensionen": ergebnis_dimensionen,
    "konfliktgruppen": konflikt_ergebnis,
}
json.dump(out, open(OUT_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("geschrieben:", OUT_JSON)

# ---------------------------------------------------------------------
# Lesbares Markdown
# ---------------------------------------------------------------------
lines = [
    "# Aigora -- Sitzung-3-Endergebnis (finale Abstimmung)", "",
    f"Kohorte: {len(cohort_final)} Personen. Ausgewertete Stimmdateien: {len(votes)}.",
]
if missing_cohort:
    lines.append(f"Kohorten-Mitglieder ohne S3-Stimmdatei: {', '.join(missing_cohort)}.")
if out_of_cohort:
    lines.append(f"**Nicht mitgezaehlt (Stimmdatei gefunden, aber nicht in cohort_final.txt):** "
                 f"{', '.join(out_of_cohort)} -- bitte pruefen, ob das ein regulaerer, "
                 f"nachtraeglich nicht aufgenommener Teilnehmer ist.")
lines.append(f"Mehrheitsschwelle fuer 'traegt': > {MEHRHEITSSCHWELLE:.0%}.")
lines.append("")

for dim, inhalt in ergebnis_dimensionen.items():
    lines.append(f"## {dim}")
    lines.append("")
    lines.append("| Aussage | Ja | Nein | kein Urteil | Zustimmungsquote | Traegt? |")
    lines.append("|---|--:|--:|--:|--:|:--:|")
    for it in inhalt["items"]:
        quote_str = f"{it['zustimmungsquote']:.0%}" if it["zustimmungsquote"] is not None else "--"
        traegt_str = "JA" if it["traegt"] else ("NEIN" if it["zustimmungsquote"] is not None else "--")
        aussage_kurz = it["aussage_final"][:110] + ("..." if len(it["aussage_final"]) > 110 else "")
        lines.append(f"| {aussage_kurz} | {it['ja']} | {it['nein']} | {it['kein_urteil']} | "
                     f"{quote_str} | {traegt_str} |")
    lines.append("")

if konflikt_ergebnis:
    lines.append("## Konfliktgruppen (Entweder-Oder-Entscheidungen)")
    lines.append("")
    for kg in konflikt_ergebnis:
        lines.append(f"**{kg['index']}. {kg['gemeinsamer_kern']}**  ")
        lines.append(f"(entschieden: {kg['n_entschieden']}, kein Urteil: {kg['kein_urteil']})")
        lines.append("")
        for opt in kg["optionen"]:
            anteil_str = f"{opt['anteil']:.0%}" if opt["anteil"] is not None else "--"
            lines.append(f"- {opt['stimmen']} Stimmen ({anteil_str}): {opt['kurzlabel']}")
        lines.append("")

open(OUT_MD, "w", encoding="utf-8").write("\n".join(lines))
print("geschrieben:", OUT_MD)

# Konsolen-Zusammenfassung
n_items = sum(len(v["items"]) for v in ergebnis_dimensionen.values())
n_traegt = sum(1 for v in ergebnis_dimensionen.values() for it in v["items"] if it["traegt"])
print(f"\n{n_items} Empfehlungs-Items ausserhalb von Konfliktgruppen, davon {n_traegt} mit Mehrheit (>50%).")
print(f"{len(konflikt_ergebnis)} Konfliktgruppen mit Entweder-Oder-Wahl.")

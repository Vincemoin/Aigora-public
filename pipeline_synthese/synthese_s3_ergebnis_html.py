# -*- coding: utf-8 -*-
"""
synthese_s3_ergebnis_html.py

Rendert data/synthese/s3_ergebnis_final.json (siehe synthese_s3_ergebnis.py)
als lesbares HTML-Endergebnis-Dokument -- gleiche Farbsprache/Kartenlayout
wie synthese_policy_brief.py (DIM_FARBEN), aber mit den tatsaechlichen
Abstimmungsergebnissen statt der Vor-Abstimmungs-Kandidaten.

Nutzung:
    python synthese_s3_ergebnis_html.py
Erzeugt: data/synthese/s3_ergebnis_final.html
"""
import json
import os
from html import escape as e

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IN_PATH = os.path.join(REPO, "data", "synthese", "s3_ergebnis_final.json")
OUT_PATH = os.path.join(REPO, "data", "synthese", "s3_ergebnis_final.html")

DIM_FARBEN = {
    "Übergeordnete Ziele": "#1a6b3c", "Konkrete Ziele": "#2d7d9a",
    "Zwischenziele": "#5c6bc0", "Umsetzungslogik": "#7b5ea7",
    "Instrumententyp": "#b06a20", "Feinausgestaltung": "#9e3030",
}
DIM_REIHENFOLGE = ["Übergeordnete Ziele", "Konkrete Ziele", "Zwischenziele",
                   "Umsetzungslogik", "Instrumententyp", "Feinausgestaltung"]
KONFLIKT_FARBE = "#e67e22"

d = json.load(open(IN_PATH, encoding="utf-8"))


def quote_bar(ja, nein, kein_urteil, farbe):
    total = ja + nein + kein_urteil
    if total == 0:
        return ""
    w_ja = ja / total * 100
    w_nein = nein / total * 100
    w_offen = 100 - w_ja - w_nein
    return (
        '<div style="display:flex;height:14px;border-radius:7px;overflow:hidden;'
        f'margin-top:6px;background:#eee">'
        f'<div style="width:{w_ja:.2f}%;background:{farbe}"></div>'
        f'<div style="width:{w_nein:.2f}%;background:#c0392b"></div>'
        f'<div style="width:{w_offen:.2f}%;background:#ddd"></div>'
        '</div>'
    )


def item_card(it, farbe):
    quote = it["zustimmungsquote"]
    quote_str = f"{quote:.0%}" if quote is not None else "n/a"
    traegt = it["traegt"]
    status_badge = (
        f'<span style="background:{farbe};color:#fff;border-radius:3px;font-size:.68rem;'
        f'font-weight:700;padding:2px 7px">TRÄGT ({quote_str})</span>' if traegt else
        f'<span style="background:#c0392b;color:#fff;border-radius:3px;font-size:.68rem;'
        f'font-weight:700;padding:2px 7px">KEINE MEHRHEIT ({quote_str})</span>'
    )
    kommentare_html = ""
    if it["kommentare"]:
        rows = "".join(
            f'<div style="margin:3px 0;padding:4px 8px;background:#fafafa;border-radius:4px;'
            f'font-size:.78rem"><b>{e(k["pid"])}:</b> {e(k["kommentar"])}</div>'
            for k in it["kommentare"]
        )
        kommentare_html = (
            f'<details style="margin-top:8px"><summary style="cursor:pointer;color:#888;'
            f'font-size:.75rem">{len(it["kommentare"])} Kommentar(e)</summary>'
            f'<div style="margin-top:6px">{rows}</div></details>'
        )
    return (
        f'<div style="border:1px solid {farbe}55;border-radius:10px;padding:12px 16px;'
        f'margin:10px 0;background:#fff;box-shadow:0 1px 3px rgba(0,0,0,.06)">'
        f'<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:4px">'
        f'<span style="font-size:.68rem;font-weight:700;color:{farbe}">{e(it["id"])}</span>{status_badge}</div>'
        f'<div style="font-size:.92rem;font-weight:600;line-height:1.5">{e(it["aussage_final"])}</div>'
        f'{quote_bar(it["ja"], it["nein"], it["kein_urteil"], farbe)}'
        f'<div style="font-size:.72rem;color:#888;margin-top:4px">'
        f'{it["ja"]} Ja &middot; {it["nein"]} Nein &middot; {it["kein_urteil"]} kein Urteil '
        f'(n={it["ja"] + it["nein"] + it["kein_urteil"]})</div>'
        f'{kommentare_html}'
        '</div>'
    )


def dim_section(dim):
    farbe = DIM_FARBEN.get(dim, "#555")
    inhalt = d["dimensionen"].get(dim, {"items": []})
    items = inhalt["items"]
    if not items:
        return ""
    cards = "".join(item_card(it, farbe) for it in items)
    return (
        f'<section style="margin:24px 0">'
        f'<h2 style="color:{farbe};border-bottom:2px solid {farbe};padding-bottom:4px;'
        f'font-size:1.15rem">{e(dim)}</h2>{cards}</section>'
    )


def konflikt_card(kg):
    opts = sorted(kg["optionen"], key=lambda o: -(o["stimmen"]))
    max_stimmen = max((o["stimmen"] for o in opts), default=0)
    rows = []
    for opt in opts:
        anteil = opt["anteil"]
        anteil_str = f"{anteil:.0%}" if anteil is not None else "n/a"
        gewinner = opt["stimmen"] == max_stimmen and max_stimmen > 0
        bar_w = (opt["stimmen"] / max_stimmen * 100) if max_stimmen else 0
        rows.append(
            '<div style="margin:8px 0">'
            f'<div style="font-size:.85rem;{"font-weight:700" if gewinner else ""};color:#333">'
            f'{"🏆 " if gewinner else ""}{e(opt["kurzlabel"])}</div>'
            f'<div style="display:flex;align-items:center;gap:8px;margin-top:3px">'
            f'<div style="flex:1;height:10px;background:#f3e2cc;border-radius:5px;overflow:hidden">'
            f'<div style="width:{bar_w:.1f}%;height:100%;background:{KONFLIKT_FARBE}"></div></div>'
            f'<span style="font-size:.78rem;color:#7a4a00;min-width:70px;text-align:right">'
            f'{opt["stimmen"]} Stimmen ({anteil_str})</span></div>'
            '</div>'
        )
    kommentare_html = ""
    if kg["kommentare"]:
        krows = "".join(
            f'<div style="margin:3px 0;padding:4px 8px;background:#fff8f0;border-radius:4px;'
            f'font-size:.78rem"><b>{e(k["pid"])}:</b> {e(k["kommentar"])}</div>'
            for k in kg["kommentare"]
        )
        kommentare_html = (
            f'<details style="margin-top:8px"><summary style="cursor:pointer;color:#a06000;'
            f'font-size:.75rem">{len(kg["kommentare"])} Kommentar(e)</summary>'
            f'<div style="margin-top:6px">{krows}</div></details>'
        )
    return (
        f'<div style="border:2px solid {KONFLIKT_FARBE};border-radius:10px;padding:14px 18px;'
        f'margin:14px 0;background:#fff8f0">'
        f'<div style="font-size:.9rem;color:#333;margin-bottom:8px;font-weight:500">'
        f'{e(kg["gemeinsamer_kern"])}</div>'
        f'{"".join(rows)}'
        f'<div style="font-size:.72rem;color:#a06000;margin-top:6px">'
        f'entschieden: {kg["n_entschieden"]}, kein Urteil: {kg["kein_urteil"]}</div>'
        f'{kommentare_html}'
        '</div>'
    )


n_items = sum(len(v["items"]) for v in d["dimensionen"].values())
n_traegt = sum(1 for v in d["dimensionen"].values() for it in v["items"] if it["traegt"])

meldungen = []
if d.get("stimmen_ausserhalb_kohorte_uebersprungen"):
    meldungen.append(
        f'Nicht mitgezählt (Stimmdatei gefunden, aber nicht in der Kohorte): '
        f'{", ".join(d["stimmen_ausserhalb_kohorte_uebersprungen"])}.'
    )
if d.get("kohorte_ohne_stimmdatei"):
    meldungen.append(
        f'Kohorten-Mitglieder ohne S3-Stimme: {", ".join(d["kohorte_ohne_stimmdatei"])}.'
    )
meldungen_html = (
    f'<div style="font-size:.8rem;color:#888;max-width:820px;margin:6px auto 0">'
    + " ".join(e(m) for m in meldungen) + '</div>' if meldungen else ""
)

html_out = f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8">
<title>Aigora — Sitzung-3-Endergebnis</title>
<style>
  body {{ font-family: -apple-system, Segoe UI, Roboto, Arial, sans-serif; background:#f7f7f8; margin:0; padding:24px 16px 60px; color:#1a1a1a; }}
  .wrap {{ max-width:840px; margin:0 auto; }}
</style>
</head>
<body>
<div class="wrap">
  <div style="text-align:center;margin-bottom:8px">
    <div style="font-size:.72rem;color:#999;letter-spacing:.05em;text-transform:uppercase">Aigora — Bürgerbeteiligung Wärmewende</div>
    <h1 style="margin:6px 0 4px;font-size:1.5rem">Sitzung-3-Endergebnis: finale Abstimmung</h1>
    <div style="font-size:.85rem;color:#555">
      {d['stimmen_gezaehlt_n']} von {d['kohorte_n']} Kohorten-Mitgliedern haben abgestimmt &middot;
      {n_traegt} von {n_items} Einzelempfehlungen tragen (&gt;{d['mehrheitsschwelle']:.0%} Zustimmung) &middot;
      {len(d['konfliktgruppen'])} Entweder-Oder-Konfliktgruppen entschieden
    </div>
    {meldungen_html}
  </div>

  {''.join(dim_section(dim) for dim in DIM_REIHENFOLGE)}

  <section style="margin:24px 0">
    <h2 style="color:{KONFLIKT_FARBE};border-bottom:2px solid {KONFLIKT_FARBE};padding-bottom:4px;font-size:1.15rem">
      Entweder-Oder-Entscheidungen
    </h2>
    <p style="font-size:.82rem;color:#666;max-width:700px">Diese Punkte schlossen sich gegenseitig aus — jede Person musste sich für eine Option entscheiden. 🏆 markiert die Option mit den meisten Stimmen.</p>
    {''.join(konflikt_card(kg) for kg in d['konfliktgruppen'])}
  </section>

  <div style="text-align:center;font-size:.72rem;color:#aaa;margin-top:30px">
    Quelle: {e(d['quelle_empfehlung'])} &middot; erzeugt aus den echten Sitzung-3-Stimmdateien
  </div>
</div>
</body>
</html>
"""

open(OUT_PATH, "w", encoding="utf-8").write(html_out)
print("geschrieben:", OUT_PATH)

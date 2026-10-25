#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Module PRONOSTICS — séparé de bot_v12.py.
Ne lit ni n'écrit bankroll.json : il utilise uniquement le rapport d'analyses
en mémoire et écrit data/pronostics.md.
Les pourcentages sont des estimations, pas des garanties. Simulation uniquement.
"""

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

OUTPUT_FILE = Path(__file__).resolve().parent / "data" / "pronostics.md"
LOCAL_TZ = ZoneInfo("Europe/Paris")

PRUDENT_MIN = 0.65      # catégorie « Prudent »
RISKY_MIN = 0.35        # plancher de la catégorie « Plus risqué »
MAX_P = 0.90            # au-delà : quasi certain, cote sans intérêt (ex. Over 0.5)
COMBO_MIN = 0.60        # probabilité minimale d'une sélection de combiné
VALUE_EDGE = 0.03       # écart modèle - bookmaker jugé intéressant
TOP_N = 10
COMBO_EXCLUDED = {"Over 1.5"}   # règle : jamais de « plus de 1,5 but » en combiné

LABELS = {
    "1": "Victoire domicile (1)", "N": "Match nul (N)", "2": "Victoire extérieur (2)",
    "1X": "Domicile ou nul (1X)", "X2": "Extérieur ou nul (X2)", "12": "Pas de nul (12)",
    "Over 0.5": "Plus de 0,5 but", "Over 1.5": "Plus de 1,5 but",
    "Over 2.5": "Plus de 2,5 buts", "Over 3.5": "Plus de 3,5 buts",
    "Under 1.5": "Moins de 1,5 but", "Under 2.5": "Moins de 2,5 buts",
    "Under 3.5": "Moins de 3,5 buts",
    "BTTS Oui": "Les 2 équipes marquent : OUI", "BTTS Non": "Les 2 équipes marquent : NON",
}
GROUPS = [
    ("⚽ Résultat", ["1", "N", "2"]),
    ("🔁 Double chance", ["1X", "X2", "12"]),
    ("🥅 Marchés de buts", ["Over 1.5", "Under 1.5", "Over 2.5", "Under 2.5", "Over 3.5", "Under 3.5"]),
    ("🤝 Les deux équipes marquent", ["BTTS Oui", "BTTS Non"]),
]


def _f(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def pct(p):
    return f"{p:.1%}"


def bookmaker_data(item):
    """Cotes 1/N/2 (si fournies par l'API) et probabilités implicites sans marge."""
    odds = item.get("odds") or {}
    raw = {"1": _f(odds.get("homeWin")), "N": _f(odds.get("draw")), "2": _f(odds.get("awayWin"))}
    if not all(v > 1.0 for v in raw.values()):
        return {}, {}
    inverse = {k: 1.0 / v for k, v in raw.items()}
    total = sum(inverse.values())
    return raw, {k: v / total for k, v in inverse.items()}


def build_selections(matches):
    selections = []
    for item in matches:
        raw, book = bookmaker_data(item)
        for market, p in (item.get("all_markets") or {}).items():
            p = _f(p)
            selections.append({
                "item": item, "market": market, "p": p,
                "odd": raw.get(market), "book": book.get(market),
                "edge": (p - book[market]) if market in book else None,
            })
    return selections


def match_name(item):
    return f"{item.get('home_team', '?')} vs {item.get('away_team', '?')}"


def match_section(item):
    raw, book = bookmaker_data(item)
    probs = item.get("all_markets") or {}
    lines = [
        f"## {item.get('date', '')} {item.get('kickoff_local', '')} — {match_name(item)}",
        f"*{item.get('competition_name', '')}*", "",
    ]
    for title, markets in GROUPS:
        available = [m for m in markets if m in probs]
        if not available:
            continue
        best = max(available, key=lambda m: _f(probs[m]))
        lines += [f"### {title}", "",
                  "| Sélection | Modèle | Bookmaker | Écart |", "|---|---:|---:|---:|"]
        for m in available:
            p = _f(probs[m])
            star = " ⭐" if m == best else ""
            if m in book:
                lines.append(f"| {LABELS[m]}{star} | {pct(p)} | {pct(book[m])} (cote {raw[m]:.2f}) "
                             f"| {(p - book[m]) * 100:+.1f} pt |")
            else:
                lines.append(f"| {LABELS[m]}{star} | {pct(p)} | n/d | — |")
        lines.append("")
    return lines


def ranking(selections):
    prudent = sorted([s for s in selections if PRUDENT_MIN <= s["p"] <= MAX_P],
                     key=lambda s: s["p"], reverse=True)[:TOP_N]

    risky_pool = [s for s in selections if RISKY_MIN <= s["p"] < PRUDENT_MIN]
    with_edge = sorted([s for s in risky_pool if s["edge"] is not None and s["edge"] >= VALUE_EDGE],
                       key=lambda s: s["edge"], reverse=True)
    without = sorted([s for s in risky_pool if s["edge"] is None],
                     key=lambda s: s["p"], reverse=True)
    risky = (with_edge + without)[:TOP_N]
    return prudent, risky


def selection_line(rank, s):
    text = f"{rank}. **{match_name(s['item'])}** — {LABELS[s['market']]} : **{pct(s['p'])}**"
    if s["book"] is not None:
        text += f" (bookmaker {pct(s['book'])}, écart {s['edge'] * 100:+.1f} pt, cote {s['odd']:.2f})"
    else:
        text += " (comparaison bookmaker indisponible)"
    return text


def build_combos(selections):
    """Une sélection par match (la plus probable, hors « Over 1.5 »), puis combinés de 2 à 4."""
    best_per_match = {}
    for s in selections:
        if s["market"] in COMBO_EXCLUDED or not (COMBO_MIN <= s["p"] <= MAX_P):
            continue
        key = s["item"].get("id")
        if key not in best_per_match or s["p"] > best_per_match[key]["p"]:
            best_per_match[key] = s
    pool = sorted(best_per_match.values(), key=lambda s: s["p"], reverse=True)

    combos = []
    for size in (2, 3, 4):
        for label, start in (("Combiné prudent", 0), ("Combiné alternatif", size)):
            legs = pool[start:start + size]
            if len(legs) == size:
                combos.append((size, label, legs))
    return combos


def combo_lines(combos):
    if not combos:
        return ["Pas assez de sélections fiables pour proposer des combinés aujourd'hui.", ""]
    lines = []
    for size, label, legs in combos:
        total_p = 1.0
        for s in legs:
            total_p *= s["p"]
        lines += [f"### {label} — {size} sélections", ""]
        for s in legs:
            lines.append(f"- {match_name(s['item'])} → **{LABELS[s['market']]}** ({pct(s['p'])})")
        lines += ["", f"- 📊 **Probabilité estimée du combiné : {pct(total_p)}**"]
        if all(s["odd"] for s in legs):
            total_odd = 1.0
            for s in legs:
                total_odd *= s["odd"]
            lines.append(f"- 📈 **Cote totale bookmaker : {total_odd:.2f}**")
        else:
            lines.append("- 📈 Cote totale bookmaker : indisponible")
        lines.append(f"- 🧮 Cote théorique du modèle : {1.0 / total_p:.2f}")
        lines.append("")
    return lines


def generate(report, output_file=OUTPUT_FILE):
    matches = report.get("matches", [])
    now = datetime.now(LOCAL_TZ).strftime("%Y-%m-%d %H:%M")
    lines = [
        f"# 🔮 Pronostics — {now}", "",
        "> Simulation virtuelle uniquement. Les pourcentages sont des estimations "
        "du modèle, pas des garanties.",
        "> Les cotes bookmaker ne sont comparées que lorsque l'API les fournit.", "",
    ]

    selections = build_selections(matches)
    prudent, risky = ranking(selections)

    lines += ["# 🏆 Classement des meilleurs pronostics", "", "## 🛡️ Prudent", ""]
    lines += [selection_line(i, s) for i, s in enumerate(prudent, 1)] or ["Aucune sélection."]
    lines += ["", "## 🎲 Plus risqué", ""]
    lines += [selection_line(i, s) for i, s in enumerate(risky, 1)] or ["Aucune sélection."]

    lines += ["", "---", "", "# 🎟️ Combinés automatiques", "",
              "*Règle : aucun « plus de 1,5 but ». Probabilité du combiné = produit "
              "des probabilités (matchs supposés indépendants).*", ""]
    lines += combo_lines(build_combos(selections))

    lines += ["---", "", "# 📋 Pronostics match par match", ""]
    for item in matches:
        lines += match_section(item) + ["---", ""]

    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output_file

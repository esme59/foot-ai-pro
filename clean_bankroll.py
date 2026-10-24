import json
import shutil
from pathlib import Path
from datetime import datetime, date, timezone

FICHIER = Path("data/bankroll.json")
DATE_LIMITE = date(2026, 10, 25)


def lire_date(pari):
    valeur = (
        pari.get("date_match")
        or pari.get("match_date")
        or pari.get("date")
    )

    if not valeur:
        raise ValueError(
            f"Date manquante pour le match : {pari.get('match_id')}"
        )

    valeur = str(valeur).strip()

    try:
        resultat = datetime.fromisoformat(
            valeur.replace("Z", "+00:00")
        )
        return resultat.date()
    except ValueError:
        raise ValueError(
            f"Format de date invalide : {valeur}"
        )


def est_en_attente(pari):
    statut = str(
        pari.get("statut", pari.get("status", ""))
    ).strip().lower()

    return statut in ("en_attente", "en attente", "pending")


def main():
    print("Debut du nettoyage de la bankroll...")

    if not FICHIER.exists():
        raise FileNotFoundError(
            f"Fichier introuvable : {FICHIER}"
        )

    with FICHIER.open("r", encoding="utf-8") as f:
        donnees = json.load(f)

    paris = donnees.get("paris", [])

    if not isinstance(paris, list):
        raise ValueError("Le champ 'paris' n'est pas une liste.")

    if not paris:
        print("Aucun pari dans le fichier. Rien a modifier.")
        return

    conserves = []
    supprimes = []

    for pari in paris:
        date_match = lire_date(pari)

        if date_match <= DATE_LIMITE:
            conserves.append(pari)
        else:
            supprimes.append(pari)

    print(f"Paris trouves : {len(paris)}")
    print(f"Paris a conserver : {len(conserves)}")
    print(f"Paris a supprimer : {len(supprimes)}")

    if not supprimes:
        print("Aucun pari apres le 25 octobre 2026.")
        print("Aucune modification effectuee.")
        return

    sauvegarde = FICHIER.with_name("bankroll.json.backup")

    if sauvegarde.exists():
        print(
            "ARRET : bankroll.json.backup existe deja. "
            "Aucune modification effectuee pour eviter un "
            "double remboursement."
        )
        return

    remboursement = round(
        sum(
            float(p.get("mise", p.get("stake", 0)) or 0)
            for p in supprimes
            if est_en_attente(p)
        ),
        2
    )

    # Verifier les donnees avant de toucher au fichier original.
    anciens_bets = donnees.get("bets", [])

    if not isinstance(anciens_bets, list):
        raise ValueError("Le champ 'bets' n'est pas une liste.")

    ids_conserves = {
        p.get("match_id")
        for p in conserves
        if p.get("match_id") is not None
    }

    nouveaux_bets = [
        b for b in anciens_bets
        if b.get("match_id") in ids_conserves
    ]

    gagnes = sum(
        1 for p in conserves
        if str(p.get("statut", p.get("status", ""))).strip().upper()
        in ("GAGNE", "WON")
    )

    perdus = sum(
        1 for p in conserves
        if str(p.get("statut", p.get("status", ""))).strip().upper()
        in ("PERDU", "LOST")
    )

    attente = sum(1 for p in conserves if est_en_attente(p))
    termines = gagnes + perdus

    taux = round(gagnes / termines * 100, 2) if termines else 0.0

    capital = float(
        donnees.get(
            "bankroll_actuelle",
            donnees.get("bankroll", 0)
        ) or 0
    )

    capital = round(capital + remboursement, 2)

    donnees["paris"] = conserves
    donnees["bets"] = nouveaux_bets

    donnees["statistiques"] = {
        "total_paris": len(conserves),
        "paris_gagnes": gagnes,
        "paris_perdus": perdus,
        "paris_en_attente": attente,
        "taux_reussite": taux,
    }

    donnees["bankroll_actuelle"] = capital
    donnees["bankroll"] = capital

    donnees["mises_totales"] = round(
        sum(float(p.get("mise", p.get("stake", 0)) or 0)
            for p in conserves),
        2
    )

    donnees["gains_totaux"] = round(
        sum(float(p.get("gain", p.get("profit", 0)) or 0)
            for p in conserves),
        2
    )

    donnees["benefice_total"] = round(
        sum(
            float(p.get("gain", p.get("profit", 0)) or 0)
            - float(p.get("mise", p.get("stake", 0)) or 0)
            for p in conserves
            if str(p.get("statut", p.get("status", ""))).strip().upper()
            in ("GAGNE", "PERDU", "WON", "LOST")
        ),
        2
    )

    donnees["profit"] = donnees["benefice_total"]
    donnees["derniere_mise_a_jour"] = (
        datetime.now(timezone.utc).isoformat()
    )

    # Sauvegarder l'original avant de modifier le fichier.
    shutil.copy2(FICHIER, sauvegarde)

    temporaire = FICHIER.with_suffix(".json.tmp")

    try:
        with temporaire.open("w", encoding="utf-8") as f:
            json.dump(donnees, f, ensure_ascii=False, indent=2)
            f.write("\n")

        temporaire.replace(FICHIER)

    except Exception:
        if temporaire.exists():
            temporaire.unlink()
        raise

    print("NETTOYAGE TERMINE")
    print(f"Paris conserves : {len(conserves)}")
    print(f"Paris supprimes : {len(supprimes)}")
    print(f"Mises remboursees : {remboursement:.2f} euros")
    print(f"Capital disponible : {capital:.2f} euros")
    print("Sauvegarde de l'original creee.")


if __name__ == "__main__":
    try:
        main()
    except Exception as erreur:
        print(f"ERREUR : {type(erreur).__name__}: {erreur}")
        raise
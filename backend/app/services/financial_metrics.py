# Le fichier financial_metrics.py centralise les calculs financiers (marges, ROA, ROE, croissance) de manière sécurisée.
# Il gère les valeurs manquantes, évite les divisions invalides, détecte les incohérences comptables et garantit des résultats fiables sans faire planter le workflow

import json

NA = "Data not available"   # texte unique pour toute donnée absente ou non significative
FIELDS = ("revenue", "net_income", "operating_income", "assets", "equity")


# Convertit une valeur en nombre et retourne None si elle est absente ou invalide. (ex. NULL en base)
def to_float(value):
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


# Calcule un ratio en pourcentage en évitant les divisions invalides ; None si une donnée manque ou si le dénominateur est <= 0
def ratio_pct(num, den):
    if num is None or den is None or den <= 0:
        return None
    return num / den * 100


# Calcule le taux de croissance en vérifiant que la valeur précédente est positive ; None si la base de comparaison est absente, nulle ou négative
def growth_pct(current, previous):
    if current is None or previous is None or previous <= 0:
        return None
    return (current - previous) / previous * 100


# Moyenne de deux soldes ; None si l'un manque
def average(a, b):
    return None if a is None or b is None else (a + b) / 2


# Formats centralisés (2 décimales, séparateur de milliers)
def fmt_pct(x):
    return NA if x is None else f"{x:.2f}%"

# Formate un montant avec un séparateur de milliers
def fmt_money(x):
    return NA if x is None else f"{x:,.0f}"


# Construit le texte des KPI (même format qu'avant, utilisé par les agents et l'évaluateur)
# Génère un rapport de KPI financiers, vérifie la cohérence des données et signale les anomalies
def build_kpi_report(kpis_text: str) -> str:
    try:
        rows = json.loads(kpis_text)
    except Exception:
        return NA
    # Entrée invalide : pas une liste non vide d'objets
    if not isinstance(rows, list) or not rows or not all(isinstance(r, dict) for r in rows):
        return NA

    # Normaliser chaque ligne : valeurs numériques ou None
    data = [{"fiscal_year": r.get("fiscal_year"), "end_date": r.get("end_date"),
             **{k: to_float(r.get(k)) for k in FIELDS}} for r in rows]

    # out --> stocker les résultat
    # warnings --> enregistrer les anomalies.
    out, warnings = [], []

    # Parcourt les données de chaque exercice fiscal
    for d in data:   # FY le plus récent d'abord
        # Récupère les cinq indicateurs financiers de l'exercice
        rev, ni, op, a, e = (d[k] for k in FIELDS)
        # Estime les dettes totales : actifs - capitaux propres
        liabilities = None if a is None or e is None else a - e   # approximation actifs - capitaux propres

        # Calcule et formate les principaux indicateurs financiers
        out.append(
            f"{d['end_date']} (FY{d['fiscal_year']}, USD): "
            f"revenue={fmt_money(rev)}; net_income={fmt_money(ni)}; operating_income={fmt_money(op)}; "
            f"assets={fmt_money(a)}; equity={fmt_money(e)}; "
            f"total_liabilities(assets-equity)={fmt_money(liabilities)}; "
            f"net_margin={fmt_pct(ratio_pct(ni, rev))} (net_income/revenue); "
            f"operating_margin={fmt_pct(ratio_pct(op, rev))} (operating_income/revenue); "
            f"ROA={fmt_pct(ratio_pct(ni, a))} (net_income/assets, year-end); "
            f"ROE={fmt_pct(ratio_pct(ni, e))} (net_income/equity, year-end); "
            f"equity_ratio={fmt_pct(ratio_pct(e, a))} (equity/assets)"
        )
        # Contrôles de cohérence comptable
        # Signale les actifs négatifs ou nuls
        if a is not None and a <= 0:
            warnings.append(f"FY{d['fiscal_year']}: assets <= 0")
        # Signale les capitaux propres supérieurs aux actifs
        if a is not None and e is not None and e > a:
            warnings.append(f"FY{d['fiscal_year']}: equity > assets")
        # Signale les capitaux propres négatifs ou nuls, rendant le ROE non significatif
        if e is not None and e <= 0:
            warnings.append(f"FY{d['fiscal_year']}: equity <= 0, ROE not meaningful")

    # Vérifie qu'au moins deux exercices sont disponibles pour calculer les évolutions
    if len(data) >= 2:
        # Récupère l'exercice le plus récent (n) et le précédent (p)
        n, p = data[0], data[1]   # année courante et année précédente

        # Calcule le taux de croissance du chiffre d'affaires
        out.append(f"revenue_growth={fmt_pct(growth_pct(n['revenue'], p['revenue']))} "
                   f"((rev_FY_n - rev_FY_n-1)/rev_FY_n-1)")

        # Calcule la croissance du résultat net et du résultat opérationnel
        for k in ("net_income", "operating_income"):
            out.append(f"{k}_growth={fmt_pct(growth_pct(n[k], p[k]))} "
                       f"(FY{p['fiscal_year']} -> FY{n['fiscal_year']})")
        # Ratios complémentaires sur soldes moyens (début + fin d'exercice)
        span = f"FY{p['fiscal_year']}-FY{n['fiscal_year']}"

        # Calcule le ROA avec la moyenne des actifs des deux exercices
        out.append(f"ROA_avg={fmt_pct(ratio_pct(n['net_income'], average(n['assets'], p['assets'])))} "
                   f"(net_income/average assets {span})")

        # Calcule le ROE avec la moyenne des capitaux propres des deux exercices
        out.append(f"ROE_avg={fmt_pct(ratio_pct(n['net_income'], average(n['equity'], p['equity'])))} "
                   f"(net_income/average equity {span})")

    if warnings:
        out.append("data_quality_warnings: " + "; ".join(warnings))
    return "\n".join(out)

# Un exercice fiscal est une période de 12 mois utilisée par une entreprise pour calculer ses résultats financiers.

# ============================================================
#              EXEMPLE DE DONNÉES FINANCIÈRES
# ============================================================
#
# Indicateur          | Définition
# --------------------|-----------------------------------------------
# Revenue             | Chiffre d'affaires total généré par les ventes.
# Net Income          | Bénéfice net après déduction des charges,
#                     | des intérêts et des impôts.
# Operating Income    | Résultat généré par l'activité principale.
# Assets              | Total des actifs détenus par l'entreprise.
# Equity              | Capitaux propres représentant la valeur revenant aux actionnaires après déduction des dettes des actifs.
# ============================================================

# RATIOS FINANCIERS
#
# Net Margin (Marge nette) : Mesure la part du chiffre d'affaires qui reste sous forme de bénéfice net --> (Net Income / Revenue) * 100

# Operating Margin (Marge opérationnelle) : Mesure la rentabilité de l'activité principale de l'entreprise --> (Operating Income / Revenue) * 100

# ROA (Return on Assets) : Mesure la capacité de l'entreprise à générer des bénéfices à partir de ses actifs --> (Net Income / Assets) * 100

# ROE (Return on Equity) : Mesure la rentabilité des capitaux propres investis par les actionnaires --> (Net Income / Equity) * 100

# Revenue Growth (Croissance du chiffre d'affaires) : ((Revenue actuel - Revenue précédent) / Revenue précédent) * 100
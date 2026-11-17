import re


# Extraire tous les nombres des KPI calculés (sans virgules de milliers)
def _kpi_numbers(kpi):
    return {x.replace(",", "") for x in re.findall(r"\d[\d,]*\.?\d*", kpi)}


# Vérifier que chaque % et chaque montant du rapport existe dans les KPI
def numbers_match(outputs, reference_outputs=None):
    kpi_nums = _kpi_numbers(outputs.get("kpi_calc", ""))
    report = outputs.get("report", "")
    found, bad = 0, []
    for p in re.findall(r"(\d+[.,]\d+)\s?%", report):
        found += 1
        if p.replace(",", ".") not in kpi_nums:
            bad.append(p + "%")
    for m in re.findall(r"(\d[\d\s\u202f\u00a0]*)\s?M USD", report):
        found += 1
        digits = re.sub(r"\D", "", m)
        if digits + "000000" not in kpi_nums:
            bad.append(m.strip() + " M USD")
    score = 1.0 if found and not bad else 0.0
    return {"key": "numbers_match", "score": score,
            "comment": f"{found} nombres, erreurs: {bad}"}


# Vérifier que le rapport n'est pas vide ni en erreur
def report_not_empty(outputs, reference_outputs=None):
    r = outputs.get("report", "")
    return {"key": "report_not_empty",
            "score": float(len(r) > 200 and not r.startswith("ERREUR"))}


# Vérifier l'absence de termes interdits (causes inventées, mots subjectifs)
def no_forbidden_words(outputs, reference_outputs=None):
    words = ["cloud", "azure", "robuste", "solide", "maîtrise des coûts"]
    hit = [w for w in words if w in outputs.get("report", "").lower()]
    return {"key": "no_forbidden_words", "score": float(not hit),
            "comment": f"trouvés: {hit}"}


# Vérifier que le Supervisor n'a pas demandé de validation humaine à tort
def no_unneeded_review(outputs, reference_outputs=None):
    return {"key": "no_false_alert",
            "score": float(not outputs.get("needs_review", False))}
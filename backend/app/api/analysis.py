# Créer les routes et valider les données reçues
from fastapi import APIRouter, Response
from app.services.pdf_report import report_to_pdf
from pydantic import BaseModel
from uuid import uuid4

import os
from fastapi import HTTPException                       # renvoyer des erreurs HTTP (403)
from fastapi.responses import HTMLResponse              # renvoyer une page HTML
from app.services.approval_token import make_token, verify_token

import html                                                    # échapper le texte généré par le LLM
from app.graph.workflow import get_pending_review

from fastapi import Depends
from app.services.security import require_api_key
from app.services.decisions import record_decision, release_decision

from typing import Literal      # restreindre un champ à des valeurs précises
from pydantic import BaseModel, Field   # Field : contraintes de taille

REVIEWER = os.getenv("REVIEWER_EMAIL", "unknown")   # identité enregistrée dans l'audit

BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000")  # base des liens de l'email

import requests                       # appeler le webhook n8n
from fastapi import BackgroundTasks   # exécuter l'envoi après la réponse HTTP

N8N_WEBHOOK_URL = os.getenv("N8N_WEBHOOK_URL", "")  # URL du webhook lue depuis l'environnement

# Lancer le workflow, ou le reprendre après la validation humaine
from app.graph.workflow import run_financial_analysis, resume_analysis

router = APIRouter(prefix="/analysis", tags=["Multi-Agent Analysis"])


# Question : entre 10 et 4000 caractères (refuse vide, trop courte ou trop longue)
class AnalysisRequest(BaseModel):
    question: str = Field(min_length=10, max_length=4000)


# Décision humaine : uniquement approve ou reject, commentaire limité
class ReviewRequest(BaseModel):
    action: Literal["approve", "reject"]
    comment: str = Field(default="", max_length=2000)


# Transformer le résultat : en attente de validation, ou terminé
def fmt(result, thread_id):
    if "__interrupt__" in result:
        return {"status": "PENDING_HUMAN_REVIEW", "thread_id": thread_id,
                "review_data": result["__interrupt__"][0].value,
                                # lien Approuver signé (valable 24 h)
                "approve_url": f"{BASE_URL}/analysis/{thread_id}/decision?action=approve&token={make_token(thread_id, 'approve')}",
                # lien Rejeter signé
                "reject_url": f"{BASE_URL}/analysis/{thread_id}/decision?action=reject&token={make_token(thread_id, 'reject')}"}
               
    return {"status": "COMPLETED", "thread_id": thread_id,
            "report": result.get("report", ""),
            "supervisor_decision": result.get("supervisor_decision", "")}

# Envoie le rapport validé à n8n (qui génère le PDF et l'email)
def notify_n8n(payload: dict):
    if not N8N_WEBHOOK_URL:                      # webhook non configuré : ne rien faire
        return
    try:
        requests.post(N8N_WEBHOOK_URL, json=payload, timeout=30)  # envoi du rapport
    except requests.RequestException as e:       # ne pas faire échouer la validation
        print(f"Notification n8n échouée : {e}")
        
# Lancer une analyse avec un identifiant unique (thread_id)
@router.post("/", dependencies=[Depends(require_api_key)])
async def analyze(request: AnalysisRequest):
    tid = str(uuid4())
    return fmt(await run_financial_analysis(request.question, tid), tid)


# Reprendre l'analyse en pause après la décision de l'humain
@router.post("/{thread_id}/review", dependencies=[Depends(require_api_key)])
async def review(thread_id: str, body: ReviewRequest):
    return fmt(await resume_analysis(thread_id, body.action, body.comment), thread_id)

# Rapport envoyé au PDF : non vide, limité à 100 000 caractères
class PdfRequest(BaseModel):
    report: str = Field(min_length=1, max_length=100_000)

# Générer le PDF à partir du rapport (utilisé par n8n pour l'email)
@router.post("/pdf", dependencies=[Depends(require_api_key)])
def make_pdf(body: PdfRequest):
    return Response(
        content=report_to_pdf(body.report),
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=rapport_microsoft.pdf"},
    )

# Décision depuis le lien email : action restreinte, token de taille raisonnable
class DecisionBody(BaseModel):
    action: Literal["approve", "reject"]
    token: str = Field(min_length=1, max_length=200)


# Page de confirmation : le clic sur l'email ne décide rien (évite les scanners d'email)
@router.get("/{thread_id}/decision", response_class=HTMLResponse)
async def decision_page(thread_id: str, action: str, token: str):
    if action not in ("approve", "reject") or not verify_token(thread_id, action, token):
        raise HTTPException(403, "Lien invalide ou expiré")
    # Lire ce qui est en attente de validation
    review = await get_pending_review(thread_id)
    if review is None:                                         # déjà décidé ou introuvable
        return HTMLResponse("<h3 style='font-family:sans-serif;text-align:center'>Analyse déjà traitée ou introuvable.</h3>")
    # html.escape : le texte vient d'un LLM, on l'affiche comme du texte, jamais comme du HTML
    reason = html.escape(review.get("supervisor_decision", ""))
    analysis = html.escape(review.get("analysis", ""))
    label = "Approuver" if action == "approve" else "Rejeter"
    return f"""
    <html><body style="font-family:sans-serif;max-width:800px;margin:40px auto">
      <h2>Analyse financière Microsoft : validation requise</h2>
      <h3>Motif de la validation (Supervisor)</h3>
      <pre style="white-space:pre-wrap;background:#f5f5f5;padding:12px">{reason}</pre>
      <details><summary><b>Voir l'analyse à valider</b></summary>
        <pre style="white-space:pre-wrap;background:#f5f5f5;padding:12px">{analysis}</pre>
      </details>
      <div style="text-align:center;margin-top:30px">
        <button id="b" style="padding:14px 28px;font-size:18px" onclick="go()">{label} l'analyse</button>
        <p id="msg"></p>
      </div>
      <script>
        async function go() {{
          document.getElementById('b').disabled = true;
          const r = await fetch('{BASE_URL}/analysis/{thread_id}/decision', {{
            method: 'POST',
            headers: {{'Content-Type': 'application/json'}},
            body: JSON.stringify({{action: '{action}', token: '{token}'}})
          }});
          document.getElementById('msg').innerText =
            r.ok ? 'Décision enregistrée ✅' : 'Erreur ou décision déjà prise ❌';
        }}
      </script>
    </body></html>"""


# Enregistre la décision : vérifie le token puis reprend le workflow LangGraph
@router.post("/{thread_id}/decision")
async def decision(thread_id: str, body: DecisionBody, background: BackgroundTasks):
    if body.action not in ("approve", "reject") or not verify_token(thread_id, body.action, body.token):
        raise HTTPException(403, "Lien invalide ou expiré")
        # Usage unique : une seule décision par analyse (409 si le lien a déjà servi)
    if not record_decision(thread_id, body.action, REVIEWER):
        raise HTTPException(409, "Décision déjà prise")
    try:
        result = fmt(await resume_analysis(thread_id, body.action), thread_id)  # reprend le workflow
    except Exception:
        release_decision(thread_id)   # échec : libérer pour pouvoir réessayer
        raise
    if body.action == "approve" and result.get("report"):                   # seulement si approuvé
        background.add_task(notify_n8n, {"thread_id": thread_id, "report": result["report"]})  # envoi en arrière-plan
    return result
# Créer les routes et valider les données reçues
from fastapi import APIRouter, Response
from app.services.pdf_report import report_to_pdf
from pydantic import BaseModel
from uuid import uuid4

import os
from fastapi import HTTPException                       # renvoyer des erreurs HTTP (403)
from fastapi.responses import HTMLResponse              # renvoyer une page HTML
from app.services.approval_token import make_token, verify_token

BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000")  # base des liens de l'email

import requests                       # appeler le webhook n8n
from fastapi import BackgroundTasks   # exécuter l'envoi après la réponse HTTP

N8N_WEBHOOK_URL = os.getenv("N8N_WEBHOOK_URL", "")  # URL du webhook lue depuis l'environnement

# Lancer le workflow, ou le reprendre après la validation humaine
from app.graph.workflow import run_financial_analysis, resume_analysis

router = APIRouter(prefix="/analysis", tags=["Multi-Agent Analysis"])


# Structure de la question envoyée par le frontend
class AnalysisRequest(BaseModel):
    question: str


# Structure de la décision humaine (approve ou reject)
class ReviewRequest(BaseModel):
    action: str
    comment: str = ""


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
@router.post("/")
async def analyze(request: AnalysisRequest):
    tid = str(uuid4())
    return fmt(await run_financial_analysis(request.question, tid), tid)


# Reprendre l'analyse en pause après la décision de l'humain
@router.post("/{thread_id}/review")
async def review(thread_id: str, body: ReviewRequest):
    return fmt(await resume_analysis(thread_id, body.action, body.comment), thread_id)

# Structure du rapport envoyé pour conversion en PDF
class PdfRequest(BaseModel):
    report: str


# Générer le PDF à partir du rapport (utilisé par n8n pour l'email)
@router.post("/pdf")
def make_pdf(body: PdfRequest):
    return Response(
        content=report_to_pdf(body.report),
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=rapport_microsoft.pdf"},
    )

# Corps de la décision envoyée par la page de confirmation
class DecisionBody(BaseModel):
    action: str   # "approve" ou "reject"
    token: str    # token signé reçu dans l'email


# Page de confirmation : le clic sur l'email ne décide rien (évite les scanners d'email)
@router.get("/{thread_id}/decision", response_class=HTMLResponse)
def decision_page(thread_id: str, action: str, token: str):
    if action not in ("approve", "reject") or not verify_token(thread_id, action, token):
        raise HTTPException(403, "Lien invalide ou expiré")   # refuser si lien falsifié/expiré
    label = "Approuver" if action == "approve" else "Rejeter"  # texte du bouton
    return f"""
    <html><body style="font-family:sans-serif;text-align:center;margin-top:80px">
      <h2>Analyse financière Microsoft</h2>
      <button id="b" style="padding:14px 28px;font-size:18px" onclick="go()">{label} l'analyse</button>
      <p id="msg"></p>
      <script>
        async function go() {{
          document.getElementById('b').disabled = true;   // empêcher le double clic
          const r = await fetch('{BASE_URL}/analysis/{thread_id}/decision', {{
            method: 'POST',                               // la décision part en POST
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
    result = fmt(await resume_analysis(thread_id, body.action), thread_id)  # reprend le workflow
    if body.action == "approve" and result.get("report"):                   # seulement si approuvé
        background.add_task(notify_n8n, {"thread_id": thread_id, "report": result["report"]})  # envoi en arrière-plan
    return result
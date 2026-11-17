from typing import TypedDict


# État partagé entre les agents
class FinancialAnalysisState(TypedDict):
    question: str
    plan: str
    research: str
    analysis: str
    risk_review: str
    supervisor_decision: str
    report: str
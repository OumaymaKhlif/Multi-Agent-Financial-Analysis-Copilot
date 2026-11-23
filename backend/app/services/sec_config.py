import os

# entralise la configuration de la collecte des données financières de Microsoft
COMPANY_NAME = "Microsoft Corporation"
CIK = "0000789019"
TICKER = "MSFT"

SEC_BASE_URL = "https://data.sec.gov"
SUBMISSIONS_URL = f"{SEC_BASE_URL}/submissions/CIK{CIK}.json"
COMPANY_FACTS_URL = (
    f"{SEC_BASE_URL}/api/xbrl/companyfacts/CIK{CIK}.json"
)

import os
USER_AGENT = os.getenv("SEC_USER_AGENT", "FinancialAnalysisCopilot khlif.oumayma30@gmail.com")
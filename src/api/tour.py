"""End-user onboarding content served by the backend so the UI can evolve independently."""
from fastapi import APIRouter, Depends
from src.api.auth import get_current_user

router = APIRouter(prefix="/tour", tags=["product tour"])

STEPS = [
    {"id": "ask", "title": "Ask in plain English",
     "body": "Name things the way you know them - zones, campaigns, advertisers, websites or managers. AdOps Copilot looks up the IDs itself.",
     "sample": "Which zones have the lowest fill rate this month?"},
    {"id": "scope", "title": "Choose the data domain",
     "body": "Revive covers your ad server: delivery, revenue, setup and change history. Exchange covers RTB and programmatic data. The active mode decides which tools AdOps Copilot can use.",
     "sample": "Switch to Exchange and ask: What is the current exchange health?"},
    {"id": "health", "title": "Find what's broken",
     "body": "Health checks look across the whole ad server for campaigns expiring or behind pace, zones with nothing linked or no fill, wrong-size banners and inactive users.",
     "sample": "What's wrong with the ad server right now?"},
    {"id": "investigate", "title": "Investigate a change",
     "body": "For 'why did this move' questions AdOps Copilot breaks the metric down and checks the audit log for settings changes around the same date, then adds the relevant playbook.",
     "sample": "Why did Zone_3_fill_rate_decline's fill rate drop?"},
    {"id": "access", "title": "See only what's yours",
     "body": "Admins see the whole ad server. Managers see only their own advertisers, websites and users. New accounts need an admin to grant access before using Revive.",
     "sample": "Which websites and advertisers do I manage, and how much revenue did they make?"},
    {"id": "history", "title": "Return to your work",
     "body": "Every signed-in conversation is saved to your account. Reopen, continue, or delete chats from History.",
     "sample": "Open History and continue your previous investigation."},
]

@router.get("")
def tour(user=Depends(get_current_user)):
    return {"steps": STEPS}

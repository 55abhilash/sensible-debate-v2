"""HTML page routes - each one just renders a template shell. All of the
actual behaviour (fetching topics, opening websockets) happens client-side
in the matching static/js file."""
from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/")
async def home(request: Request):
    return templates.TemplateResponse(request, "index.html", {})


@router.get("/waiting/{topic_id}")
async def waiting(request: Request, topic_id: str):
    return templates.TemplateResponse(request, "waiting.html", {"topic_id": topic_id})


@router.get("/debate/{session_id}")
async def debate(request: Request, session_id: str):
    return templates.TemplateResponse(request, "debate.html", {"session_id": session_id})

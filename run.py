"""Local development entry point: `python run.py`.
In production, run uvicorn directly via a process manager - see DEPLOYMENT.md."""
import uvicorn

from app.config import settings

if __name__ == "__main__":
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=True)

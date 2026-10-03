from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse

from app.database import init_db
from app.realtime import realtime
from app.routes import pages, topics, ws

app = FastAPI(title="Sensible Debate")


@app.on_event("startup")
async def on_startup():
    init_db()
    await realtime.start()


@app.on_event("shutdown")
async def on_shutdown():
    await realtime.stop()


@app.get("/healthz")
async def healthz():
    """Used by the load balancer's target group health check. Confirms
    this process can actually reach both Redis and the database, not
    just that the process itself is alive - a process that's up but can't
    reach either dependency should be pulled out of rotation."""
    try:
        await realtime.redis.ping()
    except Exception:
        return JSONResponse({"ok": False, "detail": "redis unreachable"}, status_code=503)

    try:
        from sqlalchemy import text
        from app.database import get_session
        db = get_session()
        try:
            db.execute(text("SELECT 1"))
        finally:
            db.close()
    except Exception:
        return JSONResponse({"ok": False, "detail": "database unreachable"}, status_code=503)

    return {"ok": True}


app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(pages.router)
app.include_router(topics.router)
app.include_router(ws.router)

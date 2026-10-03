#!/bin/sh
# UVICORN_WORKERS defaults to 1, which is the right choice for a
# single-vCPU instance (t4g.micro). On a bigger instance type you can
# raise it - the Redis-backed design (see app/realtime.py) means, unlike
# the original single-process build, it's now safe to run more than one
# worker per process too, not just more than one instance.
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers "${UVICORN_WORKERS:-1}"

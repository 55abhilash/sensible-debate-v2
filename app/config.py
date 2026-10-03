"""
Central configuration for Sensible Debate.

Every value can be overridden with an environment variable, which is how
the timing rules or database location are changed in production without
touching the code (see .env.example).
"""
import os


class Settings:
    # --- Debate pacing (in seconds) -----------------------------------
    ARGUMENT_SECONDS: int = int(os.getenv("SD_ARGUMENT_SECONDS", 5 * 60))
    REFLECTION_SECONDS: int = int(os.getenv("SD_REFLECTION_SECONDS", 2 * 60))

    # 0 means "no limit" - the debate continues until someone leaves.
    MAX_ROUNDS: int = int(os.getenv("SD_MAX_ROUNDS", 0))

    # --- Storage --------------------------------------------------------
    DATABASE_URL: str = os.getenv("SD_DATABASE_URL", "sqlite:///./data/sensible_debate.db")

    # Redis holds *live* debate state (whose turn, timers, who's connected)
    # and relays updates between server processes, so any process can
    # serve any connection - see app/realtime.py. Required once you run
    # more than one process/instance; a single-process local dev run
    # still needs it (there's no in-memory fallback anymore).
    REDIS_URL: str = os.getenv("SD_REDIS_URL", "redis://127.0.0.1:6379/0")

    # --- Networking -------------------------------------------------------
    HOST: str = os.getenv("SD_HOST", "0.0.0.0")
    PORT: int = int(os.getenv("SD_PORT", 8000))

    # A topic that nobody joins is automatically closed after this long,
    # so the "open topics" list doesn't fill up with abandoned rooms.
    TOPIC_EXPIRY_MINUTES: int = int(os.getenv("SD_TOPIC_EXPIRY_MINUTES", 60))


settings = Settings()

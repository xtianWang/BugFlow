import os


DATABASE_URL = os.getenv("BUGFLOW_DATABASE_URL", "sqlite:///bugflow.db")

SECRET_KEY = os.getenv("BUGFLOW_SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError("BUGFLOW_SECRET_KEY environment variable must be set.")

ALGORITHM = "HS256"

_access_token_expire_minutes = os.getenv("BUGFLOW_ACCESS_TOKEN_EXPIRE_MINUTES", "30")
try:
    ACCESS_TOKEN_EXPIRE_MINUTES = int(_access_token_expire_minutes)
except ValueError as error:
    raise RuntimeError(
        "BUGFLOW_ACCESS_TOKEN_EXPIRE_MINUTES must be a positive integer."
    ) from error

if ACCESS_TOKEN_EXPIRE_MINUTES <= 0:
    raise RuntimeError("BUGFLOW_ACCESS_TOKEN_EXPIRE_MINUTES must be a positive integer.")

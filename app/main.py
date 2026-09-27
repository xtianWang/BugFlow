from fastapi import FastAPI

from app.routers import auth, projects


app = FastAPI(title="BugFlow API")

app.include_router(auth.router)
app.include_router(projects.router)


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}

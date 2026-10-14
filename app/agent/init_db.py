"""Explicit additive schema initialization. Never invoked at API startup."""
from app.database import engine
import app.models
from app.agent.models import AgentTrace, DebugTask

if __name__ == "__main__":
    AgentTrace.__table__.create(engine, checkfirst=True)
    DebugTask.__table__.create(engine, checkfirst=True)
    print("Agent tables initialized; existing tables unchanged")

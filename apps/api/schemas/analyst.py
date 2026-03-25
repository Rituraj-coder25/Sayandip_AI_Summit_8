from typing import Optional

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    question: str
    context: str = ""
    conversation_history: list[dict] = Field(default_factory=list)
    user_role: str = "ANALYST"


class ScenarioRequest(BaseModel):
    hypothesis: str
    depth: int = 3
    use_swarm: Optional[bool] = None
    # None = use global MIROFISH_ENABLED setting
    # True = force enable for this request (requires MIROFISH_URL accessible)
    # False = skip swarm simulation for this request


from pydantic import BaseModel, Field
from typing import List
from datetime import datetime, UTC


class AgentResult(BaseModel):
    agent_name: str
    direction: str = Field(..., description="bullish | bearish | neutral")
    confidence: float = Field(..., ge=0.0, le=1.0)
    risk_score: float = Field(..., ge=0.0, le=100.0)
    signals: List[str] = Field(default_factory=list)
    explanation: str
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


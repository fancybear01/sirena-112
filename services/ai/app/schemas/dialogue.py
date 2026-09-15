"""Модели реплики AI-абонента.

Состав ответа зафиксирован задачей #15: reply, callerState, revealedFacts,
hangUp. Поле meta добавлено для наблюдаемости и не несёт методического смысла.
"""

from enum import Enum
from typing import List, Optional

from pydantic import Field

from app.schemas.common import CamelModel, ResponseMeta
from app.schemas.scenario import Scenario


class SpeakerRole(str, Enum):
    OPERATOR = "OPERATOR"
    CALLER = "CALLER"


class DialogueTurn(CamelModel):
    """Одна реплика в истории разговора."""

    role: SpeakerRole
    text: str
    at_ms: Optional[int] = Field(default=None, ge=0)


class CallerState(CamelModel):
    """Состояние абонента между репликами.

    Шкалы влияют на то, как абонент отвечает и раскрывает ли скрытые факты.
    Core передаёт состояние обратно на следующем шаге, AI его не хранит.
    """

    panic: float = Field(ge=0, le=1)
    trust: float = Field(ge=0, le=1)
    patience: float = Field(ge=0, le=1)
    revealed_facts: List[str] = Field(default_factory=list)


class DialogueRequest(CamelModel):
    ai_session_id: str = Field(min_length=1)
    scenario: Scenario
    caller_state: Optional[CallerState] = None
    history: List[DialogueTurn] = Field(default_factory=list)
    operator_utterance: str = Field(min_length=1)


class DialogueResponse(CamelModel):
    reply: str
    caller_state: CallerState
    revealed_facts: List[str]
    hang_up: bool
    meta: ResponseMeta

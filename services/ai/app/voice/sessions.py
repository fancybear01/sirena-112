"""Голосовые AI-сессии.

Сессию создаёт Core перед звонком и передаёт разрешённый контекст сценария.
AI хранит его в памяти по aiSessionId: доступа к базе у сервиса нет и быть
не должно.

Состояние абонента живёт здесь же, потому что в голосовом режиме между
репликами нет запроса от Core, куда его можно было бы вернуть. В карточном
режиме всё остаётся как было: состояние ездит в теле запроса.
"""

import threading
from dataclasses import dataclass, field
from typing import Dict, Optional
from uuid import uuid4

from app.schemas.dialogue import CallerState
from app.schemas.scenario import Scenario

# Больше этого числа одновременных звонков сервис не берёт: каждая сессия
# держит буфер аудио, и без предела память кончится молча.
MAX_SESSIONS = 32


class TooManySessions(RuntimeError):
    """Достигнут предел одновременных голосовых сессий."""


@dataclass
class AiSession:
    """Контекст одного звонка."""

    ai_session_id: str
    session_id: str
    scenario: Scenario
    caller_state: Optional[CallerState] = None
    # Поток занят: второе подключение к той же сессии не допускается,
    # иначе два соединения начнут отвечать одному абоненту вперемешку.
    attached: bool = False
    lock: threading.Lock = field(default_factory=threading.Lock)


class SessionStore:
    """Потокобезопасное хранилище сессий в памяти."""

    def __init__(self, limit: int = MAX_SESSIONS) -> None:
        self._limit = limit
        self._sessions: Dict[str, AiSession] = {}
        self._lock = threading.Lock()

    def create(self, session_id: str, scenario: Scenario) -> AiSession:
        with self._lock:
            if len(self._sessions) >= self._limit:
                raise TooManySessions(
                    "Достигнут предел одновременных голосовых сессий: {limit}".format(
                        limit=self._limit
                    )
                )
            session = AiSession(
                ai_session_id="ai-{token}".format(token=uuid4()),
                session_id=session_id,
                scenario=scenario,
            )
            self._sessions[session.ai_session_id] = session
            return session

    def get(self, ai_session_id: str) -> Optional[AiSession]:
        with self._lock:
            return self._sessions.get(ai_session_id)

    def resolve(self, ai_session_id: str, session_id: str) -> Optional[AiSession]:
        """Возвращает сессию, только если пара идентификаторов совпала.

        Требование контракта: неизвестный, завершённый или несоответствующий
        sessionId не должен открывать поток.
        """
        session = self.get(ai_session_id)
        if session is None or session.session_id != session_id:
            return None
        return session

    def close(self, ai_session_id: str) -> bool:
        with self._lock:
            return self._sessions.pop(ai_session_id, None) is not None

    def count(self) -> int:
        with self._lock:
            return len(self._sessions)

    def clear(self) -> None:
        with self._lock:
            self._sessions.clear()


_store = SessionStore()


def store() -> SessionStore:
    return _store

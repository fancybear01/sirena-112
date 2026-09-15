"""Реплика AI-абонента: заглушка с фиксированным ответом.

Здесь намеренно нет никакой логики раскрытия фактов и изменения состояния:
задача #14 фиксирует только форму ответа, чтобы Core и frontend могли на неё
опереться. Управляемое поведение абонента добавляется задачей #15 в этом же
модуле, контракт при этом не меняется.

Инвариант, который обязан сохраниться и дальше: абонент не сообщает ничего,
чего нет в scenario.groundTruth.
"""

from app.config import SERVICE_VERSION
from app.schemas.common import ResponseMeta
from app.schemas.dialogue import CallerState, DialogueRequest, DialogueResponse

# Нейтральная реплика: не содержит адреса, имени и обстоятельств,
# поэтому не может противоречить ни одному сценарию.
FALLBACK_REPLY = "Алло! Вы меня слышите? Помогите, пожалуйста."

DEFAULT_PANIC = 0.5
DEFAULT_TRUST = 0.5
DEFAULT_PATIENCE = 0.5


def _initial_state(request: DialogueRequest) -> CallerState:
    """Берёт состояние из запроса, иначе из профиля абонента, иначе среднее."""
    if request.caller_state is not None:
        return request.caller_state

    caller = request.scenario.caller
    return CallerState(
        panic=caller.panic if caller and caller.panic is not None else DEFAULT_PANIC,
        trust=caller.trust if caller and caller.trust is not None else DEFAULT_TRUST,
        patience=(
            caller.patience if caller and caller.patience is not None else DEFAULT_PATIENCE
        ),
        revealed_facts=[],
    )


def respond(request: DialogueRequest) -> DialogueResponse:
    """Возвращает фиксированную реплику и неизменённое состояние абонента."""
    state = _initial_state(request)

    return DialogueResponse(
        reply=FALLBACK_REPLY,
        caller_state=state,
        revealed_facts=list(state.revealed_facts),
        hang_up=False,
        meta=ResponseMeta(engine="mock", version=SERVICE_VERSION, deterministic=True),
    )

"""Поведение AI-абонента по детерминированным правилам.

Главный принцип: реплика собирается только из значений, лежащих в эталоне
сценария. Обрамляющие слова вроде "Записывайте" не содержат ни адреса,
ни имени, ни обстоятельств. Поэтому абонент не может сообщить того, чего нет
в сценарии - не потому что его об этом попросили, а потому что взять неоткуда.

Случайности здесь нет ни в одном месте: одинаковый вход всегда даёт одинаковый
ответ, иначе занятие невозможно было бы разобрать с преподавателем.

Все реплики написаны без прошедшего времени первого лица: один и тот же движок
играет и мужчин, и женщин, а "я сказал" или "я сказала" выдало бы пол,
которого в сценарии может не быть.
"""

from typing import Any, Dict, List, Optional, Tuple

from app.config import SERVICE_VERSION
from app.engines.question_intents import facts_for, match_question, match_tone
from app.schemas.common import ResponseMeta
from app.schemas.dialogue import CallerState, DialogueRequest, DialogueResponse
from app.schemas.scenario import Scenario

# Сколько фактов абонент выдаёт за одну реплику. Человек в стрессе не диктует
# анкету: если оператор хочет больше подробностей, он спрашивает ещё раз.
MAX_FACTS_PER_REPLY = 2

# Выше этого значения паники абонент отвечает рвано и с восклицаниями.
PANIC_FLAVOUR_THRESHOLD = 0.5

DEFAULT_PANIC = 0.5
DEFAULT_TRUST = 0.5
DEFAULT_PATIENCE = 0.5

# Насколько меняются шкалы. Значения подобраны так, чтобы терпение кончалось
# примерно за шесть-семь бесполезных реплик подряд.
TRUST_FOR_GREETING = 0.2
TRUST_FOR_CALMING = 0.1
PANIC_FOR_CALMING = -0.2
PANIC_FOR_PROGRESS = -0.05
PANIC_FOR_CONFUSION = 0.1
PATIENCE_FOR_PROGRESS = -0.05
PATIENCE_FOR_REPEAT = -0.2
PATIENCE_FOR_CONFUSION = -0.15
# Приветствие и попытка успокоить - правильные действия по регламенту,
# наказывать за них нельзя. Терпение всё же убывает: время идёт.
PATIENCE_FOR_TONE = -0.02

CALM = "calm"
PANICKED = "panicked"

ANSWER_TEMPLATES: Dict[str, Dict[str, str]] = {
    "ADDRESS": {
        CALM: "Записывайте: {facts}.",
        PANICKED: "{facts}! Приезжайте скорее!",
    },
    "VICTIMS": {
        CALM: "{facts}.",
        PANICKED: "{facts}, но тут страшно!",
    },
    "CALLER_ID": {
        CALM: "{facts}.",
        PANICKED: "{facts}, только быстрее, пожалуйста!",
    },
    "BUILDING": {
        CALM: "{facts}.",
        PANICKED: "{facts}! Тут уже дышать нечем!",
    },
    "LANDMARK": {
        CALM: "{facts}.",
        PANICKED: "{facts}, вы не пропустите!",
    },
    "WHAT_HAPPENED": {
        CALM: "{facts}.",
        PANICKED: "{facts}! Помогите, пожалуйста!",
    },
}

REPEAT_REPLIES = {
    CALM: "Вы уже про это спрашивали.",
    PANICKED: "Вы уже спрашивали! Приезжайте скорее!",
}

UNSURE_REPLIES = {
    CALM: "Не знаю, отсюда не видно.",
    PANICKED: "Да не знаю я! Приезжайте уже!",
}

# Своё имя человек знает всегда, поэтому "не знаю" здесь звучало бы нелепо.
# Если в сценарии нет данных о заявителе, он просто не хочет называться -
# так бывает и в жизни.
UNSURE_BY_INTENT = {
    "CALLER_ID": {
        CALM: "Не хочу называться, это обязательно?",
        PANICKED: "Какая разница кто я! Приезжайте!",
    },
}

UNKNOWN_REPLIES = {
    CALM: "Простите, не понимаю вопрос.",
    PANICKED: "Что? Вы приедете или нет?",
}

# Ответ на реплику, в которой нет вопроса: приветствие или попытка успокоить.
# Фактов такая реплика не раскрывает - оператор обязан спросить сам.
GREETING_REPLIES = {
    CALM: "Здравствуйте! Мне нужна помощь.",
    PANICKED: "Алло! Помогите, пожалуйста!",
}

CALMING_REPLIES = {
    CALM: "Хорошо, жду.",
    PANICKED: "Скорее, пожалуйста!",
}

HANGUP_REPLY = "Всё, не могу больше, буду звонить в другое место!"


def _clamp(value: float) -> float:
    """Держит шкалу в границах от нуля до единицы."""
    return round(min(1.0, max(0.0, value)), 3)


def _initial_state(request: DialogueRequest) -> CallerState:
    """Берёт состояние из запроса, иначе из профиля абонента, иначе среднее.

    Состояние хранит Core и присылает его обратно на каждом шаге: AI-сервис
    ничего не помнит между запросами.
    """
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


def _victims_phrase(victims) -> Optional[str]:
    """Превращает структурные сведения о пострадавших в человеческую фразу."""
    if victims is None:
        return None
    if not victims.present:
        return "пострадавших нет"

    parts = ["пострадавшие есть"] if victims.count is None else [
        "пострадавших {count}".format(count=victims.count)
    ]
    if victims.threat_to_people:
        parts.append("людям угрожает опасность")
    return ", ".join(parts)


def _fact_value(scenario: Scenario, key: str) -> Optional[str]:
    """Достаёт значение факта из ожидаемого ввода оператора.

    Эталон описывает, что оператор должен был записать в карточку. Ровно это
    абонент и знает: адрес, обстоятельства, сведения о пострадавших, своё имя.
    Ничего сверх этого у него нет, поэтому и выдумать он ничего не может.
    """
    expected = scenario.ground_truth.expected_input

    if key == "address":
        return expected.address.display_address if expected.address else None
    if key == "victims":
        return _victims_phrase(expected.victims)
    if key == "description":
        return expected.description
    if key == "callerName":
        return expected.caller.full_name if expected.caller else None
    if key == "callerPhone":
        if expected.caller and expected.caller.phone_numbers:
            return expected.caller.phone_numbers[0].value
        return None

    value: Any = expected.extra_facts.get(key)
    return None if value is None else str(value)


def _pick_new_facts(
    scenario: Scenario, intent: str, revealed: List[str]
) -> Tuple[List[str], bool]:
    """Выбирает факты, которые абонент назовёт в этой реплике.

    Возвращает список ключей и признак того, что в сценарии такие факты вообще
    есть. Второе нужно, чтобы отличить повтор вопроса от вопроса, ответа
    на который абонент просто не знает.
    """
    available = [key for key in facts_for(intent) if _fact_value(scenario, key) is not None]
    fresh = [key for key in available if key not in revealed]
    return fresh[:MAX_FACTS_PER_REPLY], bool(available)


def _render(template: str, facts_text: str) -> str:
    """Подставляет факты в шаблон, начиная фразу с заглавной буквы."""
    if template.startswith("{facts}") and facts_text:
        facts_text = facts_text[0].upper() + facts_text[1:]
    return template.format(facts=facts_text)


def respond(request: DialogueRequest) -> DialogueResponse:
    """Отвечает на реплику оператора в пределах фактов сценария."""
    state = _initial_state(request)
    scenario = request.scenario
    utterance = request.operator_utterance

    intent = match_question(utterance)
    tone = match_tone(utterance)
    new_facts, intent_has_facts = _pick_new_facts(scenario, intent, state.revealed_facts)

    repeated = bool(intent) and intent_has_facts and not new_facts
    unsure = bool(intent) and not intent_has_facts
    # Реплика без вопроса, но по регламенту: представился, успокаивает.
    tone_only = not intent and bool(tone)

    panic = state.panic
    trust = state.trust
    patience = state.patience

    if "GREETING" in tone:
        trust += TRUST_FOR_GREETING
    if "CALMING" in tone:
        trust += TRUST_FOR_CALMING
        panic += PANIC_FOR_CALMING

    if new_facts:
        # Разговор движется: абоненту спокойнее, но время всё равно идёт.
        panic += PANIC_FOR_PROGRESS
        patience += PATIENCE_FOR_PROGRESS
    elif tone_only:
        panic += PANIC_FOR_PROGRESS
        patience += PATIENCE_FOR_TONE
    elif repeated:
        patience += PATIENCE_FOR_REPEAT
    else:
        # Вопрос не распознан или абонент не знает ответа.
        patience += PATIENCE_FOR_CONFUSION
        panic += PANIC_FOR_CONFUSION

    panic, trust, patience = _clamp(panic), _clamp(trust), _clamp(patience)
    flavour = PANICKED if panic >= PANIC_FLAVOUR_THRESHOLD else CALM
    hang_up = patience <= 0.0

    if hang_up:
        reply = HANGUP_REPLY
    elif new_facts:
        facts_text = ", ".join(str(_fact_value(scenario, key)) for key in new_facts)
        reply = _render(ANSWER_TEMPLATES[intent][flavour], facts_text)
    elif tone_only:
        reply = (
            GREETING_REPLIES[flavour] if "GREETING" in tone else CALMING_REPLIES[flavour]
        )
    elif repeated:
        reply = REPEAT_REPLIES[flavour]
    elif unsure:
        reply = UNSURE_BY_INTENT.get(intent, UNSURE_REPLIES)[flavour]
    else:
        reply = UNKNOWN_REPLIES[flavour]

    revealed = list(state.revealed_facts) + ([] if hang_up else new_facts)

    return DialogueResponse(
        reply=reply,
        caller_state=CallerState(
            panic=panic, trust=trust, patience=patience, revealed_facts=revealed
        ),
        revealed_facts=revealed,
        hang_up=hang_up,
        meta=ResponseMeta(engine="rules", version=SERVICE_VERSION, deterministic=True),
    )

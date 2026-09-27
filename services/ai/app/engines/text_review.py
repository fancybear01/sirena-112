"""Разбор текста карточки: смысл, грамотность, механика, регламент, время.

Зачем отдельный движок. В rule_scoring уже есть проверка описания, но она
сравнивает набор слов как есть: "задымление" и "задымлении" для неё разные
слова, и оператор теряет балл за падеж. Здесь слова приводятся к начальной
форме, поэтому сравнение идёт по смыслу, а не по написанию.

Главное правило модуля: **не выдавать догадку за проверенный вывод.** У каждой
проверки есть измеренная точность из docs/ai-text-review.md, и та проверка,
которой доверять нельзя, помечается как требующая глаза преподавателя.
Нейросети здесь нет: разбор детерминированный, одинаковый текст всегда даёт
одинаковый вывод.

Морфология подключается через pymorphy3. Если словаря на машине нет, модуль
не притворяется: он переходит на сравнение слов без разбора и прямо пишет
в ограничениях, что грамотность не проверялась.
"""

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Set

# Точность проверок, измеренная на разметке из benchmarks/text_review.
# Числа не выдуманы: как они получены, написано в docs/ai-text-review.md.
# Проверка с точностью ниже порога всегда просит глаз преподавателя.
MEASURED_ACCURACY: Dict[str, float] = {
    # Совпадение с экспертом на отложенной половине разметки, темы которой
    # при подборе порогов не участвовали. Простое правило на тех же примерах
    # даёт 0.56, то есть разбор по формам добавляет двадцать пять пунктов.
    # Но шестнадцати примеров мало, чтобы доверять суждению о смысле,
    # поэтому этот вывод всё равно уходит преподавателю на проверку.
    "MEANING": 0.81,
    # Проверка словарная, а не оценочная: слово либо есть в словаре, либо нет.
    # На разметке ни одной ложной тревоги, но плохих примеров там всего
    # четыре - число обнадёживает, а не доказывает.
    "SPELLING": 1.0,
    "MECHANICS": 1.0,
    # Проверка факта: поле заполнено или нет, слов больше порога или нет.
    # Суждения здесь не выносится, ошибиться нечем. Сам порог в словах -
    # это принятая нами условность, и она названа в ответе словами.
    "REGULATION": 1.0,
    # Сравнение двух чисел. Ошибиться тут нечем, это не суждение.
    "TIME": 1.0,
}

# Ниже этого доверия вывод показывается преподавателю как требующий проверки.
# Порог высокий намеренно: сами собой его проходят только проверки факта -
# словарь, механика, арифметика времени. Суждение о смысле не проходит,
# и это правильно: оценивать пересказ своими словами должен человек.
TRUSTED_FROM = 0.9

# Какую долю обстоятельств эталона надо отразить, чтобы описание считалось
# полным. Порог не выдуман и не подогнан: он выбран на одной половине
# разметки и проверен на другой, где тем сценариев нет вовсе. Подробности
# и числа - в docs/ai-text-review.md.
MEANING_PASSED_FROM = 0.8
MEANING_PARTIAL_FROM = 0.05

WORDS = re.compile(r"[^\w\-]+", re.UNICODE)
CYRILLIC = re.compile(r"[а-яё]", re.IGNORECASE)
LATIN = re.compile(r"[a-z]", re.IGNORECASE)
REPEATED_PUNCTUATION = re.compile(r"([!?.,;:])\1+")

# Служебные слова смысла не несут, сравнивать по ним нечего.
STOP_LEMMAS = frozenset(
    """
    и а но или да же ли бы не ни в во на за по из от до для об про при
    с со у к ко над под перед через между это тот этот такой который
    быть был была было были есть стать как что чем чём где когда куда
    там тут уже ещё еще все весь вся всё очень просто также тоже
    свой его её ее их наш ваш они она оно мы вы ты я себя сам
    """.split()
)

# Короче трёх букв слово почти всегда служебное, а разбор на нём ненадёжен.
# Отбор идёт по начальной форме, а не по написанию: иначе "дыме" попадало бы
# в сравнение, а "дым" - нет, и правильное описание теряло бы обстоятельство.
MINIMUM_LEMMA_LENGTH = 3

# Для проверки по словарю длина считается по написанию: короткие слова
# разбираются неоднозначно, и ругаться на них - только ложные тревоги.
MINIMUM_SPELLED_LENGTH = 4

# Длина слова в простом правиле. Оставлена такой, какой была до разбора
# по формам: правило сравнивается с новым методом, и менять его нельзя.
BASELINE_WORD_LENGTH = 4


class Morphology:
    """Разбор русских слов. Отдельным классом, чтобы честно жить без словаря."""

    def __init__(self) -> None:
        self._analyzer = None
        try:
            import pymorphy3

            self._analyzer = pymorphy3.MorphAnalyzer()
        except Exception:  # noqa: BLE001 - отсутствие словаря не ошибка сервиса
            self._analyzer = None
        self._cache: Dict[str, tuple] = {}

    @property
    def available(self) -> bool:
        return self._analyzer is not None

    def _parse(self, word: str) -> tuple:
        if word not in self._cache:
            parsed = self._analyzer.parse(word)[0]
            self._cache[word] = (parsed.normal_form, parsed.is_known)
        return self._cache[word]

    def lemma(self, word: str) -> str:
        """Начальная форма слова. Без словаря - слово как есть."""
        if self._analyzer is None:
            return word
        return self._parse(word)[0]

    def known(self, word: str) -> Optional[bool]:
        """Есть ли слово в словаре. None означает, что судить нечем."""
        if self._analyzer is None:
            return None
        return self._parse(word)[1]


_morphology: Optional[Morphology] = None


def morphology() -> Morphology:
    """Один разбор на процесс: словарь весит пятнадцать мегабайт."""
    global _morphology
    if _morphology is None:
        _morphology = Morphology()
    return _morphology


def use_morphology(replacement: Optional[Morphology]) -> None:
    """Подмена для тестов: надо проверять и работу без словаря."""
    global _morphology
    _morphology = replacement


def words(text: Optional[str]) -> List[str]:
    """Слова текста в нижнем регистре, без пунктуации."""
    cleaned = (text or "").lower().replace("ё", "е")
    return [word for word in WORDS.sub(" ", cleaned).split() if word]


def meaningful_lemmas(text: Optional[str]) -> Set[str]:
    """Начальные формы значимых слов: по ним и сравниваем смысл."""
    analyzer = morphology()
    result = set()
    for word in words(text):
        if word.isdigit():
            continue
        lemma = analyzer.lemma(word)
        if lemma in STOP_LEMMAS or len(lemma) < MINIMUM_LEMMA_LENGTH:
            continue
        result.add(lemma)
    return result


@dataclass
class Finding:
    """Вывод одной проверки."""

    code: str
    status: str
    explanation: str
    details: List[str] = field(default_factory=list)
    confidence: float = 0.0
    needs_teacher_check: bool = True

    def settle(self) -> "Finding":
        """Проставляет доверие по измеренной точности проверки."""
        accuracy = MEASURED_ACCURACY.get(self.code, 0.0)
        self.confidence = accuracy
        if self.status == "NOT_CHECKED":
            self.needs_teacher_check = True
        else:
            self.needs_teacher_check = accuracy < TRUSTED_FROM
        return self


def _status(share: float) -> str:
    if share >= 0.999:
        return "PASSED"
    return "PARTIAL" if share > 0 else "FAILED"


def meaning_status(share: float, passed_from: float = None, partial_from: float = None) -> str:
    """Вердикт по доле отражённых обстоятельств.

    Пороги вынесены в аргументы не для красоты: на них опирается подбор
    в бенчмарке, и жёсткие числа внутри функции не дали бы их проверить.
    """
    upper = MEANING_PASSED_FROM if passed_from is None else passed_from
    lower = MEANING_PARTIAL_FROM if partial_from is None else partial_from
    if share >= upper:
        return "PASSED"
    return "PARTIAL" if share >= lower else "FAILED"


# --- проверки -----------------------------------------------------------------


def check_meaning(expected: Optional[str], actual: Optional[str]) -> Finding:
    """Отражены ли в тексте обстоятельства эталона.

    Сравниваются начальные формы слов: оператор вправе написать своими
    словами и в своём падеже, лишь бы обстоятельства были на месте.
    """
    wanted = meaningful_lemmas(expected)
    if not wanted:
        return Finding("MEANING", "NOT_CHECKED", "в эталоне нет описания, сравнивать не с чем").settle()
    if not (actual or "").strip():
        return Finding("MEANING", "FAILED", "описание не заполнено").settle()

    got = meaningful_lemmas(actual)
    missing = sorted(wanted - got)
    share = (len(wanted) - len(missing)) / len(wanted)
    status = meaning_status(share)
    if not missing:
        explanation = "обстоятельства эталона отражены"
    elif status == "PASSED":
        # Пересказ своими словами - нормально, и придираться к каждому
        # пропущенному слову нельзя. Но показать разницу всё равно надо.
        explanation = "отражено %d%% обстоятельств, своими словами: не найдено %s" % (
            round(share * 100),
            ", ".join(missing),
        )
    else:
        explanation = "в описании не отражено: %s" % ", ".join(missing)
    return Finding("MEANING", status, explanation, missing).settle()


def check_spelling(actual: Optional[str], allowed: Sequence[str] = ()) -> Finding:
    """Слова, которых нет в словаре.

    Слова из эталона в ошибки не попадают: там встречаются названия улиц
    и организаций, которых в общем словаре и быть не должно. Без этого
    проверка ругалась бы на правильно списанный адрес.
    """
    analyzer = morphology()
    if not analyzer.available:
        return Finding(
            "SPELLING", "NOT_CHECKED", "словарь морфологии не установлен, грамотность не проверялась"
        ).settle()

    known_from_reference = {analyzer.lemma(word) for word in words(" ".join(allowed))}
    known_from_reference |= set(words(" ".join(allowed)))

    suspicious = []
    for word in words(actual):
        if len(word) < MINIMUM_SPELLED_LENGTH or word.isdigit():
            continue
        if word in known_from_reference or analyzer.lemma(word) in known_from_reference:
            continue
        if LATIN.search(word):
            continue  # латиница разбирается отдельной проверкой
        if analyzer.known(word) is False:
            suspicious.append(word)

    unique = sorted(set(suspicious))
    if not unique:
        return Finding("SPELLING", "PASSED", "слов вне словаря не найдено").settle()
    return Finding(
        "SPELLING",
        "FAILED",
        "слов нет в словаре: %s" % ", ".join(unique),
        unique,
    ).settle()


def check_mechanics(actual: Optional[str]) -> Finding:
    """Механические огрехи ручной правки.

    Ловится то, что видно без словаря: раскладка, дубли, лишняя пунктуация.
    Такие огрехи появляются именно при правке руками, а не при наборе с нуля.
    """
    text = actual or ""
    if not text.strip():
        return Finding("MECHANICS", "NOT_CHECKED", "текст пустой").settle()

    problems: List[str] = []

    mixed = [word for word in words(text) if CYRILLIC.search(word) and LATIN.search(word)]
    if mixed:
        problems.append("латиница внутри русских слов: %s" % ", ".join(sorted(set(mixed))))

    previous = None
    doubled = []
    for word in words(text):
        if word == previous and len(word) >= 3:
            doubled.append(word)
        previous = word
    if doubled:
        problems.append("слово повторено дважды: %s" % ", ".join(sorted(set(doubled))))

    if REPEATED_PUNCTUATION.search(text):
        problems.append("подряд идущие знаки пунктуации")

    if "  " in text:
        problems.append("двойные пробелы")

    letters = [character for character in text if character.isalpha()]
    if len(letters) >= 10 and all(character.isupper() for character in letters):
        problems.append("текст набран заглавными")

    if not problems:
        return Finding("MECHANICS", "PASSED", "механических огрехов не найдено").settle()
    return Finding("MECHANICS", "FAILED", "; ".join(problems), problems).settle()


def check_regulation(filled: Dict[str, bool], minimum_words: int, actual: Optional[str]) -> Finding:
    """Заполнено ли то, без чего карточка не принимается.

    Что именно обязательно, решает не этот модуль: список приходит снаружи,
    из эталона сценария. Здесь только проверка полноты.
    """
    if not filled:
        return Finding("REGULATION", "NOT_CHECKED", "нечего проверять").settle()

    missing = sorted(name for name, present in filled.items() if not present)
    short = len(words(actual)) < minimum_words

    problems = []
    if missing:
        problems.append("не заполнено: %s" % ", ".join(missing))
    if short:
        problems.append("описание короче %d слов" % minimum_words)

    if not problems:
        return Finding("REGULATION", "PASSED", "обязательные поля заполнены").settle()
    share = 0.0 if missing else 0.5
    return Finding("REGULATION", _status(share), "; ".join(problems), problems).settle()


def check_time(elapsed_seconds: Optional[int], limit_seconds: Optional[int]) -> Finding:
    """Уложился ли обучающийся в отведённое время."""
    if elapsed_seconds is None or not limit_seconds:
        return Finding("TIME", "NOT_CHECKED", "время не передано или норма не задана").settle()
    if elapsed_seconds <= limit_seconds:
        return Finding(
            "TIME",
            "PASSED",
            "уложился: %d с из %d" % (elapsed_seconds, limit_seconds),
        ).settle()
    return Finding(
        "TIME",
        "FAILED",
        "превышено время: %d с при норме %d" % (elapsed_seconds, limit_seconds),
        ["превышение на %d с" % (elapsed_seconds - limit_seconds)],
    ).settle()


# --- простое правило для сравнения --------------------------------------------


def baseline_meaning(expected: Optional[str], actual: Optional[str]) -> float:
    """Как та же проверка выглядит без разбора слов.

    Это не мёртвый код: на этом правиле считается сравнение в бенчмарке.
    Без него нельзя показать, что разбор слов вообще что-то даёт.
    """
    wanted = {word for word in words(expected) if len(word) >= BASELINE_WORD_LENGTH}
    if not wanted:
        return 1.0
    got = set(words(actual))
    return (len(wanted) - len(wanted - got)) / len(wanted)

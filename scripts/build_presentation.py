#!/usr/bin/env python3
"""Заполняет официальный шаблон ЛЦТ-2026 содержанием нашего решения.

Дизайн шаблона не трогается: обязательные слайды 7-11 требуется сохранить
в исходном виде, поэтому скрипт только подставляет текст в готовые блоки
и удаляет неиспользуемые слайды. Ни одна фигура не двигается и не красится.

Запуск:

    python scripts/build_presentation.py \\
      --template "<путь>/ЛЦТ2026 Шаблон презентации.pptx" \\
      --output "Ваш звонок важен для нас.pptx"
"""

import argparse
import copy
import sys
from typing import List, Optional, Sequence

from pptx import Presentation
from pptx.util import Emu, Pt

TEAM = "Ваш звонок важен для нас"

# Какие слайды шаблона оставляем и что на них кладём. Порядок в файле
# определяется номерами, поэтому повествование выстроено по возрастанию.
# Слайд 14 из шаблона не используется: содержания под него не нашлось,
# а пустой слайд в презентации хуже, чем его отсутствие.
KEEP = [7, 8, 9, 10, 11, 12, 13, 15, 16, 17, 19, 20, 24, 25]


# Блоки, куда текст не влез даже самым мелким кеглем: их надо сокращать.
TIGHT: List = []


def font_of(shape):
    """Шрифт первого прогона: им размечаем новый текст, чтобы вид не поехал."""
    for paragraph in shape.text_frame.paragraphs:
        for run in paragraph.runs:
            return run.font
    return None


def write(shape, lines: Sequence[str], keep_first_style: bool = True) -> None:
    """Подставляет строки в готовый блок, сохраняя оформление шаблона."""
    frame = shape.text_frame
    sample = font_of(shape) if keep_first_style else None
    saved = None
    if sample is not None:
        saved = {
            "size": sample.size,
            "bold": sample.bold,
            "italic": sample.italic,
            "name": sample.name,
            "color": None,
        }
        try:
            if sample.color and sample.color.type is not None:
                saved["color"] = sample.color.rgb
        except Exception:  # noqa: BLE001 - у темы цвет может быть не rgb
            saved["color"] = None

    frame.clear()
    for index, line in enumerate(lines):
        paragraph = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
        run = paragraph.add_run()
        run.text = line
        if saved:
            if saved["size"]:
                run.font.size = saved["size"]
            run.font.bold = saved["bold"]
            run.font.italic = saved["italic"]
            if saved["name"]:
                run.font.name = saved["name"]
            if saved["color"] is not None:
                run.font.color.rgb = saved["color"]
    # Ноль означает, что текст не вместился и при самом мелком допустимом
    # кегле: подгонкой это не лечится, надо сокращать текст.
    if fit(shape) == 0.0:
        TIGHT.append((shape, frame.text[:40]))


# Средняя ширина знака в шрифте без засечек - примерно 0,52 кегля,
# межстрочный интервал - 1,25. Точности хватает, чтобы поймать вылет
# текста за рамку: ошибка оценки меньше строки.
CHAR_WIDTH = 0.52
LINE_HEIGHT = 1.25
# Ниже одиннадцати пунктов текст на слайде уже не читается из зала,
# поэтому это не предел подгонки, а предел допустимого: если текст
# не влез, сборка говорит об этом, и сокращать надо текст.
SMALLEST = 11.0


def lines_needed(text: str, width: float, size: float) -> int:
    per_line = max(1, int(width / (size * CHAR_WIDTH)))
    return sum(max(1, -(-len(line) // per_line)) for line in text.split("\n"))


def fit(shape) -> float:
    """Уменьшает кегль, пока текст не перестанет вылезать за рамку.

    Блоки шаблона помечены автоподгоном, но масштаб в файле не записан:
    до первой правки в редакторе текст рисуется полным кеглем и вылезает.
    Поэтому размер считаем сами и записываем явно.
    """
    frame = shape.text_frame
    frame.word_wrap = True
    runs = [run for paragraph in frame.paragraphs for run in paragraph.runs]
    sizes = [run.font.size.pt for run in runs if run.font.size]
    size = max(sizes) if sizes else 14.0
    width = Emu(shape.width).pt - 12
    height = Emu(shape.height).pt - 8
    while size > SMALLEST and lines_needed(frame.text, width, size) * size * LINE_HEIGHT > height:
        size -= 0.5
    overflows = lines_needed(frame.text, width, size) * size * LINE_HEIGHT > height
    for run in runs:
        run.font.size = Pt(size)
    # Записанный ранее масштаб автоподгона уменьшил бы кегль ещё раз.
    body = frame._txBody.find(
        "{http://schemas.openxmlformats.org/drawingml/2006/main}bodyPr")
    if body is not None:
        for auto in body.findall(
                "{http://schemas.openxmlformats.org/drawingml/2006/main}normAutofit"):
            auto.attrib.pop("fontScale", None)
            auto.attrib.pop("lnSpcReduction", None)
    return size if not overflows else 0.0


def by_position(slide, left: float, top: float, tolerance: float = 6.0):
    """Находит блок по его месту на слайде: имена фигур в шаблоне неуникальны."""
    for shape in slide.shapes:
        if not shape.has_text_frame:
            continue
        if abs(Emu(shape.left).pt - left) <= tolerance and abs(Emu(shape.top).pt - top) <= tolerance:
            return shape
    raise LookupError("нет блока в точке %.0f, %.0f" % (left, top))


def placeholder(slide, idx: int):
    for shape in slide.placeholders:
        if shape.placeholder_format.idx == idx:
            return shape
    raise LookupError("нет заполнителя %d" % idx)


def drop_shape(shape) -> None:
    shape._element.getparent().remove(shape._element)


def drop_slides(presentation, keep: Sequence[int]) -> None:
    """Удаляет слайды, которых нет в списке. Нумерация как в шаблоне, с единицы."""
    id_list = presentation.slides._sldIdLst
    entries = list(id_list)
    for number in range(len(entries), 0, -1):
        if number in keep:
            continue
        entry = entries[number - 1]
        presentation.part.drop_rel(entry.rId)
        id_list.remove(entry)


# --- содержание ---------------------------------------------------------------


def fill_title(slide) -> None:
    write(placeholder(slide, 0), [TEAM])
    write(placeholder(slide, 12), [
        "Задача №9: тренажёр для подготовки операторов службы-112",
        "Департамент по делам гражданской обороны, чрезвычайным ситуациям",
        "и пожарной безопасности города Москвы",
    ])


def fill_summary(slide) -> None:
    # Рамки шаблона здесь узкие, 389 на 70 пунктов, поэтому текст короткий:
    # подробности - на свободных слайдах после одиннадцатого.
    write(by_position(slide, 536, 206), [
        "Курсант принимает учебный вызов как на рабочем месте оператора-112. "
        "Звонящего играет ИИ: говорит голосом, отвечает по обстоятельствам "
        "и не выдаёт того, о чём не спросили. Карточку система сверяет "
        "с официальным классификатором. Интернет и видеокарта не нужны.",
    ])
    write(by_position(slide, 538, 384), [
        "Речь распознаётся и синтезируется на месте: ход разговора 0,5 с. "
        "Источник истины один - официальный классификатор на 1281 позицию, "
        "и тесты падают, если в коде появится его копия. Каждое утверждение "
        "подтверждено запускаемым скриптом.",
    ])
    write(by_position(slide, 26, 306), [
        "Капитан: Артём Малов, разработка на Kotlin, архитектура",
        "Кол-во участников: 4 человека",
        "Краткое описание:",
        "- собрались под задачу №9, у каждого своя часть системы целиком",
        "- места работы и учёбы: заполнить",
        "Город и регион: заполнить",
    ])


def fill_team(slide) -> None:
    people = [
        (41, "Артём Малов", ["Капитан, Kotlin Core", "@fancybear01",
                             "телефон: заполнить", "работа/учёба: заполнить"]),
        (222, "Полина Галактионова", ["ИИ, речь, оценка занятия", "@Polina1411",
                                      "телефон: заполнить", "работа/учёба: заполнить"]),
        # Фамилий этих двоих в репозитории нет - только имя и учётная запись.
        (404, "Максим", ["Телефония, SIP и RTP, запись", "@pestriymaks",
                         "фамилия и телефон: заполнить", "работа/учёба: заполнить"]),
        (585, "Никита", ["Веб-интерфейс, автономная поставка", "@Xrinerio",
                         "фамилия и телефон: заполнить", "работа/учёба: заполнить"]),
    ]
    for left, name, details in people:
        write(by_position(slide, left, 285), [name])
        write(by_position(slide, left, 335), details)

    # Пятая карточка лишняя: участников четверо. Правила шаблона разрешают
    # удалять лишние блоки именно на этом слайде.
    for left, top in ((753, 120), (767, 285), (767, 335), (772, 142)):
        try:
            drop_shape(by_position(slide, left, top))
        except LookupError:
            for shape in slide.shapes:
                if abs(Emu(shape.left).pt - left) <= 6 and abs(Emu(shape.top).pt - top) <= 6:
                    drop_shape(shape)
                    break


def fill_story(slide) -> None:
    write(by_position(slide, 42, 126), [
        "Собрались под задачу №9. Разделили работу по границам системы: "
        "каждый отвечает за свой сервис целиком, от кода до проверок. "
        "Договаривались через контракты, поэтому четверо писали "
        "на четырёх языках и не мешали друг другу.",
    ])
    write(by_position(slide, 42, 270), [
        "Ошибка оператора-112 стоит дороже, чем почти в любой другой программе, "
        "а учиться сегодня можно только на живых звонках или разыгранных сценках. "
        "И здесь всё измеримо: правильность карточки проверяется по официальному "
        "классификатору, а не по мнению.",
    ])
    write(by_position(slide, 42, 405), [
        "Заглушки скрывали настоящие дефекты: на подменах всё работало, а с живыми "
        "моделями вылезло, что синтез отдаёт не ту частоту, а распознавание на "
        "полсекунды останавливает обслуживание остальных звонков. Поставочный "
        "образ выглядел здоровым и не распознавал речь вообще - в нём не хватало "
        "одной системной библиотеки. Нашли за сутки до сдачи. Заодно перепроверили "
        "лицензии: библиотека синтеза свободна только до определённой версии.",
    ])


def fill_short(slide) -> None:
    write(by_position(slide, 46, 151), [
        "Четыре сервиса, каждый со своей ответственностью и описанным контрактом.",
        "",
        "Kotlin Core - занятия, карточки, отчёты, маршрутизация служб",
        "по классификатору, роли и доступ, PostgreSQL.",
        "Python AI - поведение звонящего, распознавание и синтез речи,",
        "оценка занятия и разбор текста карточки.",
        "Go Media - SIP, RTP, мост к Asterisk, запись занятия в WAV.",
        "React Web - рабочее место оператора и преподавателя.",
        "",
        "Модели речи локальные. Оценка детерминированная: одинаковый ввод",
        "всегда даёт одинаковый разбор.",
    ])
    write(by_position(slide, 513, 151), [
        "Тренажёр закрывает разрыв между теорией и живым звонком:",
        "курсант ошибается на учебном вызове, а не на настоящем.",
        "",
        "Развитие: сценарии всех уровней сложности, подбор следующего задания",
        "по истории обучения, интеграция с системами заказчика, разбор записи",
        "занятия вместе с транскриптом.",
        "",
        "Решение переносится на другие диспетчерские службы: классификатор,",
        "сценарии и рубрика оценивания - это данные, а не код.",
    ])


def fill_problem(slide) -> None:
    write(placeholder(slide, 0), ["ПРОБЛЕМА"])
    write(placeholder(slide, 1), [
        "Ошибка оператора-112 стоит жизни, а учиться негде.",
        "",
        "На настоящих звонках учиться нельзя: цена ошибки слишком высока.",
        "",
        "Разыгранные сценки не масштабируются и зависят от того, кто играет.",
        "",
        "У преподавателя нет объективной меры: разбор опирается на мнение,",
        "а не на эталон.",
        "",
        "Классификатор происшествий - 1281 позиция, у каждой свои обязательные",
        "вопросы и свой состав служб. Это запоминается только практикой.",
    ])


def fill_flow(slide) -> None:
    write(placeholder(slide, 0), ["КАК ПРОХОДИТ ЗАНЯТИЕ"])
    write(placeholder(slide, 1), [
        "1. Преподаватель выдаёт задание из каталога сценариев.",
        "2. Курсант принимает вызов - голосом или в карточном режиме.",
        "3. Звонящий-ИИ отвечает по обстоятельствам: паникует, отвлекается,",
        "    не выдаёт того, о чём не спросили.",
        "4. Курсант ведёт карточку: признаки, обязательные вопросы, адрес,",
        "    пострадавшие, обстоятельства.",
        "5. Система вычисляет тип происшествия и состав служб по классификатору.",
        "6. Разбор по критериям: что засчитано, что упущено и почему.",
        "",
        "Занятие записывается: голос курсанта и голос ИИ - на разных каналах,",
        "чтобы разбор можно было послушать.",
    ])


def fill_verified(slide) -> None:
    write(placeholder(slide, 0), ["ЧТО УЖЕ РАБОТАЕТ И ЧЕМ ПОДТВЕРЖДЕНО"])
    blocks = [
        (13, "Живой голос", [
            "Два хода на человеческой речи,",
            "распознано дословно.",
            "Vosk и Piper локально, без",
            "интернета и видеокарты.",
        ]),
        (14, "Карточный режим", [
            "Сквозной прогон в CI на каждое",
            "изменение: два занятия подряд",
            "дают одинаковый результат",
            "и 14 назначенных служб.",
        ]),
        (15, "Хранение", [
            "Восстановление состояния после",
            "перезапуска проверяется в CI.",
            "Резервная копия с протоколом",
            "сверки после восстановления.",
        ]),
        (16, "Отчёты и форматы", [
            "XLSX, PDF и JSON открываются",
            "настоящими читалками.",
            "Импорт сценария проверяет схему",
            "и версию классификатора.",
        ]),
    ]
    # Заголовки карточек - 37, 39, 41, 43; тексты под ними - 38, 40, 42, 44.
    for position, (_, title, lines) in enumerate(blocks):
        write(placeholder(slide, 37 + position * 2), [title])
        write(placeholder(slide, 38 + position * 2), lines)


def fill_numbers(slide) -> None:
    write(placeholder(slide, 0), ["ИЗМЕРЕННЫЕ ПОКАЗАТЕЛИ"])
    rows = [
        "Отклик API, p95: 0,14 с при нормативе 2 с",
        "Ход разговора с ИИ: 0,5 с при бюджете паузы 1,2 с",
        "20 занятий одновременно: 0,67 с на ход",
        "Распознавание 3,3 с речи: 0,4 с. Синтез ответа: 0,2 с",
        "Запуск сервиса с моделями: 1,6 с",
    ]
    for offset, text in enumerate(rows):
        write(placeholder(slide, 15 + offset), [text])


def fill_text_review(slide) -> None:
    write(placeholder(slide, 0), ["ОЦЕНКА ТЕКСТА КАРТОЧКИ"])
    # Раскладка слайда: сверху слева способ проверки, под ним цифры,
    # справа сверху вывод, справа снизу честный предел.
    write(placeholder(slide, 14), [
        "Как проверяли",
        "",
        "Разбор текста карточки сравнили с экспертной разметкой. Пороги",
        "подбирали на одной половине набора, проверяли на другой - её темы",
        "в подборе не участвовали.",
    ])
    write(placeholder(slide, 12), [
        "Что с чем сравнивали: совпадение с экспертом",
        "",
        "простое сравнение слов - 0,56",
        "разбор по начальным формам - 0,81",
        "нейросетевые эмбеддинги, две модели - 0,50 и 0,69",
        "",
        "Отчёт приведён целиком, вместе с разбором ошибок:",
        "docs/ai-text-review.md.",
    ])
    write(placeholder(slide, 10), [
        "Что выбрали",
        "",
        "Нейросеть выигрыша не дала,",
        "и в текстовой части мы оставили",
        "правила: тот же результат",
        "без 400 МБ модели в поставке",
        "и без потери предсказуемости.",
        "",
        "Орфография, порядок вопросов",
        "и сроки проверяются точно:",
        "здесь ошибиться нечем.",
    ])
    write(placeholder(slide, 11), [
        "Где предел",
        "",
        "Вывод о смысле помечен как",
        "требующий проверки человеком:",
        "0,81 - достаточно для подсказки",
        "и мало для оценки без человека.",
    ])


def fill_architecture(slide) -> None:
    write(placeholder(slide, 0), ["АРХИТЕКТУРА"])
    write(placeholder(slide, 14), [
        "Браузер",
        "   │ TLS",
        "   ▼",
        "Web (React + nginx)",
        "   │",
        "   ▼",
        "Kotlin Core ──────> PostgreSQL",
        "   │   │                │",
        "   │   │                └─> резервная копия",
        "   │   │                    и проверенное",
        "   │   │                    восстановление",
        "   │   └──> Python AI: Vosk, Piper, оценка",
        "   │",
        "   └──> Go Media ──> Asterisk: SIP, RTP",
        "              └──> запись занятия в WAV",
        "",
        "Всё разворачивается одной командой",
        "в изолированном контуре.",
    ])
    components = [
        "Kotlin Core: состояние занятий, классификатор, службы, роли, база",
        "Python AI: звонящий, распознавание и синтез речи, оценка и разбор текста",
        "Go Media: телефония SIP и RTP, мост к Asterisk, запись занятия",
        "React Web: рабочее место оператора и преподавателя",
        "Мониторинг: сводный статус и метрики; API расширений только для чтения",
    ]
    for offset, text in enumerate(components):
        write(placeholder(slide, 15 + offset), [text])


def fill_gaps(slide) -> None:
    write(placeholder(slide, 0), ["БЕЗОПАСНОСТЬ И ЭКСПЛУАТАЦИЯ"])
    blocks = [
        ("Защита данных", [
            "TLS 1.3 и HSTS на браузерном",
            "канале.",
            "",
            "Роли ADMIN, TEACHER, STUDENT,",
            "доступ по группам.",
            "",
            "Отдельные токены служб,",
            "журнал аудита.",
        ]),
        ("Надёжность", [
            "Ежедневная резервная копия.",
            "",
            "Восстановление доказано",
            "потабличной сверкой.",
            "",
            "Состояние переживает",
            "перезапуск - проверка в CI.",
        ]),
        ("Эксплуатация", [
            "Управление сервисами",
            "из интерфейса админа.",
            "",
            "Метрики Prometheus",
            "для мониторинга заказчика.",
            "",
            "API расширений только",
            "для чтения, без ПДн.",
        ]),
    ]
    for target, (title, lines) in zip((26, 31, 32), blocks):
        write(placeholder(slide, target), [title, ""] + lines)


def fill_plans(slide) -> None:
    write(placeholder(slide, 0), ["ПЛАНЫ РАЗВИТИЯ"])
    # У каждого этапа две рамки: заголовок и пояснение под ним. Рамки
    # перекрываются, поэтому заголовок должен занимать ровно одну строку.
    steps = [
        ("Сценарии всех уровней",
         "Каталог среднего и высокого уровня: механика готова, нужно содержание."),
        ("Замеры у заказчика",
         "Нормативы снимались на ноутбуке, целевой сервер даст свои цифры."),
        ("Шифрование целиком",
         "Хранимые данные и каналы между службами. Канал до браузера уже закрыт."),
        ("Адаптивная сложность",
         "Следующее задание подбирается по истории обучения, а не вручную."),
        ("Разбор записи",
         "Прослушивание занятия вместе с транскриптом и оценкой по шагам."),
    ]
    for position, (title, detail) in enumerate(steps):
        write(placeholder(slide, 26 + position * 2), [title])
        write(placeholder(slide, 27 + position * 2), [detail])


def fill_principles(slide) -> None:
    write(placeholder(slide, 0), ["ТРИ ПРИНЦИПА, НА КОТОРЫХ ПОСТРОЕНО РЕШЕНИЕ"])
    blocks = [
        ("Один источник истины", [
            "Классификатор единственный.",
            "Тесты сканируют исходники",
            "и падают, если в коде завелась",
            "копия названий служб",
            "или кодов происшествий.",
            "",
            "Расхождение эталона и системы",
            "невозможно по устройству,",
            "а не по договорённости.",
        ]),
        ("Заглушка не выдаётся за работу", [
            "Нет моделей - понятная ошибка,",
            "а не придуманный текст.",
            "",
            "Каждый транскрипт помечен",
            "признаком подмены.",
            "",
            "Оценка ИИ идёт с измеренной",
            "точностью и пометкой, чему",
            "нельзя верить без человека.",
        ]),
        ("Проверяемость вместо обещаний", [
            "Восемь запускаемых проверок:",
            "форматы, нагрузка, восстановление",
            "из копии, шифрование канала,",
            "утечка персональных данных,",
            "покрытие требований, контракт",
            "расширений, живой голос.",
            "",
            "Каждая печатает результат",
            "и возвращает ошибку при",
            "расхождении.",
        ]),
    ]
    for position, (title, lines) in enumerate(blocks):
        write(placeholder(slide, 37 + position * 2), [title])
        write(placeholder(slide, 38 + position * 2), lines)


FILLERS = {
    7: fill_title,
    8: fill_summary,
    9: fill_team,
    10: fill_story,
    11: fill_short,
    12: fill_problem,
    13: fill_flow,
    16: fill_verified,
    15: fill_numbers,
    19: fill_text_review,
    20: fill_architecture,
    17: fill_principles,
    24: fill_gaps,
    25: fill_plans,
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template", required=True)
    parser.add_argument("--output", required=True)
    arguments = parser.parse_args()

    presentation = Presentation(arguments.template)
    problems: List[str] = []

    for number, filler in FILLERS.items():
        try:
            filler(presentation.slides[number - 1])
            print("слайд %-3d заполнен" % number)
        except Exception as error:  # noqa: BLE001
            problems.append("слайд %d: %s" % (number, error))
            print("слайд %-3d НЕ ЗАПОЛНЕН: %s" % (number, error))

    drop_slides(presentation, KEEP)
    presentation.save(arguments.output)
    if TIGHT:
        print("\nТЕКСТ НЕ ВЛЕЗ при кегле %.1f - сократить:" % SMALLEST)
        for shape, sample in TIGHT:
            print("   %r" % sample)
    print("\nготово: %s, слайдов %d" % (arguments.output, len(presentation.slides)))

    if problems:
        print("\nНЕ ЗАПОЛНИЛОСЬ:")
        for problem in problems:
            print("  -", problem)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

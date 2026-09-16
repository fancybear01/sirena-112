"""Сравнение адресов: форма записи не должна влиять на оценку."""

import pytest

from app.engines.address_match import compare, parse

REFERENCE = "Москва, ул. Берзарина, д. 21, корп. 1, под. 3"


@pytest.mark.parametrize(
    "answer",
    [
        "Москва, ул. Берзарина, д. 21, корп. 1, под. 3",
        "ул Берзарина дом 21 корпус 1 подъезд 3",
        "БЕРЗАРИНА, 21, К1, П3",
        "берзарина д21 к1 п3",
        "Берзарина, 21, корп 1, подъезд 3, Москва",
    ],
)
def test_same_address_written_differently(answer):
    assert compare(REFERENCE, answer).share == 1.0


def test_city_is_not_required():
    """В московской системе-112 город один, требовать его отдельно незачем."""
    assert compare(REFERENCE, "ул. Берзарина, д. 21, корп. 1, под. 3").share == 1.0


def test_missing_parts_are_named(client=None):
    match = compare(REFERENCE, "Берзарина 21")

    assert match.share == 0.5
    assert match.missing == ["корпус 1", "подъезд 3"]


def test_completely_different_address():
    assert compare(REFERENCE, "Тверская, дом 15").share == 0.0


def test_empty_answer():
    assert compare(REFERENCE, "").share == 0.0


def test_empty_reference_matches_anything():
    """Если адреса в эталоне нет, проверять нечего."""
    assert compare("", "что угодно").share == 1.0


def test_parse_keeps_human_names():
    assert parse("д. 21, корп. 1") == [("21", "дом 21"), ("1", "корпус 1")]


def test_street_name_with_digits_is_not_broken():
    """"52-я Парковая" не должна распасться на части."""
    values = [value for value, _ in parse("52-я Парковая, д. 4")]

    assert "52" in values and "я" in values and "парковая" in values

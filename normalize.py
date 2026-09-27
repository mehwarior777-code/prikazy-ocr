# -*- coding: utf-8 -*-
"""
normalize.py — нормализация распознанных значений (OCR-шум → чистые данные).

Что чистим:
  - ИНН: «1194З5» → «119435», «667ООО» → «667000» (буквы, похожие на цифры);
  - даты: «15.03.2023», «2023-03-15», «05.02.23» → «дд.мм.гггг»;
  - суммы: «1 371 600,4 ₽», «1371600,4руб.» → float 1371600.4.
"""
import re

# Буквы, которые OCR часто путает с цифрами (замена до фильтрации нецифр)
_INN_LETTERS = str.maketrans({
    "О": "0", "о": "0", "O": "0", "Q": "0", "q": "0",
    "З": "3", "з": "3",
    "В": "8", "B": "8", "в": "8", "b": "8",
    "Б": "6", "б": "6",
    "l": "1", "I": "1", "|": "1",
    "S": "5", "s": "5",
    "Г": "7",
})


def norm_inn(value):
    """
    Приводит ИНН к строке из цифр (10/12 знаков), убирая OCR-шум.

    Args:
        value: Распознанное значение ИНН

    Returns:
        str: Только цифры ('' если цифр нет)
    """
    if value is None:
        return ""
    s = str(value).strip().translate(_INN_LETTERS)
    digits = re.sub(r"\D", "", s)
    return digits


def norm_date(value):
    """
    Приводит дату к формату дд.мм.гггг.

    Args:
        value: Дата в виде «дд.мм.гггг», «гггг-мм-дд», «дд/мм/гг» и т.п.

    Returns:
        str: Дата дд.мм.гггг или '' если распознать не удалось
    """
    if value is None:
        return ""
    s = str(value).strip()
    m = re.search(r"(\d{1,4})[./\-](\d{1,2})[./\-](\d{1,4})", s)
    if not m:
        return ""
    a, b, c = m.group(1), m.group(2), m.group(3)
    if len(a) == 4:      # год-месяц-день
        y, mo, d = a, b, c
    elif len(c) == 4:    # день-месяц-год
        d, mo, y = a, b, c
    elif len(c) == 2:    # день.месяц.гг (2-значный год)
        d, mo, y = a, b, "20" + c
    else:
        return ""
    d, mo = d.zfill(2), mo.zfill(2)
    if not (1 <= int(mo) <= 12):       # месяц/день могли перепутать
        d, mo = mo, d
    if not (1 <= int(d) <= 31 and 1 <= int(mo) <= 12):
        return ""
    return "%s.%s.%s" % (d, mo, y)


def inn_checksum_valid(inn):
    """
    Проверяет ИНН по контрольной сумме (как у ФНС): 10 или 12 цифр.

    Args:
        inn (str): ИНН после нормализации (только цифры)

    Returns:
        bool: True, если контрольная сумма сходится
    """
    if not inn or not re.fullmatch(r"\d{10}|\d{12}", inn or ""):
        return False

    def _weighted(part, weights):
        return sum(int(ch) * w for ch, w in zip(part, weights))

    if len(inn) == 10:
        s = _weighted(inn[:9], [2, 4, 10, 3, 5, 9, 4, 6, 8])
        return (s % 11) % 10 == int(inn[9])
    s1 = _weighted(inn[:10], [7, 2, 4, 10, 3, 5, 9, 4, 6, 8])
    if (s1 % 11) % 10 != int(inn[10]):
        return False
    s2 = _weighted(inn[:11], [3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8])
    return (s2 % 11) % 10 == int(inn[11])


def norm_amount(value):
    """
    Приводит сумму к числу float (рубли, десятичная точка).

    Args:
        value: Сумма как число или строка («1 371 600,4 ₽», «1371600,4»)

    Returns:
        float: Сумма или None, если число не найдено
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    s = s.replace("\u00a0", " ").replace(" ", "")
    s = s.replace("₽", "").replace("руб.", "").replace("руб", "")
    s = s.replace(",", ".")
    # если точек несколько — это были разделители тысяч («1.371.600,4»)
    if s.count(".") > 1:
        s = s.replace(".", "")
    m = re.search(r"\d+(?:\.\d{1,2})?", s)
    return float(m.group()) if m else None


if __name__ == "__main__":
    # самопроверка
    cases = [
        ("norm_inn", norm_inn, "1194З5", "119435"),
        ("norm_inn", norm_inn, "667ООО", "667000"),
        ("norm_inn", norm_inn, "2320109650", "2320109650"),
        ("norm_inn", norm_inn, "нет данных", ""),
        ("norm_date", norm_date, "15.03.2023", "15.03.2023"),
        ("norm_date", norm_date, "2023-03-15", "15.03.2023"),
        ("norm_date", norm_date, "05.02.23", "05.02.2023"),
        ("norm_date", norm_date, "-", ""),
        ("norm_amount", norm_amount, "1 371 600,4 ₽", 1371600.4),
        ("norm_amount", norm_amount, "1371600,4", 1371600.4),
        ("norm_amount", norm_amount, "200000", 200000.0),
        ("norm_amount", norm_amount, "не указано", None),
        ("inn_checksum", inn_checksum_valid, "2320109650", True),
        ("inn_checksum", inn_checksum_valid, "2320109659", False),
        ("inn_checksum", inn_checksum_valid, "667000", False),
        ("inn_checksum", inn_checksum_valid, "", False),
    ]
    ok = True
    for name, fn, inp, expected in cases:
        got = fn(inp)
        mark = "✅" if got == expected else "❌"
        if got != expected:
            ok = False
        print("%s %s(%r) = %r (ожидалось %r)" % (mark, name, inp, got, expected))
    print("\nИТОГ:", "ВСЕ ПРОШЛИ" if ok else "ЕСТЬ ПАДЕНИЯ")
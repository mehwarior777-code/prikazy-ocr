# -*- coding: utf-8 -*-
"""
pipeline.py — полный процесс трека №2: PDF судебного акта → OCR → JSON-извлечение.

Пути OCR: qwen3-vl:8b (по умолчанию, лучший) или paddle.
Выход: JSON-файл рядом с PDF (имя_результат.json) + печать.

Использование:
  python pipeline.py <файл.pdf|папка> [--ocr qwen3vl|paddle] [--extract-model qwen2.5:14b]
"""
import argparse
import base64
import json
import os
import re
import sys
import time
import urllib.request

OLLAMA = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
OCR_MODEL = os.environ.get("OCR_MODEL", "qwen3-vl:8b")

OCR_PROMPT = (
    "Ты OCR-система для судебных документов. Распознай ВЕСЬ текст с изображения, "
    "сохраняя структуру строк (каждая строка документа — отдельная строка вывода). "
    "Не додумывай отсутствующий текст."
)

EXTRACT_PROMPT = """Ты — система извлечения структурированных данных из судебных документов (РФ).
Из текста ниже извлеки поля и верни ТОЛЬКО валидный JSON без пояснений, без markdown-обёрток.

Схема ответа (строго):
{{
  "document_type": "судебный приказ|исполнительный лист|решение|определение|другое",
  "case_number": "номер дела",
  "document_date": "дата вынесения",
  "effective_date": "дата вступления в силу",
  "judge": "ФИО судьи",
  "court": {{"name": "...", "address": "..."}},
  "creditor": {{"name": "...", "inn": "...", "address": "..."}},
  "debtor": {{"name": "...", "birth_date": "...", "passport": "...", "inn": "...", "address": "..."}},
  "amounts": {{"principal": 0.0, "penalty": 0.0, "state_duty": 0.0, "total": 0.0}},
  "recipient": {{"bank": "...", "bik": "...", "account": "..."}}
}}

Правила:
- Номер дела сохраняй ТОЧНО (пример: "А40-167933/2023").
- document_date и effective_date — только даты в формате дд.мм.гггг (или "").
- judge — ФИО судьи, если указан (иначе "").
- recipient — банковские реквизиты получателя (банк, БИК, счёт), если указаны (иначе "").
- Суммы — числа в рублях, десятичная точка.
- Если поле отсутствует — "" (строки) или null (числа).
- Адрес ответчика/должника важен — часть составного ключа.
- В решении может быть несколько ответчиков/истцов — бери ПЕРВОГО.
- Не выдумывай данные, которых нет в тексте.

Текст документа:
%s"""

TRANSLATE_PROMPT = """Ты — переводчик судебных документов на русский язык.
Переведи текст ниже на русский, соблюдая правила:
- НЕ переводи: имена людей, названия компаний/организаций/судов, адреса, страны и города.
- Номера дел, даты, суммы и прочие реквизиты оставь без изменений.
- Остальной текст переведи на русский.
- Если текст уже на русском — верни его без изменений.
- Ответь только переводом, без комментариев и пояснений.

Текст:
%s"""


def pdf_to_pngs(path, dpi=140, max_pages=2):
    try:
        import pymupdf as fitz
    except ImportError:
        import fitz
    doc = fitz.open(path)
    out = []
    for i in range(min(len(doc), max_pages)):
        pix = doc[i].get_pixmap(dpi=dpi)
        p = "%s__p%d.png" % (path, i)
        pix.save(p)
        out.append(p)
    return out


def prep_image(png):
    """Ресайз до длинной стороны <=1024px и конвертация в JPEG (лимит qwen3-vl)."""
    from PIL import Image
    im = Image.open(png).convert("RGB")
    im.thumbnail((1024, 1024))
    jpg = png + "_small.jpg"
    im.save(jpg, "JPEG", quality=85)
    return jpg


def ask_ollama(model, prompt, images=None, num_predict=4096, timeout=900):
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"num_predict": num_predict, "temperature": 0.1 if not images else 0.3},
    }
    if images:
        payload["images"] = images
    req = urllib.request.Request(
        OLLAMA + "/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        resp = json.loads(r.read().decode("utf-8"))
    return resp.get("response", "")


def detect_foreign_text(text, min_len=150):
    """
    Определяет, есть ли в тексте заметный иностранный фрагмент.

    Args:
        text (str): Распознанный текст документа
        min_len (int): Минимальная длина текста, при которой имеет смысл проверять

    Returns:
        str: Название языка/письменности ('' — текст русский/смешанный, перевод не нужен)
    """
    t = (text or "").strip()
    if len(t) < min_len:
        return ""
    letters = [ch for ch in t if ch.isalpha()]
    if not letters:
        return ""
    total = float(len(letters))
    cyr = sum(1 for ch in letters if "\u0400" <= ch <= "\u04FF")
    cjk = sum(1 for ch in letters if "\u4E00" <= ch <= "\u9FFF")
    if cjk / total > 0.03:
        return "китайский/иероглифы"
    if cyr / total < 0.7:
        return "латиница (английский/финский и т.п.)"
    return ""


def translate_text(text, model, max_chars=6000):
    """
    Переводит фрагмент текста на русский (имена, названия, реквизиты — без изменений).

    Args:
        text (str): Исходный текст
        model (str): Модель Ollama для перевода
        max_chars (int): Ограничение длины запроса

    Returns:
        str: Перевод на русском (пустая строка, если модель не ответила)
    """
    snippet = text[:max_chars]
    return ask_ollama(model, TRANSLATE_PROMPT % snippet, num_predict=4096, timeout=900).strip()


def pdf_text_layer(path):
    """Возвращает текст из встроенного текстового слоя PDF (если он есть)."""
    try:
        import pymupdf as fitz
    except ImportError:
        import fitz
    doc = fitz.open(path)
    txt = []
    for i in range(min(len(doc), 2)):
        txt.append(doc[i].get_text() or "")
    return "\n".join(txt)


def is_image(path):
    return path.lower().rsplit(".", 1)[-1] in ("jpg", "jpeg", "png", "tif", "tiff", "bmp", "webp")


def ocr_qwen3vl(path):
    lines_all = []
    if is_image(path):
        jpg = prep_image(path)
        with open(jpg, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        lines_all.append(ask_ollama(OCR_MODEL, OCR_PROMPT, images=[b64], num_predict=3072))
        return "\n".join(lines_all)
    for p in pdf_to_pngs(path):
        jpg = prep_image(p)
        with open(jpg, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        lines_all.append(ask_ollama(OCR_MODEL, OCR_PROMPT, images=[b64], num_predict=3072))
    return "\n".join(lines_all)


def ocr_paddle(path):
    os.environ.setdefault("FLAGS_use_mkldnn", "0")
    from paddleocr import PaddleOCR
    ocr = PaddleOCR(use_doc_orientation_classify=False, use_doc_unwarping=False,
                    use_textline_orientation=False, lang="ru")
    lines_all = []
    if is_image(path):
        result = ocr.predict(path)
        for page in result:
            if isinstance(page, dict) and "rec_texts" in page:
                lines_all.append("\n".join(page["rec_texts"]))
        return "\n".join(lines_all)
    for p in pdf_to_pngs(path):
        result = ocr.predict(p)
        for page in result:
            if isinstance(page, dict) and "rec_texts" in page:
                lines_all.append("\n".join(page["rec_texts"]))
    return "\n".join(lines_all)


def extract_json(raw):
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.S)
    if m:
        return json.loads(m.group(1))
    s, e = raw.find("{"), raw.rfind("}")
    if s != -1 and e > s:
        return json.loads(raw[s:e + 1])
    return {"raw": raw[:500]}


def process(pdf, ocr_engine, extract_model):
    name = os.path.basename(pdf)
    print("\n### %s [%s]" % (name, ocr_engine))
    t0 = time.time()
    text = None
    if pdf.lower().endswith(".pdf"):
        layer = pdf_text_layer(pdf)
        if len(layer.strip()) >= 200:
            text = layer
            print("--- в PDF есть текстовый слой (%d символов) — OCR не нужен" % len(text))
    if text is None:
        if ocr_engine == "qwen3vl":
            text = ocr_qwen3vl(pdf)
            if len(text.strip()) < 200:
                print("--- qwen3vl пусто/мало (%d) → fallback Paddle" % len(text.strip()))
                text = ocr_paddle(pdf)
        else:
            text = ocr_paddle(pdf)
        print("--- OCR %d символов за %.1f с" % (len(text), time.time() - t0))

    txt_path = pdf + "_text.txt"
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(text)

    raw = ask_ollama(extract_model, EXTRACT_PROMPT % text, num_predict=1500)
    data = extract_json(raw)
    data["_source"] = name

    # Нормализация распознанных значений (OCR-шум → чистые данные)
    from normalize import inn_checksum_valid, norm_amount, norm_date, norm_inn
    cred = data.get("creditor") or {}
    debt = data.get("debtor") or {}
    if cred.get("inn"):
        cred["inn"] = norm_inn(cred["inn"])
    if debt.get("inn"):
        debt["inn"] = norm_inn(debt["inn"])
    if debt.get("birth_date"):
        debt["birth_date"] = norm_date(debt["birth_date"])
    amt = data.get("amounts") or {}
    for k in ("principal", "penalty", "state_duty", "total"):
        v = norm_amount(amt.get(k)) if amt.get(k) is not None else None
        if v is not None:
            amt[k] = v
    if amt:
        data["amounts"] = amt
    print("--- 🔧 Нормализация ИНН/дат/сумм применена")

    # Контроль качества: сомнительные значения → предупреждения
    warns = []
    for label, dct in (("взыскателя", cred), ("должника", debt)):
        inn = dct.get("inn") or ""
        if inn and not inn_checksum_valid(inn):
            warns.append("ИНН %s (%s) не прошёл контрольную сумму" % (label, inn))
    if amt.get("principal") is None and amt.get("total") is None:
        warns.append("суммы не извлечены")
    if data.get("document_date"):
        data["document_date"] = norm_date(data["document_date"])
    if data.get("effective_date"):
        data["effective_date"] = norm_date(data["effective_date"])
    rcpt = data.get("recipient") or {}
    if rcpt.get("bik"):
        rcpt["bik"] = norm_inn(rcpt["bik"])
    if rcpt.get("account"):
        rcpt["account"] = norm_inn(rcpt["account"])
    if rcpt:
        data["recipient"] = rcpt
    if warns:
        data["warnings"] = warns
        data["suspicious"] = True
        print("--- ⚠️ Сомнительные поля: " + "; ".join(warns))

    # Этап 1.5: перевод на русский, если текст документа явно иностранный
    lang = detect_foreign_text(text)
    if lang:
        print("--- 🌐 Обнаружен иностранный текст (%s) — перевожу на русский…" % lang)
        ru = translate_text(text, extract_model)
        if ru.strip():
            data["translation"] = {"language": lang, "translation_ru": ru.strip()}
            print("--- 🌐 Перевод готов: %d символов" % len(ru.strip()))
        else:
            print("--- 🌐 Модель не дала перевод — пропускаю")

    out_path = pdf + "_result.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print("JSON:", json.dumps({k: v for k, v in data.items() if not k.startswith("_")},
                              ensure_ascii=False)[:600])
    return data


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("target", help="PDF-файл или папка")
    ap.add_argument("--ocr", choices=["qwen3vl", "paddle"], default="qwen3vl")
    ap.add_argument("--extract-model", default=os.environ.get("EXTRACT_MODEL", "qwen2.5:14b"))
    args = ap.parse_args()

    if os.path.isdir(args.target):
        pdfs = []
        for root, _dirs, files in os.walk(args.target):
            for f in sorted(files):
                if f.lower().endswith((".pdf", ".jpg", ".jpeg", ".png", ".tif", ".tiff")):
                    pdfs.append(os.path.join(root, f))
        pdfs.sort()
        print("Найдено документов:", len(pdfs))
    else:
        pdfs = [args.target]

    results = []
    for pdf in pdfs:
        try:
            results.append(process(pdf, args.ocr, args.extract_model))
        except Exception as e:
            print("ERROR %s: %r" % (pdf, e))

    # сводная таблица в JSON
    if results:
        summ = os.path.join(args.target if os.path.isdir(args.target) else os.path.dirname(args.target),
                            "СВОДКА_результатов.json")
        with open(summ, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print("\nСводка сохранена:", summ)


if __name__ == "__main__":
    main()
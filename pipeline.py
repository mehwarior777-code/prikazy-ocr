# -*- coding: utf-8 -*-
"""
pipeline.py — конвейер трека №2: PDF судебного акта → OCR → JSON-извлечение → сводка.

OCR: qwen3-vl:8b (по умолчанию) с fallback на PaddleOCR при пустом/коротком результате.
Извлечение полей: qwen2.5:14b (локально через Ollama).

Использование:
  python pipeline.py <файл.pdf|папка> [--ocr qwen3vl|paddle] [--extract-model qwen2.5:14b]

Результаты рядом с PDF: *_text.txt, *_result.json, СВОДКА_результатов.json.
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
EXTRACT_MODEL_DEF = os.environ.get("EXTRACT_MODEL", "qwen2.5:14b")

OCR_PROMPT = (
    "Ты OCR-система для судебных документов. Распознай ВЕСЬ текст с изображения, "
    "сохраняя структуру строк (каждая строка документа — отдельная строка вывода). "
    "Не додумывай отсутствующий текст."
)

EXTRACT_PROMPT = """Ты — система извлечения структурированных данных из судебных документов (РФ).
Из текста ниже извлеки поля и верни ТОЛЬКО валидный JSON без пояснений, без markdown-обёрток.

Схема ответа (строго):
{{
  "document_type": "судебный приказ|решение|определение|другое",
  "case_number": "номер дела",
  "court": {{"name": "...", "address": "..."}},
  "creditor": {{"name": "...", "inn": "...", "address": "..."}},
  "debtor": {{"name": "...", "birth_date": "...", "passport": "...", "inn": "...", "address": "..."}},
  "amounts": {{"principal": 0.0, "penalty": 0.0, "state_duty": 0.0, "total": 0.0}}
}}

Правила:
- Номер дела сохраняй ТОЧНО (пример: "А40-167933/2023").
- Суммы — числа в рублях, десятичная точка.
- Если поле отсутствует — "" (строки) или null (числа).
- Адрес ответчика/должника важен — часть составного ключа.
- В решении может быть несколько ответчиков/истцов — бери ПЕРВОГО.
- Не выдумывай данные, которых нет в тексте.

Текст документа:
%s"""


def pdf_to_pngs(path, dpi=140, max_pages=2):
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


def ocr_qwen3vl(path):
    lines_all = []
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
    ap.add_argument("--extract-model", default=EXTRACT_MODEL_DEF)
    args = ap.parse_args()

    if os.path.isdir(args.target):
        pdfs = sorted(f for f in os.listdir(args.target) if f.lower().endswith(".pdf"))
        pdfs = [os.path.join(args.target, f) for f in pdfs]
        print("Найдено PDF:", len(pdfs))
    else:
        pdfs = [args.target]

    results = []
    for pdf in pdfs:
        try:
            results.append(process(pdf, args.ocr, args.extract_model))
        except Exception as e:
            print("ERROR %s: %r" % (pdf, e))

    if results:
        summ = os.path.join(args.target if os.path.isdir(args.target) else os.path.dirname(args.target),
                            "СВОДКА_результатов.json")
        with open(summ, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print("\nСводка сохранена:", summ)


if __name__ == "__main__":
    main()
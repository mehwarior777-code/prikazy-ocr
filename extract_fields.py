# -*- coding: utf-8 -*-
"""
extract_fields.py — извлечение структурированных полей из текста судебного документа
через локальную Ollama (qwen2.5). Возвращает строгий JSON.

Использование:
  python extract_fields.py <файл-с-текстом> [--model qwen2.5:14b] [--base http://127.0.0.1:11434]
"""
import argparse
import json
import re
import sys
import urllib.request

PROMPT_TEMPLATE = """Ты — система извлечения структурированных данных из судебных документов (РФ).
Из текста ниже извлеки поля и верни ТОЛЬКО валидный JSON без пояснений, без ```markdown-обёрток.

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
- Номер дела сохраняй ТОЧНО, включая скобки и слэши (пример: "2-456(86)/2020").
- Суммы — числа в рублях, десятичная точка, без пробелов и "руб.".
- Если поле отсутствует в тексте — ставь "" (для строк) или null (для чисел).
- Адрес должника ОБЯЗАТЕЛЕН и важен — это часть составного ключа документа.
- Не выдумывай данные, которых нет в тексте.

Текст документа:
%s"""


def extract_json(raw):
    """Два прохода: сначала ```json-блок, потом самый большой {...}."""
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.S)
    if m:
        return json.loads(m.group(1))
    start, end = raw.find("{"), raw.rfind("}")
    if start != -1 and end > start:
        return json.loads(raw[start:end + 1])
    raise ValueError("JSON не найден в ответе модели")


def ask_ollama(model, prompt, base, num_predict=1500):
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"num_predict": num_predict, "temperature": 0.1},
    }
    req = urllib.request.Request(
        base.rstrip("/") + "/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=900) as r:
        resp = json.loads(r.read().decode("utf-8"))
    return resp.get("response", "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file", help="путь к файлу с текстом документа")
    ap.add_argument("--model", default="qwen2.5:14b")
    ap.add_argument("--base", default="http://127.0.0.1:11434")
    ap.add_argument("--raw", action="store_true", help="показать сырой ответ модели")
    args = ap.parse_args()

    with open(args.file, encoding="utf-8") as f:
        text = f.read().strip()

    prompt = PROMPT_TEMPLATE % text
    raw = ask_ollama(args.model, prompt, args.base)
    if args.raw:
        print("RAW:", raw)
        return
    try:
        data = extract_json(raw)
        print(json.dumps(data, ensure_ascii=False, indent=2))
    except Exception as e:
        print("PARSE_ERR:", repr(e))
        print("RAW:", raw[:2000])
        sys.exit(1)


if __name__ == "__main__":
    main()
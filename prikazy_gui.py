# -*- coding: utf-8 -*-
"""
prikazy_gui.py — GUI-прототип трека №2 (хакатон): PDF судебного акта → OCR → JSON → Excel.

Окно tkinter:
  - выбор PDF-файла или папки;
  - живой лог процесса (построчно из pipeline.py);
  - таблица результатов (номер дела, суд, взыскатель, должник, суммы);
  - кнопки: открыть Excel, открыть папку результатов.

Запуск: pythonw prikazy_gui.py   (без консоли, только окно)
"""
import io
import json
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# --- пути окружения ---
PYTHON = os.environ.get("PYTHON_EXE") or sys.executable
BASE = os.path.dirname(os.path.abspath(__file__))
PIPELINE = os.path.join(BASE, "pipeline.py")
EXCEL = os.path.join(BASE, "документы_судов.xlsx")
DEFAULT_TARGET = os.environ.get("DEFAULT_DIR") or BASE

FOLDER_KEY = "папка"
FILE_KEY = "файл"

# --- тёмная тема: палитра ---
BG = "#1e1e1e"          # фон окна
BG_PANEL = "#252526"    # панели, заголовки, кнопки
BG_FIELD = "#2d2d30"    # поля ввода, таблица
FG = "#e8e8e8"          # основной текст
ACCENT = "#0e639c"      # акцент
ACCENT_ACTIVE = "#1177bb"
SELECT = "#094771"      # выделенная строка таблицы
BORDER = "#3f3f46"


def apply_dark_theme(root):
    """Переводит всё окно (ttk + tk) в тёмную тему."""
    root.configure(bg=BG)
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    style.configure(".", background=BG, foreground=FG, fieldbackground=BG_FIELD,
                    bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER,
                    troughcolor=BG, focuscolor=ACCENT)
    style.configure("TFrame", background=BG)
    style.configure("TLabel", background=BG, foreground=FG)
    style.configure("TLabelframe", background=BG, foreground=FG, bordercolor=BORDER)
    style.configure("TLabelframe.Label", background=BG, foreground=FG)
    style.configure("TButton", background=BG_PANEL, foreground=FG, bordercolor=BORDER,
                    padding=(8, 3))
    style.map("TButton",
              background=[("pressed", ACCENT), ("active", ACCENT_ACTIVE)],
              foreground=[("pressed", "#ffffff"), ("active", "#ffffff")])
    style.configure("TRadiobutton", background=BG, foreground=FG, focuscolor=BG)
    style.map("TRadiobutton", background=[("active", BG)])
    style.configure("TEntry", fieldbackground=BG_FIELD, foreground=FG,
                    insertcolor=FG, bordercolor=BORDER)
    style.map("TEntry", bordercolor=[("focus", ACCENT)])
    style.configure("Treeview", background=BG_FIELD, fieldbackground=BG_FIELD,
                    foreground=FG, bordercolor=BG, rowheight=22)
    style.map("Treeview", background=[("selected", SELECT)],
              foreground=[("selected", "#ffffff")])
    style.configure("Treeview.Heading", background=BG_PANEL, foreground=FG,
                    relief="flat", bordercolor=BORDER, padding=(4, 3))
    style.map("Treeview.Heading", background=[("active", BG_FIELD)])
    style.configure("Vertical.TScrollbar", background=BG_PANEL, troughcolor=BG,
                    bordercolor=BG, arrowcolor=FG, relief="flat")
    style.configure("Horizontal.TScrollbar", background=BG_PANEL, troughcolor=BG,
                    bordercolor=BG, arrowcolor=FG, relief="flat")
    style.configure("StatusOk.TLabel", background=BG, foreground="#6ccb5f")
    style.configure("StatusBusy.TLabel", background=BG, foreground="#e5c07b")
    style.configure("StatusErr.TLabel", background=BG, foreground="#e06c75")


def apply_light_theme(root):
    """Переводит всё окно обратно в светлую системную тему."""
    root.configure(bg="SystemButtonFace")
    style = ttk.Style(root)
    try:
        if "vista" in style.theme_names():
            style.theme_use("vista")
        else:
            style.theme_use("default")
    except tk.TclError:
        pass
    btn = "SystemButtonFace"
    fg = "SystemButtonText"
    win = "SystemWindow"
    winfg = "SystemWindowText"
    style.configure(".", background=btn, foreground=fg, fieldbackground=win,
                    troughcolor=btn, bordercolor="#d0d0d0",
                    lightcolor="#d0d0d0", darkcolor="#d0d0d0")
    style.configure("TFrame", background=btn)
    style.configure("TLabel", background=btn, foreground=fg)
    style.configure("TLabelframe", background=btn, foreground=fg)
    style.configure("TLabelframe.Label", background=btn, foreground=fg)
    style.configure("TButton", background=btn, foreground=fg)
    style.map("TButton", background=[("pressed", btn), ("active", "#e5f1fb")],
              foreground=[("pressed", fg), ("active", fg)])
    style.configure("TRadiobutton", background=btn, foreground=fg)
    style.map("TRadiobutton", background=[("active", btn)])
    style.configure("TEntry", fieldbackground=win, foreground=winfg, insertcolor=winfg)
    style.configure("Treeview", background=win, fieldbackground=win,
                    foreground=winfg, rowheight=22)
    style.map("Treeview", background=[("selected", "#cce4f7")],
              foreground=[("selected", winfg)])
    style.configure("Treeview.Heading", background=btn, foreground=fg, relief="raised")
    style.map("Treeview.Heading", background=[("active", "#e5f1fb")])
    style.configure("Vertical.TScrollbar", background=btn, troughcolor=btn, arrowcolor=fg)
    style.configure("Horizontal.TScrollbar", background=btn, troughcolor=btn, arrowcolor=fg)
    style.configure("StatusOk.TLabel", background=btn, foreground="#1a7f37")
    style.configure("StatusBusy.TLabel", background=btn, foreground="#9a6700")
    style.configure("StatusErr.TLabel", background=btn, foreground="#cf222e")


class ToolTip:
    """Всплывающая подсказка: появляется, только если курсор замер на месте (0.7 с)."""

    DELAY_MS = 700

    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tip = None
        self.after_id = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._cancel, add="+")
        widget.bind("<ButtonPress>", self._cancel, add="+")

    def _schedule(self, _e=None):
        self._cancel_hide()
        if self.tip is None and self.after_id is None:
            self.after_id = self.widget.after(self.DELAY_MS, self._show)

    def _cancel(self, _e=None):
        self._cancel_hide()
        self._hide()

    def _cancel_hide(self):
        if self.after_id is not None:
            try:
                self.widget.after_cancel(self.after_id)
            except Exception:
                pass
            self.after_id = None

    def _show(self, _e=None):
        if self.tip is not None:
            return
        x = self.widget.winfo_rootx() + 14
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry("+%d+%d" % (x, y))
        tk.Label(self.tip, text=self.text, justify="left",
                 bg="#ffffe1", fg="#1a1a1a", relief="solid", borderwidth=1,
                 font=("Segoe UI", 9), padx=7, pady=4).pack()

    def _hide(self, _e=None):
        if self.tip is not None:
            self.tip.destroy()
            self.tip = None


class PrikazyApp:
    """Главное окно приложения."""

    def __init__(self, root):
        self.root = root
        self.q = queue.Queue()
        self.proc = None
        self.folder_mode = tk.StringVar(value=FILE_KEY)
        self.target = tk.StringVar(value=self._load_default_dir())
        self.default_dir = self.target.get()
        self.dark = True  # текущая тема: True — тёмная, False — светлая
        self._started_at = 0.0
        self._bytes_read = 0
        self._lines_read = 0
        self._last_tick = 0.0

        root.title("Prikazy OCR — прототип (хакатон, трек №2)")
        root.geometry("1020x680")
        root.minsize(900, 560)

        self._build_top()
        self._build_log()
        self._build_table()
        self._build_status()

        self.log("🟢 Приложение запущено. Выбери PDF-файл или папку с PDF и нажми «▶ Запустить».")
        self.log("📂 Папка по умолчанию: %s" % self.target.get())
        self.log("   Смени на свою через «Обзор…» и нажми «📌 По умолчанию» — запомнится между запусками")
        self.root.after(100, self._pump)

    # ---------- интерфейс ----------
    def _build_top(self):
        frm = ttk.Frame(self.root, padding=6)
        frm.pack(fill="x")
        ttk.Label(frm, text="Цель обработки:").pack(side="left")
        ttk.Radiobutton(frm, text="Папка", value=FOLDER_KEY, variable=self.folder_mode).pack(side="left", padx=4)
        ttk.Radiobutton(frm, text="Файл", value=FILE_KEY, variable=self.folder_mode).pack(side="left", padx=4)
        ent = ttk.Entry(frm, textvariable=self.target, width=72)
        ent.pack(side="left", padx=6)
        ToolTip(ent, "Папка/файл по умолчанию — откуда берутся дела.\nВыбери другой путь через «Обзор…» и нажми «📌 По умолчанию»")
        b_browse = ttk.Button(frm, text="Обзор…", command=self._browse)
        b_browse.pack(side="left")
        ToolTip(b_browse, "Выбрать PDF-файл или папку с делами")
        b_def = ttk.Button(frm, text="📌 По умолчанию", command=self._set_default_dir)
        b_def.pack(side="left", padx=4)
        ToolTip(b_def, "Запомнить этот путь как папку по умолчанию (сохранится между запусками)")
        b_start = ttk.Button(frm, text="▶ Запустить", command=self._start)
        b_start.pack(side="left", padx=8)
        ToolTip(b_start, "Запустить распознавание и обработку")
        b_stop = ttk.Button(frm, text="⏹ Стоп", command=self._stop)
        b_stop.pack(side="left")
        ToolTip(b_stop, "Прервать обработку")
        self.theme_btn = ttk.Button(frm, text="☀️ Светлая", command=self._toggle_theme)
        self.theme_btn.pack(side="right", padx=4)
        ToolTip(self.theme_btn, "Переключить тему: тёмная ↔ светлая")

    def _build_log(self):
        lbl = ttk.LabelFrame(self.root, text="Живой лог процесса (PDF → OCR → JSON)")
        lbl.pack(fill="both", expand=False, padx=6, pady=2)
        self.txt = tk.Text(lbl, height=12, wrap="word", state="disabled",
                           font=("Consolas", 9), bg="#111111", fg="#e8e8e8")
        sb = ttk.Scrollbar(lbl, command=self.txt.yview)
        self.txt.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.txt.pack(side="left", fill="both", expand=True)
        self.log_menu = tk.Menu(self.root, tearoff=0, bg=BG_PANEL, fg=FG,
                                activebackground=ACCENT_ACTIVE, activeforeground="#ffffff",
                                selectcolor=ACCENT)
        self.log_menu.add_command(label="Копировать", command=self._copy_log)
        self.log_menu.add_command(label="Выделить всё", command=self._select_all_log)
        self.log_menu.add_separator()
        self.log_menu.add_command(label="Очистить лог", command=self._clear_log)
        self.txt.bind("<Button-3>", self._show_log_menu)
        self.txt.bind("<Control-c>", lambda e: (self._copy_log(), "break")[1])

    def _build_table(self):
        lbl = ttk.LabelFrame(self.root, text="Результаты (карточки дел)")
        lbl.pack(fill="both", expand=True, padx=6, pady=2)
        cols = ("case", "type", "date", "court", "creditor", "debtor", "addr", "inn", "amount", "status")
        self.tree = ttk.Treeview(lbl, columns=cols, show="headings", height=8)
        heads = {
            "case": ("Номер дела", 150),
            "type": ("Тип", 80),
            "date": ("Дата", 90),
            "court": ("Суд", 180),
            "creditor": ("Взыскатель", 190),
            "debtor": ("Должник", 190),
            "addr": ("Адрес должника", 220),
            "inn": ("ИНН должника", 110),
            "amount": ("Сумма, ₽", 110),
            "status": ("Статус", 70),
        }
        for c, (t, w) in heads.items():
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor="w")
        sb = ttk.Scrollbar(lbl, command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        # настраиваемые колонки (ПКМ по таблице — как в MetaTrader)
        self.col_vars = {}
        self.col_menu = tk.Menu(self.root, tearoff=0, bg=BG_PANEL, fg=FG,
                                activebackground=ACCENT_ACTIVE, activeforeground="#ffffff",
                                selectcolor=ACCENT)
        for c, (t, _w) in heads.items():
            var = tk.BooleanVar(value=True)
            self.col_vars[c] = var
            self.col_menu.add_checkbutton(label=t, variable=var, command=self._apply_cols)
        self.tree.bind("<Button-3>", self._show_col_menu)
        self._load_col_config()

        bar = ttk.Frame(lbl)
        bar.pack(fill="x")
        b_excel = ttk.Button(bar, text="📊 Таблица (Excel)", command=self._open_excel)
        b_excel.pack(side="left", padx=4, pady=2)
        ToolTip(b_excel, "Открыть итоговую таблицу документы_судов.xlsx")
        b_dir = ttk.Button(bar, text="📁 Папка с файлами", command=self._open_folder)
        b_dir.pack(side="left", padx=4)
        ToolTip(b_dir, "Открыть папку с результатами обработки")
        self.tree.bind("<Double-1>", self._show_card)

    def _build_status(self):
        self.status = ttk.Label(self.root, text="Готов к работе", style="StatusOk.TLabel", relief="sunken", anchor="w")
        self.status.pack(fill="x", padx=6, pady=3)

    # ---------- тема ----------
    def _toggle_theme(self):
        self.dark = not self.dark
        if self.dark:
            apply_dark_theme(self.root)
        else:
            apply_light_theme(self.root)
        self._repaint_widgets()
        self.theme_btn.configure(text="☀️ Светлая" if self.dark else "🌙 Тёмная")

    def _repaint_widgets(self):
        """Перекрашивает tk-виджеты, которые ttk-стили не трогают."""
        if self.dark:
            self.txt.configure(bg="#111111", fg="#e8e8e8")
            mbg, mfg, mac = BG_PANEL, FG, ACCENT_ACTIVE
        else:
            self.txt.configure(bg="#ffffff", fg="#111111")
            mbg, mfg, mac = "SystemButtonFace", "SystemButtonText", "#0078d7"
        for menu in (self.log_menu, self.col_menu):
            menu.configure(bg=mbg, fg=mfg, activebackground=mac,
                           activeforeground="#ffffff", selectcolor=mac)

    # ---------- настройка колонок ----------
    def _col_config_path(self):
        return os.path.join(BASE, "gui_config.json")

    def _apply_cols(self):
        cols = ("case", "type", "date", "court", "creditor", "debtor", "addr", "inn", "amount", "status")
        visible = [c for c in cols if self.col_vars.get(c) and self.col_vars[c].get()]
        if not visible:
            self.col_vars["case"].set(True)
            visible = ["case"]
        self.tree.configure(displaycolumns=tuple(visible))
        self._save_config()

    def _read_config(self):
        try:
            with io.open(self._col_config_path(), "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and "cols" in data:
                return data
            # старый формат (плоский dict колонок) — конвертируем
            return {"cols": data or {}, "default_dir": ""}
        except Exception:
            return {}

    def _save_config(self):
        try:
            data = {
                "cols": {c: v.get() for c, v in self.col_vars.items()},
                "default_dir": getattr(self, "default_dir", "") or "",
            }
            with io.open(self._col_config_path(), "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _load_default_dir(self):
        """Папка по умолчанию из gui_config.json; если её нет/удалена — DEFAULT_TARGET."""
        cfg = self._read_config()
        d = cfg.get("default_dir")
        if d and os.path.exists(d):
            return d
        return DEFAULT_TARGET

    def _set_default_dir(self):
        """Запоминает текущий путь как папку по умолчанию; файл → предупреждение."""
        p = self.target.get().strip()
        if not p:
            messagebox.showinfo("Prikazy OCR", "Сначала укажи путь в поле цели (кнопка «Обзор…»).")
            return
        if os.path.isfile(p):
            folder = os.path.dirname(p) or p
            keep = messagebox.askyesno(
                "Prikazy OCR",
                "В поле указан ФАЙЛ:\n%s\n\nЕсли сохранить его как путь по умолчанию, "
                "то при удалении этого файла путь перестанет работать.\n\n"
                "Сохранить вместо него папку файла?\n%s" % (p, folder))
            if keep:
                p = folder
                self.target.set(p)
        self.default_dir = p
        self._save_config()
        self.log("📌 Папка по умолчанию сохранена: " + p)
        self.status.configure(text="📌 Папка по умолчанию: " + p)

    def _load_col_config(self):
        cfg = self._read_config()
        cols = cfg.get("cols") or {}
        for c, v in cols.items():
            if c in self.col_vars:
                self.col_vars[c].set(bool(v))
        self._apply_cols()
        d = cfg.get("default_dir")
        if d and os.path.exists(d):
            self.default_dir = d
            self.target.set(d)

    def _show_col_menu(self, e):
        try:
            self.col_menu.tk_popup(e.x_root, e.y_root)
        finally:
            self.col_menu.grab_release()

# ---------- действия ----------
    def log(self, msg):
        self.txt.configure(state="normal")
        self.txt.insert("end", msg + "\n")
        self.txt.see("end")
        self.txt.configure(state="disabled")

    def _copy_log(self):
        try:
            sel = self.txt.get("sel.first", "sel.last")
        except tk.TclError:
            return
        if sel:
            self.root.clipboard_clear()
            self.root.clipboard_append(sel)

    def _select_all_log(self):
        self.txt.configure(state="normal")
        self.txt.tag_add("sel", "1.0", "end")
        self.txt.configure(state="disabled")

    def _clear_log(self):
        self.txt.configure(state="normal")
        self.txt.delete("1.0", "end")
        self.txt.configure(state="disabled")

    def _show_log_menu(self, e):
        try:
            self.log_menu.tk_popup(e.x_root, e.y_root)
        finally:
            self.log_menu.grab_release()

    def _browse(self):
        cur = self.target.get().strip()
        if os.path.isfile(cur):
            start = os.path.dirname(cur)
        elif os.path.isdir(cur):
            start = cur
        else:
            start = DEFAULT_TARGET
        if self.folder_mode.get() == FOLDER_KEY:
            p = filedialog.askdirectory(initialdir=start, title="Папка с PDF")
        else:
            p = filedialog.askopenfilename(
                initialdir=start, title="PDF-файл",
                filetypes=[("Документы", "*.pdf *.jpg *.jpeg *.png *.tif *.tiff"), ("PDF", "*.pdf"), ("Все файлы", "*.*")])
        if p:
            self.target.set(p)

    def _start(self):
        if self.proc is not None:
            self.log("⏳ Обработка уже идёт — дождись окончания.")
            return
        target = self.target.get().strip()
        if not target or not os.path.exists(target):
            messagebox.showerror("Prikazy OCR", "Укажи существующий файл или папку с PDF.")
            return
        self.default_dir = target if os.path.isdir(target) else os.path.dirname(target) or target
        self._save_config()
        self.tree.delete(*self.tree.get_children())
        self.status.configure(text="⏳ Обработка…", style="StatusBusy.TLabel")
        self._started_at = time.time()
        self._last_tick = 0.0
        self.log("▶ Старт: %s" % target)
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        env["PYTHONWARNINGS"] = "ignore"
        self.proc = subprocess.Popen(
            [PYTHON, "-u", PIPELINE, target],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", env=env,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
        threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self):
        warned = False
        for line in self.proc.stdout:
            self._bytes_read += len(line.encode("utf-8", "replace"))
            self._lines_read += 1
            if line.startswith("warning:") or "API is deprecated" in line:
                if not warned:
                    warned = True
                    self.q.put("ℹ️ (служебное сообщение библиотеки — не влияет на результат)")
                continue
            self.q.put(line.rstrip())
        self.proc.wait()
        self.q.put(None)

    def _stop(self):
        if self.proc is not None and self.proc.poll() is None:
            self.proc.kill()
            self.log("⏹ Остановлено пользователем.")
            self.status.configure(text="⏹ Остановлено", style="StatusErr.TLabel")

    def _show_card(self, _e):
        sel = self.tree.selection()
        if not sel:
            return
        card = getattr(self, "_cards", {}).get(sel[0])
        if card is None:
            return
        win = tk.Toplevel(self.root)
        win.title("Карточка дела — " + str(card.get("case_number") or "—"))
        win.geometry("640x520")
        win.configure(bg=BG if self.dark else "SystemButtonFace")
        tbg, tfg = ("#111111", "#e8e8e8") if self.dark else ("#ffffff", "#111111")
        txt = tk.Text(win, wrap="word", state="disabled",
                      font=("Consolas", 10), bg=tbg, fg=tfg)
        txt.pack(fill="both", expand=True, padx=6, pady=6)
        txt.configure(state="normal")
        txt.insert("1.0", json.dumps({k: v for k, v in card.items() if k != "_source"},
                                     ensure_ascii=False, indent=2))
        txt.configure(state="disabled")
        btns = ttk.Frame(win)
        btns.pack(fill="x", padx=6, pady=4)
        ttk.Button(btns, text="📋 Копировать карточку",
                   command=lambda: (win.clipboard_clear(),
                                    win.clipboard_append(json.dumps(card, ensure_ascii=False, indent=2)))).pack(side="left")
        ttk.Button(btns, text="Закрыть", command=win.destroy).pack(side="right")

    def _open_excel(self):
        if os.path.exists(EXCEL):
            os.startfile(EXCEL)
            self.log("📊 Открыт Excel: " + EXCEL)
        else:
            messagebox.showinfo("Prikazy OCR", "Excel ещё не создан.\nСначала запусти обработку папки с делами.")

    def _open_folder(self):
        os.startfile(BASE)

    # ---------- цикл обновления ----------
    def _pump(self):
        try:
            while True:
                item = self.q.get_nowait()
                if item is None:
                    self._done()
                elif item:
                    self.log(item)
        except queue.Empty:
            pass
        self._update_progress()
        self.root.after(100, self._pump)

    def _update_progress(self):
        if self.proc is None or self.proc.poll() is not None:
            return
        now = time.time()
        if now - self._last_tick < 0.5:
            return
        self._last_tick = now
        secs = int(now - self._started_at)
        kb = self._bytes_read / 1024.0
        self.status.configure(
            text="⏳ Обработка… %d с • лог %d строк • %.1f КБ" % (secs, self._lines_read, kb),
            style="StatusBusy.TLabel")

    def _done(self):
        self.proc = None
        self.status.configure(text="✅ Обработка завершена", style="StatusOk.TLabel")
        self.log("✅ Процесс завершился. Загружаю карточки…")
        self._load_cards()

    def _load_cards(self):
        base = self.target.get().strip()
        summary = os.path.join(base if os.path.isdir(base) else os.path.dirname(base),
                               "СВОДКА_результатов.json")
        if not os.path.exists(summary):
            base2 = os.path.join(BASE, "СВОДКА_результатов.json")
            if os.path.exists(base2):
                summary = base2
            else:
                self.log("⚠️ Сводка не найдена: " + summary)
                return
        try:
            with open(summary, "r", encoding="utf-8") as f:
                rows = json.load(f)
        except Exception as e:
            self.log("❌ Не удалось прочитать сводку: %r" % e)
            return
        self._cards = {}
        for r in rows:
            case = r.get("case_number") or "—"
            dtype = r.get("document_type") or ""
            ddate = r.get("document_date") or ""
            court = (r.get("court") or {}).get("name") or ""
            cred = (r.get("creditor") or {}).get("name") or ""
            debt = (r.get("debtor") or {}).get("name") or ""
            addr = (r.get("debtor") or {}).get("address") or ""
            inn = (r.get("debtor") or {}).get("inn") or ""
            amt = r.get("amounts") or {}
            total = amt.get("total")
            total_s = ("%.2f" % total) if total is not None else "—"
            status = "⚠️" if r.get("suspicious") else ("🌐" if r.get("translation") else "✅")
            iid = self.tree.insert("", "end", values=(case, dtype, ddate, court, cred, debt, addr, inn, total_s, status))
            self._cards[iid] = r
        self.log("📋 Карточек загружено: %d" % len(rows))
        bad = sum(1 for r in rows if r.get("suspicious"))
        if bad:
            self.log("⚠️ %d карточек с сомнительными полями — открой карточку и сверь по скану" % bad)
            self.status.configure(text="⚠️ %d сомнительных — проверь вручную" % bad,
                                  style="StatusErr.TLabel")
        else:
            self.status.configure(text="✅ Готово: %d карточек" % len(rows),
                                  style="StatusOk.TLabel")


def main():
    root = tk.Tk()
    apply_dark_theme(root)
    app = PrikazyApp(root)
    if len(sys.argv) > 1:
        f = os.path.abspath(sys.argv[1])
        if os.path.isfile(f) and f.lower().endswith(".pdf"):
            app.target.set(f)
            app.folder_mode.set(FILE_KEY)
            app.log("📎 Получен файл из «Открыть с помощью»: " + f)
            app.log("▶ Нажми «Запустить», чтобы обработать этот PDF.")
    root.mainloop()


if __name__ == "__main__":
    main()
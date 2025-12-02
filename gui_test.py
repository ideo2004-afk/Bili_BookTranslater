#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# AI Book Translator v6.5

import sys, os, json, shutil, subprocess, time, datetime, re, threading, signal
from pathlib import Path
from typing import Optional, List, Tuple

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QLabel,
    QFileDialog, QTableWidget, QTableWidgetItem, QMessageBox,
    QAbstractItemView, QHeaderView, QDialog, QFormLayout, QLineEdit,
    QCheckBox, QComboBox, QDoubleSpinBox, QSpinBox, QDialogButtonBox,
    QToolBar, QStyle, QPushButton, QHBoxLayout, QTextEdit, QSplitter,
    QGroupBox, QSizePolicy, QMenu, QStatusBar, QToolButton, QListWidget, QListWidgetItem, QProgressBar
)
from PySide6.QtCore import Qt, QThread, Signal, QSize, QTimer, QSettings, QPoint
from PySide6.QtGui import QAction, QIcon, QDesktopServices
from PySide6.QtCore import QUrl

from book_maker.utils import LANGUAGES

if getattr(sys, 'frozen', False):
    # PyInstaller 打包後的資源路徑
    APP_DIR = Path(sys._MEIPASS)
else:
    APP_DIR = Path(__file__).resolve().parent
CONFIG_PATH = APP_DIR / "config.json"
ICONS_DIR = APP_DIR / "icons"
ACCEPT_SUFFIX = {".epub", ".txt", ".srt"}
ROLE_ORIGIN_NAME = Qt.UserRole + 1
ROLE_ORIGIN_PATH = Qt.UserRole + 2

def guess_backend_dir(app_dir: Path) -> Path:
    """尋找包含 make_book.py 的 backend 目錄"""
    # 首先檢查環境變數
    env_p = os.environ.get("BILI_BACKEND_DIR")
    if env_p:
        p = Path(env_p).expanduser().resolve()
        if (p / "make_book.py").exists():
            return p
    # 檢查當前目錄（app_dir）是否包含 make_book.py
    if (app_dir / "make_book.py").exists():
        return app_dir.resolve()
    # 檢查常見的子目錄結構
    for c in [app_dir / "bilingual_book_maker", app_dir.parent / "bilingual_book_maker"]:
        if (c / "make_book.py").exists():
            return c.resolve()
    # 默認返回當前目錄（即使找不到，也返回一個有效路徑）
    return app_dir.resolve()

def load_config(defaults: dict) -> dict:
    if CONFIG_PATH.exists():
        try:
            d = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            defaults.update(d)
        except Exception:
            pass
    return defaults

def save_config(cfg: dict):
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")

def list_ollama_models() -> List[str]:
    try:
        res = subprocess.run(["ollama", "list"], capture_output=True, text=True, check=False)
        if res.returncode != 0 or not res.stdout:
            return []
        lines = [l.strip() for l in res.stdout.splitlines() if l.strip()]
        if lines and lines[0].lower().startswith("name"):
            lines = lines[1:]
        models, seen = [], set()
        for ln in lines:
            name = ln.split()[0]
            if name and name not in seen:
                seen.add(name); models.append(name)
        return models
    except Exception:
        return []

class Worker(QThread):
    stdout_line = Signal(str)
    stderr_line = Signal(str)
    done = Signal(int, str)

    def __init__(self, cmd: str, cwd: str, env: dict = None):
        super().__init__()
        self.cmd = cmd; self.cwd = cwd
        self.env = env if env is not None else os.environ.copy()
        self._proc: Optional[subprocess.Popen] = None
        self._pgid: Optional[int] = None
        self._user_cancelled = False

    def _pump_stream(self, stream, is_err: bool, logfile_handle):
        # Read character by character to handle \r correctly
        # This is less efficient but necessary for tqdm progress bars
        # Alternatively, we can read chunks and split by \r or \n
        
        # Better approach for GUI: read lines but treat \r as newline
        # However, iter(stream.readline, '') relies on universal_newlines=True which handles \n
        # But tqdm uses \r to update the same line.
        
        while True:
            # Read a line. If universal_newlines=True, this might buffer until \n
            # We need to ensure we get updates even if there's no \n (just \r)
            # But subprocess with text=True usually buffers lines.
            
            # Let's try reading raw characters if we want real-time \r updates
            # But that's complex. 
            # Let's stick to readline but maybe check if we can force unbuffered?
            # bufsize=1 means line buffered.
            
            line = stream.readline()
            if not line:
                break
                
            # Handle \r splitting manually if multiple updates came in one read
            parts = line.split('\r')
            for part in parts:
                if not part: continue
                clean_line = part.strip()
                if not clean_line: continue
                
                if is_err:
                    self.stderr_line.emit(clean_line)
                else:
                    self.stdout_line.emit(clean_line)

    def run(self):
        try:
            # ★ 新的 process group，之後可對整組送 SIGINT（等同 Ctrl+C）
            self._proc = subprocess.Popen(
                self.cmd, cwd=self.cwd, shell=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, bufsize=1, universal_newlines=True,
                preexec_fn=os.setsid,  # macOS/Unix
                env=self.env  # Pass environment variables
            )
            try:
                self._pgid = os.getpgid(self._proc.pid)
            except Exception:
                self._pgid = None

            threads = []
            if self._proc.stdout:
                t_out = threading.Thread(target=self._pump_stream, args=(self._proc.stdout, False, None), daemon=True)
                threads.append(t_out); t_out.start()
            if self._proc.stderr:
                t_err = threading.Thread(target=self._pump_stream, args=(self._proc.stderr, True, None), daemon=True)
                threads.append(t_err); t_err.start()
            for t in threads: t.join()
            self._proc.wait()
            rc = self._proc.returncode or 0
            
            # 判斷是否為使用者手動停止或系統中斷
            # Unix: -2 (SIGINT), Python: 130 (128+2)
            if self._user_cancelled or rc == -2 or rc == 130:
                self.done.emit(rc, "已停止 🛑")
            else:
                self.done.emit(rc, "完成 ✅" if rc==0 else f"失敗（code={rc}）")
        except Exception as e:
            self.done.emit(1, f"錯誤：{e}")

    def terminate_job(self):
        """只送 SIGINT（Ctrl+C），交由 bilingual 自己處理暫存與收尾。"""
        if not self._proc or self._proc.poll() is not None:
            return
        self._user_cancelled = True
        try:
            if self._pgid is not None:
                os.killpg(self._pgid, signal.SIGINT)  # Ctrl+C
            else:
                self._proc.send_signal(signal.SIGINT)
        except Exception:
            pass

class SettingsWidget(QWidget):
    def __init__(self, cfg: dict, backend_dir: Path, parent=None):
        super().__init__(parent)
        self.cfg = cfg.copy()
        self.backend_dir = backend_dir
        
        # Main Layout
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(24, 24, 24, 24)
        main_layout.setSpacing(20)
        
        # Title
        lbl_title = QLabel("設定")
        lbl_title.setStyleSheet("font-size: 24px; font-weight: bold; color: #f4f4f5;")
        main_layout.addWidget(lbl_title)
        
        # Scroll Area for settings form
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("background-color: transparent;")
        
        content_widget = QWidget()
        content_widget.setStyleSheet("background-color: transparent;")
        self.layout = QVBoxLayout(content_widget)
        self.layout.setSpacing(16)
        
        # --- Group 1: 模型設定 ---
        grp_model = QGroupBox("模型設定")
        form_model = QFormLayout(grp_model)
        form_model.setLabelAlignment(Qt.AlignRight)
        
        self.model_combo = QComboBox(); self.model_combo.setEditable(True)
        
        # 1. 加入 Ollama 模型
        ollama_models = list_ollama_models()
        if ollama_models:
            self.model_combo.addItems(ollama_models)
            self.model_combo.insertSeparator(len(ollama_models))
            
        # 2. 加入雲端模型 (Gemini, OpenAI)
        cloud_models = ["gemini-2.5-pro", "gemini-3-pro-preview", "gpt-4o", "gpt-4-turbo", "gpt-3.5-turbo"]
        self.model_combo.addItems(cloud_models)
        
        # 設定預設值
        current_model = self.cfg.get("ollama_model")
        if not current_model or current_model == "qwen3:8b": 
             if self.cfg.get("model") == "gemini":
                 current_model = "gemini-3-pro-preview"
             elif self.cfg.get("model") == "chatgptapi" and not self.cfg.get("ollama_model"):
                 current_model = "gpt-4o"
             elif ollama_models:
                 current_model = ollama_models[0]
             else:
                 current_model = "gemini-3-pro-preview"

        self.model_combo.setCurrentText(current_model)
            
        self.lang = QComboBox(); self.lang.setEditable(False)
        self.lang_map = {
            "繁體中文": "zh-hant", "英文": "en", "日文": "ja", "韓文": "ko",
            "法文": "fr", "西班牙文": "es", "德文": "de", "義大利文": "it"
        }
        self.lang.addItems(list(self.lang_map.keys()))
        
        current_code = self.cfg.get("language", "zh-hant")
        default_display = "繁體中文"
        for name, code in self.lang_map.items():
            if code == current_code:
                default_display = name; break
        self.lang.setCurrentText(default_display)

        self.temp = QDoubleSpinBox(); self.temp.setRange(0.0, 2.0); self.temp.setDecimals(2); self.temp.setSingleStep(0.1)
        self.temp.setValue(float(self.cfg.get("temperature", 0.5)))

        self.prompt = QComboBox(); self.prompt.setEditable(True)
        prompt_files = sorted([f.name for f in APP_DIR.glob("prompt*.json")])
        if not prompt_files: prompt_files = ["prompt.json"]
        self.prompt.addItems(prompt_files)
        current_prompt = self.cfg.get("prompt", "prompt.json")
        if current_prompt in prompt_files: self.prompt.setCurrentText(current_prompt)
        else: self.prompt.setEditText(current_prompt)
            
        self.google_key = QLineEdit(self.cfg.get("google_api_key", ""))
        self.google_key.setPlaceholderText("Gemini 模型需要 (GOOGLE_API_KEY)")
        self.google_key.setEchoMode(QLineEdit.Password)
        
        self.openai_key = QLineEdit(self.cfg.get("openai_api_key", ""))
        self.openai_key.setPlaceholderText("GPT 模型需要 (OPENAI_API_KEY)")
        self.openai_key.setEchoMode(QLineEdit.Password)

        form_model.addRow("翻譯模型:", self.model_combo)
        form_model.addRow("Google API Key:", self.google_key)
        form_model.addRow("OpenAI API Key:", self.openai_key)
        form_model.addRow("目標語言:", self.lang)
        form_model.addRow("溫度 (Temperature):", self.temp)
        form_model.addRow("提示詞 (Prompt):", self.prompt)
        
        self.layout.addWidget(grp_model)

        # --- Group 2: 進階選項 ---
        grp_adv = QGroupBox("進階選項")
        v_adv = QVBoxLayout(grp_adv)
        
        self.chk_resume = QCheckBox("從中斷點續跑 (--resume)")
        self.chk_resume.setChecked(bool(self.cfg.get("resume", False)))
        self.chk_resume.setToolTip("若上次翻譯中斷，勾選此項可接續進度")

        self.chk_context = QCheckBox("啟用上下文 (--use_context)")
        self.chk_context.setChecked(bool(self.cfg.get("use_context", False)))
        self.chk_context.setToolTip("將前文摘要傳送給 AI 以提升連貫性 (會增加 Token 消耗)")

        self.chk_glossary = QCheckBox("啟用術語表 (Glossary)")
        self.chk_glossary.setChecked(bool(self.cfg.get("use_glossary", True)))
        self.chk_glossary.setToolTip("自動維護名詞對照表 (nouns.json) 以保持翻譯一致性")

        hb_acc = QHBoxLayout()
        self.chk_accumulated = QCheckBox("啟用累積字數")
        self.chk_accumulated.setChecked(bool(self.cfg.get("use_accumulated", True)))
        self.spin_accumulated = QSpinBox(); self.spin_accumulated.setRange(100, 10000); self.spin_accumulated.setValue(int(self.cfg.get("accumulated_num", 800)))
        hb_acc.addWidget(self.chk_accumulated)
        hb_acc.addWidget(QLabel("每批次字數:"))
        hb_acc.addWidget(self.spin_accumulated)
        hb_acc.addStretch()

        v_adv.addWidget(self.chk_resume)
        v_adv.addWidget(self.chk_context)
        v_adv.addWidget(self.chk_glossary)
        v_adv.addLayout(hb_acc)
        self.layout.addWidget(grp_adv)

        # 輸出設定
        gb_out = QGroupBox("輸出設定")
        form_out = QFormLayout()
        self.out_dir_edit = QLineEdit(self.cfg["output_dir"])
        btn_out = QPushButton("...")
        btn_out.setFixedSize(30, 25)
        btn_out.clicked.connect(self.pick_output_dir)
        h_out = QHBoxLayout()
        h_out.addWidget(self.out_dir_edit)
        h_out.addWidget(btn_out)
        form_out.addRow("輸出資料夾:", h_out)
        
        self.chk_bilingual = QCheckBox("雙語對照 (Bilingual)")
        self.chk_bilingual.setChecked(self.cfg.get("bilingual", True))
        self.chk_bilingual.setToolTip("若取消勾選，將只輸出翻譯後的內容 (Single Translate)")
        form_out.addRow(self.chk_bilingual)
        
        gb_out.setLayout(form_out)
        self.layout.addWidget(gb_out)
        
        self.layout.addStretch()
        scroll.setWidget(content_widget)
        main_layout.addWidget(scroll)

        # Save Button
        btn_save = QPushButton("儲存設定")
        btn_save.setFixedHeight(40)
        btn_save.setStyleSheet("""
            QPushButton {
                background-color: #3b82f6; 
                color: white; 
                border-radius: 6px; 
                font-weight: bold;
            }
            QPushButton:hover { background-color: #2563eb; }
        """)
        btn_save.clicked.connect(self.save_settings)
        main_layout.addWidget(btn_save)

    def pick_output_dir(self):
        d = QFileDialog.getExistingDirectory(self, "選擇輸出目錄", self.out_dir_edit.text() or str(Path.home()/ "Desktop"))
        if d: self.out_dir_edit.setText(d)

    def save_settings(self):
        selected_display = self.lang.currentText().strip()
        selected_model = self.model_combo.currentText().strip()
        
        if selected_model.lower().startswith("gemini"):
            model_type = "gemini"; ollama_model = ""
        elif selected_model.lower().startswith("gpt"):
            model_type = "chatgptapi"; ollama_model = "" 
        else:
            model_type = "chatgptapi"; ollama_model = selected_model

        self.cfg.update({
            "model": model_type,
            "ollama_model": ollama_model,
            "selected_model_display": selected_model,
            "google_api_key": self.google_key.text().strip(),
            "openai_api_key": self.openai_key.text().strip(),
            "language": self.lang_map.get(selected_display, "zh-hant"),
            "temperature": float(self.temp.value()),
            "prompt": self.prompt.currentText().strip(),
            "use_accumulated": self.chk_accumulated.isChecked(),
            "accumulated_num": self.spin_accumulated.value(),
            "resume": self.chk_resume.isChecked(),
            "use_context": self.chk_context.isChecked(),
            "use_glossary": self.chk_glossary.isChecked(),
            "bilingual": self.chk_bilingual.isChecked(),
            "output_dir": self.out_dir_edit.text().strip() or str(Path.home()/ "Desktop"),
        })
        save_config(self.cfg)
        QMessageBox.information(self, "設定已儲存", "設定已成功更新！")

class Sidebar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(64)
        self.setObjectName("Sidebar")
        self.setStyleSheet("""
            QWidget#Sidebar {
                background-color: #090909; /* zinc-950 */
                border-right: 1px solid #27272a; /* zinc-800 */
            }
            QToolButton {
                border: none;
                border-radius: 10px;
                padding: 8px;
                background-color: transparent;
            }
            QToolButton:hover {
                background-color: #27272a; /* zinc-800 */
            }
            QToolButton:checked {
                background-color: #3f3f46; /* zinc-700 */
            }
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 16, 8, 16)
        layout.setSpacing(12)
        
        def create_btn(icon_name, tooltip, checkable=False):
            btn = QToolButton()
            btn.setIcon(self._load_icon(icon_name))
            btn.setIconSize(QSize(24, 24))
            btn.setToolTip(tooltip)
            btn.setCursor(Qt.PointingHandCursor)
            if checkable:
                btn.setCheckable(True)
                btn.setAutoExclusive(True)
            return btn
            
        # Navigation Group
        self.btn_tasks = create_btn("list", "任務列表", True)
        self.btn_tasks.setChecked(True)
        self.btn_settings = create_btn("settings", "設定", True)
        
        layout.addWidget(self.btn_tasks)
        layout.addWidget(self.btn_settings)
        
        layout.addSpacing(20)
        
        # Action Buttons
        self.btn_add = create_btn("plus", "新增檔案")
        self.btn_run = create_btn("play", "開始翻譯")
        self.btn_stop = create_btn("x", "停止")
        self.btn_del = create_btn("trash", "刪除檔案")
        self.btn_folder = create_btn("folder", "開啟輸出目錄")
        
        layout.addWidget(self.btn_add)
        layout.addWidget(self.btn_run)
        layout.addWidget(self.btn_stop)
        layout.addWidget(self.btn_del)
        layout.addWidget(self.btn_folder)
        
        # Log toggle button
        self.btn_log = create_btn("file-text", "顯示/隱藏日誌")
        layout.addWidget(self.btn_log)
        
        layout.addStretch()

    def _load_icon(self, name):
        icon_path = ICONS_DIR / f"{name}.svg"
        if icon_path.exists():
            # Recolor icon to #a1a1aa (zinc-400) or similar for dark theme
            pixmap = QIcon(str(icon_path)).pixmap(24, 24)
            if not pixmap.isNull():
                from PySide6.QtGui import QPainter, QColor
                painter = QPainter(pixmap)
                painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
                painter.fillRect(pixmap.rect(), QColor("#a1a1aa"))
                painter.end()
                return QIcon(pixmap)
        return QIcon()

class TaskCard(QWidget):
    def __init__(self, file_name, model, output_path, parent=None):
        super().__init__(parent)
        self.setObjectName("TaskCard")
        self.setStyleSheet("""
            QWidget#TaskCard {
                background-color: #18181b; /* zinc-900 */
                border: 1px solid #27272a; /* zinc-800 */
                border-radius: 12px;
            }
            QWidget#TaskCard:hover {
                border: 1px solid #3b82f6; /* blue-500 */
                background-color: #27272a;
            }
            QLabel { color: #a1a1aa; }
            QLabel#Title { 
                color: #f4f4f5; 
                font-weight: bold; 
                font-size: 14px;
            }
            QProgressBar {
                background-color: #27272a;
                border: none;
                border-radius: 2px;
                height: 4px;
                text-align: center;
            }
            QProgressBar::chunk {
                background-color: #3b82f6;
                border-radius: 2px;
            }
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)
        
        # Top Row: Icon + Title + Status
        top_row = QHBoxLayout()
        
        icon_label = QLabel()
        icon_path = ICONS_DIR / "file-text.svg"
        if icon_path.exists():
            # Recolor icon for card
            pixmap = QIcon(str(icon_path)).pixmap(16, 16)
            if not pixmap.isNull():
                from PySide6.QtGui import QPainter, QColor
                painter = QPainter(pixmap)
                painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
                painter.fillRect(pixmap.rect(), QColor("#a1a1aa"))
                painter.end()
                icon_label.setPixmap(pixmap)
        top_row.addWidget(icon_label)
        
        self.lbl_title = QLabel(file_name)
        self.lbl_title.setObjectName("Title")
        top_row.addWidget(self.lbl_title)
        top_row.addStretch()
        
        self.lbl_status = QLabel("準備中")
        self.lbl_status.setStyleSheet("""
            background-color: #27272a; 
            color: #a1a1aa; 
            padding: 4px 8px; 
            border-radius: 4px; 
            font-size: 11px;
        """)
        top_row.addWidget(self.lbl_status)
        
        layout.addLayout(top_row)
        
        # Info Row: Model + Duration
        info_row = QHBoxLayout()
        self.lbl_model = QLabel(model)
        self.lbl_model.setStyleSheet("font-family: monospace; font-size: 11px;")
        info_row.addWidget(self.lbl_model)
        
        info_row.addWidget(QLabel("•"))
        
        self.lbl_duration = QLabel("00:00")
        self.lbl_duration.setStyleSheet("font-family: monospace; font-size: 11px;")
        info_row.addWidget(self.lbl_duration)
        
        info_row.addStretch()
        layout.addLayout(info_row)
        
        # Progress Bar
        self.pbar = QProgressBar()
        self.pbar.setRange(0, 100)
        self.pbar.setValue(0)
        self.pbar.setTextVisible(False)
        layout.addWidget(self.pbar)
        
        # Progress Text
        self.lbl_progress_text = QLabel("0%")
        self.lbl_progress_text.setStyleSheet("font-size: 11px; color: #71717a;")
        layout.addWidget(self.lbl_progress_text)
        
        # Output Path (Bottom)
        path_row = QHBoxLayout()
        self.lbl_output = QLabel(output_path)
        self.lbl_output.setStyleSheet("font-size: 11px; color: #71717a;")
        self.lbl_output.setWordWrap(False)
        path_row.addWidget(self.lbl_output)
        layout.addLayout(path_row)

    def update_status(self, status, progress=0, duration="00:00", remaining="00:00"):
        self.lbl_status.setText(status)
        if status == "執行中…":
            self.lbl_status.setStyleSheet("background-color: #1e3a8a; color: #93c5fd; padding: 4px 8px; border-radius: 4px; font-size: 11px;")
        elif status == "完成":
            self.lbl_status.setStyleSheet("background-color: #14532d; color: #86efac; padding: 4px 8px; border-radius: 4px; font-size: 11px;")
        elif "失敗" in status or "停止" in status:
            self.lbl_status.setStyleSheet("background-color: #7f1d1d; color: #fca5a5; padding: 4px 8px; border-radius: 4px; font-size: 11px;")
        else:
            self.lbl_status.setStyleSheet("background-color: #27272a; color: #a1a1aa; padding: 4px 8px; border-radius: 4px; font-size: 11px;")
            
        self.pbar.setValue(progress)
        self.lbl_duration.setText(duration)
        
        if progress > 0:
             self.lbl_progress_text.setText(f"{progress}% (還需 {remaining})")
        else:
             self.lbl_progress_text.setText(f"{progress}%")

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QLabel,
    QFileDialog, QTableWidget, QTableWidgetItem, QMessageBox,
    QAbstractItemView, QHeaderView, QDialog, QFormLayout, QLineEdit,
    QCheckBox, QComboBox, QDoubleSpinBox, QSpinBox, QDialogButtonBox,
    QToolBar, QStyle, QPushButton, QHBoxLayout, QTextEdit, QSplitter,
    QGroupBox, QSizePolicy, QMenu, QStatusBar, QToolButton, QListWidget, 
    QListWidgetItem, QProgressBar, QStackedWidget, QScrollArea, QFrame
)
from PySide6.QtCore import Qt, QThread, Signal, QSize, QTimer, QSettings, QPoint
from PySide6.QtGui import QAction, QIcon, QDesktopServices

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        
        self.backend_dir = guess_backend_dir(APP_DIR)
        self.backend_books = self.backend_dir / "books"
        self.backend_books.mkdir(parents=True, exist_ok=True)

        defaults = {"model":"chatgptapi","ollama_model":"qwen3:8b","language":"zh-hant",
                    "temperature":0.5,"prompt":"prompt.json", 
                    "google_api_key": "", "openai_api_key": "",
                    "use_accumulated":False, "accumulated_num":800,
                    "resume":False, "bilingual":True, "output_dir":str(Path.home()/ "Desktop")}
        self.cfg = load_config(defaults)

        self.setWindowTitle("Bili 多語翻譯")
        self.resize(1120, 750)
        self.setAcceptDrops(True)
        self.setUnifiedTitleAndToolBarOnMac(True)
        self.setWindowIcon(QIcon("icon.png"))
        
        # Load QSS Style
        try:
            with open("gui/styles/dark_theme.qss", "r") as f:
                self.setStyleSheet(f.read())
        except Exception as e:
            print(f"Failed to load style: {e}")

        # Main Layout (Horizontal: Sidebar | Content | Log Sidebar)
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        self.main_layout = QHBoxLayout(main_widget)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        # 1. Sidebar (Left)
        self.sidebar = Sidebar()
        self.main_layout.addWidget(self.sidebar)
        
        # Connect Sidebar Buttons
        self.sidebar.btn_tasks.clicked.connect(lambda: self.switch_view(0))
        self.sidebar.btn_settings.clicked.connect(lambda: self.switch_view(1))
        
        self.sidebar.btn_add.clicked.connect(self.pick_files)
        self.sidebar.btn_run.clicked.connect(self.run_selected_with_choice)
        self.sidebar.btn_stop.clicked.connect(self.stop_current)
        self.sidebar.btn_del.clicked.connect(self.delete_item)
        self.sidebar.btn_folder.clicked.connect(self.open_output_dir)
        self.sidebar.btn_log.clicked.connect(self.toggle_log_panel)

        # 2. Content Area (Stacked Widget)
        self.stack = QStackedWidget()
        self.main_layout.addWidget(self.stack)

        # --- View 0: Tasks View ---
        self.task_view = QWidget()
        self.task_view_layout = QHBoxLayout(self.task_view) # Horizontal to hold Task List + Log Panel
        self.task_view_layout.setContentsMargins(0, 0, 0, 0)
        self.task_view_layout.setSpacing(0)
        
        # Task List Container
        task_container = QWidget()
        task_layout = QVBoxLayout(task_container)
        task_layout.setContentsMargins(0, 0, 0, 0)
        task_layout.setSpacing(0)
        
        self.settings = QSettings("BilingualBookMaker", "App")
        
        # Task List
        self.task_list = QListWidget()
        self.task_list.setFrameShape(QListWidget.NoFrame)
        self.task_list.setStyleSheet("background-color: transparent; outline: none;")
        self.task_list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.task_list.setSpacing(8)
        self.task_list.setContentsMargins(16, 16, 16, 16)
        
        task_layout.addWidget(self.task_list)
        self.task_view_layout.addWidget(task_container)
        
        # Log Sidebar (Right) - Part of Task View
        self.log_panel = QWidget()
        self.log_panel.setFixedWidth(400)
        self.log_panel.setStyleSheet("background-color: #18181b; border-left: 1px solid #27272a;")
        self.log_panel.setVisible(False)
        
        log_layout = QVBoxLayout(self.log_panel)
        log_layout.setContentsMargins(0, 0, 0, 0)
        log_layout.setSpacing(0)
        
        # Log Header
        log_header = QWidget()
        log_header.setFixedHeight(40)
        log_header.setStyleSheet("border-bottom: 1px solid #27272a;")
        lh_layout = QHBoxLayout(log_header)
        lh_layout.setContentsMargins(16, 0, 16, 0)
        lh_layout.addWidget(QLabel("執行日誌"))
        lh_layout.addStretch()
        
        btn_clear = QPushButton("清除")
        btn_clear.setFixedSize(60, 24)
        btn_clear.setStyleSheet("background: transparent; color: #71717a; border: none;")
        btn_clear.setCursor(Qt.PointingHandCursor)
        btn_clear.clicked.connect(lambda: self.log_text.clear())
        lh_layout.addWidget(btn_clear)
        
        btn_close_log = QPushButton()
        btn_close_log.setIcon(self.sidebar._load_icon("x")) # Reuse sidebar icon loader if possible or just load directly
        btn_close_log.setFixedSize(24, 24)
        btn_close_log.setStyleSheet("background: transparent; border: none;")
        btn_close_log.setCursor(Qt.PointingHandCursor)
        btn_close_log.clicked.connect(self.toggle_log_panel)
        lh_layout.addWidget(btn_close_log)

        log_layout.addWidget(log_header)
        
        # Log Text Area
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet("border: none; padding: 8px;")
        log_layout.addWidget(self.log_text)
        
        self.task_view_layout.addWidget(self.log_panel)
        
        self.stack.addWidget(self.task_view)
        
        # --- View 1: Settings View ---
        self.settings_widget = SettingsWidget(self.cfg, self.backend_dir)
        self.stack.addWidget(self.settings_widget)
        
        # Status Bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("就緒")

        self.queue = []; self.current_worker = None; self.current_row = None
        self.row_start_time = {}
        self.elapsed_timer = QTimer(self); self.elapsed_timer.timeout.connect(self._tick_elapsed)
        self.elapsed_timer.start(3000)

        self.append_log(f"[APP] APP_DIR={APP_DIR}")
        
    def switch_view(self, index):
        self.stack.setCurrentIndex(index)
        # Update sidebar state if needed (though QToolButton with autoExclusive handles visual toggle)
        
    def toggle_log_panel(self):
        visible = self.log_panel.isVisible()
        self.log_panel.setVisible(not visible)
        
    def pick_files(self):
        # Ensure we are on task view
        self.switch_view(0)
        self.sidebar.btn_tasks.setChecked(True)
        
        files, _ = QFileDialog.getOpenFileNames(self, "選擇檔案", str(Path.home()), "Supported (*.epub *.txt *.srt);;All Files (*)")
        for f in files:
            p = Path(f)
            if self._is_supported_source(p): self.add_job_and_run_immediately(f)

    def _is_supported_source(self, p: Path) -> bool:
        suffix_ok = p.suffix.lower() in {".epub",".txt",".srt"}
        reject = ("_bilingual" in p.stem.lower()) or (".temp" in p.name.lower()) or p.name.lower().endswith(".log")
        if not suffix_ok:
            QMessageBox.critical(self, "不支援的檔案", f"只支援：.epub, .txt, .srt\n{p}"); return False
        if reject:
            QMessageBox.critical(self, "無效的輸入", "這看起來是輸出檔或暫存檔（*_bilingual.*, *.temp*, *.log*），請不要丟入。"); return False
        return True

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls(): e.acceptProposedAction()

    def dropEvent(self, e):
        for url in e.mimeData().urls():
            p = Path(url.toLocalFile())
            if p.is_file():
                if self._is_supported_source(p): self.add_job_and_run_immediately(str(p))
            else:
                QMessageBox.critical(self, "不支援", "目前只支援拖入檔案（非資料夾）。")

    def open_output_dir(self):
        out_dir = Path(self.cfg.get("output_dir", str(Path.home()/"Desktop"))).expanduser()
        try:
            out_dir.mkdir(parents=True, exist_ok=True); subprocess.run(["open", str(out_dir)])
        except Exception as e:
            QMessageBox.critical(self, "開啟失敗", str(e))

    def add_job_and_run_immediately(self, filepath: str):
        # Settings are now configured in the Settings View before running
        # We assume current config is valid or use defaults
        
        src = Path(filepath); dst = self.backend_books / src.name
        try:
            shutil.copy2(src, dst)
            copy_status = "Created" if not dst.exists() else "Overwritten"
        except Exception as e:
            QMessageBox.critical(self, "複製檔案失敗", f"{e}"); return

        # Create Task Card
        model_display = self.cfg.get("selected_model_display", self.cfg.get("ollama_model", "chatgptapi"))
        card = TaskCard(src.name, model_display, self.cfg["output_dir"])
        
        # Add to List
        item = QListWidgetItem(self.task_list)
        item.setSizeHint(QSize(0, 140)) # Card height
        
        # Store metadata in item
        item.setData(ROLE_ORIGIN_NAME, src.name)
        item.setData(ROLE_ORIGIN_PATH, str(src))
        
        self.task_list.addItem(item)
        self.task_list.setItemWidget(item, card)
        
        row = self.task_list.row(item) # Get row index

        self.append_log(f"[SOURCE] {src}  →  {dst} | COPY={copy_status}")
        self.queue = [row]; self.run_next(resume=False)



    def build_cmd(self, cfg: dict, row: int, resume: bool) -> str:
        make_book = self.backend_dir / "make_book.py"
        if not make_book.exists():
            QMessageBox.critical(self, "找不到 make_book.py", f"{make_book}"); return ""
        prompt_path = cfg.get("prompt") or "prompt.json"

        item = self.task_list.item(row)
        origin_name = item.data(ROLE_ORIGIN_NAME)
        
        if "_bilingual" in origin_name.lower():
            origin_name = origin_name.lower().replace("_bilingual","")

        book_rel_path = f"books/{origin_name}"
        model_type = cfg.get("model", "chatgptapi")
        
        args = [sys.executable, str(self.backend_dir / "make_book.py"),
                "--model", model_type,
                "--language", cfg["language"],
                "--temperature", str(cfg["temperature"]),
                "--prompt", prompt_path,
                "--book_name", book_rel_path]
        
        if model_type == "chatgptapi" and cfg.get("ollama_model"):
            args.extend(["--ollama_model", cfg["ollama_model"]])
        
        if cfg.get("use_accumulated", False):
            args.extend(["--accumulated_num", str(cfg.get("accumulated_num", 800))])

        if cfg.get("use_context", False):
            args.append("--use_context")

        if not cfg.get("use_glossary", True):
            args.append("--no_glossary")

        if not cfg.get("bilingual", True):
            args.append("--single_translate")

        if resume: args.append("--resume")

        q = lambda s: f'"{s}"' if " " in s else s
        return " ".join(q(a) for a in args)

    def run_selected_with_choice(self):
        # For simplicity in list widget, just run selected or all
        # Logic similar to before but adapted for ListWidget
        rows = [i.row() for i in self.task_list.selectedIndexes()]
        if not rows:
             # Run all pending
             rows = []
             for i in range(self.task_list.count()):
                 item = self.task_list.item(i)
                 card = self.task_list.itemWidget(item)
                 if "完成" not in card.lbl_status.text() and "執行中" not in card.lbl_status.text():
                     rows.append(i)
        
        if not rows:
            QMessageBox.information(self, "提示", "沒有可執行的項目。"); return
            
        if len(rows) == 1:
            ret = QMessageBox.question(self, "執行選項", "要從中斷點續跑（Resume）嗎？\n選 否 會從頭重跑。",
                                       QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel)
            if ret == QMessageBox.Cancel: return
            resume = (ret == QMessageBox.Yes)
        else:
            resume = bool(self.cfg.get("resume", False))

        self.queue = rows; self.run_next(resume=resume)

    def _selected_rows_or_all_pending(self):
        # This method is no longer used directly, replaced by logic in run_selected_with_choice
        pass

    def run_next(self, resume: bool):
        if self.current_worker or not self.queue: return
        r = self.queue.pop(0); self.current_row = r
        
        item = self.task_list.item(r)
        card = self.task_list.itemWidget(item)
        
        card.update_status("執行中…", 0, "00:00", "00:00")
        self.row_start_time[r] = time.time()

        cmd = self.build_cmd(self.cfg, r, resume=resume)
        if not cmd:
            card.update_status("失敗")
            self.run_next(resume=resume); return
            
        self.append_log(f"$ {cmd}")
        self.status_bar.showMessage(f"正在翻譯: {item.data(ROLE_ORIGIN_NAME)} ...")

        env = os.environ.copy()
        model_type = self.cfg.get("model", "chatgptapi")
        if model_type == "gemini":
            g_key = self.cfg.get("google_api_key", "").strip()
            if g_key: env["GOOGLE_API_KEY"] = g_key
        elif model_type == "chatgptapi":
            if not self.cfg.get("ollama_model"):
                o_key = self.cfg.get("openai_api_key", "").strip()
                if o_key: env["OPENAI_API_KEY"] = o_key

        self.current_worker = Worker(cmd, str(APP_DIR), env=env)
        self.current_worker.stdout_line.connect(lambda line, row=r: self.on_stdout(row, line))
        self.current_worker.stderr_line.connect(lambda line, row=r: self.on_stderr(row, line))
        self.current_worker.done.connect(lambda rc, msg, row=r: self.on_done(row, rc, msg, resume))
        self.current_worker.start()

    def on_stdout(self, row: int, line: str):
        self.append_log(line)
        self._parse_progress(row, line)

    def on_stderr(self, row: int, line: str):
        self.append_log(line)
        self._parse_progress(row, line)

    def _parse_progress(self, row: int, line: str):
        ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
        clean_line = ansi_escape.sub('', line)

        if "%|" in clean_line:
            try:
                match = re.search(r'(\d+)%\|', clean_line)
                tqdm_time_match = re.search(r'<(\d+:\d+:?\d*),', clean_line)
                
                if match:
                    percent = int(match.group(1))
                    
                    item = self.task_list.item(row)
                    card = self.task_list.itemWidget(item)
                    
                    # Calculate elapsed
                    elapsed_str = "00:00"
                    start = self.row_start_time.get(row)
                    if start:
                        elapsed_str = self._fmt_sec(int(time.time() - start))
                    
                    remaining_str = "估計中"
                    if tqdm_time_match:
                        remaining_str = tqdm_time_match.group(1)
                        parts = remaining_str.split(':')
                        if len(parts) == 2: remaining_str = f"00:{remaining_str}"
                    
                    card.update_status("執行中…", percent, elapsed_str, remaining_str)
                    
            except Exception as e:
                self.append_log(f"Error parsing progress: {e}")

    def delete_item(self):
        row = self.task_list.currentRow()
        if row < 0: return
        
        item = self.task_list.item(row)
        origin_name = item.data(ROLE_ORIGIN_NAME)
        
        ret = QMessageBox.warning(self, "確認刪除", 
                                  f"確定要刪除 {origin_name} 嗎？\n這將同時刪除來源檔與輸出的雙語檔！",
                                  QMessageBox.Yes | QMessageBox.No)
        if ret != QMessageBox.Yes: return

        # 1. Delete source in backend/books
        src_path = self.backend_books / origin_name
        try:
            if src_path.exists(): src_path.unlink()
            self.append_log(f"已刪除來源檔: {src_path.name}")
        except Exception as e:
            self.append_log(f"刪除來源檔失敗 {src_path.name}: {e}")
            
        # 2. Delete output files (e.g. *_bilingual.epub)
        stem = Path(origin_name).stem
        for p in self.backend_books.glob(f"{stem}_bilingual.*"):
            try: 
                p.unlink()
                self.append_log(f"已刪除輸出檔: {p.name}")
            except Exception as e: 
                self.append_log(f"刪除輸出檔失敗 {p.name}: {e}")

        # 3. Delete Glossary file
        try:
            glossary_file = self.backend_books / f"{stem}_nouns.json"
            if glossary_file.exists():
                glossary_file.unlink()
                self.append_log(f"已刪除 Glossary 檔: {glossary_file.name}")
        except Exception as e:
            self.append_log(f"刪除 Glossary 檔失敗 {glossary_file.name}: {e}")

        # 4. Delete progress file
        try:
            progress_file = self.backend_books / f".{stem}.temp.bin"
            if progress_file.exists():
                progress_file.unlink()
                self.append_log(f"已刪除進度檔: {progress_file.name}")
        except Exception as e:
            self.append_log(f"刪除進度檔失敗 {progress_file.name}: {e}")
        
        self.task_list.takeItem(row) # This removes it from list
        self.append_log(f"--- 刪除完成: {origin_name} ---")

    def _tick_elapsed(self):
        # The original code had some commented out logic here, but it's not relevant for the current ListWidget based UI.
        pass

    def on_done(self, row: int, rc: int, msg: str, resume: bool):
        start = self.row_start_time.get(row, time.time())
        elapsed = max(0, int(time.time() - start))
        self.table.setItem(row, 4, QTableWidgetItem(self._fmt_sec(elapsed)))
        
        if "已停止" in msg:
            status = "已停止"
            msg += "\n[提示] 您可以再次選取此項目並點擊「執行」，選擇「是」來恢復翻譯 (Resume)。"
        elif rc == 0:
            status = "完成"
        else:
            status = "失敗"
            
        self.table.setItem(row, 2, QTableWidgetItem(status))
        self.append_log(msg)

        try:
            origin_name = self.table.item(row,0).data(ROLE_ORIGIN_NAME) or Path(self.table.item(row,0).text()).name
            stem = Path(origin_name).stem
            latest = self._find_latest_output(self.backend_books, stem)
            if latest:
                out_dir = Path(self.cfg["output_dir"]).expanduser().resolve()
                out_dir.mkdir(parents=True, exist_ok=True)
                target = out_dir / latest.name
                shutil.copy2(latest, target)
                self.table.setItem(row, 6, QTableWidgetItem(str(target)))
                self.append_log(f"[輸出] {target}")
                # QMessageBox.information(self, "完成", f"翻譯完成！\n已輸出：{target}")
                self.append_log(f"✅ 翻譯完成！已輸出：{target}")
        except Exception as e:
            self.append_log(f"[搬移輸出] 失敗：{e}")

        self.current_worker=None; self.current_row=None
        self.status_bar.showMessage("就緒")
        
        # 如果是手動停止，不要繼續執行佇列中的下一個任務
        if status == "已停止":
            return
            
        self.run_next(resume=resume)

    def stop_current(self):
        if self.current_worker:
            self.append_log("[STOP] 傳送 Ctrl+C（SIGINT）…")
            self.current_worker.terminate_job()

    def delete_selected_source_and_outputs(self):
        rows = self._selected_rows_or_all_pending()
        if not rows: return
        ok = QMessageBox.question(self, "刪除檔案", "要刪除 backend/books 的來源副本與對應 _bilingual.* 嗎？",
                                  QMessageBox.Yes|QMessageBox.No)
        if ok != QMessageBox.Yes: return
        for r in rows:
            filename = self.table.item(r,0).text()
            src_in_backend = self.backend_books / filename
            stem = src_in_backend.stem
            try:
                if src_in_backend.exists(): src_in_backend.unlink()
            except Exception as e:
                self.append_log(f"[刪除來源失敗] {e}")
            try:
                for p in self.backend_books.glob(f"{stem}_bilingual.*"):
                    try: p.unlink()
                    except Exception as e: self.append_log(f"[刪除輸出失敗] {p}: {e}")
            except Exception as e:
                self.append_log(f"[搜尋輸出失敗] {e}")
            try:
                # 刪除 Glossary 檔案
                glossary_file = self.backend_books / f"{stem}_nouns.json"
                if glossary_file.exists():
                    glossary_file.unlink()
                    self.append_log(f"[刪除 Glossary] {glossary_file.name}")
            except Exception as e:
                self.append_log(f"[刪除 Glossary 失敗] {e}")
            try:
                self.table.removeRow(r)
            except Exception:
                pass

    def append_log(self, text: str):
        # 寫入 UI
        if hasattr(self, 'log_view'):
            self.log_view.append(text)
            self.log_view.ensureCursorVisible()

    def _fmt_sec(self, s: int) -> str:
        s = int(max(0, s)); m, s = divmod(s, 60); h, m = divmod(m, 60)
        return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"

    def closeEvent(self, event):
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("windowState", self.saveState())
        super().closeEvent(event)

    def _find_latest_output(self, books_dir: Path, stem: str) -> Optional[Path]:
        cands = [p for p in books_dir.glob(f"{stem}_bilingual.*") if p.is_file()]
        if not cands: return None
        cands.sort(key=lambda p: p.stat().st_mtime, reverse=True); return cands[0]

def apply_stylesheet(app):
    # 使用系統原生風格 (macOS 自動適應 Dark/Light Mode)
    # 僅保留些微通用的調整，不強制顏色
    qss = """
    QGroupBox {
        font-weight: bold;
    }
    """
    app.setStyleSheet(qss)

def main():
    print("Starting main...")
    app = QApplication(sys.argv)
    apply_stylesheet(app)
    print("App created, creating window...")
    try:
        win = MainWindow()
        win.show()
        print("Window shown, entering event loop...")
        sys.exit(app.exec())
    except Exception as e:
        print(f"Error in main: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()

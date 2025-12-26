#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# AI Book Translator v1.2.7

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



from book_maker.utils import LANGUAGES, global_state
from book_maker.cli import main as book_maker_main
import io

if getattr(sys, 'frozen', False):
    # PyInstaller 打包後的資源路徑
    APP_DIR = Path(sys._MEIPASS)
else:
    APP_DIR = Path(__file__).resolve().parent

# Define User Data Directory
USER_DATA_DIR = Path.home() / "Documents" / "Bili"
USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
(USER_DATA_DIR / "books").mkdir(parents=True, exist_ok=True)
(USER_DATA_DIR / "log").mkdir(parents=True, exist_ok=True)

# Config path is now in user data dir
CONFIG_PATH = USER_DATA_DIR / "config.json"
# We might want to copy a default config if it doesn't exist
DEFAULT_CONFIG_PATH = APP_DIR / "config.json"
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
    # If user config doesn't exist but default one does, copy it
    if not CONFIG_PATH.exists() and DEFAULT_CONFIG_PATH.exists():
        try:
            shutil.copy2(DEFAULT_CONFIG_PATH, CONFIG_PATH)
        except Exception:
            pass

    if CONFIG_PATH.exists():
        try:
            d = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            defaults.update(d)
        except Exception:
            pass
    return defaults

def save_config(cfg: dict):
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")

def copy_resources():
    """Copy necessary resources (prompts, config) to USER_DATA_DIR"""
    # Copy all prompt_*.json files
    for p in APP_DIR.glob("prompt*.json"):
        target = USER_DATA_DIR / p.name
        if not target.exists():
            try:
                shutil.copy2(p, target)
            except Exception:
                pass
    
    # Copy config.json if not exists
    if not CONFIG_PATH.exists() and DEFAULT_CONFIG_PATH.exists():
        try:
            shutil.copy2(DEFAULT_CONFIG_PATH, CONFIG_PATH)
        except Exception:
            pass

def list_ollama_models() -> List[str]:
    ollama_bin = "ollama"
    # Check common paths for macOS App Bundle environment
    if shutil.which("ollama") is None:
        for p in ["/usr/local/bin/ollama", "/opt/homebrew/bin/ollama"]:
            if os.path.exists(p):
                ollama_bin = p
                break

    try:
        res = subprocess.run([ollama_bin, "list"], capture_output=True, text=True, check=False)
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

class StreamRedirector(io.StringIO):
    def __init__(self, signal, is_err=False):
        super().__init__()
        self.signal = signal
        self.is_err = is_err

    def write(self, text):
        if text:
            self.signal.emit(text)
        return super().write(text)

class DirectWorker(QThread):
    stdout_line = Signal(str)
    stderr_line = Signal(str)
    done = Signal(int, str)

    def __init__(self, args: List[str], cwd: str, env: dict = None):
        super().__init__()
        self.args = args
        self.cwd = cwd
        self.env = env if env is not None else os.environ.copy()
        self._user_cancelled = False

    def run(self):
        # Reset cancellation flag
        global_state.is_cancelled = False
        
        # Save original stdout/stderr and CWD
        original_stdout = sys.stdout
        original_stderr = sys.stderr
        original_cwd = os.getcwd()
        original_env = os.environ.copy()

        try:
            # Redirect stdout/stderr
            sys.stdout = StreamRedirector(self.stdout_line)
            sys.stderr = StreamRedirector(self.stderr_line, is_err=True)
            
            # Change CWD
            os.chdir(self.cwd)
            
            # Update Environment
            os.environ.update(self.env)

            # Run the main function
            # Note: book_maker_main might raise SystemExit on error or success
            try:
                book_maker_main(self.args)
                self.done.emit(0, "完成 ✅")
            except SystemExit as e:
                code = e.code if isinstance(e.code, int) else 1
                if code == 0:
                    self.done.emit(0, "完成 (v1.2.6) ✅")
                elif self._user_cancelled:
                    self.done.emit(1, "已暫停")
                else:
                    self.done.emit(code, f"失敗 (Code: {code})")
            except KeyboardInterrupt:
                if self._user_cancelled:
                    self.done.emit(1, "已暫停")
                else:
                    self.done.emit(1, "已暫停")
            except Exception as e:
                if self._user_cancelled:
                    self.done.emit(1, "已暫停")
                else:
                    self.done.emit(1, f"錯誤: {str(e)}")
                import traceback
                self.stderr_line.emit(traceback.format_exc())

        except Exception as e:
            self.done.emit(1, f"系統錯誤: {str(e)}")
        finally:
            # Restore original state
            sys.stdout = original_stdout
            sys.stderr = original_stderr
            os.chdir(original_cwd)
            os.environ.clear()
            os.environ.update(original_env)

    def terminate_job(self):
        self._user_cancelled = True
        global_state.is_cancelled = True
        self.stderr_line.emit("正在等待當前翻譯批次完成...")


class SettingsWidget(QWidget):
    def __init__(self, cfg: dict, backend_dir: Path, main_window, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.backend_dir = backend_dir
        self.main_window = main_window
        
        # Main Layout
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(24, 24, 24, 24)
        main_layout.setSpacing(20)
        
        # Title
        lbl_title = QLabel("設定")
        lbl_title.setObjectName("SettingsTitle")
        main_layout.addWidget(lbl_title)

        # Clarification Label
        lbl_note = QLabel("請選擇翻譯模型、語言、提示詞，Gemini和OpenAI需填入API Key。")
        lbl_note.setObjectName("SettingsNote")
        main_layout.addWidget(lbl_note)
        
        # Scroll Area for settings form
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("background-color: transparent;")
        
        content_widget = QWidget()
        content_widget.setStyleSheet("background-color: transparent;")
        self.layout = QVBoxLayout(content_widget)
        self.layout.setSpacing(16)
        
        def _fix_combo_popup(combo):
            view = QListView()
            view.setStyleSheet("""
                QListView {
                    background-color: #27272a;
                    color: #f4f4f5;
                    border: 1px solid #3f3f46;
                    outline: none;
                }
                QListView::item {
                    padding: 4px;
                    min-height: 24px;
                }
                QListView::item:selected {
                    background-color: #3b82f6;
                    color: white;
                }
            """)
            view.setMinimumWidth(300)
            combo.setView(view)

        # --- Group 1: 模型設定 ---
        grp_model = QGroupBox("模型設定")
        form_model = QFormLayout(grp_model)
        form_model.setLabelAlignment(Qt.AlignRight)
        
        self.model_combo = QComboBox(); self.model_combo.setEditable(False)
        _fix_combo_popup(self.model_combo)
        
        # 1. 加入 Ollama 模型
        ollama_models = list_ollama_models()
        if ollama_models:
            self.model_combo.addItems(ollama_models)
            self.model_combo.insertSeparator(len(ollama_models))
            
        # 2. 加入雲端模型 (Gemini, OpenAI)
        cloud_models = [
            "gpt-5.1", "gpt-4o", "gpt-4.1", "gemini-2.5-pro", "gemini-2.5-flash", 
            "gemini-2.0-flash",
        ]
        self.model_combo.addItems(cloud_models)
        
        
        # 設定預設值 (These will be loaded by load_settings)
            
        self.lang = QComboBox(); self.lang.setEditable(False)
        self.lang.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        _fix_combo_popup(self.lang)
        self.lang_map = {
            "繁體中文": "zh-hant", "英文": "en", "日文": "ja", "韓文": "ko",
            "法文": "fr", "西班牙文": "es", "德文": "de", "義大利文": "it"
        }
        self.lang.addItems(list(self.lang_map.keys()))
        
        
        # Default language handled in load_settings

        self.temp = QDoubleSpinBox(); self.temp.setRange(0.0, 2.0); self.temp.setDecimals(2); self.temp.setSingleStep(0.1)
        # self.temp.setValue(float(self.cfg.get("temperature", 0.5)))
        
        # self.prompt = QComboBox() # Removed

        # Default prompt handled in load_settings
            
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
        form_model.addRow("模型溫度:", self.temp)
        # form_model.addRow("提示詞:", self.prompt) # Removed for auto-selection
        
        self.layout.addWidget(grp_model)

        # Advanced settings (Context/Resume) have been simplified/removed from UI
        # Load initial values handled at end of __init__

        # 輸出設定
        gb_out = QGroupBox("輸出設定")
        form_out = QFormLayout()
        self.out_dir_edit = QLineEdit(self.cfg["output_dir"])

        btn_out = QPushButton("選擇路徑")
        btn_out.setObjectName("SecondaryButton")
        btn_out.setCursor(Qt.PointingHandCursor)
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

        # Buttons Layout
        h_btns = QHBoxLayout()
        h_btns.setSpacing(15)
        h_btns.setAlignment(Qt.AlignCenter)

        # Save Button
        btn_save = QPushButton("儲存設定")
        btn_save.setFixedHeight(40)
        btn_save.setFixedWidth(120)
        btn_save.setCursor(Qt.PointingHandCursor)
        # Save Button
        btn_save = QPushButton("儲存設定")
        btn_save.setFixedHeight(40)
        btn_save.setFixedWidth(120)
        btn_save.setCursor(Qt.PointingHandCursor)
        btn_save.clicked.connect(self.save_settings)

        # Cancel Button

        btn_cancel = QPushButton("取消")
        btn_cancel.setObjectName("CancelButton")
        btn_cancel.setFixedHeight(40)
        btn_cancel.setFixedWidth(120)
        btn_cancel.setCursor(Qt.PointingHandCursor)
        
        h_btns.addWidget(btn_save)
        h_btns.addWidget(btn_cancel)
        
        main_layout.addLayout(h_btns)
        
        self.btn_cancel = btn_cancel

        # Load initial values (Must be called after all widgets are created)
        self.load_settings()

    def load_settings(self):
        # Model
        current_model = self.cfg.get("selected_model_display")
        if not current_model: current_model = "gemini-2.5-pro"
        self.model_combo.setCurrentText(current_model)
        
        # Language
        current_code = self.cfg.get("language", "zh-hant")
        default_display = "繁體中文"
        for name, code in self.lang_map.items():
            if code == current_code:
                default_display = name; break
        self.lang.setCurrentText(default_display)
        
        # Temp
        self.temp.setValue(float(self.cfg.get("temperature", 0.5)))
        
        # Prompt selection is now automatic based on language
        # current_prompt = self.cfg.get("prompt", "prompt_繁中.json")
        # idx = self.prompt.findText(current_prompt)
        # if idx >= 0: self.prompt.setCurrentIndex(idx)
        # else: self.prompt.setEditText(current_prompt)
        
        # Context - REMOVED
        # Default to False if not set
        # self.chk_context.setChecked(self.cfg.get("use_context", False))
        
        # Keys
        self.google_key.setText(self.cfg.get("google_api_key", ""))
        self.openai_key.setText(self.cfg.get("openai_api_key", ""))
        
        # Output Dir
        self.out_dir_edit.setText(self.cfg.get("output_dir", str(Path.home()/"Desktop")))
        
        # Bilingual
        self.chk_bilingual.setChecked(self.cfg.get("bilingual", True))

    def revert_settings(self):
        self.load_settings()

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

        
        # Read context setting from UI - DISABLED
        # use_context = self.chk_context.isChecked()
        use_context = False 
        use_glossary = True 
        
        # Batch size still auto-determined for now unless we add UI for it
        if ollama_model:
            accumulated_num = self.cfg.get("accumulated_num_ollama", 600)
        else:
            # Smart Batch Sizing (Cloud)
            # Logic: Reasoning models (Gemini 2.5/3) need smaller chunks (1000) to allow space for "Thinking"
            # Standard models (Gemini 2.0, GPT-4) can handle larger chunks (2000) for speed.
            m_low = selected_model.lower()
            if "flash" in m_low or "gpt" in m_low:
                 # Standard Speed Models -> Speed Mode
                accumulated_num = 2000
            elif "gemini-2.5" in m_low or "gemini-3" in m_low or "o1-" in m_low:
                # Reasoning Models (High thinking cost) -> Safe Mode
                accumulated_num = 1000
            else:
                # Default for unknown models
                accumulated_num = 1000

        self.cfg.update({
            "model": model_type,
            "ollama_model": ollama_model,
            "selected_model_display": selected_model,
            "google_api_key": self.google_key.text().strip(),
            "openai_api_key": self.openai_key.text().strip(),
            "language": self.lang_map.get(selected_display, "zh-hant"),
            "temperature": float(self.temp.value()),
            # Auto-select prompt based on language
            "prompt": "prompt_tw.json" if selected_display == "繁體中文" else "prompt_general.json",
            "use_accumulated": True,
            "accumulated_num": accumulated_num,
            "interval": 5.0,
            # "resume": self.chk_resume.isChecked(), # Removed from UI
            "use_context": use_context,
            "use_glossary": use_glossary,
            "bilingual": self.chk_bilingual.isChecked(),
            "output_dir": self.out_dir_edit.text().strip() or str(Path.home()/ "Desktop"),
        })
        save_config(self.cfg)
        
        # Check if there are pending files
        if self.main_window.pending_filepaths:
            filepaths = self.main_window.pending_filepaths[:] # Copy list
            self.main_window.pending_filepaths = []
            
            # Switch back to tasks view
            self.main_window.stack.setCurrentIndex(0)
            self.main_window.sidebar.btn_settings.setChecked(False)
            
            # Process the files
            for fp in filepaths:
                self.main_window._add_job_internal(fp)
                
            self.main_window.status_label.setText("就緒")
        else:
            QMessageBox.information(self, "設定已儲存", "設定已成功更新！")
            # Switch back to tasks view
            self.main_window.stack.setCurrentIndex(0)
            self.main_window.sidebar.btn_settings.setChecked(False)

class Sidebar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(64)
        self.setObjectName("Sidebar")

        
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
        self.btn_settings = create_btn("settings", "設定", True)
        
        layout.addWidget(self.btn_settings)
        
        layout.addSpacing(20)
        
        # Action Buttons
        self.btn_run = create_btn("play", "開始翻譯")
        self.btn_stop = create_btn("x", "暫停翻譯")
        self.btn_del = create_btn("trash", "刪除檔案")
        self.btn_folder = create_btn("folder", "開啟輸出目錄")
        
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
        self.lbl_title.setObjectName("CardTitle")
        top_row.addWidget(self.lbl_title)
        top_row.addStretch()
        
        self.lbl_status = QLabel("準備中")
        self.lbl_status.setObjectName("CardStatus")
        self.lbl_status.setAlignment(Qt.AlignCenter)
        top_row.addWidget(self.lbl_status)
        
        layout.addLayout(top_row)
        
        # Info Row: Model + Duration
        info_row = QHBoxLayout()
        self.lbl_model = QLabel(model)
        self.lbl_model.setObjectName("CardModel")
        info_row.addWidget(self.lbl_model)
        
        info_row.addWidget(QLabel("•"))
        
        self.lbl_duration = QLabel("00:00")
        self.lbl_duration.setObjectName("CardDuration")
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
        self.lbl_progress_text.setObjectName("ProgressText")
        layout.addWidget(self.lbl_progress_text)
        
        # Output Path (Bottom)
        path_row = QHBoxLayout()
        self.lbl_output = QLabel(output_path)
        self.lbl_output.setObjectName("OutputPath")
        self.lbl_output.setWordWrap(False)
        path_row.addWidget(self.lbl_output)
        layout.addLayout(path_row)

    def set_model(self, model_name):
        self.lbl_model.setText(model_name)

    def update_status(self, status, progress=0, duration="00:00", remaining="00:00"):
        self.lbl_status.setText(status)
        if status == "執行中…":
            self.lbl_status.setStyleSheet("background-color: #3b82f6; color: #eeeeee; padding: 4px 8px; border-radius: 4px; font-size: 11px;")
        elif status == "完成":
            self.lbl_status.setStyleSheet("background-color: #14532d; color: #eeeeee; padding: 4px 8px; border-radius: 4px; font-size: 11px;")
        elif "失敗" in status or "停止" in status or "暫停" in status:
            self.lbl_status.setStyleSheet("background-color: #7f1d1d; color: #eeeeee; padding: 4px 8px; border-radius: 4px; font-size: 11px;")
        else:
            self.lbl_status.setStyleSheet("background-color: #27272a; color: #a1a1aa; padding: 4px 8px; border-radius: 4px; font-size: 11px;")
            
        self.pbar.setValue(progress)
        self.lbl_duration.setText(duration)
        if remaining != "00:00":
             self.lbl_duration.setText(f"{duration} (剩餘 {remaining})")
        else:
             self.lbl_progress_text.setText(f"{progress}%")

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        # Find parent QListWidget
        parent = self.parent()
        while parent and not isinstance(parent, QListWidget):
            parent = parent.parent()
        
        if parent:
            # Map local position to QListWidget coordinates
            # Note: itemAt takes position relative to viewport, but mapFromGlobal handles it if we use global
            pos_in_list = parent.viewport().mapFromGlobal(self.mapToGlobal(event.position().toPoint()))
            item = parent.itemAt(pos_in_list)
            
            if item:
                if event.modifiers() & Qt.ControlModifier:
                    item.setSelected(not item.isSelected())
                elif event.modifiers() & Qt.ShiftModifier:
                    # Simple shift support: select everything from current to this
                    curr = parent.currentRow()
                    target = parent.row(item)
                    if curr != -1:
                        start, end = min(curr, target), max(curr, target)
                        for i in range(start, end + 1):
                            parent.item(i).setSelected(True)
                    else:
                        item.setSelected(True)
                else:
                    # Single click: clear others unless Ctrl/Shift
                    parent.clearSelection()
                    item.setSelected(True)
                
                parent.setCurrentItem(item)

    def mouseDoubleClickEvent(self, event):
        super().mouseDoubleClickEvent(event)
        # Find parent QListWidget
        parent = self.parent()
        while parent and not isinstance(parent, QListWidget):
            parent = parent.parent()
            
        if parent:
            pos_in_list = parent.viewport().mapFromGlobal(self.mapToGlobal(event.position().toPoint()))
            item = parent.itemAt(pos_in_list)
            if item:
                parent.itemDoubleClicked.emit(item)

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QLabel,
    QFileDialog, QTableWidget, QTableWidgetItem, QMessageBox,
    QAbstractItemView, QHeaderView, QDialog, QFormLayout, QLineEdit,
    QCheckBox, QComboBox, QDoubleSpinBox, QSpinBox, QDialogButtonBox,
    QToolBar, QStyle, QPushButton, QHBoxLayout, QTextEdit, QSplitter,
    QGroupBox, QSizePolicy, QMenu, QStatusBar, QToolButton, QListWidget, 
    QListWidgetItem, QProgressBar, QStackedWidget, QScrollArea, QFrame, QListView
)
from PySide6.QtCore import Qt, QThread, Signal, QSize, QTimer, QSettings, QPoint
from PySide6.QtGui import QAction, QIcon, QDesktopServices

class EmptyStateWidget(QWidget):
    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("EmptyStateWidget")
        
        # Main layout to center the box
        main_layout = QVBoxLayout(self)
        main_layout.setAlignment(Qt.AlignHCenter) # Center horizontally only
        main_layout.addSpacing(100) # Move down from top
        
        # Inner fixed-size box
        self.box = QFrame()
        self.box.setFixedSize(500, 150)
        self.box.setObjectName("EmptyBox")
        
        # Layout inside the box
        box_layout = QVBoxLayout(self.box)
        box_layout.setAlignment(Qt.AlignCenter)
        box_layout.setSpacing(2)
        box_layout.setContentsMargins(4, 4, 4, 4)
                
        # Main Text
        lbl_main = QLabel("將檔案拖到這裡或點擊上傳")
        lbl_main.setAlignment(Qt.AlignCenter)
        lbl_main.setObjectName("EmptyStateMain")
        box_layout.addWidget(lbl_main)
        
        # Sub Text
        lbl_sub = QLabel("支援 EPUB/TXT/SRT/MD 格式檔案")
        lbl_sub.setAlignment(Qt.AlignCenter)
        lbl_sub.setObjectName("EmptyStateSub")
        box_layout.addWidget(lbl_sub)
        
        # Logo & Title Container
        top_container = QWidget()
        top_layout = QHBoxLayout(top_container) # Changed to Horizontal
        top_layout.setAlignment(Qt.AlignCenter)
        top_layout.setSpacing(15) # Increased spacing slightly
        
        # Logo
        logo_label = QLabel()
        logo_label.setAlignment(Qt.AlignCenter)
        logo_path = ICONS_DIR / "logo.svg"
        if logo_path.exists():
            pixmap = QIcon(str(logo_path)).pixmap(64, 64) 
            if not pixmap.isNull():
                logo_label.setPixmap(pixmap)
        top_layout.addWidget(logo_label)
        
        # Title
        title_label = QLabel("Bili 原文書翻譯")
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setObjectName("EmptyStateTitle") 
        top_layout.addWidget(title_label)
        
        main_layout.addWidget(top_container)
        main_layout.addWidget(self.box)
        main_layout.addStretch() # Push everything up

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        
        # Ensure resources are copied to user dir
        copy_resources()
        
        # Load Stylesheet
        self.load_stylesheet()
        
        self.settings = QSettings("Bili", "App")
        
        self.backend_dir = guess_backend_dir(APP_DIR)
        # Use user data dir for books to ensure writability
        self.backend_books = USER_DATA_DIR / "books"
        self.backend_books.mkdir(parents=True, exist_ok=True)

        defaults = {"model":"gemini","ollama_model":"","language":"zh-hant",
                    "temperature":0.7,"prompt":"prompt_繁中.json", 
                    "google_api_key": "", "openai_api_key": "",
                    "use_accumulated":True, "accumulated_num":600,
                    "resume":False, "bilingual":True, "output_dir":str(Path.home()/ "Desktop"),
                    "selected_model_display": "gemini-2.0-flash"}
        self.cfg = load_config(defaults)

        self.setWindowTitle("Bili 原文書翻譯 v1.2.7")
        self.resize(900, 700)
        self.setAcceptDrops(True)
        self.setUnifiedTitleAndToolBarOnMac(True)
        self.setWindowIcon(QIcon("icon.png"))
        
        # Track if user has been prompted about settings (Persistent)
        self.has_shown_settings_prompt = self.settings.value("has_shown_settings_prompt", False, type=bool)
        self.pending_filepaths = []  # Store filepaths when settings review is triggered
        
        # Load QSS Style
        # self.load_stylesheet() is already called above at line 898


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
        self.sidebar.btn_settings.clicked.connect(lambda: self.switch_view(1))
        
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
        task_view_main_layout = QVBoxLayout(self.task_view)
        task_view_main_layout.setContentsMargins(0, 0, 0, 0)
        task_view_main_layout.setSpacing(0)
        
        # Create a QSplitter for resizable panels
        self.task_splitter = QSplitter(Qt.Horizontal)
        self.task_splitter.setHandleWidth(1)
        self.task_splitter.setStyleSheet("""
            QSplitter::handle {
                background-color: #27272a;
            }
            QSplitter::handle:hover {
                background-color: #3f3f46;
            }
        """)
        
        # Task List Container
        task_container = QWidget()
        task_layout = QVBoxLayout(task_container)
        task_layout.setContentsMargins(0, 0, 0, 0)
        task_layout.setSpacing(0)
        
        # Empty State Placeholder
        self.empty_state = EmptyStateWidget()
        self.empty_state.clicked.connect(self.pick_files)
        
        # Task List Container
        self.task_list = QListWidget()
        self.task_list.setFrameShape(QListWidget.NoFrame)
        self.task_list.setStyleSheet("background-color: transparent; outline: none;")
        self.task_list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.task_list.setSpacing(8)
        self.task_list.setContentsMargins(16, 16, 16, 16)
        self.task_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.task_list.itemDoubleClicked.connect(self.run_selected_with_choice)
        
        # Stack to switch between empty state and task list
        self.task_stack = QStackedWidget()
        self.task_stack.addWidget(self.empty_state)  # Index 0
        self.task_stack.addWidget(self.task_list)    # Index 1
        
        task_layout.addWidget(self.task_stack)
        self.task_splitter.addWidget(task_container)
        
        # Log Sidebar (Right) - Part of Task View
        self.log_panel = QWidget()
        self.log_panel.setMinimumWidth(200)
        self.log_panel.setObjectName("LogPanel")
        self.log_panel.setAttribute(Qt.WA_StyledBackground, True) # Ensure background is painted
        self.log_panel.setVisible(False)
        
        log_layout = QVBoxLayout(self.log_panel)
        log_layout.setContentsMargins(0, 0, 0, 0)
        log_layout.setSpacing(0)
        
        # Log Header
        log_header = QWidget()
        log_header.setFixedHeight(40)
        log_header_layout = QHBoxLayout(log_header)
        log_header_layout.setContentsMargins(10, 0, 10, 0)
        
        lbl_log_title = QLabel("執行日誌")
        lbl_log_title.setObjectName("LogTitle")
        log_header_layout.addWidget(lbl_log_title)
        log_header_layout.addStretch()
        
        btn_clear_log = QPushButton("清除")
        btn_clear_log.setCursor(Qt.PointingHandCursor)
        btn_clear_log.setObjectName("ClearLogButton")
        btn_clear_log.clicked.connect(self.clear_log)
        log_header_layout.addWidget(btn_clear_log)
        
        btn_close_log = QPushButton()
        btn_close_log.setIcon(QIcon(str(ICONS_DIR / "x.svg")))
        btn_close_log.setIconSize(QSize(16, 16))
        btn_close_log.setCursor(Qt.PointingHandCursor)
        btn_close_log.setFixedSize(24, 24)
        btn_close_log.setObjectName("CloseLogButton")
        btn_close_log.clicked.connect(self.toggle_log_panel)
        log_header_layout.addWidget(btn_close_log)
        
        log_layout.addWidget(log_header)
        
        # Log Text Area
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFrameShape(QFrame.NoFrame)
        self.log_text.setObjectName("LogTextArea")
        log_layout.addWidget(self.log_text)
        
        self.task_splitter.addWidget(self.log_panel)
        
        # Set initial sizes for splitter (Content : Log)
        self.task_splitter.setSizes([700, 0]) # Log hidden initially
        self.task_splitter.setCollapsible(0, False)
        self.task_splitter.setCollapsible(1, True)
        
        task_view_main_layout.addWidget(self.task_splitter)
        
        # --- View 1: Settings View ---
        self.settings_widget = SettingsWidget(self.cfg, self.backend_dir, main_window=self)
        
        # Add views to stack
        self.stack.addWidget(self.task_view)      # Index 0
        self.stack.addWidget(self.settings_widget) # Index 1
        
        # Connect settings cancel button to switch back to task view
        self.settings_widget.btn_cancel.clicked.connect(self.on_settings_cancel)
        
        # Status Bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        # Style moved to QStatusBar in qss
        self.status_bar.setSizeGripEnabled(False) # Remove size grip on Mac to look cleaner
        
        self.status_label = QLabel("就緒")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setObjectName("StatusLabel")
        self.status_bar.addWidget(self.status_label, 1) # Stretch factor 1 to center
        
        version_label = QLabel("by @Lee 2025 v1.3.0")
        version_label.setObjectName("VersionLabel")
        self.status_bar.addPermanentWidget(version_label)

        self.queue = []; self.current_worker = None; self.current_row = None
        self.should_continue_queue = False
        self.row_start_time = {}

        self.append_log(f"[APP] APP_DIR={APP_DIR}")
        
        # Auto-load existing files
        QTimer.singleShot(100, self.load_existing_files)
        
    def load_existing_files(self):
        if not self.backend_books.exists(): return
        
        # Gather all valid files
        files = []
        for p in self.backend_books.iterdir():
            if not p.is_file(): continue
            if p.name.startswith("."): continue # skip hidden files
            if "_bili" in p.name: continue
            if p.suffix.lower() == '.json': continue
            if p.suffix.lower() not in ['.epub', '.txt', '.srt', '.md', '.docx']: continue
            
            # Check modification time to sort
            files.append((p.stat().st_mtime, p))
            
        # Sort by modification time (newest first)
        files.sort(key=lambda x: x[0], reverse=True)
        
        count = 0
        for _, p in files:
            self._add_job_internal(str(p), skip_copy=True, auto_run=False)
            count += 1
            
        if count > 0:
            self.append_log(f"[AutoLoad] Loaded {count} existing files from {self.backend_books}")
        
    def switch_view(self, index):
        self.stack.setCurrentIndex(index)
        # Update sidebar state if needed (though QToolButton with autoExclusive handles visual toggle)
        
    def toggle_log_panel(self):
        visible = self.log_panel.isVisible()
        self.log_panel.setVisible(not visible)
        if not visible:
            # If opening, ensure it has width
            current_sizes = self.task_splitter.sizes()
            if len(current_sizes) >= 2 and current_sizes[1] == 0:
                total = sum(current_sizes)
                # Give log panel ~30% width
                new_log_width = int(total * 0.3)
                new_task_width = total - new_log_width
                self.task_splitter.setSizes([new_task_width, new_log_width])
        
    def on_settings_cancel(self):
        self.settings_widget.revert_settings()
        self.switch_view(0)
        self.sidebar.btn_settings.setChecked(False)
        
    def pick_files(self):
        # Ensure we are on task view
        self.switch_view(0)
        
        files, _ = QFileDialog.getOpenFileNames(self, "選擇檔案", str(Path.home()), "Supported (*.epub *.txt *.srt *.docx *.md);;All Files (*)")
        for f in files:
            p = Path(f)
            if self._is_supported_source(p): self.add_job_and_run_immediately(f)

    def _is_supported_source(self, p: Path) -> bool:
        suffix_ok = p.suffix.lower() in {".epub",".txt",".srt", ".docx", ".md"}
        reject = ("_bili" in p.stem.lower()) or (".temp" in p.name.lower()) or p.name.lower().endswith(".log")
        if not suffix_ok:
            # Special hint for .doc
            if p.suffix.lower() == ".doc":
                QMessageBox.critical(self, "不支援的檔案", f"不支援舊版 Word (.doc)。\n請先另存為 .docx 格式再試。\n{p}")
            else:
                QMessageBox.critical(self, "不支援的檔案", f"只支援：.epub, .txt, .srt, .docx, .md\n{p}")
            return False
        if reject:
            QMessageBox.critical(self, "無效的輸入", "這看起來是輸出檔或暫存檔（*_bili.*, *.temp*, *.log*），請不要丟入。"); return False
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
        # If task list is empty, force user to review settings first
        if self.task_list.count() == 0:
            self.pending_filepaths.append(filepath)
            
            # Switch to settings view
            self.stack.setCurrentIndex(1)
            self.sidebar.btn_settings.setChecked(True)
            
            # Show a message in status bar
            self.status_label.setText("請先確認設定參數，完成後按「儲存設定」開始翻譯")
            return
        
        # If tasks exist, just add directly
        self._add_job_internal(filepath)

    def _add_job_internal(self, filepath: str, skip_copy: bool = False, auto_run: bool = True):
        src = Path(filepath); dst = self.backend_books / src.name
        
        copy_status = "Skipped"
        if not skip_copy:
            try:
                # If src and dst are the same, don't copy
                if src.resolve() != dst.resolve():
                    shutil.copy2(src, dst)
                    copy_status = "Created" if not dst.exists() else "Overwritten"
                else:
                    copy_status = "Same File"
            except Exception as e:
                QMessageBox.critical(self, "複製檔案失敗", f"{e}"); return
        else:
             # Even if skip_copy is True, ensure file exists
             if not dst.exists():
                 self.append_log(f"[Error] File not found for autoload: {dst}")
                 return

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
        
        # Show task list instead of empty state
        self.task_stack.setCurrentIndex(1)
        
        row = self.task_list.row(item) # Get row index

        self.append_log(f"[SOURCE] {src}  →  {dst} | COPY={copy_status}")
        
        if auto_run:
            self.queue.append(row)
            self.run_next(resume=False)



    def build_args(self, cfg: dict, row: int, resume: bool) -> List[str]:
        # No longer checking for make_book.py existence since we import it
        
        prompt_path = cfg.get("prompt") or "prompt.json"

        item = self.task_list.item(row)
        origin_name = item.data(ROLE_ORIGIN_NAME)
        
        if "_bili" in origin_name.lower():
            origin_name = origin_name.lower().replace("_bili","")


        # Use relative path for book name, assuming CWD is set correctly
        book_rel_path = f"books/{origin_name}"
        model_type = cfg.get("model", "chatgptapi")
        
        # Construct args list (not command string)
        args = [
                "--model", model_type,
                "--language", cfg["language"],
                "--temperature", str(cfg["temperature"]),
                "--prompt", prompt_path,
                "--book_name", book_rel_path]
        
        if model_type == "chatgptapi":
            if cfg.get("ollama_model"):
                args.extend(["--ollama_model", cfg["ollama_model"]])
            else:
                # For cloud OpenAI models (gpt-5, gpt-4o, etc.), we should use 'openai' model type
                # and pass the specific model name via --model_list
                selected_model = cfg.get("selected_model_display")
                if selected_model and not selected_model.startswith("gpt-4o"):
                     # Update the model argument in the list to 'openai'
                     try:
                        idx = args.index("--model")
                        args[idx + 1] = "openai"
                        args.extend(["--model_list", selected_model])
                     except ValueError:
                        pass
        
        if model_type == "gemini":
            # Pass the specific Gemini model (e.g. gemini-2.5-pro) as model_list
            selected_model = cfg.get("selected_model_display")
            if selected_model:
                args.extend(["--model_list", selected_model])
        
        if cfg.get("use_accumulated", False):
            args.extend(["--accumulated_num", str(cfg.get("accumulated_num", 800))])

        # if cfg.get("use_context", False):
        #     args.append("--use_context")

        if not cfg.get("use_glossary", True):
            args.append("--no_glossary")

        if not cfg.get("bilingual", True):
            args.append("--single_translate")

        if resume: args.append("--resume")

        if cfg.get("interval"):
            args.extend(["--interval", str(cfg.get("interval"))])

        return args

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



    def run_next(self, resume: bool):
        if self.current_worker or not self.queue: return
        
        # Default: We want to continue unless stopped explicitly
        self.should_continue_queue = True
        self.append_log(f"[Scheduler] Starting next task. Queue remaining: {len(self.queue)-1}")
        
        r = self.queue.pop(0); self.current_row = r
        
        item = self.task_list.item(r)
        card = self.task_list.itemWidget(item)
        
        # Determine the display string effectively
        if self.cfg.get("model") == "gemini":
            model_display = self.cfg.get("selected_model_display", "gemini")
        elif self.cfg.get("model") == "chatgptapi":
             if self.cfg.get("ollama_model"):
                 model_display = self.cfg.get("ollama_model")
             else:
                 model_display = self.cfg.get("selected_model_display", "gpt-4o")
        else:
             model_display = self.cfg.get("model", "Unknown")

        if hasattr(card, 'set_model'):
            card.set_model(model_display)
        
        card.update_status("執行中…", 0, "00:00", "00:00")
        self.row_start_time[r] = time.time()

        args = self.build_args(self.cfg, r, resume=resume)
        # if not args: # build_args always returns list
        #     card.update_status("失敗")
        #     self.run_next(resume=resume); return
            
        self.append_log(f"$ Direct Call: {args}")
        self.status_label.setText(f"正在翻譯: {item.data(ROLE_ORIGIN_NAME)} ...")

        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env["COLUMNS"] = "1000"  # Prevent rich from wrapping text too early
        model_type = self.cfg.get("model", "chatgptapi")
        if model_type == "gemini":
            g_key = self.cfg.get("google_api_key", "").strip()
            if g_key: env["GOOGLE_API_KEY"] = g_key
        elif model_type == "chatgptapi":
            if not self.cfg.get("ollama_model"):
                o_key = self.cfg.get("openai_api_key", "").strip()
                if o_key: env["OPENAI_API_KEY"] = o_key
        # No need to set PYTHONPATH for direct call as we are in the same process
        # But we still need to set environment variables for API keys
        
        # Run in USER_DATA_DIR so logs and temp files are written there
        self.current_worker = DirectWorker(args, str(USER_DATA_DIR), env=env)
        self.current_worker.stdout_line.connect(lambda line, row=r: self.on_stdout(row, line))
        self.current_worker.stderr_line.connect(lambda line, row=r: self.on_stderr(row, line))
        self.current_worker.done.connect(lambda rc, msg, row=r: self.on_done(row, rc, msg))
        # Handle thread lifecycle properly
        self.current_worker.finished.connect(lambda row=r, resume_flag=resume: self.on_worker_finished(row, resume_flag))
        self.current_worker.start()

    def on_stdout(self, row: int, line: str):
        self.append_log(line)
        self._parse_progress(row, line)

    def on_stderr(self, row: int, line: str):
        self.append_log(line)
        self._parse_progress(row, line)

    def _parse_progress(self, row: int, line: str):
        # Prevent progress update from overwriting "Pause" status if stopped
        if global_state.is_cancelled:
            return

        # Prevent progress update from overwriting "Completed" or "Failed" status
        # This fixes the bug where late logs reset the status to "Running"
        try:
            item = self.task_list.item(row)
            if item:
                card = self.task_list.itemWidget(item)
                if card:
                    status_text = card.lbl_status.text()
                    if "完成" in status_text or "失敗" in status_text or "暫停" in status_text:
                        return
        except Exception:
            pass

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
        errors = []
        
        try:
            if src_path.exists(): src_path.unlink()
        except Exception as e:
            errors.append(f"無法刪除來源檔: {e}")
            
        # 2. Delete output files (e.g. *_bili.epub)
        stem = Path(origin_name).stem
        files_to_delete = []
        files_to_delete.extend(self.backend_books.glob(f"{stem}_bili.*"))
        files_to_delete.extend(self.backend_books.glob(f"{stem}_bili_temp.*"))
        files_to_delete.extend(self.backend_books.glob(f"{stem}_temp.*"))
        files_to_delete.append(self.backend_books / f"{stem}_nouns.json")
        files_to_delete.append(self.backend_books / f".{stem}.temp.bin")

        for p in files_to_delete:
            if p.exists():
                try:
                    p.unlink()
                except Exception as e:
                    errors.append(f"無法刪除 {p.name}: {e}")
        
        self.task_list.takeItem(row) # This removes it from list
        
        if errors:
            self.append_log(f"刪除失敗: {origin_name} (細節: {'; '.join(errors)})")
        else:
            self.append_log(f"刪除完成: {origin_name}")
        
        # Show empty state if no items left
        if self.task_list.count() == 0:
            self.task_stack.setCurrentIndex(0)



    def on_done(self, row: int, rc: int, msg: str):
        # NOTE: Do NOT destroy self.current_worker here. It is still running (emitting this signal).
        # We just update UI and set the flag for the finished() handler.
        
        start = self.row_start_time.get(row, time.time())
        elapsed = max(0, int(time.time() - start))
        
        item = self.task_list.item(row)
        card = self.task_list.itemWidget(item)
        
        status = "失敗"
        
        # High priority check for cancellation
        if global_state.is_cancelled or "已暫停" in msg:
            status = "暫停"
            card.update_status(status, 0, self._fmt_sec(elapsed), "00:00")
            self.should_continue_queue = False
        elif rc == 0:
            status = "完成 (v1.2.7)" # Keep UI clean
            card.update_status(status, 100, self._fmt_sec(elapsed), "00:00")
            # Ensure we continue
            self.should_continue_queue = True
        else:
            status = "失敗"
            card.update_status(status, 0, self._fmt_sec(elapsed), "00:00")
            # self.should_continue_queue = True 

            
        self.append_log(msg)

        # File moving logic remains here as it's UI/Business logic, not thread management
        try:
            origin_name = item.data(ROLE_ORIGIN_NAME)
            stem = Path(origin_name).stem
            latest = self._find_latest_output(self.backend_books, stem)
            if latest:
                # Get output directory from config, default to Desktop
                out_dir_str = self.cfg.get("output_dir", "")
                if not out_dir_str or out_dir_str.strip() == "":
                    out_dir = Path.home() / "Desktop"
                else:
                    out_dir = Path(out_dir_str).expanduser().resolve()
                
                # Safety check: if out_dir is home root, fallback to Desktop to avoid permission issues
                if out_dir == Path.home():
                    self.append_log(f"[警告] 輸出目錄設為使用者根目錄 ({out_dir}) 可能導致權限問題，自動改為桌面。")
                    out_dir = Path.home() / "Desktop"

                out_dir.mkdir(parents=True, exist_ok=True)
                target = out_dir / latest.name
                
                self.append_log(f"[搬移] 來源: {latest} -> 目標: {target}")
                shutil.copy2(latest, target)
                self.append_log(f"[輸出] {target}")
                self.append_log(f"✅ 翻譯完成！已輸出：{target}")
        except Exception as e:
            self.append_log(f"[搬移輸出] 失敗：{e}")
            # Fallback to Desktop
            try:
                fallback_dir = Path.home() / "Desktop"
                fallback_dir.mkdir(parents=True, exist_ok=True)
                target = fallback_dir / latest.name
                self.append_log(f"[自動修正] 嘗試改存到桌面: {target}")
                shutil.copy2(latest, target)
                self.append_log(f"✅ 翻譯完成！已輸出到桌面：{target}")
            except Exception as e2:
                self.append_log(f"[搬移輸出] 再次失敗 (桌面): {e2}")

    def on_worker_finished(self, row: int, resume: bool):
        self.append_log(f"[Scheduler] Worker finished for row {row}. Checking queue...")
        # Now it is safe to cleanup the worker
        self.current_worker = None
        self.current_row = None
        self.status_label.setText("就緒")
        
        if self.should_continue_queue:
            self.append_log("[Scheduler] Queue active, running next...")
            self.run_next(resume=resume)
        else:
            self.append_log("[Scheduler] Queue stopped (should_continue_queue=False).")
            pass

    def stop_current(self):
        if not self.current_worker:
            return

        self.append_log("[STOP] 收到停止信號，正在等待當前批次完成...")
        self.status_label.setText("收到停止信號，正在等待當前批次完成...")
        
        if self.current_worker.isRunning():
            # Crucial Fix: Do NOT use terminate() as it causes SegFaults (Exit Code 139)
            # Instead, set the cancellation flag and let the thread exit gracefully.
            if hasattr(self.current_worker, 'terminate_job'):
                self.current_worker.terminate_job()
            else:
                 # Fallback if method missing
                 global_state.is_cancelled = True
                 
            # Disable the Stop button momentarily can be good, but here we just rely on the log
            # We do NOT wait() here to avoid freezing the UI. 
            # The thread will emit 'done' when it finishes loop.
        else:
             # If not running but somehow state lingers
             # But we should ensure the UI updates if the thread was stuck
             self.on_done(self.current_row, 1, "已暫停", False)

    def append_log(self, text: str):
        # 寫入 UI
        if hasattr(self, 'log_text'):
            self.log_text.append(text)
            self.log_text.ensureCursorVisible()

    def _fmt_sec(self, s: int) -> str:
        s = int(max(0, s)); m, s = divmod(s, 60); h, m = divmod(m, 60)
        return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"

    def closeEvent(self, event):
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("windowState", self.saveState())
        super().closeEvent(event)

    def _find_latest_output(self, books_dir: Path, stem: str) -> Optional[Path]:
        # Prefer _bili.* over _bilingual.*
        cands = [p for p in books_dir.glob(f"{stem}_bili.*") if p.is_file()]
        
        if not cands: return None
        cands.sort(key=lambda p: p.stat().st_mtime, reverse=True); return cands[0]

    def clear_log(self):
        self.log_text.clear()

    def load_stylesheet(self):
        style_path = APP_DIR / "gui" / "styles" / "dark_theme.qss"
        if style_path.exists():
            try:
                qss = style_path.read_text(encoding="utf-8")
                # Replace relative icon paths with absolute paths
                # Use as_posix() to ensure forward slashes on Windows/macOS for CSS url()
                icons_root = ICONS_DIR.as_posix()
                # Handle optional quotes in the original QSS: url("icons/...") or url(icons/...)
                # Replacement always uses quotes: url("ABSOLUTE_PATH/...")
                qss = re.sub(r'url\((["\']?)icons/([^)]+)\1\)', f'url("{icons_root}/\\2")', qss)
                self.setStyleSheet(qss)
                self.append_log(f"[Theme] Loaded dark theme from {style_path}")
            except Exception as e:
                print(f"Failed to load stylesheet: {e}")
                self.append_log(f"[Theme] Failed to load stylesheet: {e}")
        else:
            print(f"Stylesheet not found: {style_path}")
            self.append_log(f"[Theme] Stylesheet not found: {style_path}")

def main():
    print("Starting main...")
    app = QApplication(sys.argv)
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
    import multiprocessing
    multiprocessing.freeze_support()
    main()

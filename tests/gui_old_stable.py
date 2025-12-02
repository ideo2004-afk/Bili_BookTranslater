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
    QGroupBox, QSizePolicy, QMenu, QStatusBar
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

class SettingsDialog(QDialog):
    def __init__(self, cfg: dict, backend_dir: Path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("翻譯設定")
    def __init__(self, cfg: dict, backend_dir: Path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("翻譯設定")
        self.setMinimumSize(500, 550)
        self.cfg = cfg.copy()
        
        layout = QVBoxLayout(self)

        # --- Group 1: 模型設定 ---
        grp_model = QGroupBox("模型設定")
        form_model = QFormLayout(grp_model)
        
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
        # 優先使用 ollama_model，如果沒有則檢查 model
        current_model = self.cfg.get("ollama_model")
        if not current_model or current_model == "qwen3:8b": # 舊預設值
             # 如果 cfg 中有指定 model 為 gemini，則優先顯示
             if self.cfg.get("model") == "gemini":
                 current_model = "gemini-3-pro-preview" # Default to newest
             elif self.cfg.get("model") == "chatgptapi" and not self.cfg.get("ollama_model"):
                 current_model = "gpt-4o"
             elif ollama_models:
                 current_model = ollama_models[0]
             else:
                 current_model = "gemini-3-pro-preview"

        self.model_combo.setCurrentText(current_model)
            
        self.lang = QComboBox(); self.lang.setEditable(False)
        
        # 定義顯示名稱與代碼的對應
        self.lang_map = {
            "繁體中文": "zh-hant",
            "英文": "en",
            "日文": "ja",
            "韓文": "ko",
            "法文": "fr",
            "西班牙文": "es",
            "德文": "de",
            "義大利文": "it"
        }
        self.lang.addItems(list(self.lang_map.keys()))
        
        # 設定預設選中項 (根據代碼反查顯示名稱)
        current_code = self.cfg.get("language", "zh-hant")
        default_display = "繁體中文"
        for name, code in self.lang_map.items():
            if code == current_code:
                default_display = name
                break
        self.lang.setCurrentText(default_display)
        self.lang.currentTextChanged.connect(self.on_language_changed)

        self.temp = QDoubleSpinBox(); self.temp.setRange(0.0, 2.0); self.temp.setDecimals(2); self.temp.setSingleStep(0.1)
        self.temp.setValue(float(self.cfg.get("temperature", 0.5)))

        # Prompt Selection (ComboBox)
        self.prompt = QComboBox()
        self.prompt.setEditable(True)  # Allow manual entry or new filenames
        
        # Scan for prompt files
        prompt_files = sorted([f.name for f in APP_DIR.glob("prompt*.json")])
        if not prompt_files:
            prompt_files = ["prompt.json"]
            
        self.prompt.addItems(prompt_files)
        
        # Set current selection
        current_prompt = self.cfg.get("prompt", "prompt.json")
        if current_prompt in prompt_files:
            self.prompt.setCurrentText(current_prompt)
        else:
            self.prompt.setEditText(current_prompt)
            
        # API Key Inputs
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
        
        layout.addWidget(grp_model)

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

        # 累積字數
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
        
        layout.addWidget(grp_adv)

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
        layout.addWidget(gb_out)

        # --- Buttons ---
        btns = QDialogButtonBox()
        btns.setStandardButtons(QDialogButtonBox.Cancel | QDialogButtonBox.Ok)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def on_language_changed(self, text):
        """當語言改變時，不再自動切換 Prompt，避免混淆"""
        pass

    def pick_output_dir(self):
        d = QFileDialog.getExistingDirectory(self, "選擇輸出目錄", self.out_dir_edit.text() or str(Path.home()/ "Desktop"))
        if d: self.out_dir_edit.setText(d)

    def get_config(self) -> dict:
        cfg = self.cfg.copy()
        # 將顯示名稱轉換回語言代碼
        selected_display = self.lang.currentText().strip()
        
        # 判斷模型類型
        selected_model = self.model_combo.currentText().strip()
        if selected_model.lower().startswith("gemini"):
            model_type = "gemini"
            ollama_model = "" # 清空 ollama_model
        elif selected_model.lower().startswith("gpt"):
            model_type = "chatgptapi" # OpenAI 使用 chatgptapi
            ollama_model = "" 
        else:
            # 假設是 Ollama 模型
            model_type = "chatgptapi"
            ollama_model = selected_model

        cfg.update({
            "model": model_type,
            "ollama_model": ollama_model,
            "selected_model_display": selected_model, # 暫存顯示用
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
        return cfg

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
        self.resize(1120, 680)
        self.setAcceptDrops(True)
        self.setUnifiedTitleAndToolBarOnMac(True)  # macOS 統一標題列與工具列風格

        # Restore geometry
        self.settings = QSettings("BilingualBookMaker", "GUI")
        if self.settings.value("geometry"):
            self.restoreGeometry(self.settings.value("geometry"))
        if self.settings.value("windowState"):
            self.restoreState(self.settings.value("windowState"))

        self._build_toolbar()

        # 設置表格
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["檔案", "模型", "狀態", "進度", "耗時", "還需", "輸出路徑"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for i in range(1, 7):
            self.table.horizontalHeader().setSectionResizeMode(i, QHeaderView.ResizeToContents)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_table_context_menu)
        
        # 設置狀態列
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("就緒")

        # 設置日誌區域
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        
        # 使用 Splitter 分割畫面
        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(self.table)
        
        # 下方區域容器 (包含標籤與 Log)
        bottom_widget = QWidget()
        bottom_layout = QVBoxLayout(bottom_widget)
        bottom_layout.setContentsMargins(5, 5, 5, 5)
        
        # Log 標題列 (標籤 + 清除按鈕)
        log_header = QHBoxLayout()
        log_header.addWidget(QLabel("執行日誌："))
        log_header.addStretch()
        btn_clear = QPushButton("清除日誌")
        btn_clear.setFixedSize(80, 26)
        btn_clear.clicked.connect(self.log_view.clear)
        log_header.addWidget(btn_clear)
        
        bottom_layout.addLayout(log_header)
        bottom_layout.addWidget(self.log_view)
        splitter.addWidget(bottom_widget)

        # 設定 Splitter 初始比例 (約 2:1)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 1)

        self.setCentralWidget(splitter)

        self.queue = []; self.current_worker = None; self.current_row = None
        self.row_start_time = {}
        self.elapsed_timer = QTimer(self); self.elapsed_timer.timeout.connect(self._tick_elapsed)
        self.elapsed_timer.start(3000)

        self.append_log(f"[APP] APP_DIR={APP_DIR}")
        self.append_log(f"[APP] BACKEND_DIR={self.backend_dir} 存在={self.backend_dir.exists()}")
        self.append_log(f"[APP] make_book.py={self.backend_dir/'make_book.py'} 存在={(self.backend_dir/'make_book.py').exists()}")

    def _build_toolbar(self):
        tb = QToolBar()
        tb.setObjectName("MainToolbar")
        tb.setIconSize(QSize(20, 20))  # 稍微縮小圖示以符合原生風格
        tb.setMovable(False)
        tb.setFloatable(False)
        tb.setToolButtonStyle(Qt.ToolButtonIconOnly)  # 僅顯示圖示，不顯示文字
        
        # 載入 SVG 圖示
        def load_icon(name):
            icon_path = ICONS_DIR / f"{name}.svg"
            if icon_path.exists():
                return QIcon(str(icon_path))
            return QIcon()
        
        # 依照範例圖風格排列： [新增] | [執行] [停止] [刪除] ...
        # Action: 新增
        act_add = tb.addAction(load_icon("plus"), "新增檔案")
        act_add.triggered.connect(self.pick_files)
        
        tb.addSeparator() # 分隔線
        
        # Action: 執行
        act_run = tb.addAction(load_icon("play"), "執行")
        act_run.triggered.connect(self.run_selected_with_choice)
        
        # Action: 停止
        act_stop = tb.addAction(load_icon("x"), "停止")
        act_stop.triggered.connect(self.stop_current)

        tb.addSeparator() # 分隔線

        # Action: 刪除
        act_del = tb.addAction(load_icon("trash"), "刪除")
        act_del.triggered.connect(self.delete_item)
        
        # Action: 開啟資料夾
        act_folder = tb.addAction(load_icon("folder"), "開啟輸出目錄")
        act_folder.triggered.connect(self.open_output_dir)
        
        self.addToolBar(Qt.TopToolBarArea, tb)

        pref = QAction("Preferences…", self); pref.setMenuRole(QAction.PreferencesRole); pref.triggered.connect(self.open_preferences)
        self.menuBar().addMenu("&File").addAction(pref)



    def show_table_context_menu(self, pos: QPoint):
        index = self.table.indexAt(pos)
        if not index.isValid():
            return
            
        menu = QMenu(self)
        
        action_open_src = QAction("開啟來源檔案位置", self)
        action_open_src.triggered.connect(lambda: self._open_file_location(index.row(), ROLE_ORIGIN_PATH))
        menu.addAction(action_open_src)
        
        action_open_out = QAction("開啟輸出資料夾", self)
        action_open_out.triggered.connect(self.open_output_dir)
        menu.addAction(action_open_out)
        
        menu.addSeparator()
        
        action_remove = QAction("從列表中移除", self)
        action_remove.triggered.connect(self.delete_selected_source_and_outputs)
        menu.addAction(action_remove)
        
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _open_file_location(self, row, role):
        path_str = self.table.item(row, 0).data(role)
        if path_str:
            p = Path(path_str)
            if p.exists():
                subprocess.run(["open", "-R", str(p)]) # macOS specific
            else:
                QMessageBox.warning(self, "找不到檔案", f"檔案不存在：\n{p}")

    def open_output_dir(self):
        out_dir = Path(self.cfg.get("output_dir", str(Path.home()/"Desktop"))).expanduser()
        try:
            out_dir.mkdir(parents=True, exist_ok=True); subprocess.run(["open", str(out_dir)])
        except Exception as e:
            QMessageBox.critical(self, "開啟失敗", str(e))

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls(): e.acceptProposedAction()
    def dropEvent(self, e):
        for url in e.mimeData().urls():
            p = Path(url.toLocalFile())
            if p.is_file():
                if self._is_supported_source(p): self.add_job_and_run_immediately(str(p))
            else:
                QMessageBox.critical(self, "不支援", "目前只支援拖入檔案（非資料夾）。")

    def _is_supported_source(self, p: Path) -> bool:
        suffix_ok = p.suffix.lower() in {".epub",".txt",".srt"}
        reject = ("_bilingual" in p.stem.lower()) or (".temp" in p.name.lower()) or p.name.lower().endswith(".log")
        if not suffix_ok:
            QMessageBox.critical(self, "不支援的檔案", f"只支援：.epub, .txt, .srt\n{p}"); return False
        if reject:
            QMessageBox.critical(self, "無效的輸入", "這看起來是輸出檔或暫存檔（*_bilingual.*, *.temp*, *.log*），請不要丟入。"); return False
        return True

    def pick_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "選擇檔案", str(Path.home()), "Supported (*.epub *.txt *.srt);;All Files (*)")
        for f in files:
            p = Path(f)
            if self._is_supported_source(p): self.add_job_and_run_immediately(f)

    def add_job_and_run_immediately(self, filepath: str):
        d = SettingsDialog(self.cfg, self.backend_dir, parent=self)
        if d.exec() != QDialog.Accepted: return
        self.cfg = d.get_config(); save_config(self.cfg)

        src = Path(filepath); dst = self.backend_books / src.name
        try:
            shutil.copy2(src, dst)
            copy_status = "Created" if not dst.exists() else "Overwritten"
        except Exception as e:
            QMessageBox.critical(self, "複製檔案失敗", f"{e}"); return

        row = self.table.rowCount(); self.table.insertRow(row)
        item0 = QTableWidgetItem(src.name)
        item0.setToolTip(str(dst))
        item0.setData(ROLE_ORIGIN_NAME, src.name)
        item0.setData(ROLE_ORIGIN_PATH, str(src))
        self.table.setItem(row, 0, item0)
        # 顯示選擇的模型名稱 (可能是 ollama, gemini, 或 gpt)
        self.table.setItem(row, 1, QTableWidgetItem(self.cfg.get("selected_model_display", self.cfg.get("ollama_model", "chatgptapi"))))
        self.table.setItem(row, 2, QTableWidgetItem("準備中"))
        self.table.setItem(row, 3, QTableWidgetItem("0%"))
        self.table.setItem(row, 4, QTableWidgetItem("00:00"))
        self.table.setItem(row, 5, QTableWidgetItem("00:00"))
        self.table.setItem(row, 6, QTableWidgetItem(self.cfg["output_dir"]))

        self.append_log(f"[SOURCE] {src}  →  {dst} | COPY={copy_status}")
        self.queue = [row]; self.run_next(resume=False)

    def open_preferences(self):
        d = SettingsDialog(self.cfg, self.backend_dir, parent=self)
        if d.exec() == QDialog.Accepted:
            self.cfg = d.get_config(); save_config(self.cfg)

    def build_cmd(self, cfg: dict, row: int, resume: bool) -> str:
        make_book = self.backend_dir / "make_book.py"
        if not make_book.exists():
            QMessageBox.critical(self, "找不到 make_book.py", f"{make_book}"); return "", Path()
        prompt_path = cfg.get("prompt") or "prompt.json"

        origin_name = self.table.item(row, 0).data(ROLE_ORIGIN_NAME) or Path(self.table.item(row, 0).text()).name
        if "_bilingual" in origin_name.lower():
            origin_name = origin_name.lower().replace("_bilingual","")

        # 修正：使用 APP_DIR 作為執行目錄，確保相對路徑與 CLI 行為一致
        # make_book.py 預期在專案根目錄執行，並讀取 books/ 下的檔案
        
        # 來源檔案相對於 APP_DIR 的路徑
        # 假設 backend_dir 就是 APP_DIR (通常是這樣)，如果不是，需要調整
        # 這裡直接使用 "books/filename" 格式，因為我們已經把檔案 copy 到 backend_books 了
        
        book_rel_path = f"books/{origin_name}"
        
        # 根據模型類型決定參數
        model_type = cfg.get("model", "chatgptapi")
        
        args = [sys.executable, str(self.backend_dir / "make_book.py"),
                "--model", model_type,
                "--language", cfg["language"],
                "--temperature", str(cfg["temperature"]),
                "--prompt", prompt_path,
                "--book_name", book_rel_path]
        
        # 只有當 model 是 chatgptapi 且有指定 ollama_model 時，才加入 --ollama_model
        # 注意：如果使用者選的是 gpt-*，model 也是 chatgptapi，但 ollama_model 會是空字串
        if model_type == "chatgptapi" and cfg.get("ollama_model"):
            args.extend(["--ollama_model", cfg["ollama_model"]])
        
        if cfg.get("use_accumulated", False):
            args.extend(["--accumulated_num", str(cfg.get("accumulated_num", 800))])

        if cfg.get("use_context", False):
            args.append("--use_context")

        # Glossary 現在是預設功能，但如果使用者取消勾選，則加入 --no_glossary
        if not cfg.get("use_glossary", True):
            args.append("--no_glossary")

        if not cfg.get("bilingual", True):
            args.append("--single_translate")

        if resume: args.append("--resume")

        q = lambda s: f'"{s}"' if " " in s else s
        return " ".join(q(a) for a in args)

    def run_selected_with_choice(self):
        rows = self._selected_rows_or_all_pending()
        if not rows:
            QMessageBox.information(self, "提示", "沒有可執行的項目。"); return
        if len(rows) == 1:
            ret = QMessageBox.question(self, "執行選項", "要從中斷點續跑（Resume）嗎？\n選 否 會從頭重跑。",
                                       QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel)
            if ret == QMessageBox.Cancel: return
            resume = (ret == QMessageBox.Yes)
        else:
            resume = bool(self.cfg.get("resume", False))

        if not resume:
            for r in rows:
                src_path = self.table.item(r,0).data(ROLE_ORIGIN_PATH)
                if not src_path: continue
                src = Path(src_path); dst = self.backend_books / Path(src_path).name
                try:
                    shutil.copy2(src, dst)
                    self.append_log(f"[REFRESH SOURCE] {src} → {dst} | Overwritten")
                except Exception as e:
                    QMessageBox.critical(self, "覆蓋來源檔失敗", f"{e}"); return

        self.queue = rows; self.run_next(resume=resume)

    def _selected_rows_or_all_pending(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        if not rows:
            rows = [r for r in range(self.table.rowCount())
                    if self.table.item(r,2).text() not in ("完成","執行中…")]
        return rows

    def run_next(self, resume: bool):
        if self.current_worker or not self.queue: return
        r = self.queue.pop(0); self.current_row = r
        self.table.setItem(r, 2, QTableWidgetItem("執行中…"))
        self.row_start_time[r] = time.time()
        self.table.setItem(r, 3, QTableWidgetItem("0%"))
        self.table.setItem(r, 4, QTableWidgetItem("00:00"))
        self.table.setItem(r, 5, QTableWidgetItem("00:00"))

        cmd = self.build_cmd(self.cfg, r, resume=resume)
        if not cmd:
            self.table.setItem(r, 2, QTableWidgetItem("失敗")); self.run_next(resume=resume); return
        self.append_log(f"$ {cmd}")
        self.status_bar.showMessage(f"正在翻譯: {self.table.item(r, 0).text()} ...")

        # 準備環境變數
        env = os.environ.copy()
        model_type = self.cfg.get("model", "chatgptapi")
        
        if model_type == "gemini":
            g_key = self.cfg.get("google_api_key", "").strip()
            if g_key: env["GOOGLE_API_KEY"] = g_key
        elif model_type == "chatgptapi":
            # 只有當不是 Ollama 時才設定 OPENAI_API_KEY
            if not self.cfg.get("ollama_model"):
                o_key = self.cfg.get("openai_api_key", "").strip()
                if o_key: env["OPENAI_API_KEY"] = o_key

        # 修正：CWD 改為 APP_DIR，這樣 make_book.py 產生的暫存檔才會在預期位置 (APP_DIR/books/...)
        # 之前設為 backend_dir (通常也是 APP_DIR)，但為了保險起見，明確使用 APP_DIR
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
        # Strip ANSI escape codes (colors, etc) which might confuse regex
        ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
        clean_line = ansi_escape.sub('', line)

        # Parse progress: "Translating (Total: 556,637 tokens):  41%|████... "
        # or "Estimating:  29%|██▉       | 43/146 ..."
        # tqdm output often contains \r which might not be captured as a new line in some cases,
        # but here we receive lines.
        # We look for the pattern "N%|" which is characteristic of tqdm
        # We look for the pattern "N%|" which is characteristic of tqdm
        if "%|" in clean_line:
            try:
                # Extract percentage
                # Look for pattern like " 41%|"
                # Tqdm usually outputs " 41%|"
                # We use a simple regex that looks for digits followed by %|
                match = re.search(r'(\d+)%\|', clean_line)
                
                # Try to parse tqdm remaining time directly: [01:26<6:16:27,  2.90s/it]
                # Pattern: <(H:M:S)
                tqdm_time_match = re.search(r'<(\d+:\d+:?\d*),', clean_line)
                
                if match:
                    percent = int(match.group(1))
                    self.table.setItem(row, 3, QTableWidgetItem(f"{percent}%"))
                    
                    if tqdm_time_match:
                        remaining_str = tqdm_time_match.group(1)
                        # Ensure format is HH:MM:SS or MM:SS
                        parts = remaining_str.split(':')
                        if len(parts) == 2:
                            remaining_str = f"00:{remaining_str}"
                        self.table.setItem(row, 5, QTableWidgetItem(remaining_str))
                    else:
                        # Fallback to calculation if tqdm time not found
                        if percent > 0:
                            start = self.row_start_time.get(row)
                            if start:
                                elapsed = time.time() - start
                                if percent >= 1:
                                    total_estimated_time = elapsed / (percent / 100)
                                    remaining_time = total_estimated_time - elapsed
                                    self.table.setItem(row, 5, QTableWidgetItem(self._fmt_sec(int(remaining_time))))
                                else:
                                    self.table.setItem(row, 5, QTableWidgetItem("估計中"))
            except Exception as e:
                self.append_log(f"Error parsing progress: {e}")
            except Exception:
                pass

    def delete_item(self):
        row = self.table.currentRow()
        if row < 0: return
        
        # 取得檔案名稱與路徑資訊
        name_item = self.table.item(row, 0)
        origin_name = name_item.data(ROLE_ORIGIN_NAME) or Path(name_item.text()).name
        
        # 智慧解析 stem: 移除 _bilingual_temp 或 _bilingual 後綴
        stem = Path(origin_name).stem
        if stem.lower().endswith("_bilingual_temp"):
            stem = stem[:-15] # len("_bilingual_temp") = 15
        elif stem.lower().endswith("_bilingual"):
            stem = stem[:-10] # len("_bilingual") = 10
            
        # 定義要刪除的模式 (使用 glob 匹配以忽略副檔名大小寫差異)
        patterns = [
            f"{stem}.*",                                      # 原檔 (匹配所有副檔名，例如 OB.txt)
            f"{stem}_bilingual_temp.*",                       # 暫存輸出
            f"{stem}_bilingual.*",                            # 完成輸出
            f"{stem}_nouns.json",                             # Glossary 檔案
            f".{stem}.temp.bin"                               # 進度檔
        ]
        
        self.append_log(f"--- 開始刪除: {stem} ---")
        
        for pattern in patterns:
            # 使用 glob 找出所有符合的檔案
            matched_files = list(self.backend_books.glob(pattern))
            
            for fpath in matched_files:
                try:
                    if fpath.is_dir():
                        shutil.rmtree(fpath)
                    else:
                        os.remove(fpath)
                    self.append_log(f"已刪除: {fpath.name}")
                except Exception as e:
                    self.append_log(f"刪除失敗 {fpath.name}: {e}")

        self.table.removeRow(row)

    def _tick_elapsed(self):
        if self.current_row is None: return
        r = self.current_row
        start = self.row_start_time.get(r)
        if not start: return
        elapsed = max(0, int(time.time() - start))
        self.table.setItem(r, 4, QTableWidgetItem(self._fmt_sec(elapsed)))
        
        # Update ETA if we have progress
        try:
            progress_item = self.table.item(r, 3)
            if progress_item:
                text = progress_item.text().replace("%", "")
                if text.isdigit():
                    percent = int(text)
                    # Only update ETA here if we don't have a direct reading from tqdm
                    # But _tick_elapsed runs every second, while stdout might be slower.
                    # If we use calculation, it might jump around.
                    # Let's check if the current value looks like a calculated one or a tqdm one.
                    # Actually, if we parsed tqdm time, we should prefer that.
                    # But we don't store "source of truth".
                    
                    # Simplest approach: if we have a valid tqdm time in the cell, don't overwrite it with simple calculation
                    # unless it's "估計中" or empty.
                    current_eta = self.table.item(r, 5).text() if self.table.item(r, 5) else ""
                    if current_eta == "估計中" or not current_eta or percent > 0:
                         # If we are relying on calculation (fallback), update it.
                         # But how do we know if we are relying on calculation?
                         # Maybe we just update it if percent > 0.
                         
                         # Wait, if on_stdout parsed tqdm time, it updated the cell.
                         # _tick_elapsed will overwrite it immediately if we are not careful.
                         # Let's Skip updating ETA in _tick_elapsed for now, and rely on on_stdout for ETA updates.
                         # Because on_stdout receives updates frequently enough (every batch/paragraph).
                         pass
        except Exception:
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
    app = QApplication(sys.argv)
    apply_stylesheet(app)
    win = MainWindow(); win.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()

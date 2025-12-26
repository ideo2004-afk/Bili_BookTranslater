# Bili (AI 雙語電子書製作工具) v1.3.0

這是一個利用 AI (ChatGPT, Gemini, Ollama 等) 來協助翻譯 EPUB/TXT/SRT 電子書與字幕的工具。專為製作高品質的雙語電子書而設計，特別針對繁體中文環境台灣慣用語進行了優化。

---

## ✨ 主要功能

1. **多語雙向翻譯**：支援英文、日文、韓文、法文、西班牙文、德文、義大利文，翻譯到繁體中文，也支援任何語言原文書的反向翻譯（例如繁體中文翻譯成日文）。
2. **支援格式**：完整支援 EPUB / TXT / SRT / Word (.docx) / Markdown (.md) 格式檔案全文翻譯，大小不受任何限制。最適合翻譯大部頭電子書或完整論文。
3. **圖形化介面 (GUI)**：提供直覺的操作介面，支援拖放檔案、進度條顯示與即時日誌。使用者可直接拖放檔案到程式視窗，即可開始翻譯。
4. **雙語對照 (Bilingual)**：可選擇輸出為雙語對照格式，適合語言學習；亦可製作純翻譯版本。
5. **多模型支援**：
    *   **雲端模型**：支援 Google Gemini (Flash/Pro) 與 OpenAI (GPT-4o/mini)。
    *   **本地模型**：支援 Ollama (Llama 3, Qwen 3, Qwen 2.5, Gemma 3 等)，完全隱私且免費。
6. **排程處理 (Batch)**：可自動排程，一次處理多本書籍，大幅提高效率。
7. **智慧術語表 (Glossary)**：程式會自動提取並維護書中的人名、地名等專有名詞，確保整本書的翻譯一致性。
8. **斷點續傳 (Resume)**：翻譯到一半出錯或想暫停？隨時可以從中斷點繼續，不會浪費已翻譯的進度與 Token。
9. **並行處理**：支援多執行緒並行翻譯，大幅提升速度。

gui/assets/screenshot01.png

gui/assets/screenshot02.png

<img width="929" height="525" alt="截圖 2025-12-08 下午5 59 33" src="https://github.com/user-attachments/assets/9009fae9-375b-4406-a762-c70ae1824abf" />

<img width="931" height="681" alt="截圖 2025-12-08 下午5 59 49" src="https://github.com/user-attachments/assets/a927b0b6-504d-47f6-b32e-6df3ac1b61ac" />


---

## 📢 最新版本 (Release v1.3.0)

目前已釋出 **v1.3.0** 版本，提供包含 macOS 環境的 GUI 介面應用程式 (`.dmg`)，請至 [Releases](https://github.com/ideo2004-afk/Bili_BookTranslater/releases) 頁面下載使用。

*(初次執行若遇安全性阻擋，請至「系統設定」>「隱私權與安全性」> 選擇「仍要打開」)*

---

## 🚀 快速開始 (一鍵安裝與執行)

我們提供了自動化腳本，讓您無需懂程式碼也能輕鬆使用。

### macOS 使用者 (推薦)

1.  **安裝環境** (只需執行一次)：
    *   雙擊 `install.command`。腳本會自動建立環境並安裝必要套件。
2.  **啟動程式**：
    *   雙擊 `run_gui.command` 即可開啟介面。

### Windows 使用者

1.  **安裝環境** (只需執行一次)：
    *   雙擊 `install.bat`。
2.  **啟動程式**：
    *   雙擊 `run_gui.bat` 即可開啟介面。

---

## 📖 使用教學

1.  **設定 API Key**：
    *   開啟程式後，點擊左側「設定」圖示。
    *   選擇模型平台 (`gemini`, `chatgptapi`, `ollama`)。
    *   填入 API Key (Ollama 留空即可)。
2.  **加入書籍與開始**：
    *   將檔案 (`.epub`, `.txt`, `.srt`, `.docx`, `.md`) 拖入視窗，點擊「開始翻譯」。

---

## ⚙️ 關於進階參數

為了確保翻譯品質與穩定性，部分參數由程式自動管理，不建議使用者手動調整：

*   **Accumulated Num (批次處理量)**：
    *   程式會自動根據所選模型調整每次傳送給 AI 的文字量，以達到最佳速度與品質平衡。
*   **Request Interval (請求間隔)**：
    *   程式固定設有安全間隔時間，防止因請求過快而導致 API 封鎖 (Rate Limit)，確保長時間翻譯任務的穩定性。

---

## 🛠️ 常見問題 (FAQ)

**Q: 翻譯看不到進度？**
A: 進度條會在翻譯幾個段落後，自動顯示。亦可點擊左側的「日誌」圖示，查看詳細的翻譯進度。尤其需檢查雲端模型是否有正確填入 API Key。

**Q: 翻譯到一半程式當掉怎麼辦？**
A: 直接重新啟動程式，再次點擊該書籍並按「開始翻譯」。程式會自動偵測並詢問是否從中斷點續傳 (Resume)，選擇「是」即可完美銜接。

**Q: 為什麼本地 Ollama 翻譯比較慢？**
A: 本地模型的速度完全取決於您的電腦顯卡 (GPU) 效能。若速度過慢，建議改用 Gemini Flash 等雲端模型，既便宜又快速。

**Q: 翻譯出來的繁體中文怪怪的？**
A: 請確認您在設定中選擇了 `prompt_繁中`，這會確保翻譯出的繁體中文風格更為自然，並使用台灣慣用語。此外，不同模型 (如 GPT-4 與 Llama 3) 的中文能力本身就有差異，建議嘗試更換模型。

---

## ⚠️ 免責聲明

本工具僅供個人學習與研究使用。請勿用於翻譯有版權爭議的書籍並進行散布。使用者需自行承擔使用本工具所產生的一切法律責任。

---

## 🔧 實用小工具 (進階)

本專案附帶了一些實用的命令列工具，供進階使用者使用：

### 雙語轉單語工具 (`2single.py`)
如果您已經製作了雙語對照的 EPUB 電子書，但想要一個「純中文」的乾淨閱讀版本，可以使用此腳本快速轉換。

*   **功能**：自動辨識並移除雙語 EPUB 中的英文段落，只保留中文內容。
*   **用法**：
    1. 開啟終端機 (Terminal)。
    2. 執行指令：
       ```bash
       python 2single.py "您的電子書.epub"
       ```
    3. 程式會自動產生一個檔名結尾為 `_Single.epub` 的純中文版本。


## Support

If you find this plugin useful and would like to support its development, please consider buying me a coffee:

<a href="https://buymeacoffee.com/ideo2004c" target="_blank"><img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" alt="Buy Me A Coffee" style="height: 60px !important;width: 217px !important;" ></a>

## License

MIT


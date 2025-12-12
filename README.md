# Bili (AI Bilingual E-book Tool) v1.2.5

This is a tool that utilizes AI (ChatGPT, Gemini, Ollama, etc.) to assist in translating EPUB/TXT/SRT e-books and subtitles. Designed for creating high-quality bilingual e-books, specifically optimized for Traditional Chinese (Taiwan) usage.

---

## ✨ Key Features

1. **Multi-language Bidirectional Translation**: Supports translation to Traditional Chinese from English, Japanese, Korean, French, Spanish, German, and Italian. Also supports reverse translation from any source language (e.g., Traditional Chinese to Japanese).
2. **Supported Formats**: Full support for EPUB / TXT / SRT / Word (.docx) / Markdown (.md) full-text translation, with no file size limits. Perfect for translating large e-books or complete academic papers.
3. **Graphical User Interface (GUI)**: Intuitive interface supporting drag-and-drop, progress bars, and real-time logs. Simply drag files into the window to start translating.
4. **Bilingual Support**: Option to output in bilingual format (great for language learning) or pure translation.
5. **Multi-Model Support**:
    *   **Cloud Models**: Supports Google Gemini (Flash/Pro) and OpenAI (GPT-4o/mini).
    *   **Local Models**: Supports Ollama (Llama 3, Qwen 3, Qwen 2.5, Gemma 3, etc.), ensuring complete privacy and free usage.
6.  **Batch Processing**: Automatically schedules and processes multiple books for maximum efficiency.
7.  **Smart Glossary**: Automatically extracts and maintains proper nouns (names, places) to ensure consistency throughout the book.
8.  **Resume Capability**: Encountered an error or want to pause? You can resume from the interruption point at any time without wasting previous progress or tokens.
9.  **Parallel Processing**: Supports multi-threaded parallel translation for significantly faster speeds.

gui/assets/screenshot01.png

gui/assets/screenshot02.png

<img width="929" height="525" alt="Screenshot 1" src="https://github.com/user-attachments/assets/9009fae9-375b-4406-a762-c70ae1824abf" />

<img width="931" height="681" alt="Screenshot 2" src="https://github.com/user-attachments/assets/a927b0b6-504d-47f6-b32e-6df3ac1b61ac" />


---

## 📢 Latest Release (v1.2.2)

**v1.2.2** is now available, including a GUI application for macOS (`.dmg`). Please download it from the [Releases](https://github.com/ideo2004-afk/Bili_BookTranslater/releases) page.

*(If blocked by security settings on first run, go to "System Settings" > "Privacy & Security" > Select "Open Anyway")*

---

## 🚀 Quick Start (One-Click Install & Run)

We provide automated scripts so you can use the tool easily without needing coding knowledge.

### macOS Users (Recommended)

1.  **Install Environment** (Run once):
    *   Double-click `install.command`. The script will automatically set up the environment and install necessary packages.
2.  **Start Application**:
    *   Double-click `run_gui.command` to open the interface.

### Windows Users

1.  **Install Environment** (Run once):
    *   Double-click `install.bat`.
2.  **Start Application**:
    *   Double-click `run_gui.bat` to open the interface.

---

## 📖 Usage Guide

1.  **Set API Key**:
    *   Open the app and click the "Settings" icon on the left.
    *   Select Model Platform (`gemini`, `chatgptapi`, `ollama`).
    *   Enter API Key (Leave empty for Ollama).
2.  **Select Translation Style (Prompt)**:
    *   The program comes with three finely tuned prompts:
        *   **Traditional Chinese (Default)**: `prompt_繁中` - Optimized for Taiwan Traditional Chinese users, emphasizing fluency and localized terminology.
        *   **General**: `prompt_通用` - Suitable for translating to other languages, with a neutral style.
        *   **Academic**: `prompt_學術` - Optimized for academic documents, preserving professional terminology with a formal tone.
3.  **Add Books & Start**:
    *   Drag files (`.epub`, `.txt`, `.srt`, `.docx`, `.md`) into the window and click "Start Translation".

---

## ⚙️ Advanced Settings

To ensure translation quality and stability, some parameters are managed automatically and manual adjustment is not recommended:

*   **Accumulated Num**:
    *   Automatically adjusts the amount of text sent to AI based on the selected model for the best balance of speed and quality.
*   **Request Interval**:
    *   Fixed safety intervals to prevent API blocking (Rate Limit), ensuring stability for long translation tasks.
*   **Context**:
    *   *Note: Enabling context often consumes massive amounts of tokens and induces hallucinations. This option is disabled and removed in the current version to ensure accuracy.*

---

## 🛠️ FAQ

**Q: I don't see any translation progress?**
A: The progress bar will update after a few paragraphs are translated. You can also click the "Log" icon on the left to view detailed progress. Check if your API Key is correct, especially for cloud models.

**Q: What if the program crashes halfway?**
A: Restart the program, click the book again, and press "Start Translation". The program will detect previous progress and ask if you want to Resume. Select "Yes" to continue seamlessly.

**Q: Why is local Ollama translation slow?**
A: Local model speed depends entirely on your Computer's GPU performance. If it's too slow, consider using cloud models like Gemini Flash, which are cheap and fast.

**Q: The translation quality seems off?**
A: Ensure you selected `prompt_繁中` in settings for natural Traditional Chinese results. Also, different models (e.g., GPT-4 vs Llama 3) have varying capabilities. Try switching models.

---

## ⚠️ Disclaimer

This tool is for personal study and research purposes only. Do not use it to translate and distribute copyrighted books. Users act at their own risk regarding any legal issues arising from the use of this tool.

---

## 🔧 Utility Tools (Advanced)

This project includes practical command-line tools for advanced users:

### Bilingual to Single Language Tool (`2single.py`)
If you have a bilingual EPUB but want a clean "Chinese-only" version, use this script.

*   **Function**: Automatically identifies and removes English paragraphs from bilingual EPUBs, keeping only Chinese content.
*   **Usage**:
    1. Open Terminal.
    2. Run command:
       ```bash
       python 2single.py "Your_Book.epub"
       ```
    3. It will generate a pure Chinese version ending in `_Single.epub`.

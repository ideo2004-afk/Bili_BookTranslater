import re
import time
from os import environ
from itertools import cycle
import google.generativeai as genai
from google.generativeai.types.generation_types import (
    StopCandidateException,
    BlockedPromptException,
)
from rich import print
from book_maker.utils import global_state
from .base_translator import Base

generation_config = {
    "temperature": 1.0,
    "top_p": 1,
    "top_k": 1,
    "max_output_tokens": 8192,
}

safety_settings = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
]

PROMPT_ENV_MAP = {
    "user": "BBM_GEMINIAPI_USER_MSG_TEMPLATE",
    "system": "BBM_GEMINIAPI_SYS_MSG",
}

GEMINIPRO_MODEL_LIST = [
    "gemini-1.5-pro",
    "gemini-1.5-pro-latest",
    "gemini-1.5-pro-001",
    "gemini-1.5-pro-002",
]

GEMINIFLASH_MODEL_LIST = [
    "gemini-1.5-flash",
    "gemini-1.5-flash-latest",
    "gemini-1.5-flash-001",
    "gemini-1.5-flash-002",
    "gemini-2.0-flash-exp",
    "gemini-2.5-flash-preview-04-17",
]

class Gemini(Base):
    DEFAULT_PROMPT = "Please help me to translate,`{text}` to {language}, please return only translated content not include the origin text"

    def __init__(self, key, language, prompt_template=None, prompt_sys_msg=None, context_flag=False, temperature=1.0, **kwargs) -> None:
        glossary_path = kwargs.get("glossary_path")
        super().__init__(key, language, glossary_path=glossary_path)
        self.context_flag = context_flag
        self.prompt = prompt_template or environ.get(PROMPT_ENV_MAP["user"]) or self.DEFAULT_PROMPT
        self.prompt_sys_msg = prompt_sys_msg or environ.get(PROMPT_ENV_MAP["system"]) or None
        self.interval = 3
        genai.configure(api_key=next(self.keys))
        generation_config["temperature"] = temperature
        self.safety_block_count = 0

    def create_convo(self):
        model = genai.GenerativeModel(model_name=self.model, generation_config=generation_config, safety_settings=safety_settings, system_instruction=self.prompt_sys_msg)
        self.convo = model.start_chat()

    def rotate_model(self):
        self.model = next(self.model_list)
        self.create_convo()
        print(f"Using model {self.model}")

    def rotate_key(self):
        genai.configure(api_key=next(self.keys))
        self.create_convo()

    def build_system_message_with_glossary(self, text=None):
        base_msg = self.prompt_sys_msg or ""
        if self.glossary_manager:
            glossary_text = ""
            if self.glossary_manager.get_glossary_count() > 0:
                glossary_text = self.glossary_manager.get_glossary_text(text_chunk=text)
            if self.glossary_manager.get_glossary_count() >= 500:
                glossary_instructions = f"\n{glossary_text}\n【重要翻譯規則 - 必須遵守】\n1. 若文本中出現對照表中的專有名詞，必須使用表中的翻譯\n2. 保持專有名詞翻譯的一致性\n"
            else:
                glossary_instructions = f"\n{glossary_text}\n【重要翻譯規則 - 必須遵守】\n1. 若文本中出現對照表中的專有名詞，必須使用表中的翻譯\n2. 若遇到新的【人名】，請在翻譯結果的最後一行（單獨一行）標註：\n   NEW_TERMS: {{\"原文英文\": \"翻譯中文\"}}\n   例如：NEW_TERMS: {{\"John Smith\": \"約翰·史密斯\"}}\n3. 保持專有名詞翻譯的一致性\n4. NEW_TERMS 標註必須是有效的 JSON 格式，且必須在翻譯文字的最後\n5. 【重要】NEW_TERMS 標註是翻譯輸出的一部分，不是說明或註解，必須包含在輸出中\n"
                if "不要輸出" in base_msg or "不要" in base_msg:
                    glossary_instructions += "\n注意：NEW_TERMS 標註是必需的輸出格式，不是說明或註解，必須包含。\n"
            return f"{base_msg}\n\n{glossary_instructions}"
        return base_msg

    def translate(self, text, is_retry=False):
        start_time = time.time()
        delay = 1
        exponential_base = 2
        attempt_count = 0
        max_attempts = 7 if not is_retry else 3
        t_text = ""
        print(text)
        text_list = text.splitlines()
        num = None
        if len(text_list) > 1:
            if text_list[0].isdigit():
                num = text_list[0]

        while attempt_count < max_attempts:
            if global_state.is_cancelled:
                raise KeyboardInterrupt("Cancelled by user")
            try:
                if self.glossary_manager:
                    sys_msg = self.build_system_message_with_glossary(text)
                    old_history = self.convo.history
                    model = genai.GenerativeModel(model_name=self.model, generation_config=generation_config, safety_settings=safety_settings, system_instruction=sys_msg)
                    self.convo = model.start_chat(history=old_history)
                self.convo.send_message(self.prompt.format(text=text, language=self.language))
                t_text = self.convo.last.text.strip()
                tag_pattern = r"<step3_refined_translation>(.*?)</step3_refined_translation>"
                tag_match = re.search(tag_pattern, t_text, re.DOTALL)
                if tag_match:
                    t_text = tag_match.group(1).strip()
                break
            except StopCandidateException as e:
                print(f"Translation failed due to StopCandidateException: {e} Attempting to switch model...")
                self.rotate_model()
            except BlockedPromptException as e:
                print(f"Translation failed due to BlockedPromptException: {e} Attempting to switch model...")
                self.rotate_model()
            except ValueError as e:
                print(f"Translation failed due to Safety/Empty Response: {e}.")
                if not is_retry:
                    print("⚠️ Safety Block detected. Attempting granular fallback...")
                    self.safety_block_count += 1
                    return self._granular_translate(text)
                return text
            except Exception as e:
                error_name = type(e).__name__
                if "DefaultCredentialsError" in error_name or ("PermissionDenied" in error_name and "leaked" in str(e)):
                    raise e
                print(f"Translation failed due to {error_name}: {e} Will sleep {delay} seconds")
                time.sleep(delay)
                delay *= exponential_base
                self.rotate_key()
                if attempt_count >= 1:
                    self.rotate_model()
            attempt_count += 1

        if attempt_count == max_attempts:
            print(f"Translation failed after {max_attempts} attempts.")
            return text if is_retry else None

        if self.context_flag:
            if len(self.convo.history) > 2:
                self.convo.history = self.convo.history[2:]
        else:
            self.convo.history = []

        if self.glossary_manager:
            t_text = self.glossary_manager.extract_new_terms(t_text)

        print("[bold green]" + re.sub("\n{3,}", "\n\n", t_text) + "[/bold green]")
        elapsed_time = time.time() - start_time
        from book_maker.utils import num_tokens_from_text
        token_count = num_tokens_from_text(text)
        self.total_tokens += token_count
        self.total_time += elapsed_time
        tps = token_count / elapsed_time if elapsed_time > 0 else 0
        print(f"⚡ Speed: {tps:.1f} tokens/s ({token_count} tokens in {elapsed_time:.1f}s)")
        time.sleep(self.interval)
        if num:
            t_text = str(num) + "\n" + t_text
        return t_text

    def _granular_translate(self, text):
        # Specific trigger for Gemini 2.5 Flash issues: Split batch into single paragraphs
        sep = "\n\n"
        text_list = text.split(sep)
        if len(text_list) <= 1:
            # Already single, nothing more to split
            return text
        
        print(f"🔍 Splitting batch of {len(text_list)} paragraphs for individual translation...")
        translated_list = []
        for i, p in enumerate(text_list):
            if global_state.is_cancelled:
                raise KeyboardInterrupt("Cancelled by user")
            print(f"  -> Granular attempt {i+1}/{len(text_list)}")
            # Try with a more stable model if we have multiple safety blocks
            if self.safety_block_count > 3 and "2.5" in self.model:
                 print("  -> Too many safety blocks. Temporarily switching to more stable model logic?")
                 # Ideal: self.rotate_model() or similar, but for now just try individual
            
            res = self.translate(p, is_retry=True)
            translated_list.append(res)
        
        return sep.join(translated_list)

    def translate_list(self, text_list):
        sep = "\n\n"
        combined_text = sep.join(text_list)
        translated_text = self.translate(combined_text)
        if not translated_text:
            return text_list
        translated_list = translated_text.split(sep)
        if len(translated_list) != len(text_list):
            print(f"Warning: Batch length mismatch ({len(translated_list)} != {len(text_list)}). Retrying individually...")
            return [self.translate(t, is_retry=True) for t in text_list]
        return translated_list

    def set_interval(self, interval):
        self.interval = interval

    def set_geminipro_models(self):
        self.set_models(GEMINIPRO_MODEL_LIST)

    def set_geminiflash_models(self):
        self.set_models(GEMINIFLASH_MODEL_LIST)

    def set_models(self, allowed_models):
        available_models = [re.sub(r"^models/", "", i.name) for i in genai.list_models()]
        model_list = sorted(list(set(available_models) & set(allowed_models)), key=allowed_models.index)
        print(f"Using model list {model_list}")
        self.model_list = cycle(model_list)
        self.rotate_model()

    def set_model_list(self, model_list):
        model_list = sorted(list(set(model_list)), key=model_list.index)
        print(f"Using model list {model_list}")
        self.model_list = cycle(model_list)
        self.rotate_model()

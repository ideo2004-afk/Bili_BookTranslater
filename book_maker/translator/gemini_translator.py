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
    "gemini-1.5-flash-002",
    "gemini-2.0-flash-exp",
    "gemini-2.5-flash-preview-04-17",
]


class Gemini(Base):
    """
    Google gemini translator
    """

    DEFAULT_PROMPT = "Please help me to translate,`{text}` to {language}, please return only translated content not include the origin text"

    def __init__(
        self,
        key,
        language,
        prompt_template=None,
        prompt_sys_msg=None,
        context_flag=False,
        temperature=1.0,
        **kwargs,
    ) -> None:
        glossary_path = kwargs.get("glossary_path")
        super().__init__(key, language, glossary_path=glossary_path)
        self.context_flag = context_flag
        self.prompt = (
            prompt_template
            or environ.get(PROMPT_ENV_MAP["user"])
            or self.DEFAULT_PROMPT
        )
        self.prompt_sys_msg = (
            prompt_sys_msg
            or environ.get(PROMPT_ENV_MAP["system"])
            or None  # Allow None, but not empty string
        )
        self.interval = 3
        genai.configure(api_key=next(self.keys))
        generation_config["temperature"] = temperature

    def create_convo(self):
        model = genai.GenerativeModel(
            model_name=self.model,
            generation_config=generation_config,
            safety_settings=safety_settings,
            system_instruction=self.prompt_sys_msg,
        )
        self.convo = model.start_chat()
        # print(model)  # Uncomment to debug and inspect the model details.

    def rotate_model(self):
        self.model = next(self.model_list)
        self.create_convo()
        print(f"Using model {self.model}")

    def rotate_key(self):
        genai.configure(api_key=next(self.keys))
        self.create_convo()

    def build_system_message_with_glossary(self, text=None):
        """Build system message with glossary instructions if available."""
        base_msg = self.prompt_sys_msg or ""
        
        if self.glossary_manager:
            glossary_text = ""
            if self.glossary_manager.get_glossary_count() > 0:
                glossary_text = self.glossary_manager.get_glossary_text(text_chunk=text)

            # Optimization: If we already have a substantial glossary (e.g. > 500 terms),
            # stop asking for NEW_TERMS to save GPU computation time.
            if self.glossary_manager.get_glossary_count() >= 500:
                glossary_instructions = f"""
{glossary_text}
【重要翻譯規則 - 必須遵守】
1. 若文本中出現對照表中的專有名詞，必須使用表中的翻譯
2. 保持專有名詞翻譯的一致性
"""
            else:
                glossary_instructions = f"""
{glossary_text}
【重要翻譯規則 - 必須遵守】
1. 若文本中出現對照表中的專有名詞，必須使用表中的翻譯
2. 若遇到新的【人名】，請在翻譯結果的最後一行（單獨一行）標註：
   NEW_TERMS: {{"原文英文": "翻譯中文"}}
   例如：NEW_TERMS: {{"John Smith": "約翰·史密斯"}}
3. 保持專有名詞翻譯的一致性
4. NEW_TERMS 標註必須是有效的 JSON 格式，且必須在翻譯文字的最後
5. 【重要】NEW_TERMS 標註是翻譯輸出的一部分，不是說明或註解，必須包含在輸出中
"""
                if "不要輸出" in base_msg or "不要" in base_msg:
                    glossary_instructions += "\n注意：NEW_TERMS 標註是必需的輸出格式，不是說明或註解，必須包含。\n"
            
            return f"{base_msg}\n\n{glossary_instructions}"
        
        return base_msg

    def translate(self, text):
        start_time = time.time()
        delay = 1
        exponential_base = 2
        attempt_count = 0
        max_attempts = 7

        t_text = ""
        print(text)
        # same for caiyun translate src issue #279 gemini for #374
        text_list = text.splitlines()
        num = None
        if len(text_list) > 1:
            if text_list[0].isdigit():
                num = text_list[0]

        while attempt_count < max_attempts:
            try:
                if self.glossary_manager:
                     sys_msg = self.build_system_message_with_glossary(text)
                     # Re-create convo with new system message, preserving history
                     old_history = self.convo.history
                     model = genai.GenerativeModel(
                        model_name=self.model,
                        generation_config=generation_config,
                        safety_settings=safety_settings,
                        system_instruction=sys_msg,
                     )
                     self.convo = model.start_chat(history=old_history)

                self.convo.send_message(
                    self.prompt.format(text=text, language=self.language)
                )
                t_text = self.convo.last.text.strip()
                # Debug: Print raw response to check for NEW_TERMS
                # print(f"🤖 Raw AI Response:\n{t_text}\n{'='*20}")
                
                # 检查是否包含特定标签,如果有则只返回标签内的内容
                tag_pattern = (
                    r"<step3_refined_translation>(.*?)</step3_refined_translation>"
                )
                tag_match = re.search(tag_pattern, t_text, re.DOTALL)
                if tag_match:
                    print(
                        "[bold green]"
                        + re.sub("\n{3,}", "\n\n", t_text)
                        + "[/bold green]"
                    )
                    t_text = tag_match.group(1).strip()
                    # print("[bold green]" + re.sub("\n{3,}", "\n\n", t_text) + "[/bold green]")
                break
            except StopCandidateException as e:
                print(
                    f"Translation failed due to StopCandidateException: {e} Attempting to switch model..."
                )
                self.rotate_model()
            except BlockedPromptException as e:
                print(
                    f"Translation failed due to BlockedPromptException: {e} Attempting to switch model..."
                )
                self.rotate_model()
            except ValueError as e:
                # This usually happens when Gemini blocks the response (empty parts)
                print(f"Translation failed due to Safety/Empty Response: {e}.")
                # Don't retry endlessly for safety blocks
                print("⚠️  Gemini refused to translate this segment (Safety Block). Returning original text to skip...")
                return text
            except Exception as e:
                error_name = type(e).__name__
                if "DefaultCredentialsError" in error_name:
                    print(f"Translation failed due to {error_name}: {e}")
                    raise e
                
                if "PermissionDenied" in error_name and "leaked" in str(e):
                    print(f"Translation failed due to leaked API key: {e}")
                    raise e
                    
                print(
                    f"Translation failed due to {error_name}: {e} Will sleep {delay} seconds"
                )
                time.sleep(delay)
                delay *= exponential_base

                self.rotate_key()
                if attempt_count >= 1:
                    self.rotate_model()

            attempt_count += 1

        if attempt_count == max_attempts:
            print(f"Translation failed after {max_attempts} attempts.")
            return

        if self.context_flag:
            if len(self.convo.history) > 2:
                self.convo.history = self.convo.history[2:]
        else:
            self.convo.history = []

        # Extract and process new proper nouns if glossary is enabled
        if self.glossary_manager:
            # Debug: Log that we're attempting to extract terms
            if self.glossary_manager.get_glossary_count() == 0:
                print(f"📚 Glossary enabled (empty), looking for NEW_TERMS in translation...")
            t_text = self.glossary_manager.extract_new_terms(t_text)

        print("[bold green]" + re.sub("\n{3,}", "\n\n", t_text) + "[/bold green]")
        
        # Calculate speed and update stats
        elapsed_time = time.time() - start_time
        from book_maker.utils import num_tokens_from_text
        token_count = num_tokens_from_text(text)
        
        self.total_tokens += token_count
        self.total_time += elapsed_time
        
        tps = token_count / elapsed_time if elapsed_time > 0 else 0
        print(f"⚡ Speed: {tps:.1f} tokens/s ({token_count} tokens in {elapsed_time:.1f}s)")

        # for rate limit(RPM)
        time.sleep(self.interval)
        if num:
            t_text = str(num) + "\n" + t_text
        return t_text

    def translate_list(self, text_list):
        # Join the list with a separator that is unlikely to appear in the text
        # Using a distinct separator helps in splitting the text back correctly
        sep = "\n\n"
        combined_text = sep.join(text_list)
        
        # Translate the combined text
        translated_text = self.translate(combined_text)
        
        # Split the translated text back into a list
        # We try to split by the separator first
        if not translated_text:
            return []
            
        translated_list = translated_text.split(sep)
        
        # Handle cases where the number of items doesn't match
        if len(translated_list) != len(text_list):
            print(f"Warning: Translated list length ({len(translated_list)}) does not match input list length ({len(text_list)}). Fallback to line splitting or padding.")
            # Fallback: try splitting by newlines if the count is way off, or just return what we have
            # In a robust system, we might want to re-translate item by item here, but for now we return what we got.
            # If the model merged lines, we might have fewer items.
            
        return translated_list

    def set_interval(self, interval):
        self.interval = interval

    def set_geminipro_models(self):
        self.set_models(GEMINIPRO_MODEL_LIST)

    def set_geminiflash_models(self):
        self.set_models(GEMINIFLASH_MODEL_LIST)

    def set_models(self, allowed_models):
        available_models = [
            re.sub(r"^models/", "", i.name) for i in genai.list_models()
        ]
        model_list = sorted(
            list(set(available_models) & set(allowed_models)),
            key=allowed_models.index,
        )
        print(f"Using model list {model_list}")
        self.model_list = cycle(model_list)
        self.rotate_model()

    def set_model_list(self, model_list):
        # keep the order of input
        model_list = sorted(list(set(model_list)), key=model_list.index)
        print(f"Using model list {model_list}")
        self.model_list = cycle(model_list)
        self.rotate_model()

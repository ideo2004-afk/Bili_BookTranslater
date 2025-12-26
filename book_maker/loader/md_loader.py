import sys
import os
import time
import pickle
from pathlib import Path

from book_maker.utils import prompt_config_to_kwargs, global_state

from .base_loader import BaseBookLoader


from .accumulation_mixin import AccumulationMixin


class MDParagraph:
    def __init__(self, text):
        self.text = text


class MarkdownBookLoader(BaseBookLoader, AccumulationMixin):
    def __init__(
        self,
        md_name,
        model,
        key,
        resume,
        language,
        model_api_base=None,
        is_test=False,
        test_num=5,
        prompt_config=None,
        single_translate=False,
        context_flag=False,
        context_paragraph_limit=0,
        temperature=1.0,
        source_lang="auto",
        parallel_workers=1,
        glossary_path=None,
        accumulated_num=1,
    ) -> None:
        self.md_name = md_name
        self.accumulated_num = accumulated_num
        self.translate_model = model(
            key,
            language,
            api_base=model_api_base,
            temperature=temperature,
            source_lang=source_lang,
            glossary_path=glossary_path,
            **prompt_config_to_kwargs(prompt_config),
        )
        self.is_test = is_test
        self.p_to_save = []
        self.test_num = test_num
        self.single_translate = single_translate
        self.md_paragraphs = []
        self.context_flag = context_flag
        self.parallel_workers = max(1, parallel_workers)

        try:
            with open(f"{md_name}", encoding="utf-8") as f:
                self.origin_book = f.read().splitlines()

        except Exception as e:
            raise Exception("can not load file") from e

        self.resume = resume
        self.bin_path = f"{Path(md_name).parent}/.{Path(md_name).stem}.temp.bin"
        if self.resume:
            self.load_state()

        self.process_markdown_content()

    def process_markdown_content(self):
        """将原始内容处理成 markdown 段落"""
        current_paragraph = []
        for line in self.origin_book:
            # 如果是空行且当前段落不为空，保存当前段落
            if not line.strip() and current_paragraph:
                self.md_paragraphs.append(MDParagraph("\n".join(current_paragraph)))
                current_paragraph = []
            # 如果是标题行，单独作为一个段落
            elif line.strip().startswith("#"):
                if current_paragraph:
                    self.md_paragraphs.append(MDParagraph("\n".join(current_paragraph)))
                    current_paragraph = []
                self.md_paragraphs.append(MDParagraph(line))
            # 其他情况，添加到当前段落
            else:
                current_paragraph.append(line)

        # 处理最后一个段落
        if current_paragraph:
            self.md_paragraphs.append(MDParagraph("\n".join(current_paragraph)))

    @staticmethod
    def _is_special_text(text):
        return text.isdigit() or text.isspace() or len(text) == 0 or text.strip() == ""

    def _make_new_book(self, book):
        pass

    def estimate(self):
        print("Calculating estimate...")
        from book_maker.utils import num_tokens_from_text
        
        total_tokens = 0
        total_paragraphs = 0
        
        for p in self.md_paragraphs:
            if self._is_special_text(p.text):
                continue
            total_tokens += num_tokens_from_text(p.text)
            total_paragraphs += 1
            
        print("\n" + "="*50)
        print("📊 Estimation Summary")
        print("="*50)
        print(f"Book: {self.md_name}")
        print(f"Total Paragraphs: {total_paragraphs}")
        print(f"Total Estimated Tokens: {total_tokens:,}")
        print("="*50 + "\n")

    def make_bilingual_book(self):
        index = 0
        p_to_save_len = len(self.p_to_save)

        try:
            # We use AccumulationMixin for everything now for consistency
            p_list = [p for p in self.md_paragraphs if not self._is_special_text(p.text)]
            self.translate_paragraphs_acc(p_list, self.accumulated_num, index, p_to_save_len)

            self.save_file(
                f"{Path(self.md_name).parent}/{Path(self.md_name).stem}_bili.md",
            )

        except (KeyboardInterrupt, Exception) as e:
            print(f"发生错误: {e}")
            print("程序将保存进度，您可以稍后继续")
            self._save_progress()
            sys.exit(1)
            
        # Print Performance Summary
        if hasattr(self.translate_model, 'total_tokens') and hasattr(self.translate_model, 'total_time'):
            total_tokens = self.translate_model.total_tokens
            total_time = self.translate_model.total_time
            avg_speed = total_tokens / total_time if total_time > 0 else 0
            
            print("\n" + "="*50)
            print("📊 Translation Performance Summary")
            print("="*50)
            print(f"Model: {self.translate_model.model}")
            print(f"Total Tokens Processed: {total_tokens:,}")
            print(f"Total Translation Time: {total_time:.2f}s")
            print(f"Average Speed: {avg_speed:.2f} tokens/s")
            print("="*50 + "\n")
            
            # Optional: Save to file
            try:
                os.makedirs("log", exist_ok=True)
                with open("log/translation_stats.txt", "a", encoding="utf-8") as f:
                    f.write(f"\n--- {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
                    f.write(f"Book: {self.md_name}\n")
                    f.write(f"Model: {self.translate_model.model}\n")
                    f.write(f"Total Tokens: {total_tokens}\n")
                    f.write(f"Total Time: {total_time:.2f}s\n")
                    f.write(f"Avg Speed: {avg_speed:.2f} t/s\n")
            except Exception as e:
                print(f"Failed to save stats: {e}")

    def _update_paragraph(self, paragraph, temp):
        if self.single_translate:
            paragraph.text = temp
        else:
            paragraph.text = f"{paragraph.text}\n\n{temp}"

    def _save_temp_book(self):
        pass

    def _save_progress(self):
        try:
            with open(self.bin_path, "wb") as f:
                pickle.dump(self.p_to_save, f)
        except Exception as e:
            raise Exception("can not save resume file") from e

    def load_state(self):
        try:
            with open(self.bin_path, "rb") as f:
                self.p_to_save = pickle.load(f)
        except FileNotFoundError:
            self.p_to_save = []
        except Exception as e:
            print(f"Error loading resume file: {e}, starting from beginning.")
            self.p_to_save = []

    def save_file(self, book_path):
        try:
            with open(book_path, "w", encoding="utf-8") as f:
                f.write("\n\n".join([p.text for p in self.md_paragraphs]))
        except Exception as e:
            raise Exception("can not save file") from e

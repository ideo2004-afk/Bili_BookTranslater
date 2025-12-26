import sys
import os
import pickle
import time
import pickle
from pathlib import Path

from book_maker.utils import prompt_config_to_kwargs, global_state

from .base_loader import BaseBookLoader


from .accumulation_mixin import AccumulationMixin


class Msg:
    def __init__(self, text):
        self.text = text


class TXTBookLoader(BaseBookLoader, AccumulationMixin):
    def __init__(
        self,
        txt_name,
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
        self.txt_name = txt_name
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
        self.context_flag = context_flag
        self.parallel_workers = max(1, parallel_workers)

        try:
            with open(f"{txt_name}", encoding="utf-8") as f:
                self.origin_book = [Msg(line.strip()) for line in f.read().splitlines() if line.strip()]

        except Exception as e:
            raise Exception("can not load file") from e

        self.resume = resume
        self.bin_path = f"{Path(txt_name).parent}/.{Path(txt_name).stem}.temp.bin"
        if self.resume:
            self.load_state()

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
        
        for msg in self.origin_book:
            if self._is_special_text(msg.text):
                continue
            total_tokens += num_tokens_from_text(msg.text)
            total_paragraphs += 1
            
        print("\n" + "="*50)
        print("📊 Estimation Summary")
        print("="*50)
        print(f"Book: {self.txt_name}")
        print(f"Total Paragraphs: {total_paragraphs}")
        print(f"Total Estimated Tokens: {total_tokens:,}")
        print("="*50 + "\n")

    def make_bilingual_book(self):
        index = 0
        p_to_save_len = len(self.p_to_save)

        try:
            # We use AccumulationMixin for everything now for consistency
            p_list = [msg for msg in self.origin_book if not self._is_special_text(msg.text)]
            self.translate_paragraphs_acc(p_list, self.accumulated_num, index, p_to_save_len)

            self.save_file(
                f"{Path(self.txt_name).parent}/{Path(self.txt_name).stem}_bili.txt"
            )

        except (KeyboardInterrupt, Exception) as e:
            print(e)
            print("you can resume it next time")
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
                    f.write(f"Book: {self.txt_name}\n")
                    f.write(f"Model: {self.translate_model.model}\n")
                    f.write(f"Total Tokens: {total_tokens}\n")
                    f.write(f"Total Time: {total_time:.2f}s\n")
                    f.write(f"Avg Speed: {avg_speed:.2f} t/s\n")
            except Exception as e:
                print(f"Failed to save stats: {e}")

    def _update_paragraph(self, msg, temp):
        # We need to update the msg object with the translation
        # But wait, for TXT, we want to print Bilingual result.
        # Original code used self.bilingual_result list.
        # Now we iterate self.origin_book.
        # p_to_save stores just the translations.
        
        # We can update msg.text to be bilingual?
        # Or we can reconstruct the book from p_to_save and origin_book at the end?
        # The Mixin iterates and calls _update_paragraph.
        
        if self.single_translate:
            msg.text = temp
        else:
            msg.text = f"{msg.text}\n{temp}"

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
            print("Resume file not found, starting from beginning.")
            self.p_to_save = []
        except Exception as e:
            print(f"Error loading resume file: {e}, starting from beginning.")
            self.p_to_save = []

    def save_file(self, book_path):
        try:
            with open(book_path, "w", encoding="utf-8") as f:
                # Reconstruct content from origin_book (which now has updated text)
                f.write("\n\n".join([msg.text for msg in self.origin_book]))
        except Exception as e:
            raise Exception("can not save file") from e

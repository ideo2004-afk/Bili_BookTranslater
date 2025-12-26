"""
inspired by: https://github.com/jesselau76/srt-gpt-translator, MIT License
"""

import re
import sys
import os
import time
import pickle
from pathlib import Path

from book_maker.utils import prompt_config_to_kwargs, global_state

from .base_loader import BaseBookLoader


from .accumulation_mixin import AccumulationMixin


class Subtitle:
    def __init__(self, number, time, text):
        self.number = number
        self.time = time
        self.text = text
    
    def __str__(self):
        return f"{self.number}\n{self.time}\n{self.text}"


class SRTBookLoader(BaseBookLoader, AccumulationMixin):
    def __init__(
        self,
        srt_name,
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
        self.srt_name = srt_name
        self.accumulated_num = accumulated_num
        self.translate_model = model(
            key,
            language,
            api_base=model_api_base,
            temperature=temperature,
            source_lang=source_lang,
            glossary_path=glossary_path,
            **prompt_config_to_kwargs(
                {
                    "system": "You are a srt subtitle file translator.",
                    "user": "Translate the following subtitle text into {language}, but keep the subtitle number and timeline and newlines unchanged: \n{text}",
                }
            ),
        )
        self.is_test = is_test
        self.p_to_save = []
        self.test_num = test_num
        self.single_translate = single_translate
        self.context_flag = context_flag
        self.parallel_workers = max(1, parallel_workers)

        if self.resume:
            self.load_state()

    @staticmethod
    def _is_special_text(text):
        return text.isdigit() or text.isspace() or len(text) == 0

    def _make_new_book(self, book):
        pass

    def estimate(self):
        print("Calculating estimate...")
        from book_maker.utils import num_tokens_from_text
        
        try:
            with open(f"{self.srt_name}", encoding="utf-8") as f:
                self.origin_book = self._parse_srt(f.read())
        except Exception as e:
            raise Exception("can not load file") from e
            
        total_tokens = 0
        total_paragraphs = 0
        
        for block in self.origin_book:
            text = block.text
            if not text:
                continue
            total_tokens += num_tokens_from_text(text)
            total_paragraphs += 1
            
        print("\n" + "="*50)
        print("📊 Estimation Summary")
        print("="*50)
        print(f"Book: {self.srt_name}")
        print(f"Total Blocks: {total_paragraphs}")
        print(f"Total Estimated Tokens: {total_tokens:,}")
        print("="*50 + "\n")

    def _parse_srt(self, srt_text):
        blocks = re.split(r"\n\s*\n", srt_text)

        final_blocks = []
        for block in blocks:
            if block.strip() == "":
                continue

            lines = block.strip().splitlines()
            if len(lines) < 3:
                # Handle edge cases or skipping
                continue
                
            number = lines[0].strip()
            timestamp = lines[1].strip()
            text = "\n".join(lines[2:]).strip()
            final_blocks.append(Subtitle(number, timestamp, text))

        return final_blocks

    def make_bilingual_book(self):
        try:
            with open(f"{self.srt_name}", encoding="utf-8") as f:
                self.origin_book = self._parse_srt(f.read())
        except Exception as e:
            raise Exception("can not load file") from e

        index = 0
        p_to_save_len = len(self.p_to_save)

        try:
            # Standardize logic to use filtered list for correct index tracking in Mixin
            p_list = [sub for sub in self.origin_book if not self._is_special_text(sub.text)]
            self.translate_paragraphs_acc(p_list, self.accumulated_num, index, p_to_save_len)

            self.save_file(
                f"{Path(self.srt_name).parent}/{Path(self.srt_name).stem}_bili.srt"
            )

        except (KeyboardInterrupt, Exception) as e:
            print(e)
            print("you can resume it next time")
            self._save_progress()
            sys.exit(0)
            
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
                    f.write(f"Book: {self.srt_name}\n")
                    f.write(f"Model: {self.translate_model.model}\n")
                    f.write(f"Total Tokens: {total_tokens}\n")
                    f.write(f"Total Time: {total_time:.2f}s\n")
                    f.write(f"Avg Speed: {avg_speed:.2f} t/s\n")
            except Exception as e:
                print(f"Failed to save stats: {e}")

    def _update_paragraph(self, subtitle, temp):
        # Update the subtitle object with the translation
        if self.single_translate:
            subtitle.text = temp
        else:
            subtitle.text = f"{subtitle.text}\n{temp}"

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
                f.write("\n\n".join([str(sub) for sub in self.origin_book]))
        except Exception as e:
            raise Exception("can not save file") from e

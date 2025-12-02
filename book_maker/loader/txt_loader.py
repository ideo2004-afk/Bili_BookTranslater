import sys
import pickle
from pathlib import Path

from book_maker.utils import prompt_config_to_kwargs

from .base_loader import BaseBookLoader


class TXTBookLoader(BaseBookLoader):
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
    ) -> None:
        self.txt_name = txt_name
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
        self.bilingual_result = []
        self.bilingual_temp_result = []
        self.test_num = test_num
        self.batch_size = 10
        self.single_translate = single_translate
        self.context_flag = context_flag
        self.parallel_workers = max(1, parallel_workers)

        try:
            with open(f"{txt_name}", encoding="utf-8") as f:
                self.origin_book = f.read().splitlines()

        except Exception as e:
            raise Exception("can not load file") from e

        self.resume = resume
        self.bin_path = f"{Path(txt_name).parent}/.{Path(txt_name).stem}.temp.bin"
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
        
        total_tokens = 0
        total_paragraphs = 0
        
        for line in self.origin_book:
            if self._is_special_text(line):
                continue
            total_tokens += num_tokens_from_text(line)
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
            sliced_list = [
                self.origin_book[i : i + self.batch_size]
                for i in range(0, len(self.origin_book), self.batch_size)
            ]
            for i in sliced_list:
                # fix the format thanks https://github.com/tudoujunha
                batch_text = "\n".join(i)
                if self._is_special_text(batch_text):
                    continue
                if not self.resume or index // self.batch_size >= p_to_save_len:
                    try:
                        max_retries = 3
                        retry_count = 0
                        while retry_count < max_retries:
                            try:
                                temp = self.translate_model.translate(batch_text)
                                break
                            except AttributeError as ae:
                                print(f"翻译出错: {ae}")
                                retry_count += 1
                                if retry_count == max_retries:
                                    raise Exception("翻译模型初始化失败") from ae
                    except Exception as e:
                        print(f"翻译过程中出错: {e}")
                        raise Exception("翻译过程中出现错误") from e

                    self.p_to_save.append(temp)
                    if not self.single_translate:
                        self.bilingual_result.append(batch_text)
                    self.bilingual_result.append(temp)
                else:
                    if not self.single_translate:
                        self.bilingual_result.append(batch_text)
                    self.bilingual_result.append(self.p_to_save[index // self.batch_size])
                index += self.batch_size
                if self.is_test and index > self.test_num:
                    break

            self.save_file(
                f"{Path(self.txt_name).parent}/{Path(self.txt_name).stem}_bilingual.txt",
                self.bilingual_result,
            )

        except (KeyboardInterrupt, Exception) as e:
            print(e)
            print("you can resume it next time")
            self._save_progress()
            self._save_temp_book()
            
            # Print Performance Summary
            if hasattr(self.translate_model, 'total_tokens') and hasattr(self.translate_model, 'total_time'):
                total_tokens = self.translate_model.total_tokens
                total_time = self.translate_model.total_time
                avg_speed = total_tokens / total_time if total_time > 0 else 0
                
                print("\n" + "="*50)
                print("📊 Translation Performance Summary")
                print("="*50)
                print(f"Model: {self.translate_model.model}")
                if hasattr(self, 'accumulated_num'):
                    print(f"Accumulated Num: {self.accumulated_num}")
                if hasattr(self, 'context_flag'):
                    print(f"Use Context: {self.context_flag}")
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
                        if hasattr(self, 'accumulated_num'):
                            f.write(f"Accumulated Num: {self.accumulated_num}\n")
                        if hasattr(self, 'context_flag'):
                            f.write(f"Use Context: {self.context_flag}\n")
                        f.write(f"Total Tokens: {total_tokens}\n")
                        f.write(f"Total Time: {total_time:.2f}s\n")
                        f.write(f"Avg Speed: {avg_speed:.2f} t/s\n")
                except Exception as e:
                    print(f"Failed to save stats: {e}")
            
            sys.exit(0)
            
        # Print Performance Summary (Success Case)
        if hasattr(self.translate_model, 'total_tokens') and hasattr(self.translate_model, 'total_time'):
            total_tokens = self.translate_model.total_tokens
            total_time = self.translate_model.total_time
            avg_speed = total_tokens / total_time if total_time > 0 else 0
            
            print("\n" + "="*50)
            print("📊 Translation Performance Summary")
            print("="*50)
            print(f"Model: {self.translate_model.model}")
            if hasattr(self, 'accumulated_num'):
                print(f"Accumulated Num: {self.accumulated_num}")
            if hasattr(self, 'context_flag'):
                print(f"Use Context: {self.context_flag}")
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
                    if hasattr(self, 'accumulated_num'):
                        f.write(f"Accumulated Num: {self.accumulated_num}\n")
                    if hasattr(self, 'context_flag'):
                        f.write(f"Use Context: {self.context_flag}\n")
                    f.write(f"Total Tokens: {total_tokens}\n")
                    f.write(f"Total Time: {total_time:.2f}s\n")
                    f.write(f"Avg Speed: {avg_speed:.2f} t/s\n")
            except Exception as e:
                print(f"Failed to save stats: {e}")

    def _save_temp_book(self):
        index = 0
        sliced_list = [
            self.origin_book[i : i + self.batch_size]
            for i in range(0, len(self.origin_book), self.batch_size)
        ]

        for i in range(len(sliced_list)):
            batch_text = "".join(sliced_list[i])
            self.bilingual_temp_result.append(batch_text)
            if self._is_special_text(self.origin_book[i]):
                continue
            if index < len(self.p_to_save):
                self.bilingual_temp_result.append(self.p_to_save[index])
            index += 1

        self.save_file(
            f"{Path(self.txt_name).parent}/{Path(self.txt_name).stem}_bilingual_temp.txt",
            self.bilingual_temp_result,
        )

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
        except Exception as e:
            raise Exception("can not load resume file") from e

    def save_file(self, book_path, content):
        try:
            with open(book_path, "w", encoding="utf-8") as f:
                # Filter out None and convert to string to avoid TypeError
                valid_content = [str(c) for c in content if c is not None]
                f.write("\n".join(valid_content))
        except Exception as e:
            raise Exception("can not save file") from e

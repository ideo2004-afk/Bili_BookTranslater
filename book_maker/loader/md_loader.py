import sys
import pickle
from pathlib import Path

from book_maker.utils import prompt_config_to_kwargs, global_state

from .base_loader import BaseBookLoader


class MarkdownBookLoader(BaseBookLoader):
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
    ) -> None:
        self.md_name = md_name
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
        self.md_paragraphs = []

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
                self.md_paragraphs.append("\n".join(current_paragraph))
                current_paragraph = []
            # 如果是标题行，单独作为一个段落
            elif line.strip().startswith("#"):
                if current_paragraph:
                    self.md_paragraphs.append("\n".join(current_paragraph))
                    current_paragraph = []
                self.md_paragraphs.append(line)
            # 其他情况，添加到当前段落
            else:
                current_paragraph.append(line)

        # 处理最后一个段落
        if current_paragraph:
            self.md_paragraphs.append("\n".join(current_paragraph))

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
        
        for p in self.md_paragraphs:
            if self._is_special_text(p):
                continue
            total_tokens += num_tokens_from_text(p)
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
            sliced_list = [
                self.md_paragraphs[i : i + self.batch_size]
                for i in range(0, len(self.md_paragraphs), self.batch_size)
            ]
            for paragraphs in sliced_list:
                batch_text = "\n\n".join(paragraphs)
                if self._is_special_text(batch_text):
                    continue
                if global_state.is_cancelled:
                    raise KeyboardInterrupt("Cancelled by user")

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
                
                self._save_progress()

            self.save_file(
                f"{Path(self.md_name).parent}/{Path(self.md_name).stem}_bili.md",
                self.bilingual_result,
            )

        except (KeyboardInterrupt, Exception) as e:
            print(f"发生错误: {e}")
            print("程序将保存进度，您可以稍后继续")
            self._save_progress()
            self._save_temp_book()
            sys.exit(1)  # 使用非零退出码表示错误

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
            f"{Path(self.md_name).parent}/{Path(self.md_name).stem}_bili_temp.md",
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
        except FileNotFoundError:
            self.p_to_save = []
        except Exception as e:
            print(f"Error loading resume file: {e}, starting from beginning.")
            self.p_to_save = []

    def save_file(self, book_path, content):
        try:
            with open(book_path, "w", encoding="utf-8") as f:
                f.write("\n".join(content))
        except Exception as e:
            raise Exception("can not save file") from e

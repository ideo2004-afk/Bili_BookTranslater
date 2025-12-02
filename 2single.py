#!/usr/bin/env python3
"""
將中英雙語 EPUB 檔案轉換為純中文版本
移除所有英文段落，只保留中文段落
"""

import re
import sys
from pathlib import Path
from bs4 import BeautifulSoup
from ebooklib import epub, ITEM_DOCUMENT


def has_chinese(text):
    """檢查文字是否包含中文字符"""
    if not text:
        return False
    return bool(re.search(r'[\u4e00-\u9fff]', text))


def is_english_paragraph(text):
    """判斷段落是否為英文段落（應被移除）"""
    if not text:
        return False
    
    # 如果包含中文字符，肯定不是純英文段落
    if has_chinese(text):
        return False
    
    # 移除空白、標點符號和數字
    clean_text = re.sub(r'[\s\W\d]', '', text)
    if not clean_text:
        # 只有標點或數字，保留
        return False
    
    # 計算 ASCII 字母字符比例
    ascii_letters = sum(1 for c in clean_text if c.isalpha() and ord(c) < 128)
    if len(clean_text) == 0:
        return False
    
    # 如果主要是 ASCII 字母字符（>70%），且沒有中文，視為英文段落
    return ascii_letters / len(clean_text) > 0.7


def process_epub(input_path, output_path):
    """處理 EPUB 檔案，移除英文段落"""
    print(f"讀取 EPUB: {input_path}")
    book = epub.read_epub(input_path)
    
    # 創建新的 EPUB
    new_book = epub.EpubBook()
    new_book.metadata = book.metadata
    new_book.spine = book.spine
    new_book.toc = book.toc
    
    processed_count = 0
    removed_count = 0
    
    # 處理所有文件
    for item in book.get_items():
        if item.get_type() == ITEM_DOCUMENT:
            # 解析 HTML
            soup = BeautifulSoup(item.content, 'html.parser')
            
            # 找到所有 <p> 標籤
            paragraphs = soup.find_all('p')
            
            for p in paragraphs:
                text = p.get_text(strip=True)
                
                # 如果段落是空的，跳過
                if not text:
                    continue
                
                # 判斷是否為英文段落
                if is_english_paragraph(text):
                    # 移除英文段落
                    p.decompose()
                    removed_count += 1
                else:
                    # 保留中文段落或其他段落
                    processed_count += 1
            
            # 更新內容
            item.content = soup.encode('utf-8')
        
        # 將項目添加到新書中
        new_book.add_item(item)
    
    # 寫入新檔案
    print(f"處理完成: 保留 {processed_count} 個段落，移除 {removed_count} 個英文段落")
    print(f"寫入檔案: {output_path}")
    epub.write_epub(output_path, new_book, {})
    print("完成！")


def main():
    if len(sys.argv) != 2:
        print("使用方法: python 2single.py <epub檔案路徑>")
        print("範例: python 2single.py 'books/Metal Gear Solid q3_14b - Raymond Benson.epub'")
        sys.exit(1)
    
    input_path = Path(sys.argv[1])
    
    if not input_path.exists():
        print(f"錯誤: 檔案不存在: {input_path}")
        sys.exit(1)
    
    if not input_path.suffix.lower() == '.epub':
        print(f"錯誤: 檔案必須是 .epub 格式")
        sys.exit(1)
    
    # 生成輸出檔名（在原始檔名後加上 _Single）
    output_path = input_path.parent / f"{input_path.stem}_Single.epub"
    
    try:
        process_epub(str(input_path), str(output_path))
    except Exception as e:
        print(f"錯誤: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()


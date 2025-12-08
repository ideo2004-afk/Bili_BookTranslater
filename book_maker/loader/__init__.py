from book_maker.loader.epub_loader import EPUBBookLoader
from book_maker.loader.txt_loader import TXTBookLoader
from book_maker.loader.srt_loader import SRTBookLoader
from book_maker.loader.md_loader import MarkdownBookLoader
from book_maker.loader.docx_loader import DOCXBookLoader

BOOK_LOADER_DICT = {
    "epub": EPUBBookLoader,
    "txt": TXTBookLoader,
    "srt": SRTBookLoader,
    "md": MarkdownBookLoader,
    "docx": DOCXBookLoader,
    # TODO add more here
}

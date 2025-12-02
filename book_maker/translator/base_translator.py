import itertools
from abc import ABC, abstractmethod


class Base(ABC):
    def __init__(self, key, language, glossary_path=None):
        self.key = key
        self.keys = itertools.cycle(key.split(","))
        self.language = language
        
        # Initialize glossary manager if path is provided
        self.glossary_manager = None
        if glossary_path:
            try:
                from book_maker.glossary_manager import GlossaryManager
                self.glossary_manager = GlossaryManager(glossary_path)
            except Exception as e:
                print(f"⚠ Warning: Failed to initialize GlossaryManager: {e}")
                self.glossary_manager = None
        
        # Performance tracking
        self.total_tokens = 0
        self.total_time = 0

    @abstractmethod
    def rotate_key(self):
        pass

    @abstractmethod
    def translate(self, text):
        pass

    def set_deployment_id(self, deployment_id):
        pass

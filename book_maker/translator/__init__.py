from book_maker.translator.chatgptapi_translator import ChatGPTAPI
from book_maker.translator.gemini_translator import Gemini

MODEL_DICT = {
    "openai": ChatGPTAPI,
    "chatgptapi": ChatGPTAPI,
    "gpt4": ChatGPTAPI,
    "gpt4omini": ChatGPTAPI,
    "gpt4o": ChatGPTAPI,
    "o1preview": ChatGPTAPI,
    "o1": ChatGPTAPI,
    "o1mini": ChatGPTAPI,
    "o3mini": ChatGPTAPI,
    "gemini": Gemini,
    "geminipro": Gemini,
}

---
description: Implement Context-Aware Glossary Filtering
---

# Context-Aware Glossary Filtering

## Objective
Optimize the glossary injection mechanism to support an unlimited number of glossary terms without consuming excessive tokens or exceeding context windows.

## Current Limitation
Currently, the system blindly injects the first N (e.g., 100) items from the glossary into the system prompt, regardless of whether they appear in the text being translated. This wastes tokens and limits the effective glossary size.

## Proposed Solution
Modify `glossary_manager.py` to implement "Context-Aware Filtering".

1.  **Update `get_glossary_text` signature**:
    Accept the `current_text` (the text chunk about to be translated) as an argument.

2.  **Filter Logic**:
    Instead of taking the first `max_items`, iterate through *all* available glossary terms.
    Check if the source term (key) exists in `current_text`.
    Only include the terms that are actually present in the current text.

3.  **Update Callers**:
    Update `chatgptapi_translator.py` (and other translators) to pass the source text when calling `get_glossary_text`.

## Benefits
*   **Unlimited Glossary Size**: The JSON file can grow to thousands of terms.
*   **Minimal Token Usage**: Only relevant terms are sent to the AI.
*   **Improved Accuracy**: Reduces distraction for the AI by removing irrelevant terms from the context.

## Implementation Plan
1.  Modify `book_maker/glossary_manager.py`: `get_glossary_text(self, text_chunk: str = None, max_items: int = 100)`
2.  Modify `book_maker/translator/chatgptapi_translator.py`: Update `build_system_message_with_glossary` to pass the text.

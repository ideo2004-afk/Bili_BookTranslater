"""
Glossary Manager for maintaining proper noun translations.
Manages loading, saving, and updating a JSON-based glossary of proper nouns.
"""

import json
import os
import re
import time
from threading import Lock, RLock
from typing import Dict, Optional


class GlossaryManager:
    """Manages a glossary of proper noun translations."""
    
    def __init__(self, glossary_path: str = "nouns.json"):
        """
        Initialize the GlossaryManager.
        
        Args:
            glossary_path: Path to the JSON glossary file
        """
        self.glossary_path = glossary_path
        self.glossary: Dict[str, str] = {}
        self.lock = RLock()
        self.load_glossary()
    
    def load_glossary(self) -> None:
        """Load the glossary from the JSON file."""
        if os.path.exists(self.glossary_path):
            try:
                # Update mtime
                with open(self.glossary_path, 'r', encoding='utf-8') as f:
                    self.glossary = json.load(f)
                print(f"✓ Loaded {len(self.glossary)} terms from {self.glossary_path}")
            except Exception as e:
                print(f"⚠ Warning: Failed to load glossary from {self.glossary_path}: {e}")
                self.glossary = {}
        else:
            print(f"ℹ No existing glossary found at {self.glossary_path}, starting fresh")
            self.glossary = {}
            self.save_glossary()  # Create empty file immediately for user feedback



    def save_glossary(self) -> None:
        """Save the glossary to the JSON file (thread-safe and atomic)."""
        with self.lock:
            try:
                # Atomic write: write to temp file then rename
                temp_path = f"{self.glossary_path}.tmp"
                with open(temp_path, 'w', encoding='utf-8') as f:
                    json.dump(self.glossary, f, ensure_ascii=False, indent=2)
                
                # Rename temp file to actual file (atomic on POSIX)
                os.replace(temp_path, self.glossary_path)
                
                # Update mtime after save to prevent unnecessary reload
                # print(f"✓ Saved {len(self.glossary)} terms to {self.glossary_path}")
            except Exception as e:
                print(f"✗ Error: Failed to save glossary to {self.glossary_path}: {e}")
                if os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except:
                        pass
    
    def get_glossary_text(self, text_chunk: str = None, max_items: int = 100) -> str:
        """
        Generate formatted glossary text for use in prompts.
        
        Args:
            text_chunk: The text to be translated. If provided, only glossary terms present
                       in this text will be included (Context-Aware Filtering).
            max_items: Maximum number of items to include (to avoid prompt length issues)
            
        Returns:
            Formatted glossary text
        """
        if not self.glossary:
            return ""
        
        items = []
        if text_chunk:
            # Context-Aware Filtering Optimized
            # Instead of iterating 150+ times, we use one regex pass to find all known terms
            try:
                # Create a regex pattern that matches any of the glossary keys
                # We sort by length descending to match longest terms first (e.g. "New York City" before "New York")
                # Escape keys to handle special characters safely
                sorted_keys = sorted(self.glossary.keys(), key=len, reverse=True)
                if not sorted_keys:
                    return ""
                    
                pattern = "|".join(map(re.escape, sorted_keys))
                # Use a set to avoid duplicates if a term appears multiple times
                found_terms = set(re.findall(pattern, text_chunk))
                
                for term in found_terms:
                    items.append((term, self.glossary[term]))
            except Exception as e:
                print(f"⚠ Warning: Regex filtering failed: {e}, falling back to loop")
                # Fallback to original loop if regex fails (e.g. too complex)
                for original, translation in self.glossary.items():
                    if original in text_chunk:
                        items.append((original, translation))
        else:
            # Fallback to original behavior: take first N items
            items = list(self.glossary.items())[:max_items]
        
        if not items:
            return ""
        
        glossary_lines = [f"- {original} → {translation}" 
                         for original, translation in items]
        glossary_text = "\n".join(glossary_lines)
        
        return f"""【專有名詞對照表】
{glossary_text}
"""
    
    def extract_new_terms(self, translated_text: str) -> str:
        """
        Extract new proper nouns from translated text and update glossary.
        
        The AI is expected to mark new terms in the format:
        NEW_TERMS: {"original": "translation", ...}
        
        Args:
            translated_text: The translated text from the AI
            
        Returns:
            Clean translated text with the NEW_TERMS marker removed
        """
        # Optimization: Use Regex to find the JSON block instead of character-by-character parsing
        # This is significantly faster for large text blocks.
        # Pattern looks for NEW_TERMS: followed by a JSON object (curly braces)
        # DOTALL flag allows matching across newlines
        pattern = r'(NEW_TERMS:\s*)(\{.*?\})\s*$'
        match = re.search(pattern, translated_text, re.IGNORECASE | re.DOTALL)
        
        if not match:
            return translated_text
            
        marker_str = match.group(1)
        json_str = match.group(2)
        full_match_str = match.group(0)
        
        try:
            new_terms = json.loads(json_str)
            
            if isinstance(new_terms, dict):
                if new_terms:
                    # 有新的專有名詞
                    print(f"📝 Found {len(new_terms)} new proper noun(s):")
                    for original, translation in new_terms.items():
                        print(f"   {original} → {translation}")
                    
                    # Update the glossary
                    self.update_glossary(new_terms)
                
                # Remove the NEW_TERMS section from the text
                # We replace the matched string with an empty string, stripping trailing whitespace
                clean_text = translated_text.replace(full_match_str, "").rstrip()
                return clean_text
            else:
                print(f"⚠ Warning: NEW_TERMS JSON is not a dictionary: {type(new_terms)}")
                
        except json.JSONDecodeError as e:
            print(f"⚠ Warning: Failed to parse NEW_TERMS JSON: {e}")
            # Fallback: If simple regex failed (maybe nested braces?), we just return original
            # In a high-performance scenario, it's better to skip a malformed term than crash or hang.
        except Exception as e:
            print(f"⚠ Warning: Error processing NEW_TERMS: {e}")
        
        return translated_text
    
    def update_glossary(self, new_terms: Dict[str, str]) -> None:
        """
        Update the glossary with new terms and save to file.
        
        Args:
            new_terms: Dictionary of {original: translation} pairs
        """
        if not new_terms:
            return
        
        with self.lock:
            # Check size limit
            if len(self.glossary) >= 500:
                # Only allow updates to existing terms, ignore new ones
                filtered_terms = {}
                for k, v in new_terms.items():
                    if k in self.glossary:
                        filtered_terms[k] = v
                
                if not filtered_terms:
                    print(f"ℹ Glossary limit (500) reached. Ignoring {len(new_terms)} new terms.")
                    return
                
                new_terms = filtered_terms
                print(f"ℹ Glossary limit reached. Only updating {len(new_terms)} existing terms.")

            # Update the glossary
            updated_count = 0
            for original, translation in new_terms.items():
                if original not in self.glossary:
                    self.glossary[original] = translation
                    updated_count += 1
                # Strict Consistency Policy:
                # If the term already exists, we DO NOT update it automatically.
                # This ensures that once a name is translated, it stays consistent throughout the book.
                # If the user wants to change a translation, they should edit the JSON file manually.
                elif self.glossary[original] != translation:
                    # Debug log to show AI tried to change it, but we ignored it
                    # print(f"🔒 Ignoring AI translation change for '{original}': '{self.glossary[original]}' -> '{translation}'")
                    pass
            
            if updated_count > 0:
                # Save the updated glossary
                self.save_glossary()
    
    def get_term(self, original: str) -> Optional[str]:
        """
        Get the translation for a specific term.
        
        Args:
            original: The original term
            
        Returns:
            The translation if found, None otherwise
        """
        return self.glossary.get(original)
    
    def has_term(self, original: str) -> bool:
        """
        Check if a term exists in the glossary.
        
        Args:
            original: The original term
            
        Returns:
            True if the term exists, False otherwise
        """
        return original in self.glossary
    
    def get_glossary_count(self) -> int:
        """Get the number of terms in the glossary."""
        return len(self.glossary)

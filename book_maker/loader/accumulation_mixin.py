import sys
from book_maker.utils import global_state, num_tokens_from_text
from .helper import shorter_result_link

class AccumulationMixin:
    """
    Mixin for loaders that need token accumulation logic.
    Requires the following attributes/methods on the host class:
    - self.translate_model
    - self.resume
    - self.p_to_save (list)
    - self._save_progress()
    - self._update_paragraph(paragraph_obj, translated_text)
    """

    def translate_paragraphs_acc(self, p_list, send_num, index, p_to_save_len):
        count = 0
        wait_p_list = []
        
        # Determine starting point based on resume
        # p_list contains all valid paragraphs.
        
        current_idx = 0
        
        for i, p in enumerate(p_list):
            if global_state.is_cancelled:
                raise KeyboardInterrupt("Cancelled by user")
            
            # Resume check
            if current_idx < p_to_save_len and self.resume:
                # Already translated
                # For Mixin usage, we might need a way to verify if we need to call update
                # In docx_loader, we called _update_paragraph to ensure the doc object has the text.
                # Since p_to_save holds the text:
                temp = self.p_to_save[current_idx]
                self._update_paragraph(p, temp)
                current_idx += 1
                continue

            # Need translation
            # We assume p has a .text attribute or is a string. 
            # If p is a complex object, _update_paragraph handles the update, 
            # but for token counting we need text.
            # Let's assume p.text works (docx, and our future wrappers).
            # If p is just string (unlikely for objects we want to update in place), we might need handling.
            # In our plan: TXT/MD/SRT will use wrapper objects.
            
            length = num_tokens_from_text(text_content)
            
            # If a single paragraph is too long, process immediately
            if length > send_num:
                self._deal_new_acc(p, current_idx, wait_p_list, wait_p_indices)
                current_idx += 1
                continue
            
            # If adding this would exceed limit, process batch first
            if count + length >= send_num:
                self._deal_old_acc(wait_p_list, wait_p_indices)
                # After clearing, add current
                wait_p_list.append(p)
                wait_p_indices.append(current_idx)
                count = length
            else:
                 wait_p_list.append(p)
                 wait_p_indices.append(current_idx)
                 count += length
            
            current_idx += 1
            # If last item, flush
            if i == len(p_list) - 1:
                self._deal_old_acc(wait_p_list, wait_p_indices)
        
        # Save final progress
        self._save_progress()

    def _deal_old_acc(self, wait_p_list, wait_p_indices):
        if not wait_p_list:
            return

        text_list = [p.text if hasattr(p, 'text') else str(p) for p in wait_p_list]
        result_txt_list = self.translate_model.translate_list(text_list)
        
        for i, p in enumerate(wait_p_list):
            if i < len(result_txt_list):
                idx = wait_p_indices[i]
                trans_text = result_txt_list[i]
                trans_text = shorter_result_link(trans_text)
                self._update_paragraph(p, trans_text)
                
                # Update or append progress
                if idx < len(self.p_to_save):
                    self.p_to_save[idx] = trans_text
                else:
                    self.p_to_save.append(trans_text)
        
        wait_p_list.clear()
        wait_p_indices.clear()
        self._save_progress()

    def _deal_new_acc(self, p, idx, wait_p_list, wait_p_indices):
        # Flush existing
        self._deal_old_acc(wait_p_list, wait_p_indices)
        
        # Translate single
        text_content = p.text if hasattr(p, 'text') else str(p)
        trans_text = self.translate_model.translate(text_content)
        trans_text = shorter_result_link(trans_text)
        self._update_paragraph(p, trans_text)
        
        # Update or append
        if idx < len(self.p_to_save):
            self.p_to_save[idx] = trans_text
        else:
            self.p_to_save.append(trans_text)
        
        self._save_progress()

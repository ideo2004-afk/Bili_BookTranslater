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
        wait_p_indices = []
        
        current_idx = index
        
        for i, p in enumerate(p_list):
            if global_state.is_cancelled:
                raise KeyboardInterrupt("Cancelled by user")
            
            text_content = p.text if hasattr(p, 'text') else str(p)

            # Resume check
            if current_idx < p_to_save_len and self.resume:
                saved_text = self.p_to_save[current_idx]
                # Smart Resume: If translation is identical to source, re-translate
                if hasattr(self, '_is_special_text'):
                    is_special = self._is_special_text(text_content)
                else:
                    is_special = text_content.strip() == "" or text_content.isdigit()

                # Improved detection: identical or nearly identical text usually means translation failed
                if saved_text.strip() == text_content.strip() and not is_special:
                    print(f"Refining untranslated block at index {current_idx}...")
                else:
                    self._update_paragraph(p, saved_text)
                    current_idx += 1
                    continue

            # Need translation
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

"""
Shared types for the LLM module.

All streaming/chat functions return a ChatResult — a 4-tuple of:
    (response_text, token_stats, tool_calls_list, interleaved_blocks)
"""

from typing import Dict, List, Any, Optional, Tuple

# Return type for all streaming/chat functions.
# - response_text:       The concatenated model output text.
# - token_stats:         {"prompt_eval_count": int, "eval_count": int}
# - tool_calls_list:     List of tool call dicts executed during the turn.
# - interleaved_blocks:  Ordered text/tool blocks for UI rendering, or None.
ChatResult = Tuple[str, Dict[str, int], List[Dict[str, Any]], Optional[List[Dict[str, Any]]]]

"""
title: CYOA Session ID Injector
version: 0.1.0
description: Injects a unique session ID on the first message for game state tracking.
"""

from typing import Optional, List
from pydantic import BaseModel, Field
import secrets


class Filter:
    class Valves(BaseModel):
        debug: bool = Field(
            default=True,
            description="Log session ID injection to stdout.",
        )

    def __init__(self):
        self.valves = self.Valves()
        self.toggle = True  # Can be toggled per-chat in UI

    # ----------------- helpers -----------------

    def _extract_text(self, msg: dict) -> str:
        """Normalize content to a single string."""
        content = msg.get("content", "")
        if isinstance(content, str):
            return content
        elif isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    parts.append(item.get("text", ""))
                elif isinstance(item, str):
                    parts.append(item)
            return "\n".join(parts)
        return ""

    def _set_text(self, msg: dict, new_text: str) -> None:
        """Write text back, handling string or list formats."""
        content = msg.get("content", "")
        if isinstance(content, str):
            msg["content"] = new_text
        elif isinstance(content, list):
            # Replace or append text block
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    item["text"] = new_text
                    return
            # If no text block found, append one
            content.append({"type": "text", "text": new_text})
        else:
            msg["content"] = new_text

    def _is_first_message(self, messages: List[dict]) -> bool:
        """
        Check if this is the first message in the conversation.
        Returns True if there are no prior assistant messages.
        """
        for msg in messages:
            if msg.get("role") == "assistant":
                return False
        return True

    def _generate_session_id(self, first_message_content: str, timestamp_seconds: int) -> str:
        """
        Generate a deterministic session ID from first message + timestamp.
        Both models called in the same chat will have the same timestamp (to the second),
        ensuring they get the same session ID. Different chats get different timestamps.
        """
        import hashlib
        # Combine timestamp and message for uniqueness
        session_key = f"{timestamp_seconds}:{first_message_content}"
        hash_obj = hashlib.sha256(session_key.encode('utf-8'))
        return hash_obj.hexdigest()[:16]  # 16-char hex

    # ----------------- inlet -----------------

    async def inlet(
        self,
        body: dict,
        __event_emitter__,
        __user__: Optional[dict] = None,
        __model__: Optional[dict] = None,
        __request__=None,
    ) -> dict:
        if not self.toggle:
            return body

        try:
            messages: List[dict] = body.get("messages", [])
            if not messages:
                return body

            # Only inject on first message of conversation
            if not self._is_first_message(messages):
                if self.valves.debug:
                    print("[SESSION_ID] Not first message, skipping injection")
                return body

            # Find last user message
            last_user_idx = None
            for i in range(len(messages) - 1, -1, -1):
                if messages[i].get("role") == "user":
                    last_user_idx = i
                    break

            if last_user_idx is None:
                return body

            last_msg = messages[last_user_idx]
            user_text = self._extract_text(last_msg)

            # Check if session ID already injected (avoid double injection)
            if "<CYOA_SESSION_ID:" in user_text:
                if self.valves.debug:
                    print("[SESSION_ID] Session ID already present, skipping")
                return body

            # Get first user message to generate deterministic session ID
            first_user_text = ""
            for msg in messages:
                if msg.get("role") == "user":
                    first_user_text = self._extract_text(msg)
                    break

            # Use timestamp rounded to the second (both models called within same second)
            import time
            timestamp_seconds = int(time.time())
            
            # Generate deterministic session ID from timestamp + first message
            session_id = self._generate_session_id(first_user_text, timestamp_seconds)
            new_text = user_text.rstrip() + f"\n\n<CYOA_SESSION_ID:{session_id}>"

            self._set_text(last_msg, new_text)

            if self.valves.debug:
                print(f"[SESSION_ID] Injected session ID: {session_id} (ts={timestamp_seconds})")

            body["messages"] = messages
            return body

        except Exception as e:
            print(f"[SESSION_ID] ERROR in inlet: {e!r}")
            return body

    # ----------------- outlet -----------------

    async def outlet(
        self,
        body: dict,
        __user__: Optional[dict] = None,
        __model__: Optional[dict] = None,
        __request__=None,
    ) -> dict:
        """
        Remove session ID from assistant responses so it doesn't appear in chat history.
        """
        if not self.toggle:
            return body

        try:
            messages: List[dict] = body.get("messages", [])
            
            for msg in messages:
                if msg.get("role") in ["user", "assistant"]:
                    content = self._extract_text(msg)
                    if "<CYOA_SESSION_ID:" in content:
                        # Strip out the session ID tag
                        import re
                        cleaned = re.sub(r'\n*<CYOA_SESSION_ID:[a-f0-9]+>', '', content)
                        self._set_text(msg, cleaned)
            
            body["messages"] = messages
            return body

        except Exception as e:
            print(f"[SESSION_ID] ERROR in outlet: {e!r}")
            return body

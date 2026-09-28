"""One reply at a time per conversation.

Two concurrent turns on one thread would both start from the same checkpoint and the
later write would silently drop the other turn. In-process only: fine for P0's single
worker; multiple workers need a Postgres advisory lock instead (P4).
"""

import uuid


class ConversationLocks:
    def __init__(self) -> None:
        self._busy: set[uuid.UUID] = set()

    def acquire(self, conversation_id: uuid.UUID) -> bool:
        """Non-blocking: False if a reply is already being generated."""
        if conversation_id in self._busy:
            return False
        self._busy.add(conversation_id)
        return True

    def release(self, conversation_id: uuid.UUID) -> None:
        self._busy.discard(conversation_id)

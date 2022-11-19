import asyncio
import dataclasses
from asyncio.events import AbstractEventLoop
from typing import Dict

from ._messages import Message, RemoveSceneNodeMessage, ResetSceneMessage


@dataclasses.dataclass
class AsyncMessageBuffer:
    """Async iterable for keeping a persistent buffer of messages.

    Uses heuristics on scene node names to automatically cull out outdated messages."""

    message_counter: int = 0
    message_from_id: Dict[int, bytes] = dataclasses.field(default_factory=dict)
    id_from_name: Dict[str, int] = dataclasses.field(default_factory=dict)
    message_event: asyncio.Event = dataclasses.field(default_factory=asyncio.Event)

    def push(self, message: Message):
        """Push a new message to our buffer, and remove old redundant ones.

        Not currently thread-safe."""

        # If we're resetting the scene, we don't need any of the prior messages.
        if isinstance(message, ResetSceneMessage):
            self.message_from_id.clear()
            self.id_from_name.clear()

        # Add message to buffer.
        new_message_id = self.message_counter
        self.message_counter += 1
        self.message_from_id[new_message_id] = message.serialize()

        # All messages that modify scene nodes have a name field.
        node_name = getattr(message, "name", None)
        if node_name is not None:
            # If an existing message with the same scene node name already exists in our
            # buffer, we don't need the old one anymore. :-)
            if node_name is not None and node_name in self.id_from_name:
                old_message_id = self.id_from_name.pop(node_name)
                self.message_from_id.pop(old_message_id)

            # If we're removing a scene node, remove children as well.
            #
            # TODO: this currently does a linear pass over all existing messages. We
            # could easily optimize this.
            if node_name is not None and isinstance(message, RemoveSceneNodeMessage):
                remove_list = []
                for name, id in self.id_from_name.items():
                    if name.startswith(node_name):
                        remove_list.append((name, id))
                for name, id in remove_list:
                    self.id_from_name.pop(name)
                    self.message_from_id.pop(id)
            self.id_from_name[node_name] = new_message_id

    def notify(self, event_loop: AbstractEventLoop) -> None:
        """Notify serve loops that a new message is available."""
        event_loop.call_soon_threadsafe(self.message_event.set)
        event_loop.call_soon_threadsafe(self.message_event.clear)

    async def __aiter__(self):
        """Async iterator over messages. Loops infinitely, and waits when no messages
        are available."""
        last_sent_id = -1

        while True:
            # Wait for a message to arrive.
            if len(self.message_from_id) == 0:
                await self.message_event.wait()

            most_recent_message_id = next(reversed(self.message_from_id))

            # No new messages => wait.
            if most_recent_message_id <= last_sent_id:
                await self.message_event.wait()

            # Try to yield the next message ID.
            last_sent_id += 1
            message = self.message_from_id.get(last_sent_id, None)
            if message is not None:
                yield message

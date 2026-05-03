"""Message queue system for human-AI communication in HAATO missions.

This module provides a robust messaging infrastructure that sits between
Python components (MissionManager, Wingman) and X-Plane datarefs. The message
queue guarantees delivery and ordering of messages, while datarefs serve only
as I/O boundaries for visualization and human input.

Architecture:
    - Messages flow through an in-memory queue (guaranteed delivery)
    - Datarefs show only current/latest message state
    - Human commands: only latest is processed (old ones auto-dropped)
    - All messages are logged for post-mission analysis
"""

import json
import csv
import os
from collections import deque
from datetime import datetime
from typing import Optional, List, Dict, Any


class Message:
    """Represents a single message in the communication system.

    Attributes:
        type: Message category ('command', 'request', 'response', 'status')
        sender: Who sent it ('human', 'wingman_0', 'wingman_1', etc.)
        recipient: Who should receive it (same format as sender)
        payload: Dictionary containing message-specific data
        timestamp: Mission elapsed time when message was created
        message_id: Unique incrementing identifier
        processed: Whether this message has been read/handled
    """

    _id_counter = 0

    def __init__(self, msg_type: str, sender: str, recipient: str,
                 payload: Dict[str, Any], timestamp: float):
        """Create a new message.

        Args:
            msg_type: Type of message ('command', 'request', 'response', 'status')
            sender: Sender identifier ('human', 'wingman_0', etc.)
            recipient: Recipient identifier
            payload: Dictionary with message-specific data
            timestamp: Mission elapsed time (seconds)
        """
        self.type = msg_type
        self.sender = sender
        self.recipient = recipient
        self.payload = payload
        self.timestamp = timestamp
        self.message_id = Message._id_counter
        self.processed = False
        self.processed_time = None

        Message._id_counter += 1

    def mark_processed(self, mission_time: float):
        """Mark this message as processed."""
        self.processed = True
        self.processed_time = mission_time

    def to_dict(self) -> Dict[str, Any]:
        """Convert message to dictionary for logging."""
        return {
            'message_id': self.message_id,
            'type': self.type,
            'sender': self.sender,
            'recipient': self.recipient,
            'payload': self.payload,
            'timestamp': self.timestamp,
            'processed': self.processed,
            'processed_time': self.processed_time
        }

    def __repr__(self) -> str:
        return (f"Message(id={self.message_id}, type={self.type}, "
                f"{self.sender}->{self.recipient}, payload={self.payload})")


class MessageQueue:
    """Thread-safe message queue with guaranteed delivery and ordering.

    The queue maintains up to 50 messages in history. Messages are retrieved
    by recipient, ensuring each agent only sees messages intended for them.
    Special handling for 'command' type messages: only the latest is returned
    to prevent command backlog.
    """

    def __init__(self, max_size: int = 50):
        """Initialize the message queue.

        Args:
            max_size: Maximum number of messages to keep in history
        """
        self._queue = deque(maxlen=max_size)
        self._max_size = max_size

    def send(self, message: Message):
        """Add a message to the queue.

        Args:
            message: Message object to enqueue
        """
        self._queue.append(message)

    def get_messages(self, recipient: str, msg_type: Optional[str] = None,
                     mark_processed: bool = True) -> List[Message]:
        """Get all unread messages for a recipient.

        Args:
            recipient: Recipient identifier to filter by
            msg_type: Optional message type filter
            mark_processed: Whether to mark returned messages as processed

        Returns:
            List of matching unread messages
        """
        messages = []
        for msg in self._queue:
            if msg.recipient == recipient and not msg.processed:
                if msg_type is None or msg.type == msg_type:
                    messages.append(msg)

        if mark_processed:
            for msg in messages:
                msg.mark_processed(0.0)  # Will be updated with actual time by caller

        return messages

    def get_latest_message(self, recipient: str, msg_type: str,
                          mark_processed: bool = True) -> Optional[Message]:
        """Get only the most recent message for a recipient, discarding older ones.

        This is used for 'command' type messages where only the latest command
        matters and older unprocessed commands should be ignored.

        Args:
            recipient: Recipient identifier
            msg_type: Message type to filter by
            mark_processed: Whether to mark old messages as processed

        Returns:
            Most recent matching message, or None if no matches
        """
        matching_messages = []
        for msg in self._queue:
            if msg.recipient == recipient and msg.type == msg_type and not msg.processed:
                matching_messages.append(msg)

        if not matching_messages:
            return None

        # Get the latest message (most recent timestamp)
        latest = max(matching_messages, key=lambda m: m.timestamp)

        if mark_processed:
            # Mark ALL matching messages as processed (drops old commands)
            for msg in matching_messages:
                msg.mark_processed(0.0)

        return latest

    def has_messages(self, recipient: str, msg_type: Optional[str] = None) -> bool:
        """Check if there are unread messages for a recipient.

        Args:
            recipient: Recipient identifier
            msg_type: Optional message type filter

        Returns:
            True if unread messages exist
        """
        for msg in self._queue:
            if msg.recipient == recipient and not msg.processed:
                if msg_type is None or msg.type == msg_type:
                    return True
        return False

    def get_history(self, limit: Optional[int] = None) -> List[Message]:
        """Get message history (all messages, including processed).

        Args:
            limit: Optional limit on number of messages to return (most recent)

        Returns:
            List of messages from history
        """
        if limit is None:
            return list(self._queue)
        else:
            return list(self._queue)[-limit:]

    def clear_old_messages(self, recipient: str, msg_type: str):
        """Mark all old unprocessed messages of a type as processed.

        Used when a new message supersedes previous ones.

        Args:
            recipient: Recipient identifier
            msg_type: Message type to clear
        """
        for msg in self._queue:
            if msg.recipient == recipient and msg.type == msg_type and not msg.processed:
                msg.mark_processed(0.0)

    def cleanup_old_processed_messages(self, current_time: float, age_threshold: float = 30.0):
        """Remove processed messages older than the age threshold.

        Unprocessed messages are never removed regardless of age.

        Args:
            current_time: Current mission time in seconds
            age_threshold: Age in seconds after which processed messages are removed (default 30.0)
        """
        messages_to_keep = []
        for msg in self._queue:
            # Keep all unprocessed messages regardless of age
            if not msg.processed:
                messages_to_keep.append(msg)
            # Keep processed messages that are younger than threshold
            elif msg.processed_time is not None and (current_time - msg.processed_time) <= age_threshold:
                messages_to_keep.append(msg)
            # else: message is processed and old, so don't keep it

        # Replace queue contents with filtered messages
        self._queue.clear()
        self._queue.extend(messages_to_keep)

    def __len__(self) -> int:
        """Return number of messages in queue."""
        return len(self._queue)

    def __repr__(self) -> str:
        unread = sum(1 for msg in self._queue if not msg.processed)
        return f"MessageQueue(total={len(self._queue)}, unread={unread})"


class MessageLogger:
    """Logs all messages to CSV for post-mission analysis.

    Creates a CSV file with one row per message, including full payload
    and timing information.
    """

    def __init__(self, user_id: int, log_file_identifier, initiative_level, fire_layout: int = 1):
        """Initialize message logger.

        Args:
            user_id: Participant ID for the mission
            fire_layout: Fire layout for this session
        """
        self.user_id = int(user_id)
        self.fire_layout = fire_layout
        self.initiative_level = int(initiative_level)
        self.log_file_identifier = int(log_file_identifier)

        # Create logs directory if it doesn't exist
        os.makedirs('logs', exist_ok=True)

        # Create timestamped log file
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_file = f'logs/messages_p{self.user_id}_initiative{self.initiative_level}_layout{fire_layout}_{timestamp}_id{self.log_file_identifier}.csv'

        # Initialize CSV file with headers
        self.fieldnames = [
            'message_id',
            'mission_time',
            'type',
            'sender',
            'recipient',
            'payload_json',
            'processed',
            'processed_time'
        ]

        with open(self.log_file, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=self.fieldnames)
            writer.writeheader()

        #print(f"[MessageLogger] Logging messages to {self.log_file}")

    def log(self, message: Message):
        """Log a single message to CSV.

        Args:
            message: Message object to log
        """
        with open(self.log_file, 'a', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=self.fieldnames)

            row = {
                'message_id': message.message_id,
                'mission_time': message.timestamp,
                'type': message.type,
                'sender': message.sender,
                'recipient': message.recipient,
                'payload_json': json.dumps(message.payload),
                'processed': message.processed,
                'processed_time': message.processed_time if message.processed_time else ''
            }

            writer.writerow(row)

    def log_batch(self, messages: List[Message]):
        """Log multiple messages at once.

        Args:
            messages: List of Message objects to log
        """
        for msg in messages:
            self.log(msg)

    def close(self):
        """Finalize the log file."""
        pass

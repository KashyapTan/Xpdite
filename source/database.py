import sqlite3
import json
import uuid
import time
import os
from contextlib import contextmanager
from typing import List, Dict, Any, Optional


class DatabaseManager:
    def __init__(self, database_path: str = "user_data/xpdite_app.db"):
        """Initialize the database manager with the given file path."""
        db_dir = os.path.dirname(database_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
        self.database_path = database_path
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """Create a configured SQLite connection.

        Sets performance PRAGMAs on every connection:
        - foreign_keys: enforce declared FK constraints
        - busy_timeout: retry on lock instead of failing instantly
        - cache_size: 64 MB page cache
        - synchronous: NORMAL is safe with WAL and faster than FULL
        """
        conn = sqlite3.connect(self.database_path, check_same_thread=False)
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA busy_timeout = 5000")
            conn.execute("PRAGMA cache_size = -64000")
            conn.execute("PRAGMA synchronous = NORMAL")
        except Exception:
            conn.close()
            raise
        return conn

    @contextmanager
    def _connect(self):
        """Context manager that yields a connection and ensures cleanup on exit."""
        conn = self._get_connection()
        try:
            yield conn
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self):
        """Create tables, indexes, FTS virtual tables, and triggers."""
        with self._connect() as conn:
            cursor = conn.cursor()

            # WAL mode persists in the DB file — safe to re-issue on every boot.
            cursor.execute("PRAGMA journal_mode = WAL")

            # --- TABLE: CONVERSATIONS ---
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    title TEXT,
                    created_at REAL,
                    updated_at REAL,
                    total_input_tokens INTEGER DEFAULT 0,
                    total_output_tokens INTEGER DEFAULT 0
                )
            """)

            # --- TABLE: MESSAGES ---
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    num_messages INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT,
                    images TEXT,
                    model TEXT,
                    content_blocks TEXT,
                    created_at REAL,
                    FOREIGN KEY(conversation_id) REFERENCES conversations(id)
                )
            """)

            # --- TABLE: SETTINGS ---
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)

            # --- TABLE: TERMINAL EVENTS ---
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS terminal_events (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    message_index INTEGER,
                    command TEXT,
                    exit_code INTEGER,
                    output_preview TEXT,
                    full_output TEXT,
                    cwd TEXT,
                    duration_ms INTEGER,
                    timed_out INTEGER DEFAULT 0,
                    denied INTEGER DEFAULT 0,
                    pty INTEGER DEFAULT 0,
                    background INTEGER DEFAULT 0,
                    created_at REAL,
                    FOREIGN KEY(conversation_id) REFERENCES conversations(id)
                )
            """)

            # --- TABLE: MEETING RECORDINGS ---
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS meeting_recordings (
                    id TEXT PRIMARY KEY,
                    title TEXT,
                    started_at REAL,
                    ended_at REAL,
                    duration_seconds INTEGER,
                    status TEXT DEFAULT 'recording',
                    audio_file_path TEXT,
                    tier1_transcript TEXT DEFAULT '',
                    tier2_transcript_json TEXT,
                    ai_summary TEXT,
                    ai_actions_json TEXT,
                    ai_title_generated INTEGER DEFAULT 0
                )
            """)

            # --- INDEXES ---
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_messages_conversation
                ON messages(conversation_id, created_at)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_conversations_updated
                ON conversations(updated_at DESC)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_terminal_events_conversation
                ON terminal_events(conversation_id, created_at)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_meeting_recordings_started
                ON meeting_recordings(started_at DESC)
            """)

            # --- FTS5 VIRTUAL TABLES ---
            cursor.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS conversations_fts USING fts5(
                    conversation_id UNINDEXED,
                    title,
                    tokenize="unicode61"
                )
            """)
            cursor.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
                    conversation_id UNINDEXED,
                    content,
                    tokenize="unicode61"
                )
            """)

            # --- TRIGGERS ---
            cursor.execute("""
                CREATE TRIGGER IF NOT EXISTS conversations_fts_ai
                AFTER INSERT ON conversations BEGIN
                    INSERT INTO conversations_fts(rowid, conversation_id, title)
                    VALUES (new.rowid, new.id, new.title);
                END
            """)
            cursor.execute("""
                CREATE TRIGGER IF NOT EXISTS conversations_fts_au
                AFTER UPDATE OF title ON conversations BEGIN
                    DELETE FROM conversations_fts WHERE rowid = old.rowid;
                    INSERT INTO conversations_fts(rowid, conversation_id, title)
                    VALUES (new.rowid, new.id, new.title);
                END
            """)
            cursor.execute("""
                CREATE TRIGGER IF NOT EXISTS conversations_fts_ad
                AFTER DELETE ON conversations BEGIN
                    DELETE FROM conversations_fts WHERE rowid = old.rowid;
                END
            """)
            cursor.execute("""
                CREATE TRIGGER IF NOT EXISTS messages_fts_ai
                AFTER INSERT ON messages BEGIN
                    INSERT INTO messages_fts(rowid, conversation_id, content)
                    VALUES (new.rowid, new.conversation_id, new.content);
                END
            """)
            cursor.execute("""
                CREATE TRIGGER IF NOT EXISTS messages_fts_ad
                AFTER DELETE ON messages BEGIN
                    DELETE FROM messages_fts WHERE rowid = old.rowid;
                END
            """)

            # --- MESSAGE METADATA MIGRATIONS ---
            for statement in (
                "ALTER TABLE messages ADD COLUMN message_id TEXT",
                "ALTER TABLE messages ADD COLUMN turn_id TEXT",
                "ALTER TABLE messages ADD COLUMN active_response_index INTEGER DEFAULT 0",
            ):
                try:
                    cursor.execute(statement)
                except sqlite3.OperationalError:
                    pass

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS message_response_versions (
                    id TEXT PRIMARY KEY,
                    assistant_message_id TEXT NOT NULL,
                    response_index INTEGER NOT NULL,
                    content TEXT,
                    model TEXT,
                    content_blocks TEXT,
                    created_at REAL,
                    UNIQUE(assistant_message_id, response_index)
                )
            """)

            cursor.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_messages_message_id
                ON messages(message_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_messages_turn
                ON messages(conversation_id, turn_id, created_at)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_message_response_versions_assistant
                ON message_response_versions(assistant_message_id, response_index)
            """)
            cursor.execute("""
                CREATE TRIGGER IF NOT EXISTS messages_fts_au
                AFTER UPDATE OF content ON messages BEGIN
                    DELETE FROM messages_fts WHERE rowid = old.rowid;
                    INSERT INTO messages_fts(rowid, conversation_id, content)
                    VALUES (new.rowid, new.conversation_id, new.content);
                END
            """)

            self._backfill_message_metadata(cursor)

            conn.commit()

    @staticmethod
    def _decode_images(images_json: Optional[str]) -> List[str]:
        return json.loads(images_json) if images_json else []

    @staticmethod
    def _decode_content_blocks(content_blocks_json: Optional[str]) -> List[Dict] | None:
        return json.loads(content_blocks_json) if content_blocks_json else None

    def _build_response_variants(
        self, assistant_message_id: str, conn: sqlite3.Connection
    ) -> List[Dict[str, Any]]:
        rows = conn.execute(
            """SELECT response_index, content, model, content_blocks, created_at
               FROM message_response_versions
               WHERE assistant_message_id = ?
               ORDER BY response_index ASC""",
            (assistant_message_id,),
        ).fetchall()
        return [
            {
                "response_index": row[0],
                "content": row[1],
                "model": row[2],
                "content_blocks": self._decode_content_blocks(row[3]),
                "timestamp": row[4],
            }
            for row in rows
        ]

    def _build_message_record(
        self, row: tuple, conn: sqlite3.Connection
    ) -> Dict[str, Any]:
        message = {
            "num_messages": row[0],
            "message_id": row[1],
            "turn_id": row[2],
            "role": row[3],
            "content": row[4],
            "images": self._decode_images(row[5]),
            "timestamp": row[6],
            "model": row[7],
            "content_blocks": self._decode_content_blocks(row[8]),
            "active_response_index": row[9] or 0,
        }
        if message["role"] == "assistant" and message["message_id"]:
            message["response_variants"] = self._build_response_variants(
                message["message_id"], conn
            )
        return message

    def _backfill_message_metadata(self, cursor: sqlite3.Cursor) -> None:
        rows = cursor.execute(
            """SELECT num_messages, conversation_id, role, content, model, content_blocks,
                      created_at, message_id, turn_id, active_response_index
               FROM messages
               ORDER BY conversation_id ASC, created_at ASC, num_messages ASC"""
        ).fetchall()

        pending_turns: Dict[str, str] = {}

        for row in rows:
            (
                num_messages,
                conversation_id,
                role,
                content,
                model,
                content_blocks_json,
                created_at,
                message_id,
                turn_id,
                active_response_index,
            ) = row

            resolved_message_id = message_id or str(uuid.uuid4())
            resolved_turn_id = turn_id

            if not resolved_turn_id:
                if role == "user":
                    resolved_turn_id = str(uuid.uuid4())
                    pending_turns[conversation_id] = resolved_turn_id
                elif pending_turns.get(conversation_id):
                    resolved_turn_id = pending_turns.pop(conversation_id)
                else:
                    resolved_turn_id = str(uuid.uuid4())
            else:
                if role == "user":
                    pending_turns[conversation_id] = resolved_turn_id
                elif pending_turns.get(conversation_id) == resolved_turn_id:
                    pending_turns.pop(conversation_id, None)

            cursor.execute(
                """UPDATE messages
                   SET message_id = ?,
                       turn_id = ?,
                       active_response_index = COALESCE(active_response_index, 0)
                   WHERE num_messages = ?""",
                (resolved_message_id, resolved_turn_id, num_messages),
            )

            if role != "assistant":
                continue

            existing = cursor.execute(
                """SELECT 1 FROM message_response_versions
                   WHERE assistant_message_id = ?
                   LIMIT 1""",
                (resolved_message_id,),
            ).fetchone()
            if existing:
                continue

            cursor.execute(
                """INSERT INTO message_response_versions
                   (id, assistant_message_id, response_index, content, model, content_blocks, created_at)
                   VALUES (?, ?, 0, ?, ?, ?, ?)""",
                (
                    str(uuid.uuid4()),
                    resolved_message_id,
                    content,
                    model,
                    content_blocks_json,
                    created_at,
                ),
            )

    # ---------------------------------------------------------
    # WRITE OPERATIONS
    # ---------------------------------------------------------

    def start_new_conversation(self, title: str) -> str:
        """Create a new conversation and return its UUID."""
        new_id = str(uuid.uuid4())
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO conversations (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (new_id, title, now, now),
            )
            conn.commit()
        return new_id

    def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        images: List[str] | None = None,
        model: str | None = None,
        content_blocks: List[Dict] | None = None,
        *,
        turn_id: str | None = None,
        message_id: str | None = None,
        created_at: float | None = None,
        active_response_index: int = 0,
    ) -> Dict[str, Any]:
        """Save a message and return its persisted metadata."""
        now = created_at if created_at is not None else time.time()
        images_json = json.dumps(images) if images else None
        content_blocks_json = json.dumps(content_blocks) if content_blocks else None
        resolved_turn_id = turn_id or str(uuid.uuid4())
        resolved_message_id = message_id or str(uuid.uuid4())

        with self._connect() as conn:
            cursor = conn.execute(
                """INSERT INTO messages
                   (conversation_id, role, content, images, model, content_blocks, created_at,
                    message_id, turn_id, active_response_index)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    conversation_id,
                    role,
                    content,
                    images_json,
                    model,
                    content_blocks_json,
                    now,
                    resolved_message_id,
                    resolved_turn_id,
                    active_response_index,
                ),
            )
            conn.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (now, conversation_id),
            )
            conn.commit()
        return {
            "num_messages": cursor.lastrowid,
            "message_id": resolved_message_id,
            "turn_id": resolved_turn_id,
            "timestamp": now,
        }

    def get_message_by_id(self, message_id: str) -> Dict[str, Any] | None:
        """Return a single message by its stable message_id."""
        with self._connect() as conn:
            row = conn.execute(
                """SELECT num_messages, message_id, turn_id, role, content, images, created_at,
                          model, content_blocks, active_response_index, conversation_id
                   FROM messages
                   WHERE message_id = ?""",
                (message_id,),
            ).fetchone()
            if row is None:
                return None

            message = self._build_message_record(
                (
                    row[0],
                    row[1],
                    row[2],
                    row[3],
                    row[4],
                    row[5],
                    row[6],
                    row[7],
                    row[8],
                    row[9],
                ),
                conn,
            )
            message["conversation_id"] = row[10]
            return message

    def get_turn_messages(self, conversation_id: str, turn_id: str) -> List[Dict[str, Any]]:
        """Return all persisted messages for a single turn."""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT num_messages, message_id, turn_id, role, content, images, created_at,
                          model, content_blocks, active_response_index
                   FROM messages
                   WHERE conversation_id = ? AND turn_id = ?
                   ORDER BY created_at ASC, num_messages ASC""",
                (conversation_id, turn_id),
            ).fetchall()

            return [self._build_message_record(row, conn) for row in rows]

    def get_turn_payload(self, conversation_id: str, turn_id: str) -> Dict[str, Any] | None:
        """Return the canonical user/assistant payload for a turn."""
        messages = self.get_turn_messages(conversation_id, turn_id)
        if not messages:
            return None

        user_message = next((msg for msg in messages if msg["role"] == "user"), None)
        assistant_message = next(
            (msg for msg in messages if msg["role"] == "assistant"), None
        )
        if user_message is None:
            return None

        return {
            "turn_id": turn_id,
            "user": user_message,
            "assistant": assistant_message,
        }

    def get_active_chat_history(self, conversation_id: str) -> List[Dict[str, Any]]:
        """Return active conversation messages in LLM-friendly history format."""
        history: List[Dict[str, Any]] = []
        for message in self.get_full_conversation(conversation_id):
            entry: Dict[str, Any] = {
                "role": message["role"],
                "content": message["content"],
            }
            if message.get("images"):
                entry["images"] = message["images"]
            if message.get("model"):
                entry["model"] = message["model"]
            history.append(entry)
        return history

    def save_response_version(
        self,
        conversation_id: str,
        assistant_message_id: str,
        content: str,
        *,
        model: str | None = None,
        content_blocks: List[Dict] | None = None,
        created_at: float | None = None,
        replace_history: bool = False,
    ) -> Dict[str, Any]:
        """Persist an assistant response variant and mark it active."""
        now = created_at if created_at is not None else time.time()
        content_blocks_json = json.dumps(content_blocks) if content_blocks else None

        with self._connect() as conn:
            message_row = conn.execute(
                """SELECT 1
                   FROM messages
                   WHERE conversation_id = ? AND message_id = ? AND role = 'assistant'""",
                (conversation_id, assistant_message_id),
            ).fetchone()
            if message_row is None:
                raise ValueError("Assistant message not found for conversation.")

            if replace_history:
                conn.execute(
                    "DELETE FROM message_response_versions WHERE assistant_message_id = ?",
                    (assistant_message_id,),
                )
                next_index = 0
            else:
                row = conn.execute(
                    """SELECT COALESCE(MAX(response_index), -1) + 1
                       FROM message_response_versions
                       WHERE assistant_message_id = ?""",
                    (assistant_message_id,),
                ).fetchone()
                next_index = int(row[0]) if row and row[0] is not None else 0

            version_id = str(uuid.uuid4())
            conn.execute(
                """INSERT INTO message_response_versions
                   (id, assistant_message_id, response_index, content, model, content_blocks, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    version_id,
                    assistant_message_id,
                    next_index,
                    content,
                    model,
                    content_blocks_json,
                    now,
                ),
            )
            conn.execute(
                """UPDATE messages
                   SET content = ?,
                       model = ?,
                       content_blocks = ?,
                       created_at = ?,
                       active_response_index = ?
                   WHERE message_id = ? AND conversation_id = ?""",
                (
                    content,
                    model,
                    content_blocks_json,
                    now,
                    next_index,
                    assistant_message_id,
                    conversation_id,
                ),
            )
            conn.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (now, conversation_id),
            )
            conn.commit()

        return {
            "assistant_message_id": assistant_message_id,
            "response_index": next_index,
            "timestamp": now,
            "id": version_id,
        }

    def set_active_response_version(
        self, conversation_id: str, assistant_message_id: str, response_index: int
    ) -> Dict[str, Any] | None:
        """Switch the active assistant response variant for a turn."""
        if response_index < 0:
            raise ValueError("response_index must be non-negative")

        with self._connect() as conn:
            row = conn.execute(
                """SELECT rv.content, rv.model, rv.content_blocks, rv.created_at
                   FROM message_response_versions rv
                   JOIN messages m ON m.message_id = rv.assistant_message_id
                   WHERE rv.assistant_message_id = ?
                     AND rv.response_index = ?
                     AND m.conversation_id = ?""",
                (assistant_message_id, response_index, conversation_id),
            ).fetchone()
            if row is None:
                return None

            conn.execute(
                """UPDATE messages
                   SET content = ?,
                       model = ?,
                       content_blocks = ?,
                       created_at = ?,
                       active_response_index = ?
                    WHERE message_id = ? AND conversation_id = ?""",
                (
                    row[0],
                    row[1],
                    row[2],
                    row[3],
                    response_index,
                    assistant_message_id,
                    conversation_id,
                ),
            )
            conn.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (time.time(), conversation_id),
            )
            conn.commit()

        return self.get_message_by_id(assistant_message_id)

    def truncate_conversation_after_turn(self, conversation_id: str, turn_id: str) -> None:
        """Delete all later turns after the specified turn."""
        with self._connect() as conn:
            cutoff = conn.execute(
                """SELECT MAX(num_messages)
                   FROM messages
                   WHERE conversation_id = ? AND turn_id = ?""",
                (conversation_id, turn_id),
            ).fetchone()
            if cutoff is None or cutoff[0] is None:
                return

            later_assistant_ids = [
                row[0]
                for row in conn.execute(
                    """SELECT message_id
                       FROM messages
                       WHERE conversation_id = ? AND num_messages > ? AND role = 'assistant'""",
                    (conversation_id, cutoff[0]),
                ).fetchall()
            ]
            for assistant_id in later_assistant_ids:
                conn.execute(
                    "DELETE FROM message_response_versions WHERE assistant_message_id = ?",
                    (assistant_id,),
                )

            conn.execute(
                "DELETE FROM terminal_events WHERE conversation_id = ? AND message_index > ?",
                (conversation_id, cutoff[0]),
            )
            conn.execute(
                "DELETE FROM messages WHERE conversation_id = ? AND num_messages > ?",
                (conversation_id, cutoff[0]),
            )
            conn.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (time.time(), conversation_id),
            )
            conn.commit()

    def update_user_message(
        self,
        conversation_id: str,
        message_id: str,
        content: str,
        *,
        created_at: float | None = None,
        conversation_title: str | None = None,
    ) -> Dict[str, Any] | None:
        """Update the persisted content for a user message."""
        now = created_at if created_at is not None else time.time()
        with self._connect() as conn:
            cursor = conn.execute(
                """UPDATE messages
                   SET content = ?, created_at = ?
                   WHERE conversation_id = ? AND message_id = ? AND role = 'user'""",
                (content, now, conversation_id, message_id),
            )
            if cursor.rowcount == 0:
                conn.rollback()
                return None

            if conversation_title is None:
                conn.execute(
                    "UPDATE conversations SET updated_at = ? WHERE id = ?",
                    (now, conversation_id),
                )
            else:
                conn.execute(
                    "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
                    (conversation_title, now, conversation_id),
                )
            conn.commit()
        return self.get_message_by_id(message_id)

    def is_first_user_message(self, conversation_id: str, message_id: str) -> bool:
        """Return True when message_id is the first user turn in the conversation."""
        with self._connect() as conn:
            row = conn.execute(
                """SELECT message_id
                   FROM messages
                   WHERE conversation_id = ? AND role = 'user'
                   ORDER BY created_at ASC, num_messages ASC
                   LIMIT 1""",
                (conversation_id,),
            ).fetchone()
        return bool(row and row[0] == message_id)

    # ---------------------------------------------------------
    # READ OPERATIONS
    # ---------------------------------------------------------

    def get_recent_conversations(self, limit: int = 5, offset: int = 0) -> List[Dict]:
        """Return conversations ordered by most recently active, with pagination."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, title, updated_at FROM conversations ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return [{"id": r[0], "title": r[1], "date": r[2]} for r in rows]

    def get_full_conversation(self, conversation_id: str) -> List[Dict]:
        """Load all messages for a conversation in stable insertion order."""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT num_messages, message_id, turn_id, role, content, images, created_at,
                          model, content_blocks, active_response_index
                   FROM messages
                   WHERE conversation_id = ?
                   ORDER BY created_at ASC, num_messages ASC""",
                (conversation_id,),
            ).fetchall()

            return [self._build_message_record(row, conn) for row in rows]

    def delete_conversation(self, conversation_id: str) -> None:
        """Delete a conversation and all associated data (messages, terminal events)."""
        with self._connect() as conn:
            assistant_ids = [
                row[0]
                for row in conn.execute(
                    "SELECT message_id FROM messages WHERE conversation_id = ? AND role = 'assistant'",
                    (conversation_id,),
                ).fetchall()
            ]
            for assistant_id in assistant_ids:
                conn.execute(
                    "DELETE FROM message_response_versions WHERE assistant_message_id = ?",
                    (assistant_id,),
                )
            conn.execute("DELETE FROM terminal_events WHERE conversation_id = ?", (conversation_id,))
            conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation_id,))
            conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
            conn.commit()

    @staticmethod
    def _fts5_phrase(term: str) -> str:
        """Wrap a raw user string in FTS5 double-quote phrase syntax.
        Internal double-quotes are escaped by doubling ("" → literal ")."""
        return '"' + term.replace('"', '""') + '"'

    def search_conversations(self, search_term: str, limit: int = 20) -> List[Dict]:
        """Search conversations by title or message content using FTS5.
        Falls back to LIKE if FTS tables are unavailable."""
        if not search_term or not search_term.strip():
            return []

        fts_query = self._fts5_phrase(search_term)

        with self._connect() as conn:
            try:
                rows = conn.execute(
                    """SELECT c.id, c.title, c.updated_at
                       FROM conversations c
                       WHERE c.id IN (
                           SELECT conversation_id FROM conversations_fts
                           WHERE conversations_fts MATCH ?
                           UNION
                           SELECT conversation_id FROM messages_fts
                           WHERE messages_fts MATCH ?
                       )
                       ORDER BY c.updated_at DESC
                       LIMIT ?""",
                    (fts_query, fts_query, limit),
                ).fetchall()
            except sqlite3.OperationalError:
                escaped = (
                    search_term.replace("\\", "\\\\")
                    .replace("%", "\\%")
                    .replace("_", "\\_")
                )
                rows = conn.execute(
                    """SELECT DISTINCT c.id, c.title, c.updated_at
                       FROM conversations c
                       LEFT JOIN messages m ON c.id = m.conversation_id
                       WHERE c.title LIKE ? ESCAPE '\\' OR m.content LIKE ? ESCAPE '\\'
                       ORDER BY c.updated_at DESC
                       LIMIT ?""",
                    (f"%{escaped}%", f"%{escaped}%", limit),
                ).fetchall()

        return [{"id": r[0], "title": r[1], "date": r[2]} for r in rows]

    def update_conversation_title(self, conversation_id: str, title: str) -> None:
        """Update the title of an existing conversation."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE conversations SET title = ? WHERE id = ?", (title, conversation_id)
            )
            conn.commit()

    def add_token_usage(
        self, conversation_id: str, input_tokens: int, output_tokens: int
    ) -> None:
        """Accumulate token usage for a conversation. Negative values are clamped to 0."""
        input_tokens = max(0, input_tokens or 0)
        output_tokens = max(0, output_tokens or 0)

        with self._connect() as conn:
            conn.execute(
                """UPDATE conversations
                   SET total_input_tokens = total_input_tokens + ?,
                       total_output_tokens = total_output_tokens + ?
                   WHERE id = ?""",
                (input_tokens, output_tokens, conversation_id),
            )
            conn.commit()

    def get_token_usage(self, conversation_id: str) -> Dict:
        """Get cumulative token usage for a conversation."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT total_input_tokens, total_output_tokens FROM conversations WHERE id = ?",
                (conversation_id,),
            ).fetchone()

        if row:
            inp, out = row[0] or 0, row[1] or 0
            return {"input": inp, "output": out, "total": inp + out}
        return {"input": 0, "output": 0, "total": 0}

    # ---------------------------------------------------------
    # SETTINGS OPERATIONS
    # ---------------------------------------------------------

    def get_setting(self, key: str) -> str | None:
        """Get a raw setting value by key. Returns None if not found."""
        with self._connect() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def set_setting(self, key: str, value: str):
        """Set a raw setting value (upsert)."""
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value)
            )
            conn.commit()

    def delete_setting(self, key: str) -> None:
        """Delete a setting by key."""
        with self._connect() as conn:
            conn.execute("DELETE FROM settings WHERE key = ?", (key,))
            conn.commit()

    def get_enabled_models(self) -> List[str]:
        """Get the list of model names the user has toggled on."""
        value = self.get_setting("enabled_models")
        return json.loads(value) if value else []

    def set_enabled_models(self, models: List[str]):
        """Save the list of enabled model names."""
        self.set_setting("enabled_models", json.dumps(models))

    def get_system_prompt_template(self) -> str | None:
        """Returns the user-saved system prompt template, or None if not set."""
        return self.get_setting("system_prompt_template")

    def set_system_prompt_template(self, template: str | None) -> None:
        """Save a custom system prompt template. Pass None/empty to clear."""
        if not template or not template.strip():
            self.delete_setting("system_prompt_template")
        else:
            self.set_setting("system_prompt_template", template)

    # ---------------------------------------------------------
    # TERMINAL EVENT OPERATIONS
    # ---------------------------------------------------------

    def save_terminal_event(
        self,
        conversation_id: str,
        message_index: int,
        command: str,
        exit_code: int,
        output: str,
        cwd: str,
        duration_ms: int,
        pty: bool = False,
        background: bool = False,
        timed_out: bool = False,
        denied: bool = False,
    ) -> str:
        """Save a terminal command execution event. Returns event ID."""
        event_id = str(uuid.uuid4())

        if len(output) <= 1000:
            output_preview = output
        else:
            output_preview = output[:500] + "\n...\n" + output[-500:]

        max_output = 50 * 1024
        full_output = output[:max_output] if len(output) > max_output else output

        with self._connect() as conn:
            conn.execute(
                """INSERT INTO terminal_events
                   (id, conversation_id, message_index, command, exit_code,
                    output_preview, full_output, cwd, duration_ms,
                    timed_out, denied, pty, background, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    event_id, conversation_id, message_index, command, exit_code,
                    output_preview, full_output, cwd, duration_ms,
                    int(timed_out), int(denied), int(pty), int(background),
                    time.time(),
                ),
            )
            conn.commit()
        return event_id

    def get_terminal_events(self, conversation_id: str) -> List[Dict]:
        """Return all terminal events for a conversation, ordered by created_at."""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT id, message_index, command, exit_code, output_preview,
                          cwd, duration_ms, timed_out, denied, pty, background, created_at
                   FROM terminal_events
                   WHERE conversation_id = ?
                   ORDER BY created_at ASC""",
                (conversation_id,),
            ).fetchall()

        return [
            {
                "id": r[0], "message_index": r[1], "command": r[2],
                "exit_code": r[3], "output_preview": r[4], "cwd": r[5],
                "duration_ms": r[6], "timed_out": bool(r[7]), "denied": bool(r[8]),
                "pty": bool(r[9]), "background": bool(r[10]), "created_at": r[11],
            }
            for r in rows
        ]

    # ---------------------------------------------------------
    # MEETING RECORDING OPERATIONS
    # ---------------------------------------------------------

    def create_meeting_recording(self, title: str, started_at: float) -> str:
        """Create a new meeting recording entry. Returns the recording ID."""
        recording_id = str(uuid.uuid4())
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO meeting_recordings (id, title, started_at, status) VALUES (?, ?, ?, 'recording')",
                (recording_id, title, started_at),
            )
            conn.commit()
        return recording_id

    def update_meeting_recording(self, recording_id: str, **fields) -> None:
        """Update one or more allowed fields on a meeting recording."""
        allowed = {
            "title", "ended_at", "duration_seconds", "status",
            "audio_file_path", "tier1_transcript", "tier2_transcript_json",
            "ai_summary", "ai_actions_json", "ai_title_generated",
        }
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return

        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [recording_id]

        with self._connect() as conn:
            conn.execute(f"UPDATE meeting_recordings SET {set_clause} WHERE id = ?", values)
            conn.commit()

    def append_tier1_transcript(self, recording_id: str, text: str) -> None:
        """Append a live transcript chunk to the tier1_transcript field."""
        with self._connect() as conn:
            conn.execute(
                """UPDATE meeting_recordings
                   SET tier1_transcript = COALESCE(tier1_transcript, '') || ?
                   WHERE id = ?""",
                (text, recording_id),
            )
            conn.commit()

    def get_meeting_recordings(self, limit: int = 50, offset: int = 0) -> List[Dict]:
        """List meeting recordings (metadata only, no transcripts)."""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT id, title, started_at, ended_at, duration_seconds, status
                   FROM meeting_recordings
                   ORDER BY started_at DESC
                   LIMIT ? OFFSET ?""",
                (limit, offset),
            ).fetchall()

        return [
            {"id": r[0], "title": r[1], "started_at": r[2], "ended_at": r[3],
             "duration_seconds": r[4], "status": r[5]}
            for r in rows
        ]

    def get_meeting_recording(self, recording_id: str) -> Dict | None:
        """Get full meeting recording detail including transcripts."""
        with self._connect() as conn:
            r = conn.execute(
                """SELECT id, title, started_at, ended_at, duration_seconds, status,
                          audio_file_path, tier1_transcript, tier2_transcript_json,
                          ai_summary, ai_actions_json, ai_title_generated
                   FROM meeting_recordings WHERE id = ?""",
                (recording_id,),
            ).fetchone()

        if not r:
            return None
        return {
            "id": r[0], "title": r[1], "started_at": r[2], "ended_at": r[3],
            "duration_seconds": r[4], "status": r[5], "audio_file_path": r[6],
            "tier1_transcript": r[7] or "",
            "tier2_transcript_json": json.loads(r[8]) if r[8] else None,
            "ai_summary": r[9],
            "ai_actions_json": json.loads(r[10]) if r[10] else None,
            "ai_title_generated": bool(r[11]),
        }

    def delete_meeting_recording(self, recording_id: str) -> None:
        """Delete a meeting recording."""
        with self._connect() as conn:
            conn.execute("DELETE FROM meeting_recordings WHERE id = ?", (recording_id,))
            conn.commit()

    def search_meeting_recordings(self, search_term: str, limit: int = 20) -> List[Dict]:
        """Search meeting recordings by title."""
        if not search_term or not search_term.strip():
            return []

        escaped = (
            search_term.replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_")
        )

        with self._connect() as conn:
            rows = conn.execute(
                """SELECT id, title, started_at, ended_at, duration_seconds, status
                   FROM meeting_recordings
                   WHERE title LIKE ? ESCAPE '\\'
                   ORDER BY started_at DESC
                   LIMIT ?""",
                (f"%{escaped}%", limit),
            ).fetchall()

        return [
            {"id": r[0], "title": r[1], "started_at": r[2], "ended_at": r[3],
             "duration_seconds": r[4], "status": r[5]}
            for r in rows
        ]


# Global singleton instance so all modules share the same DB connection logic
db = DatabaseManager()

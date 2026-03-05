import sqlite3
import json
import uuid
import time
import os
from contextlib import contextmanager
from typing import List, Dict


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

            conn.commit()

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
    ) -> None:
        """Save a message and bump the parent conversation's updated_at timestamp."""
        now = time.time()
        images_json = json.dumps(images) if images else None
        content_blocks_json = json.dumps(content_blocks) if content_blocks else None

        with self._connect() as conn:
            conn.execute(
                "INSERT INTO messages (conversation_id, role, content, images, model, content_blocks, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (conversation_id, role, content, images_json, model, content_blocks_json, now),
            )
            conn.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (now, conversation_id),
            )
            conn.commit()

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
                """SELECT role, content, images, created_at, model, content_blocks
                   FROM messages
                   WHERE conversation_id = ?
                   ORDER BY created_at ASC, num_messages ASC""",
                (conversation_id,),
            ).fetchall()

        return [
            {
                "role": row[0],
                "content": row[1],
                "images": json.loads(row[2]) if row[2] else [],
                "timestamp": row[3],
                "model": row[4],
                "content_blocks": json.loads(row[5]) if row[5] else None,
            }
            for row in rows
        ]

    def delete_conversation(self, conversation_id: str) -> None:
        """Delete a conversation and all associated data (messages, terminal events)."""
        with self._connect() as conn:
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

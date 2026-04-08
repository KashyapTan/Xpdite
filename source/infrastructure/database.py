import sqlite3
import json
import uuid
import time
import os
from contextlib import contextmanager
from typing import List, Dict, Any, Optional, Tuple


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

            # --- TABLE: ARTIFACTS ---
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS artifacts (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT,
                    message_id TEXT,
                    artifact_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    language TEXT,
                    storage_kind TEXT NOT NULL,
                    storage_path TEXT,
                    inline_content TEXT,
                    searchable_text TEXT NOT NULL DEFAULT '',
                    size_bytes INTEGER NOT NULL DEFAULT 0,
                    line_count INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'ready',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_artifacts_conversation
                ON artifacts(conversation_id, created_at DESC)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_artifacts_message
                ON artifacts(message_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_artifacts_type
                ON artifacts(artifact_type, updated_at DESC)
            """)
            cursor.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS artifacts_fts USING fts5(
                    artifact_id UNINDEXED,
                    title,
                    searchable_text,
                    tokenize="unicode61"
                )
            """)
            cursor.execute("""
                CREATE TRIGGER IF NOT EXISTS artifacts_fts_ai
                AFTER INSERT ON artifacts BEGIN
                    INSERT INTO artifacts_fts(rowid, artifact_id, title, searchable_text)
                    VALUES (new.rowid, new.id, new.title, new.searchable_text);
                END
            """)
            cursor.execute("""
                CREATE TRIGGER IF NOT EXISTS artifacts_fts_au
                AFTER UPDATE OF title, searchable_text ON artifacts BEGIN
                    DELETE FROM artifacts_fts WHERE rowid = old.rowid;
                    INSERT INTO artifacts_fts(rowid, artifact_id, title, searchable_text)
                    VALUES (new.rowid, new.id, new.title, new.searchable_text);
                END
            """)
            cursor.execute("""
                CREATE TRIGGER IF NOT EXISTS artifacts_fts_ad
                AFTER DELETE ON artifacts BEGIN
                    DELETE FROM artifacts_fts WHERE rowid = old.rowid;
                END
            """)

            # --- MOBILE CHANNEL TABLES ---
            # Paired devices table - stores devices that have completed pairing
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS mobile_paired_devices (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    platform TEXT NOT NULL,
                    sender_id TEXT NOT NULL,
                    display_name TEXT,
                    paired_at REAL NOT NULL,
                    last_active REAL,
                    UNIQUE(platform, sender_id)
                )
            """)

            # Active sessions table - maps platform users to Xpdite tabs
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS mobile_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    platform TEXT NOT NULL,
                    sender_id TEXT NOT NULL,
                    tab_id TEXT NOT NULL,
                    conversation_id TEXT,
                    model_override TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL,
                    UNIQUE(platform, sender_id)
                )
            """)

            # Pairing codes table - short-lived codes for device pairing
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS mobile_pairing_codes (
                    code TEXT PRIMARY KEY,
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    claimed INTEGER DEFAULT 0
                )
            """)

            # Mobile channel indexes
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_mobile_sessions_tab
                ON mobile_sessions(tab_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_mobile_paired_devices_platform
                ON mobile_paired_devices(platform, sender_id)
            """)

            # Mobile origin column on messages - stores JSON with platform info
            try:
                cursor.execute("ALTER TABLE messages ADD COLUMN mobile_origin TEXT")
            except sqlite3.OperationalError:
                pass  # Column already exists

            try:
                cursor.execute(
                    "ALTER TABLE mobile_paired_devices ADD COLUMN default_model TEXT"
                )
            except sqlite3.OperationalError:
                pass  # Column already exists

            # --- TABLE: SCHEDULED JOBS ---
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS scheduled_jobs (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    cron_expression TEXT NOT NULL,
                    instruction TEXT NOT NULL,
                    model TEXT,
                    timezone TEXT NOT NULL,
                    delivery_platform TEXT,
                    delivery_sender_id TEXT,
                    enabled INTEGER DEFAULT 1,
                    is_one_shot INTEGER DEFAULT 0,
                    created_at REAL NOT NULL,
                    last_run_at REAL,
                    next_run_at REAL,
                    run_count INTEGER DEFAULT 0,
                    missed INTEGER DEFAULT 0
                )
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_scheduled_jobs_enabled
                ON scheduled_jobs(enabled, next_run_at)
            """)

            # --- TABLE: NOTIFICATIONS ---
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS notifications (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    body TEXT,
                    payload TEXT,
                    created_at REAL NOT NULL
                )
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_notifications_created
                ON notifications(created_at DESC)
            """)

            # --- CONVERSATION JOB_ID MIGRATION ---
            try:
                cursor.execute("ALTER TABLE conversations ADD COLUMN job_id TEXT")
            except sqlite3.OperationalError:
                pass  # Column already exists

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_conversations_job
                ON conversations(job_id)
            """)

            # --- CONVERSATION JOB_NAME MIGRATION ---
            # Store job_name directly so it persists even if scheduled_job is deleted
            try:
                cursor.execute("ALTER TABLE conversations ADD COLUMN job_name TEXT")
            except sqlite3.OperationalError:
                pass  # Column already exists

            self._backfill_message_metadata(cursor)

            conn.commit()

    @staticmethod
    def _decode_images(images_json: Optional[str]) -> List[str]:
        return json.loads(images_json) if images_json else []

    @staticmethod
    def _decode_content_blocks(content_blocks_json: Optional[str]) -> List[Dict] | None:
        return json.loads(content_blocks_json) if content_blocks_json else None

    @staticmethod
    def generate_artifact_id() -> str:
        return str(uuid.uuid4())

    def _artifact_rows_by_id(
        self, artifact_ids: List[str], conn: sqlite3.Connection
    ) -> Dict[str, Dict[str, Any]]:
        ids = [artifact_id for artifact_id in dict.fromkeys(artifact_ids) if artifact_id]
        if not ids:
            return {}

        placeholders = ",".join("?" for _ in ids)
        rows = conn.execute(
            f"""SELECT id, artifact_type, title, language, size_bytes, line_count,
                       status, conversation_id, message_id, created_at, updated_at
                FROM artifacts
                WHERE id IN ({placeholders})""",
            ids,
        ).fetchall()
        return {
            row[0]: {
                "id": row[0],
                "artifact_type": row[1],
                "title": row[2],
                "language": row[3],
                "size_bytes": row[4],
                "line_count": row[5],
                "status": row[6],
                "conversation_id": row[7],
                "message_id": row[8],
                "created_at": row[9],
                "updated_at": row[10],
            }
            for row in rows
        }

    def _resolve_content_blocks(
        self,
        content_blocks_json: Optional[str],
        conn: sqlite3.Connection,
    ) -> List[Dict] | None:
        blocks = self._decode_content_blocks(content_blocks_json)
        if not blocks:
            return blocks

        artifact_ids = [
            str(block.get("artifact_id") or block.get("artifactId") or "").strip()
            for block in blocks
            if block.get("type") == "artifact"
        ]
        artifact_map = self._artifact_rows_by_id(artifact_ids, conn)

        resolved_blocks: List[Dict[str, Any]] = []
        for block in blocks:
            if block.get("type") != "artifact":
                resolved_blocks.append(block)
                continue

            artifact_id = str(block.get("artifact_id") or block.get("artifactId") or "").strip()
            artifact_row = artifact_map.get(artifact_id)
            resolved_blocks.append(
                {
                    "type": "artifact",
                    "artifact_id": artifact_id,
                    "artifact_type": (
                        block.get("artifact_type")
                        or block.get("artifactType")
                        or (artifact_row or {}).get("artifact_type")
                        or ""
                    ),
                    "title": block.get("title") or (artifact_row or {}).get("title") or "Untitled artifact",
                    "language": block.get("language")
                    if block.get("language") is not None
                    else (artifact_row or {}).get("language"),
                    "size_bytes": (
                        (artifact_row or {}).get("size_bytes")
                        if artifact_row is not None
                        else int(block.get("size_bytes") or block.get("sizeBytes") or 0)
                    ),
                    "line_count": (
                        (artifact_row or {}).get("line_count")
                        if artifact_row is not None
                        else int(block.get("line_count") or block.get("lineCount") or 0)
                    ),
                    "status": (
                        "deleted"
                        if artifact_row is None
                        or str((artifact_row or {}).get("status") or "").lower() == "deleted"
                        else "ready"
                    ),
                }
            )

        return resolved_blocks

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
                "content_blocks": self._resolve_content_blocks(row[3], conn),
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
            "content_blocks": self._resolve_content_blocks(row[8], conn),
            "active_response_index": row[9] or 0,
        }
        # mobile_origin is stored as JSON text in row[10]
        if len(row) > 10 and row[10]:
            message["mobile_origin"] = json.loads(row[10])
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
        mobile_origin: Dict[str, str] | None = None,
    ) -> Dict[str, Any]:
        """Save a message and return its persisted metadata."""
        now = created_at if created_at is not None else time.time()
        images_json = json.dumps(images) if images else None
        content_blocks_json = json.dumps(content_blocks) if content_blocks else None
        mobile_origin_json = json.dumps(mobile_origin) if mobile_origin else None
        resolved_turn_id = turn_id or str(uuid.uuid4())
        resolved_message_id = message_id or str(uuid.uuid4())

        with self._connect() as conn:
            cursor = conn.execute(
                """INSERT INTO messages
                   (conversation_id, role, content, images, model, content_blocks, created_at,
                    message_id, turn_id, active_response_index, mobile_origin)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                    mobile_origin_json,
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
                          model, content_blocks, active_response_index, mobile_origin, conversation_id
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
                    row[10],
                ),
                conn,
            )
            message["conversation_id"] = row[11]
            return message

    def get_turn_messages(
        self, conversation_id: str, turn_id: str
    ) -> List[Dict[str, Any]]:
        """Return all persisted messages for a single turn."""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT num_messages, message_id, turn_id, role, content, images, created_at,
                          model, content_blocks, active_response_index, mobile_origin
                   FROM messages
                   WHERE conversation_id = ? AND turn_id = ?
                   ORDER BY created_at ASC, num_messages ASC""",
                (conversation_id, turn_id),
            ).fetchall()

            return [self._build_message_record(row, conn) for row in rows]

    def get_turn_payload(
        self, conversation_id: str, turn_id: str
    ) -> Dict[str, Any] | None:
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

    def truncate_conversation_after_turn(
        self, conversation_id: str, turn_id: str
    ) -> None:
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
                conn.execute("DELETE FROM artifacts WHERE message_id = ?", (assistant_id,))

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

    def create_artifact(
        self,
        *,
        artifact_id: str,
        conversation_id: Optional[str],
        message_id: Optional[str],
        artifact_type: str,
        title: str,
        language: Optional[str],
        storage_kind: str,
        storage_path: Optional[str],
        inline_content: Optional[str],
        searchable_text: str,
        size_bytes: int,
        line_count: int,
        status: str = "ready",
    ) -> Dict[str, Any]:
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO artifacts
                   (id, conversation_id, message_id, artifact_type, title, language,
                    storage_kind, storage_path, inline_content, searchable_text,
                    size_bytes, line_count, status, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    artifact_id,
                    conversation_id,
                    message_id,
                    artifact_type,
                    title,
                    language,
                    storage_kind,
                    storage_path,
                    inline_content,
                    searchable_text,
                    size_bytes,
                    line_count,
                    status,
                    now,
                    now,
                ),
            )
            conn.commit()
        artifact = self.get_artifact(artifact_id)
        assert artifact is not None
        return artifact

    def update_artifact(
        self,
        *,
        artifact_id: str,
        title: str,
        language: Optional[str],
        storage_path: Optional[str],
        inline_content: Optional[str],
        searchable_text: str,
        size_bytes: int,
        line_count: int,
    ) -> Dict[str, Any] | None:
        now = time.time()
        with self._connect() as conn:
            cursor = conn.execute(
                """UPDATE artifacts
                   SET title = ?,
                       language = ?,
                       storage_path = ?,
                       inline_content = ?,
                       searchable_text = ?,
                       size_bytes = ?,
                       line_count = ?,
                       updated_at = ?
                   WHERE id = ?""",
                (
                    title,
                    language,
                    storage_path,
                    inline_content,
                    searchable_text,
                    size_bytes,
                    line_count,
                    now,
                    artifact_id,
                ),
            )
            if cursor.rowcount == 0:
                conn.rollback()
                return None
            conn.commit()
        return self.get_artifact(artifact_id)

    def link_artifacts_to_message(
        self, artifact_ids: List[str], message_id: str
    ) -> None:
        if not artifact_ids:
            return
        placeholders = ",".join("?" for _ in artifact_ids)
        with self._connect() as conn:
            conn.execute(
                f"""UPDATE artifacts
                    SET message_id = ?, updated_at = ?
                    WHERE id IN ({placeholders})""",
                [message_id, time.time(), *artifact_ids],
            )
            conn.commit()

    def get_artifact(self, artifact_id: str) -> Dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """SELECT id, conversation_id, message_id, artifact_type, title, language,
                          storage_kind, storage_path, inline_content, searchable_text,
                          size_bytes, line_count, status, created_at, updated_at
                   FROM artifacts
                   WHERE id = ?""",
                (artifact_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "id": row[0],
            "conversation_id": row[1],
            "message_id": row[2],
            "artifact_type": row[3],
            "title": row[4],
            "language": row[5],
            "storage_kind": row[6],
            "storage_path": row[7],
            "inline_content": row[8],
            "searchable_text": row[9],
            "size_bytes": row[10],
            "line_count": row[11],
            "status": row[12],
            "created_at": row[13],
            "updated_at": row[14],
        }

    def list_artifacts(
        self,
        *,
        query: str = "",
        artifact_type: Optional[str] = None,
        status: Optional[str] = None,
        page: int = 1,
        page_size: int = 50,
        conversation_id: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], int]:
        page = max(page, 1)
        page_size = max(min(page_size, 200), 1)
        offset = (page - 1) * page_size
        query = query.strip()
        filters: List[str] = []
        params: List[Any] = []

        if artifact_type:
            filters.append("a.artifact_type = ?")
            params.append(artifact_type)
        if status:
            filters.append("a.status = ?")
            params.append(status)
        if conversation_id:
            filters.append("a.conversation_id = ?")
            params.append(conversation_id)

        where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""

        with self._connect() as conn:
            if query:
                fts_term = self._fts5_phrase(query)
                count_row = conn.execute(
                    f"""SELECT COUNT(*)
                        FROM artifacts a
                        JOIN artifacts_fts fts ON fts.rowid = a.rowid
                        {where_clause}
                        {"AND" if where_clause else "WHERE"} artifacts_fts MATCH ?""",
                    [*params, fts_term],
                ).fetchone()
                rows = conn.execute(
                    f"""SELECT a.id, a.artifact_type, a.title, a.language,
                               a.size_bytes, a.line_count, a.status,
                               a.conversation_id, a.message_id, a.created_at, a.updated_at
                        FROM artifacts a
                        JOIN artifacts_fts fts ON fts.rowid = a.rowid
                        {where_clause}
                        {"AND" if where_clause else "WHERE"} artifacts_fts MATCH ?
                        ORDER BY a.updated_at DESC
                        LIMIT ? OFFSET ?""",
                    [*params, fts_term, page_size, offset],
                ).fetchall()
            else:
                count_row = conn.execute(
                    f"SELECT COUNT(*) FROM artifacts a {where_clause}",
                    params,
                ).fetchone()
                rows = conn.execute(
                    f"""SELECT a.id, a.artifact_type, a.title, a.language,
                               a.size_bytes, a.line_count, a.status,
                               a.conversation_id, a.message_id, a.created_at, a.updated_at
                        FROM artifacts a
                        {where_clause}
                        ORDER BY a.updated_at DESC
                        LIMIT ? OFFSET ?""",
                    [*params, page_size, offset],
                ).fetchall()

        total = int(count_row[0]) if count_row and count_row[0] is not None else 0
        artifacts = [
            {
                "id": row[0],
                "type": row[1],
                "title": row[2],
                "language": row[3],
                "size_bytes": row[4],
                "line_count": row[5],
                "status": row[6],
                "conversation_id": row[7],
                "message_id": row[8],
                "created_at": row[9],
                "updated_at": row[10],
            }
            for row in rows
        ]
        return artifacts, total

    def delete_artifact(self, artifact_id: str) -> Dict[str, Any] | None:
        artifact = self.get_artifact(artifact_id)
        if artifact is None:
            return None
        with self._connect() as conn:
            conn.execute(
                """UPDATE artifacts
                   SET storage_path = NULL,
                       inline_content = NULL,
                       searchable_text = '',
                       status = 'deleted',
                       updated_at = ?
                   WHERE id = ?""",
                (time.time(), artifact_id),
            )
            conn.commit()
        return artifact

    def delete_artifacts_for_message(self, message_id: str) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT id, conversation_id, message_id, artifact_type, title, language,
                          storage_kind, storage_path, inline_content, searchable_text,
                          size_bytes, line_count, status, created_at, updated_at
                   FROM artifacts
                   WHERE message_id = ?""",
                (message_id,),
            ).fetchall()
            conn.execute(
                """UPDATE artifacts
                   SET storage_path = NULL,
                       inline_content = NULL,
                       searchable_text = '',
                       status = 'deleted',
                       updated_at = ?
                   WHERE message_id = ?""",
                (time.time(), message_id),
            )
            conn.commit()

        return [
            {
                "id": row[0],
                "conversation_id": row[1],
                "message_id": row[2],
                "artifact_type": row[3],
                "title": row[4],
                "language": row[5],
                "storage_kind": row[6],
                "storage_path": row[7],
                "inline_content": row[8],
                "searchable_text": row[9],
                "size_bytes": row[10],
                "line_count": row[11],
                "status": row[12],
                "created_at": row[13],
                "updated_at": row[14],
            }
            for row in rows
        ]

    def delete_artifacts_for_conversation(self, conversation_id: str) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT id, conversation_id, message_id, artifact_type, title, language,
                          storage_kind, storage_path, inline_content, searchable_text,
                          size_bytes, line_count, status, created_at, updated_at
                   FROM artifacts
                   WHERE conversation_id = ?""",
                (conversation_id,),
            ).fetchall()
            conn.execute(
                """UPDATE artifacts
                   SET storage_path = NULL,
                       inline_content = NULL,
                       searchable_text = '',
                       status = 'deleted',
                       updated_at = ?
                   WHERE conversation_id = ?""",
                (time.time(), conversation_id),
            )
            conn.commit()

        return [
            {
                "id": row[0],
                "conversation_id": row[1],
                "message_id": row[2],
                "artifact_type": row[3],
                "title": row[4],
                "language": row[5],
                "storage_kind": row[6],
                "storage_path": row[7],
                "inline_content": row[8],
                "searchable_text": row[9],
                "size_bytes": row[10],
                "line_count": row[11],
                "status": row[12],
                "created_at": row[13],
                "updated_at": row[14],
            }
            for row in rows
        ]

    def get_assistant_message_ids_after_turn(
        self, conversation_id: str, turn_id: str
    ) -> List[str]:
        with self._connect() as conn:
            cutoff = conn.execute(
                """SELECT MAX(num_messages)
                   FROM messages
                   WHERE conversation_id = ? AND turn_id = ?""",
                (conversation_id, turn_id),
            ).fetchone()
            if cutoff is None or cutoff[0] is None:
                return []
            rows = conn.execute(
                """SELECT message_id
                   FROM messages
                   WHERE conversation_id = ? AND num_messages > ? AND role = 'assistant'""",
                (conversation_id, cutoff[0]),
            ).fetchall()
        return [row[0] for row in rows if row and row[0]]

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
        """Return conversations ordered by most recently active, with pagination.
        Excludes conversations created by scheduled jobs (those have job_id set).
        """
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT id, title, updated_at FROM conversations
                   WHERE job_id IS NULL
                   ORDER BY updated_at DESC LIMIT ? OFFSET ?""",
                (limit, offset),
            ).fetchall()
        return [{"id": r[0], "title": r[1], "date": r[2]} for r in rows]

    def get_full_conversation(self, conversation_id: str) -> List[Dict]:
        """Load all messages for a conversation in stable insertion order."""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT num_messages, message_id, turn_id, role, content, images, created_at,
                          model, content_blocks, active_response_index, mobile_origin
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
                conn.execute("DELETE FROM artifacts WHERE message_id = ?", (assistant_id,))
            conn.execute(
                "DELETE FROM artifacts WHERE conversation_id = ?",
                (conversation_id,),
            )
            conn.execute(
                "DELETE FROM terminal_events WHERE conversation_id = ?",
                (conversation_id,),
            )
            conn.execute(
                "DELETE FROM messages WHERE conversation_id = ?", (conversation_id,)
            )
            conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
            conn.commit()

    @staticmethod
    def _fts5_phrase(term: str) -> str:
        """Wrap a raw user string in FTS5 double-quote phrase syntax.
        Internal double-quotes are escaped by doubling ("" → literal ")."""
        return '"' + term.replace('"', '""') + '"'

    def search_conversations(self, search_term: str, limit: int = 20) -> List[Dict]:
        """Search conversations by title or message content using FTS5.
        Falls back to LIKE if FTS tables are unavailable.
        Excludes conversations created by scheduled jobs (those have job_id set).
        """
        if not search_term or not search_term.strip():
            return []

        fts_query = self._fts5_phrase(search_term)

        with self._connect() as conn:
            try:
                rows = conn.execute(
                    """SELECT c.id, c.title, c.updated_at
                       FROM conversations c
                       WHERE c.job_id IS NULL AND c.id IN (
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
                       WHERE c.job_id IS NULL AND (c.title LIKE ? ESCAPE '\\' OR m.content LIKE ? ESCAPE '\\')
                       ORDER BY c.updated_at DESC
                       LIMIT ?""",
                    (f"%{escaped}%", f"%{escaped}%", limit),
                ).fetchall()

        return [{"id": r[0], "title": r[1], "date": r[2]} for r in rows]

    def update_conversation_title(self, conversation_id: str, title: str) -> None:
        """Update the title of an existing conversation."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE conversations SET title = ? WHERE id = ?",
                (title, conversation_id),
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
            row = conn.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ).fetchone()
        return row[0] if row else None

    def set_setting(self, key: str, value: str):
        """Set a raw setting value (upsert)."""
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                (key, value),
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
                    event_id,
                    conversation_id,
                    message_index,
                    command,
                    exit_code,
                    output_preview,
                    full_output,
                    cwd,
                    duration_ms,
                    int(timed_out),
                    int(denied),
                    int(pty),
                    int(background),
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
                "id": r[0],
                "message_index": r[1],
                "command": r[2],
                "exit_code": r[3],
                "output_preview": r[4],
                "cwd": r[5],
                "duration_ms": r[6],
                "timed_out": bool(r[7]),
                "denied": bool(r[8]),
                "pty": bool(r[9]),
                "background": bool(r[10]),
                "created_at": r[11],
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
            "title",
            "ended_at",
            "duration_seconds",
            "status",
            "audio_file_path",
            "tier1_transcript",
            "tier2_transcript_json",
            "ai_summary",
            "ai_actions_json",
            "ai_title_generated",
        }
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return

        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [recording_id]

        with self._connect() as conn:
            conn.execute(
                f"UPDATE meeting_recordings SET {set_clause} WHERE id = ?", values
            )
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
            {
                "id": r[0],
                "title": r[1],
                "started_at": r[2],
                "ended_at": r[3],
                "duration_seconds": r[4],
                "status": r[5],
            }
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
            "id": r[0],
            "title": r[1],
            "started_at": r[2],
            "ended_at": r[3],
            "duration_seconds": r[4],
            "status": r[5],
            "audio_file_path": r[6],
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

    def search_meeting_recordings(
        self, search_term: str, limit: int = 20
    ) -> List[Dict]:
        """Search meeting recordings by title."""
        if not search_term or not search_term.strip():
            return []

        escaped = (
            search_term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
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
            {
                "id": r[0],
                "title": r[1],
                "started_at": r[2],
                "ended_at": r[3],
                "duration_seconds": r[4],
                "status": r[5],
            }
            for r in rows
        ]

    # ---------------------------------------------------------
    # MOBILE CHANNEL OPERATIONS
    # ---------------------------------------------------------

    def create_pairing_code(self, code: str, expires_in_seconds: int = 600) -> None:
        """Create a new pairing code with expiry."""
        now = time.time()
        with self._connect() as conn:
            # Clean up old expired codes first
            conn.execute(
                "DELETE FROM mobile_pairing_codes WHERE expires_at < ?", (now,)
            )
            conn.execute(
                """INSERT OR REPLACE INTO mobile_pairing_codes 
                   (code, created_at, expires_at, claimed)
                   VALUES (?, ?, ?, 0)""",
                (code, now, now + expires_in_seconds),
            )
            conn.commit()

    def verify_pairing_code(self, code: str) -> bool:
        """Check if a pairing code is valid and mark it as claimed.

        Returns True if the code was valid and is now claimed.
        Returns False if the code doesn't exist, is expired, or was already claimed.
        """
        now = time.time()
        with self._connect() as conn:
            row = conn.execute(
                """SELECT claimed FROM mobile_pairing_codes
                   WHERE code = ? AND expires_at > ?""",
                (code, now),
            ).fetchone()

            if not row or row[0]:  # Not found or already claimed
                return False

            conn.execute(
                "UPDATE mobile_pairing_codes SET claimed = 1 WHERE code = ?",
                (code,),
            )
            conn.commit()
            return True

    def cleanup_expired_pairing_codes(self) -> int:
        """Remove expired pairing codes. Returns count of deleted codes."""
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM mobile_pairing_codes WHERE expires_at < ?",
                (time.time(),),
            )
            conn.commit()
            return cursor.rowcount

    def add_paired_device(
        self, platform: str, sender_id: str, display_name: str | None = None
    ) -> int:
        """Add or update a paired device. Returns the device ID."""
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO mobile_paired_devices 
                   (platform, sender_id, display_name, paired_at, last_active)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(platform, sender_id) DO UPDATE SET
                   display_name = excluded.display_name,
                   last_active = excluded.last_active""",
                (platform, sender_id, display_name, now, now),
            )
            conn.commit()

            row = conn.execute(
                "SELECT id FROM mobile_paired_devices WHERE platform = ? AND sender_id = ?",
                (platform, sender_id),
            ).fetchone()
            return row[0] if row else 0

    def get_paired_device(self, platform: str, sender_id: str) -> Dict | None:
        """Get a paired device by platform and sender ID."""
        with self._connect() as conn:
            row = conn.execute(
                """SELECT id, platform, sender_id, display_name, paired_at, last_active, default_model
                   FROM mobile_paired_devices
                   WHERE platform = ? AND sender_id = ?""",
                (platform, sender_id),
            ).fetchone()

        if not row:
            return None
        return {
            "id": row[0],
            "platform": row[1],
            "sender_id": row[2],
            "display_name": row[3],
            "paired_at": row[4],
            "last_active": row[5],
            "default_model": row[6],
        }

    def get_all_paired_devices(self) -> List[Dict]:
        """Get all paired devices."""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT id, platform, sender_id, display_name, paired_at, last_active
                   FROM mobile_paired_devices
                   ORDER BY last_active DESC"""
            ).fetchall()

        return [
            {
                "id": r[0],
                "platform": r[1],
                "sender_id": r[2],
                "display_name": r[3],
                "paired_at": r[4],
                "last_active": r[5],
            }
            for r in rows
        ]

    def delete_paired_device(self, device_id: int) -> None:
        """Delete a paired device by ID."""
        with self._connect() as conn:
            # Also delete any sessions for this device
            device = conn.execute(
                "SELECT platform, sender_id FROM mobile_paired_devices WHERE id = ?",
                (device_id,),
            ).fetchone()

            if device:
                conn.execute(
                    "DELETE FROM mobile_sessions WHERE platform = ? AND sender_id = ?",
                    (device[0], device[1]),
                )

            conn.execute(
                "DELETE FROM mobile_paired_devices WHERE id = ?",
                (device_id,),
            )
            conn.commit()

    def update_paired_device_activity(self, platform: str, sender_id: str) -> None:
        """Update the last_active timestamp for a paired device."""
        with self._connect() as conn:
            conn.execute(
                """UPDATE mobile_paired_devices SET last_active = ?
                   WHERE platform = ? AND sender_id = ?""",
                (time.time(), platform, sender_id),
            )
            conn.commit()

    def get_paired_device_default_model(
        self, platform: str, sender_id: str
    ) -> str | None:
        """Get the default model preference for a paired device."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT default_model FROM mobile_paired_devices WHERE platform = ? AND sender_id = ?",
                (platform, sender_id),
            ).fetchone()
            return row[0] if row else None

    def set_paired_device_default_model(
        self, platform: str, sender_id: str, model: str
    ) -> None:
        """Set the default model preference for a paired device."""
        with self._connect() as conn:
            conn.execute(
                """UPDATE mobile_paired_devices SET default_model = ?
                   WHERE platform = ? AND sender_id = ?""",
                (model, platform, sender_id),
            )
            conn.commit()

    def create_mobile_session(self, platform: str, sender_id: str, tab_id: str) -> int:
        """Create a new mobile session. Returns the session ID."""
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO mobile_sessions 
                   (platform, sender_id, tab_id, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(platform, sender_id) DO UPDATE SET
                   tab_id = excluded.tab_id,
                   updated_at = excluded.updated_at""",
                (platform, sender_id, tab_id, now, now),
            )
            conn.commit()

            row = conn.execute(
                "SELECT id FROM mobile_sessions WHERE platform = ? AND sender_id = ?",
                (platform, sender_id),
            ).fetchone()
            return row[0] if row else 0

    def get_mobile_session(self, platform: str, sender_id: str) -> Dict | None:
        """Get a mobile session by platform and sender ID."""
        with self._connect() as conn:
            row = conn.execute(
                """SELECT id, platform, sender_id, tab_id, conversation_id, 
                          model_override, created_at, updated_at
                   FROM mobile_sessions
                   WHERE platform = ? AND sender_id = ?""",
                (platform, sender_id),
            ).fetchone()

        if not row:
            return None
        return {
            "id": row[0],
            "platform": row[1],
            "sender_id": row[2],
            "tab_id": row[3],
            "conversation_id": row[4],
            "model_override": row[5],
            "created_at": row[6],
            "updated_at": row[7],
        }

    def get_mobile_session_by_tab(self, tab_id: str) -> Dict | None:
        """Get a mobile session by tab ID."""
        with self._connect() as conn:
            row = conn.execute(
                """SELECT id, platform, sender_id, tab_id, conversation_id, 
                          model_override, created_at, updated_at
                   FROM mobile_sessions
                   WHERE tab_id = ?""",
                (tab_id,),
            ).fetchone()

        if not row:
            return None
        return {
            "id": row[0],
            "platform": row[1],
            "sender_id": row[2],
            "tab_id": row[3],
            "conversation_id": row[4],
            "model_override": row[5],
            "created_at": row[6],
            "updated_at": row[7],
        }

    def update_mobile_session(self, platform: str, sender_id: str, **fields) -> None:
        """Update fields on a mobile session."""
        allowed = {"tab_id", "conversation_id", "model_override"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return

        updates["updated_at"] = time.time()
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [platform, sender_id]

        with self._connect() as conn:
            conn.execute(
                f"""UPDATE mobile_sessions SET {set_clause}
                    WHERE platform = ? AND sender_id = ?""",
                values,
            )
            conn.commit()

    def delete_mobile_session(self, platform: str, sender_id: str) -> None:
        """Delete a mobile session."""
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM mobile_sessions WHERE platform = ? AND sender_id = ?",
                (platform, sender_id),
            )
            conn.commit()

    def get_all_mobile_sessions(self) -> List[Dict]:
        """Get all mobile sessions."""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT id, platform, sender_id, tab_id, conversation_id, 
                          model_override, created_at, updated_at
                   FROM mobile_sessions
                   ORDER BY updated_at DESC"""
            ).fetchall()

        return [
            {
                "id": r[0],
                "platform": r[1],
                "sender_id": r[2],
                "tab_id": r[3],
                "conversation_id": r[4],
                "model_override": r[5],
                "created_at": r[6],
                "updated_at": r[7],
            }
            for r in rows
        ]

    # ---------------------------------------------------------
    # SCHEDULED JOBS OPERATIONS
    # ---------------------------------------------------------

    def create_scheduled_job(
        self,
        name: str,
        cron_expression: str,
        instruction: str,
        timezone: str,
        model: str | None = None,
        delivery_platform: str | None = None,
        delivery_sender_id: str | None = None,
        is_one_shot: bool = False,
        next_run_at: float | None = None,
    ) -> Dict[str, Any]:
        """Create a new scheduled job. Returns the full job record."""
        job_id = str(uuid.uuid4())
        now = time.time()

        with self._connect() as conn:
            conn.execute(
                """INSERT INTO scheduled_jobs
                   (id, name, cron_expression, instruction, model, timezone,
                    delivery_platform, delivery_sender_id, enabled, is_one_shot,
                    created_at, next_run_at, run_count, missed)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, 0, 0)""",
                (
                    job_id,
                    name,
                    cron_expression,
                    instruction,
                    model,
                    timezone,
                    delivery_platform,
                    delivery_sender_id,
                    int(is_one_shot),
                    now,
                    next_run_at,
                ),
            )
            conn.commit()

        return self.get_scheduled_job(job_id)  # type: ignore

    def get_scheduled_job(self, job_id: str) -> Dict[str, Any] | None:
        """Get a scheduled job by ID."""
        with self._connect() as conn:
            row = conn.execute(
                """SELECT id, name, cron_expression, instruction, model, timezone,
                          delivery_platform, delivery_sender_id, enabled, is_one_shot,
                          created_at, last_run_at, next_run_at, run_count, missed
                   FROM scheduled_jobs WHERE id = ?""",
                (job_id,),
            ).fetchone()

        if not row:
            return None
        return {
            "id": row[0],
            "name": row[1],
            "cron_expression": row[2],
            "instruction": row[3],
            "model": row[4],
            "timezone": row[5],
            "delivery_platform": row[6],
            "delivery_sender_id": row[7],
            "enabled": bool(row[8]),
            "is_one_shot": bool(row[9]),
            "created_at": row[10],
            "last_run_at": row[11],
            "next_run_at": row[12],
            "run_count": row[13],
            "missed": bool(row[14]),
        }

    def list_scheduled_jobs(self, enabled_only: bool = False) -> List[Dict[str, Any]]:
        """List all scheduled jobs, optionally filtering to enabled only."""
        query = """SELECT id, name, cron_expression, instruction, model, timezone,
                          delivery_platform, delivery_sender_id, enabled, is_one_shot,
                          created_at, last_run_at, next_run_at, run_count, missed
                   FROM scheduled_jobs"""
        if enabled_only:
            query += " WHERE enabled = 1"
        query += " ORDER BY created_at DESC"

        with self._connect() as conn:
            rows = conn.execute(query).fetchall()

        return [
            {
                "id": r[0],
                "name": r[1],
                "cron_expression": r[2],
                "instruction": r[3],
                "model": r[4],
                "timezone": r[5],
                "delivery_platform": r[6],
                "delivery_sender_id": r[7],
                "enabled": bool(r[8]),
                "is_one_shot": bool(r[9]),
                "created_at": r[10],
                "last_run_at": r[11],
                "next_run_at": r[12],
                "run_count": r[13],
                "missed": bool(r[14]),
            }
            for r in rows
        ]

    def update_scheduled_job(self, job_id: str, **fields) -> Dict[str, Any] | None:
        """Update fields on a scheduled job."""
        allowed = {
            "name",
            "cron_expression",
            "instruction",
            "model",
            "timezone",
            "delivery_platform",
            "delivery_sender_id",
            "enabled",
            "is_one_shot",
            "last_run_at",
            "next_run_at",
            "run_count",
            "missed",
        }
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return self.get_scheduled_job(job_id)

        # Convert bool fields to int for SQLite
        for bool_field in ("enabled", "is_one_shot", "missed"):
            if bool_field in updates:
                updates[bool_field] = int(updates[bool_field])

        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [job_id]

        with self._connect() as conn:
            conn.execute(f"UPDATE scheduled_jobs SET {set_clause} WHERE id = ?", values)
            conn.commit()

        return self.get_scheduled_job(job_id)

    def delete_scheduled_job(self, job_id: str) -> None:
        """Delete a scheduled job by ID."""
        with self._connect() as conn:
            conn.execute("DELETE FROM scheduled_jobs WHERE id = ?", (job_id,))
            conn.commit()

    def mark_job_run(
        self, job_id: str, last_run_at: float, next_run_at: float | None
    ) -> None:
        """Update job after execution: increment run_count, update timestamps."""
        with self._connect() as conn:
            conn.execute(
                """UPDATE scheduled_jobs
                   SET last_run_at = ?, next_run_at = ?, run_count = run_count + 1
                   WHERE id = ?""",
                (last_run_at, next_run_at, job_id),
            )
            conn.commit()

    def get_job_conversations(
        self, job_id: str | None = None, limit: int = 50, offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Get conversations generated by scheduled jobs.

        If job_id is provided, filter to that job only.
        Returns conversations with their job metadata.

        Note: Prefers the stored c.job_name (captured at creation) over the joined
        j.name so that conversations retain their original job name even if the
        scheduled job is later renamed or deleted.
        """
        if job_id:
            query = """SELECT c.id, c.title, c.created_at, c.updated_at, c.job_id,
                              COALESCE(c.job_name, j.name) as job_name
                       FROM conversations c
                       LEFT JOIN scheduled_jobs j ON c.job_id = j.id
                       WHERE c.job_id = ?
                       ORDER BY c.created_at DESC
                       LIMIT ? OFFSET ?"""
            params = (job_id, limit, offset)
        else:
            query = """SELECT c.id, c.title, c.created_at, c.updated_at, c.job_id,
                              COALESCE(c.job_name, j.name) as job_name
                       FROM conversations c
                       LEFT JOIN scheduled_jobs j ON c.job_id = j.id
                       WHERE c.job_id IS NOT NULL
                       ORDER BY c.created_at DESC
                       LIMIT ? OFFSET ?"""
            params = (limit, offset)

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()

        return [
            {
                "id": r[0],
                "title": r[1],
                "created_at": r[2],
                "updated_at": r[3],
                "job_id": r[4],
                "job_name": r[5],
            }
            for r in rows
        ]

    def start_job_conversation(
        self, title: str, job_id: str, job_name: str | None = None
    ) -> str:
        """Create a new conversation tagged with a job ID.

        Args:
            title: The conversation title (e.g., "[Job] Daily Summary")
            job_id: The scheduled job's UUID
            job_name: The job's name at creation time (persisted even if job is deleted)

        Returns:
            The new conversation's UUID.
        """
        new_id = str(uuid.uuid4())
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO conversations (id, title, created_at, updated_at, job_id, job_name)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (new_id, title, now, now, job_id, job_name),
            )
            conn.commit()
        return new_id

    # ---------------------------------------------------------
    # NOTIFICATION OPERATIONS
    # ---------------------------------------------------------

    def create_notification(
        self,
        notification_type: str,
        title: str,
        body: str | None = None,
        payload: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        """Create a notification. Returns the full notification record."""
        notification_id = str(uuid.uuid4())
        now = time.time()
        payload_json = json.dumps(payload) if payload else None

        with self._connect() as conn:
            conn.execute(
                """INSERT INTO notifications (id, type, title, body, payload, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (notification_id, notification_type, title, body, payload_json, now),
            )
            conn.commit()

        return {
            "id": notification_id,
            "type": notification_type,
            "title": title,
            "body": body,
            "payload": payload,
            "created_at": now,
        }

    def get_notification(self, notification_id: str) -> Dict[str, Any] | None:
        """Get a notification by ID."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, type, title, body, payload, created_at FROM notifications WHERE id = ?",
                (notification_id,),
            ).fetchone()

        if not row:
            return None
        return {
            "id": row[0],
            "type": row[1],
            "title": row[2],
            "body": row[3],
            "payload": json.loads(row[4]) if row[4] else None,
            "created_at": row[5],
        }

    def list_notifications(self, limit: int = 100) -> List[Dict[str, Any]]:
        """List all notifications, newest first."""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT id, type, title, body, payload, created_at
                   FROM notifications
                   ORDER BY created_at DESC
                   LIMIT ?""",
                (limit,),
            ).fetchall()

        return [
            {
                "id": r[0],
                "type": r[1],
                "title": r[2],
                "body": r[3],
                "payload": json.loads(r[4]) if r[4] else None,
                "created_at": r[5],
            }
            for r in rows
        ]

    def delete_notification(self, notification_id: str) -> None:
        """Delete a notification (mark as read)."""
        with self._connect() as conn:
            conn.execute("DELETE FROM notifications WHERE id = ?", (notification_id,))
            conn.commit()

    def delete_all_notifications(self) -> int:
        """Delete all notifications. Returns count of deleted notifications."""
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM notifications")
            conn.commit()
            return cursor.rowcount

    def get_notification_count(self) -> int:
        """Get the count of unread notifications."""
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) FROM notifications").fetchone()
            return row[0] if row else 0


# Global singleton instance so all modules share the same DB connection logic
db = DatabaseManager()

import sqlite3
import json
import uuid
import time
from typing import List, Dict, Any
import os


class DatabaseManager:
    def __init__(self, database_path="user_data/xpdite_app.db"):
        """
        Initialize the database manager.
        We use a specific file path so the data persists between app restarts.
        """
        os.makedirs(os.path.dirname(database_path), exist_ok=True)
        self.database_path = database_path
        self._init_db()

    def _get_connection(self):
        """
        Establishes a connection to the SQLite file.

        CRITICAL CONCEPT: check_same_thread=False
        By default, SQLite enforces that a connection created in one thread
        can only be used in that same thread.

        However, FastAPI (and Python's asyncio) runs in a 'ThreadPool', meaning
        different requests might happen on different threads. If we don't set
        this to False, your app will crash with a ProgrammingError when
        multiple messages come in quickly.
        """
        return sqlite3.connect(self.database_path, check_same_thread=False)

    def _init_db(self):
        """
        Schema Definition.
        We use 'IF NOT EXISTS' so this runs safely every time the app boots.
        """
        connection = self._get_connection()
        cursor = connection.cursor()

        # --- TABLE 1: CONVERSATIONS ---
        # This acts as the "Folder" for messages.
        # It holds metadata used for the Sidebar list.
        # We store 'updated_at' so we can sort the sidebar by the most active chat.

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,    -- UUID string (e.g., "550e8400-e29b...")
                title TEXT,             -- A short summary of the chat
                created_at REAL,        -- 'REAL' is SQLite's float type (Unix timestamp)
                updated_at REAL,        -- Updated every time a new message is added
                total_input_tokens INTEGER DEFAULT 0,   -- Cumulative input tokens
                total_output_tokens INTEGER DEFAULT 0   -- Cumulative output tokens
            )
        """)

        # Migration: add token columns to existing databases that lack them
        try:
            cursor.execute(
                "ALTER TABLE conversations ADD COLUMN total_input_tokens INTEGER DEFAULT 0"
            )
        except sqlite3.OperationalError:
            pass  # Column already exists
        try:
            cursor.execute(
                "ALTER TABLE conversations ADD COLUMN total_output_tokens INTEGER DEFAULT 0"
            )
        except sqlite3.OperationalError:
            pass  # Column already exists

        # Migration: add model column to messages
        try:
            cursor.execute("ALTER TABLE messages ADD COLUMN model TEXT")
        except sqlite3.OperationalError:
            pass

        # Migration: add content_blocks column to messages (stores interleaved tool-call layout)
        try:
            cursor.execute("ALTER TABLE messages ADD COLUMN content_blocks TEXT")
        except sqlite3.OperationalError:
            pass  # Column already exists

        # --- TABLE 2: MESSAGES ---
        # This holds the actual content.
        # The 'conversation_id' column links this message to a specific row
        # in the 'conversations' table. This establishes a "One-to-Many" relationship:
        # One Conversation has Many Messages.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                num_messages INTEGER PRIMARY KEY AUTOINCREMENT, -- Auto-numbers messages (1, 2, 3...)
                conversation_id TEXT,                 -- The link to the parent chat
                role TEXT,                            -- 'user' or 'assistant'
                content TEXT,                         -- The actual text body
                images TEXT,                          -- SEE NOTE BELOW
                model TEXT,                           -- Which model generated this response
                created_at REAL,
                FOREIGN KEY(conversation_id) REFERENCES conversations(id)  
            )
        """)

        # NOTE ON IMAGES: SQLite does not have an ARRAY type.
        # To store a list of image paths like ["img1.png", "img2.png"],
        # we must serialize it into a JSON string like '["img1.png", "img2.png"]'
        # before saving, and parse it back into a list when loading.

        # --- TABLE 3: SETTINGS ---
        # Key-value store for user preferences.
        # We use this to persist which models the user has toggled on.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)

        # --- TABLE 4: TERMINAL EVENTS ---
        # Stores terminal command execution history per conversation.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS terminal_events (
                id TEXT PRIMARY KEY,
                conversation_id TEXT,
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

        # --- TABLE 5: SKILLS ---
        # Behavioral guidance injected into the system prompt based on
        # active MCP tool categories. Each skill maps to one MCP server.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS skills (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                skill_name TEXT UNIQUE NOT NULL,
                display_name TEXT NOT NULL,
                slash_command TEXT UNIQUE NOT NULL,
                content TEXT NOT NULL,
                is_default INTEGER DEFAULT 1,
                is_modified INTEGER DEFAULT 0,
                enabled INTEGER DEFAULT 1,
                created_at REAL,
                updated_at REAL
            )
        """)

        # --- FTS5 VIRTUAL TABLES FOR SEARCH ---
        # unicode61 tokenizer handles accented characters and case-folding.
        # NOTE: `content_blocks` (tool call args/results) is intentionally NOT
        # indexed here — it's large, JSON-encoded, and noisy for search purposes.
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

        # --- TRIGGERS TO KEEP FTS TABLES IN SYNC ---
        # Using rowid linking so FTS deletes/updates are O(1) by rowid.

        cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS conversations_fts_ai
            AFTER INSERT ON conversations BEGIN
                INSERT INTO conversations_fts(rowid, conversation_id, title)
                VALUES (new.rowid, new.id, new.title);
            END
        """)

        # Only fires when title changes — NOT on every updated_at write.
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

        # messages.num_messages is INTEGER PRIMARY KEY AUTOINCREMENT == rowid.
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

        # --- ONE-TIME BACKFILL FOR EXISTING DATABASES ---
        # Triggers only fire on future writes, so populate each FTS table
        # independently the first time this schema version is applied.
        # NULL titles/content are harmless in FTS5 (no tokens indexed) and
        # are included so the backfill stays consistent with the triggers.
        cursor.execute("SELECT COUNT(*) FROM conversations_fts")
        fts_conv_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM conversations")
        conv_count = cursor.fetchone()[0]
        if fts_conv_count == 0 and conv_count > 0:
            cursor.execute("""
                INSERT INTO conversations_fts(rowid, conversation_id, title)
                SELECT rowid, id, title FROM conversations
            """)

        cursor.execute("SELECT COUNT(*) FROM messages_fts")
        fts_msg_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM messages")
        msg_count = cursor.fetchone()[0]
        if fts_msg_count == 0 and msg_count > 0:
            cursor.execute("""
                INSERT INTO messages_fts(rowid, conversation_id, content)
                SELECT rowid, conversation_id, content FROM messages
            """)

        connection.commit()
        connection.close()

        # Seed default skills (safe — uses INSERT OR IGNORE)
        self._seed_default_skills()

    def _seed_default_skills(self):
        """Insert default skills if they don't already exist."""
        from .mcp_integration.default_skills import DEFAULT_SKILLS

        connection = self._get_connection()
        cursor = connection.cursor()
        now = time.time()

        for skill in DEFAULT_SKILLS:
            cursor.execute(
                """INSERT OR IGNORE INTO skills
                   (skill_name, display_name, slash_command, content,
                    is_default, is_modified, enabled, created_at, updated_at)
                   VALUES (?, ?, ?, ?, 1, 0, 1, ?, ?)""",
                (
                    skill["skill_name"],
                    skill["display_name"],
                    skill["slash_command"],
                    skill["content"],
                    now,
                    now,
                ),
            )

        connection.commit()
        connection.close()

    # ---------------------------------------------------------
    # WRITE OPERATIONS (Saving Data)
    # ---------------------------------------------------------

    def start_new_conversation(self, title: str) -> str:
        """
        Creates a 'Folder' for a new chat session.
        Returns the unique ID so the frontend knows which chat is active.
        """
        connection = self._get_connection()
        cursor = connection.cursor()

        # generate a unique random ID
        new_id = str(uuid.uuid4())
        time_stamp = time.time()

        cursor.execute(
            "INSERT INTO conversations (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (new_id, title, time_stamp, time_stamp),
        )

        connection.commit()
        connection.close()
        return new_id

    def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        images: List[str] | None = None,
        model: str | None = None,
        content_blocks: List[Dict] | None = None,
    ):
        """
        Saves a message AND updates the parent conversation's timestamp.
        content_blocks stores the interleaved layout of text + tool calls
        (tool call args only — results are intentionally omitted to save storage).
        """

        connection = self._get_connection()
        cursor = connection.cursor()
        time_stamp = time.time()

        # 1. Serialize: Convert Python List -> JSON String
        images_json = json.dumps(images) if images else None
        content_blocks_json = json.dumps(content_blocks) if content_blocks else None

        cursor.execute(
            "INSERT INTO messages (conversation_id, role, content, images, model, content_blocks, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (conversation_id, role, content, images_json, model, content_blocks_json, time_stamp),
        )

        # 3. Update the Parent
        # This is crucial for the UI. When you send a message in an old chat,
        # that chat should jump to the top of the sidebar list.
        # We do this by updating 'updated_at' to right now.

        cursor.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ?",
            (time_stamp, conversation_id),
        )

        connection.commit()
        connection.close()

    # ---------------------------------------------------------
    # READ OPERATIONS (Loading Data)
    # ---------------------------------------------------------

    def get_recent_conversations(self, limit: int = 5, offset: int = 0) -> List[Dict]:
        """
        LAZY LOADING IMPLEMENTATION:
        We don't select * (all columns). We only select metadata.
        We don't select the messages here. That would be too heavy.

        SQL:
        ORDER BY updated_at DESC -> puts newest chats first.
        LIMIT 10 OFFSET 0 -> Get items 1-10
        LIMIT 10 OFFSET 10 -> Get items 11-20 (User scrolled down)
        """
        connection = self._get_connection()
        cursor = connection.cursor()

        cursor.execute(
            """SELECT id, title, updated_at from conversations
                ORDER BY updated_at DESC
                LIMIT ? OFFSET ?""",
            (limit, offset),
        )

        rows = cursor.fetchall()
        connection.close()

        # Convert raw tuples [(id, title), (id, title)]
        # into nice Dictionaries for JSON response
        return [{"id": r[0], "title": r[1], "date": r[2]} for r in rows]

    def get_full_conversation(self, conversation_id: str) -> List[Dict]:
        """
        Detailed Load:
        When user clicks a sidebar item, we fetch the actual messages.
        """
        connection = self._get_connection()
        cursor = connection.cursor()

        cursor.execute(
            """SELECT role, content, images, created_at, model, content_blocks FROM messages
                WHERE conversation_id = ?
                ORDER BY created_at ASC""",  # Oldest messages at top (like standard chat)
            (conversation_id,),
        )

        rows = cursor.fetchall()
        connection.close()

        results = []

        for row in rows:
            img_list = json.loads(row[2]) if row[2] else []
            blocks = json.loads(row[5]) if row[5] else None

            results.append(
                {
                    "role": row[0],
                    "content": row[1],
                    "images": img_list,
                    "timestamp": row[3],
                    "model": row[4],
                    "content_blocks": blocks,
                }
            )
        return results

    def delete_conversation(self, conversation_id: str):
        """
        Deletes a conversation and all its messages from the database.
        """
        connection = self._get_connection()
        cursor = connection.cursor()

        # Delete terminal events, messages, then the conversation
        cursor.execute(
            "DELETE FROM terminal_events WHERE conversation_id = ?", (conversation_id,)
        )
        cursor.execute(
            "DELETE FROM messages WHERE conversation_id = ?", (conversation_id,)
        )
        cursor.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))

        connection.commit()
        connection.close()

    @staticmethod
    def _fts5_phrase(term: str) -> str:
        """
        Wrap a raw user string in FTS5 double-quote phrase syntax.
        Internal double-quotes are escaped by doubling them ("" → literal ").
        This prevents FTS5 operator injection (*, -, AND/OR, parentheses, etc.)
        for arbitrary user input.
        """
        return '"' + term.replace('"', '""') + '"'

    def search_conversations(self, search_term: str, limit: int = 20) -> List[Dict]:
        """
        Search conversations by title or message content using FTS5.

        FTS5 path: subquery on conversations_fts (by rowid) UNION subquery on
        messages_fts (by conversation_id column), joined back to conversations
        for metadata. Falls back to LIKE if the FTS tables are unavailable or
        the query is malformed.
        """
        if not search_term or not search_term.strip():
            return []

        connection = self._get_connection()
        cursor = connection.cursor()

        fts_query = self._fts5_phrase(search_term)

        try:
            cursor.execute(
                """SELECT DISTINCT c.id, c.title, c.updated_at
                   FROM conversations c
                   WHERE c.rowid IN (
                       SELECT rowid FROM conversations_fts WHERE conversations_fts MATCH ?
                   )
                   OR c.id IN (
                       SELECT conversation_id FROM messages_fts WHERE messages_fts MATCH ?
                   )
                   ORDER BY c.updated_at DESC
                   LIMIT ?""",
                (fts_query, fts_query, limit),
            )
        except sqlite3.OperationalError:
            # Fallback: FTS tables missing or query is malformed.
            # Escape LIKE wildcards so % and _ in the term are treated literally.
            escaped = (
                search_term.replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
            )
            cursor.execute(
                """SELECT DISTINCT c.id, c.title, c.updated_at
                   FROM conversations c
                   LEFT JOIN messages m ON c.id = m.conversation_id
                   WHERE c.title LIKE ? ESCAPE '\\' OR m.content LIKE ? ESCAPE '\\'
                   ORDER BY c.updated_at DESC
                   LIMIT ?""",
                (f"%{escaped}%", f"%{escaped}%", limit),
            )

        rows = cursor.fetchall()
        connection.close()

        return [{"id": r[0], "title": r[1], "date": r[2]} for r in rows]

    def update_conversation_title(self, conversation_id: str, title: str):
        """
        Update the title of an existing conversation.
        """
        connection = self._get_connection()
        cursor = connection.cursor()

        cursor.execute(
            "UPDATE conversations SET title = ? WHERE id = ?", (title, conversation_id)
        )

        connection.commit()
        connection.close()

    def add_token_usage(
        self, conversation_id: str, input_tokens: int, output_tokens: int
    ):
        """
        Accumulate token usage for a conversation.
        Adds the given counts to the running totals.
        """
        connection = self._get_connection()
        cursor = connection.cursor()

        cursor.execute(
            """UPDATE conversations 
               SET total_input_tokens = total_input_tokens + ?,
                   total_output_tokens = total_output_tokens + ?
               WHERE id = ?""",
            (input_tokens, output_tokens, conversation_id),
        )

        connection.commit()
        connection.close()

    def get_token_usage(self, conversation_id: str) -> Dict:
        """
        Get cumulative token usage for a conversation.
        """
        connection = self._get_connection()
        cursor = connection.cursor()

        cursor.execute(
            "SELECT total_input_tokens, total_output_tokens FROM conversations WHERE id = ?",
            (conversation_id,),
        )

        row = cursor.fetchone()
        connection.close()

        if row:
            return {
                "input": row[0] or 0,
                "output": row[1] or 0,
                "total": (row[0] or 0) + (row[1] or 0),
            }
        return {"input": 0, "output": 0, "total": 0}

    # ---------------------------------------------------------
    # SETTINGS OPERATIONS (Key-Value Store)
    # ---------------------------------------------------------

    def get_enabled_models(self) -> List[str]:
        """
        Get the list of model names the user has toggled on.

        Stored as a JSON array string under the key 'enabled_models'.
        Returns an empty list if nothing has been saved yet.
        """
        connection = self._get_connection()
        cursor = connection.cursor()
        cursor.execute("SELECT value FROM settings WHERE key = ?", ("enabled_models",))
        row = cursor.fetchone()
        connection.close()

        if row and row[0]:
            return json.loads(row[0])
        return []

    def set_enabled_models(self, models: List[str]):
        """
        Save the list of enabled model names.

        Uses INSERT OR REPLACE (upsert) so it works whether or not
        the row already exists.
        """
        connection = self._get_connection()
        cursor = connection.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            ("enabled_models", json.dumps(models)),
        )
        connection.commit()
        connection.close()

    # ---------------------------------------------------------
    # GENERIC SETTINGS OPERATIONS
    # ---------------------------------------------------------

    def get_setting(self, key: str) -> str | None:
        """Get a raw setting value by key. Returns None if not found."""
        connection = self._get_connection()
        cursor = connection.cursor()
        cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = cursor.fetchone()
        connection.close()
        return row[0] if row else None

    def set_setting(self, key: str, value: str):
        """Set a raw setting value (upsert)."""
        connection = self._get_connection()
        cursor = connection.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value)
        )
        connection.commit()
        connection.close()

    def delete_setting(self, key: str):
        """Delete a setting by key."""
        connection = self._get_connection()
        cursor = connection.cursor()
        cursor.execute("DELETE FROM settings WHERE key = ?", (key,))
        connection.commit()
        connection.close()

    def get_system_prompt_template(self) -> str | None:
        """
        Returns the user-saved system prompt template, or None if not set.
        Caller should fall back to the hardcoded default when None is returned.
        """
        return self.get_setting("system_prompt_template")

    def set_system_prompt_template(self, template: str | None) -> None:
        """
        Saves a custom system prompt template. Pass None or empty string to
        clear the custom value and restore the hardcoded default.
        """
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
        """
        Save a terminal command execution event.

        Stores full output up to 50KB, always stores an output_preview
        (first 500 + last 500 chars). Returns event ID.
        """
        connection = self._get_connection()
        cursor = connection.cursor()

        event_id = str(uuid.uuid4())

        # Build preview: first 500 + last 500 chars
        if len(output) <= 1000:
            output_preview = output
        else:
            output_preview = output[:500] + "\n...\n" + output[-500:]

        # Truncate full output to 50KB
        max_output = 50 * 1024
        full_output = output[:max_output] if len(output) > max_output else output

        cursor.execute(
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
                1 if timed_out else 0,
                1 if denied else 0,
                1 if pty else 0,
                1 if background else 0,
                time.time(),
            ),
        )

        connection.commit()
        connection.close()
        return event_id

    def get_terminal_events(self, conversation_id: str) -> List[Dict]:
        """
        Returns all terminal events for a conversation, ordered by created_at.
        """
        connection = self._get_connection()
        cursor = connection.cursor()

        cursor.execute(
            """SELECT id, message_index, command, exit_code, output_preview,
                      cwd, duration_ms, timed_out, denied, pty, background, created_at
               FROM terminal_events
               WHERE conversation_id = ?
               ORDER BY created_at ASC""",
            (conversation_id,),
        )

        rows = cursor.fetchall()
        connection.close()

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
    # SKILL OPERATIONS
    # ---------------------------------------------------------

    @staticmethod
    def _row_to_skill(r) -> Dict:
        """Map a skills table row (tuple) to a dict."""
        return {
            "id": r[0],
            "skill_name": r[1],
            "display_name": r[2],
            "slash_command": r[3],
            "content": r[4],
            "is_default": bool(r[5]),
            "is_modified": bool(r[6]),
            "enabled": bool(r[7]),
            "created_at": r[8],
            "updated_at": r[9],
        }

    def get_all_skills(self) -> List[Dict]:
        """Returns all skill rows."""
        connection = self._get_connection()
        cursor = connection.cursor()
        cursor.execute(
            """SELECT id, skill_name, display_name, slash_command, content,
                      is_default, is_modified, enabled, created_at, updated_at
               FROM skills ORDER BY id ASC"""
        )
        rows = cursor.fetchall()
        connection.close()
        return [self._row_to_skill(r) for r in rows]

    def get_skill_by_name(self, skill_name: str) -> Dict | None:
        """Returns a single skill by name, or None."""
        connection = self._get_connection()
        cursor = connection.cursor()
        cursor.execute(
            """SELECT id, skill_name, display_name, slash_command, content,
                      is_default, is_modified, enabled, created_at, updated_at
               FROM skills WHERE skill_name = ?""",
            (skill_name,),
        )
        r = cursor.fetchone()
        connection.close()
        if not r:
            return None
        return self._row_to_skill(r)

    def get_skill_by_slash_command(self, command: str) -> Dict | None:
        """Returns a single skill by its slash command, or None."""
        connection = self._get_connection()
        cursor = connection.cursor()
        cursor.execute(
            """SELECT id, skill_name, display_name, slash_command, content,
                      is_default, is_modified, enabled, created_at, updated_at
               FROM skills WHERE slash_command = ?""",
            (command,),
        )
        r = cursor.fetchone()
        connection.close()
        if not r:
            return None
        return self._row_to_skill(r)

    def upsert_skill(
        self,
        skill_name: str,
        display_name: str,
        slash_command: str,
        content: str,
        is_default: bool = False,
        enabled: bool = True,
        is_modified: bool = False,
    ) -> None:
        """Insert or update a skill.

        Args:
            is_modified: When True the ON CONFLICT path sets is_modified=1,
                         allowing callers (e.g. the update-skill endpoint) to
                         mark a default skill as user-modified in a single write.
        """
        connection = self._get_connection()
        cursor = connection.cursor()
        now = time.time()
        cursor.execute(
            """INSERT INTO skills
               (skill_name, display_name, slash_command, content,
                is_default, is_modified, enabled, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(skill_name) DO UPDATE SET
                 display_name = excluded.display_name,
                 slash_command = excluded.slash_command,
                 content = excluded.content,
                 is_modified = excluded.is_modified,
                 enabled = excluded.enabled,
                 updated_at = excluded.updated_at""",
            (
                skill_name,
                display_name,
                slash_command,
                content,
                1 if is_default else 0,
                1 if is_modified else 0,
                1 if enabled else 0,
                now,
                now,
            ),
        )
        connection.commit()
        connection.close()

    def update_skill_content(self, skill_name: str, content: str) -> None:
        """Update skill content and mark as modified."""
        connection = self._get_connection()
        cursor = connection.cursor()
        cursor.execute(
            """UPDATE skills SET content = ?, is_modified = 1, updated_at = ?
               WHERE skill_name = ?""",
            (content, time.time(), skill_name),
        )
        connection.commit()
        connection.close()

    def reset_skill_to_default(self, skill_name: str) -> None:
        """Restore a default skill to its original content."""
        from .mcp_integration.default_skills import DEFAULT_SKILLS

        for default in DEFAULT_SKILLS:
            if default["skill_name"] == skill_name:
                connection = self._get_connection()
                cursor = connection.cursor()
                cursor.execute(
                    """UPDATE skills SET content = ?, is_modified = 0, updated_at = ?
                       WHERE skill_name = ?""",
                    (default["content"], time.time(), skill_name),
                )
                connection.commit()
                connection.close()
                return

    def delete_skill(self, skill_name: str) -> bool:
        """Delete a user-created skill. Returns False if it's a default."""
        skill = self.get_skill_by_name(skill_name)
        if not skill or skill["is_default"]:
            return False
        connection = self._get_connection()
        cursor = connection.cursor()
        cursor.execute("DELETE FROM skills WHERE skill_name = ?", (skill_name,))
        connection.commit()
        connection.close()
        return True

    def toggle_skill(self, skill_name: str, enabled: bool) -> None:
        """Enable or disable a skill."""
        connection = self._get_connection()
        cursor = connection.cursor()
        cursor.execute(
            "UPDATE skills SET enabled = ?, updated_at = ? WHERE skill_name = ?",
            (1 if enabled else 0, time.time(), skill_name),
        )
        connection.commit()
        connection.close()


# Global singleton instance so all modules share the same DB connection logic
db = DatabaseManager()

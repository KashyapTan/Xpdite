import hashlib
import importlib.util
import io
import json
import logging
import os
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import ollama

from ...infrastructure.config import CHILD_PYTHON_EXECUTABLE, USER_DATA_DIR

try:
    from rank_bm25 import BM25Okapi

    BM25_AVAILABLE = True
except ImportError:  # pragma: no cover - dependency is managed in pyproject.toml
    BM25Okapi = None  # type: ignore[assignment]
    BM25_AVAILABLE = False

# logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

SentenceTransformer = None
_SENTENCE_TRANSFORMERS_IMPORT_ATTEMPTED = False


_CACHE_DIR = str(USER_DATA_DIR / "cache")
_CACHE_FILE = os.path.join(_CACHE_DIR, "tool_embeddings.npz")
_CACHE_INDEX_FILE = os.path.join(_CACHE_DIR, "tool_embedding_index.json")

RRF_K = 10
DEBUG_SCORE_LOG_LIMIT = 10
_SENTENCE_TRANSFORMER_MODEL = "all-MiniLM-L6-v2"
_BUNDLED_SENTENCE_TRANSFORMER_SUBDIR = (
    Path("embedding-models") / _SENTENCE_TRANSFORMER_MODEL
)


def _ensure_sentence_transformers_available() -> bool:
    """Import sentence-transformers only when the fallback backend is needed."""
    global SentenceTransformer, _SENTENCE_TRANSFORMERS_IMPORT_ATTEMPTED

    if SentenceTransformer is not None:
        return True
    if _SENTENCE_TRANSFORMERS_IMPORT_ATTEMPTED:
        return False

    _SENTENCE_TRANSFORMERS_IMPORT_ATTEMPTED = True
    import_error: Optional[Exception] = None

    for attempt in range(2):
        try:
            SentenceTransformer = _import_sentence_transformer_class()
            return True
        except Exception as exc:
            import_error = exc
            if attempt == 0 and _inject_child_python_site_packages():
                _clear_modules_for_retry(
                    (
                        "sentence_transformers",
                        "transformers",
                        "huggingface_hub",
                        "requests",
                        "yaml",
                        "jinja2",
                        "markupsafe",
                    )
                )
                continue
            break

    logger.warning("Failed to import sentence_transformers: %s", import_error)
    return False


def _import_sentence_transformer_class():
    from sentence_transformers import SentenceTransformer as _SentenceTransformer

    return _SentenceTransformer


def _clear_modules_for_retry(prefixes: tuple[str, ...]) -> None:
    """Drop partially imported modules before retrying against a new sys.path."""
    for module_name in list(sys.modules):
        if any(
            module_name == prefix or module_name.startswith(f"{prefix}.")
            for prefix in prefixes
        ):
            sys.modules.pop(module_name, None)


def _resolve_child_python_site_packages() -> Optional[Path]:
    """Find the packaged plain-Python site-packages directory, if available."""
    child_python = CHILD_PYTHON_EXECUTABLE or os.environ.get(
        "XPDITE_CHILD_PYTHON_EXECUTABLE", ""
    ).strip()
    if not child_python:
        return None

    executable = Path(child_python).expanduser()
    candidates: List[Path] = []

    if executable.parent.name in {"bin", "Scripts"}:
        venv_root = executable.parent.parent
        candidates.append(venv_root / "Lib" / "site-packages")
        lib_dir = venv_root / "lib"
        if lib_dir.exists():
            candidates.extend(sorted(lib_dir.glob("python*/site-packages")))
    else:
        runtime_root = executable.parent
        candidates.append(runtime_root / "Lib" / "site-packages")
        lib_dir = runtime_root / "lib"
        if lib_dir.exists():
            candidates.extend(sorted(lib_dir.glob("python*/site-packages")))

    for candidate in candidates:
        if candidate.exists():
            return candidate

    return None


def _inject_child_python_site_packages() -> bool:
    """Retry imports against the packaged child runtime when PyInstaller falls short."""
    site_packages = _resolve_child_python_site_packages()
    if site_packages is None:
        return False

    site_packages_str = str(site_packages)
    if site_packages_str in sys.path:
        return False

    sys.path.insert(0, site_packages_str)
    importlib.invalidate_caches()
    logger.info(
        "Retrying sentence-transformers import using child runtime site-packages: %s",
        site_packages,
    )
    return True


def _resolve_bundled_sentence_transformer_dir() -> Optional[Path]:
    """Locate the packaged MiniLM model copy bundled with the frozen backend."""
    env_dir = os.environ.get("XPDITE_SENTENCE_TRANSFORMER_MODEL_DIR", "").strip()
    if env_dir:
        candidate = Path(env_dir).expanduser().resolve()
        if candidate.exists():
            return candidate

    candidates: List[Path] = []

    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / _BUNDLED_SENTENCE_TRANSFORMER_SUBDIR)

    executable_dir = Path(sys.executable).resolve().parent
    candidates.extend(
        [
            executable_dir / "_internal" / _BUNDLED_SENTENCE_TRANSFORMER_SUBDIR,
            executable_dir / _BUNDLED_SENTENCE_TRANSFORMER_SUBDIR,
        ]
    )

    for candidate in candidates:
        if candidate.exists():
            return candidate

    return None


def _sentence_transformers_is_importable() -> bool:
    """Cheap package-presence check that avoids importing heavy modules at startup."""
    if SentenceTransformer is not None:
        return True
    return importlib.util.find_spec("sentence_transformers") is not None


class ToolRetriever:
    """
    Hybrid semantic + BM25 retriever for MCP tools.

    Active tool embeddings are stored as a pre-normalized 2D matrix plus a
    parallel name index. Retrieval uses one matrix-vector multiply for cosine
    similarity, BM25 keyword scoring over the same tool corpus, and reciprocal
    rank fusion to combine the two signals.
    """

    def __init__(self):
        self._cache_lock = threading.RLock()
        self._embedding_matrix = np.empty((0, 0), dtype=np.float32)
        self._tool_name_index: List[str] = []
        self._bm25_index: Any = None
        self._embedding_model_type = "unknown"  # "ollama" or "sentence-transformers"
        self._st_model = None
        self._ollama_model_name = "nomic-embed-text"
        self._embedding_cache: Dict[str, np.ndarray] = {}
        self._tool_cache_index: Dict[str, str] = {}
        self._bm25_warning_emitted = False
        self._check_embedding_backend()
        self._load_cache()
        self._load_cache_index()

    def _check_embedding_backend(self):
        """Determine which embedding backend to use."""
        try:
            models_response = ollama.list()

            model_list: List[Any] = []
            if hasattr(models_response, "models"):
                model_list = list(models_response.models)
            elif isinstance(models_response, dict) and "models" in models_response:
                model_list = list(models_response["models"])
            elif isinstance(models_response, list):
                model_list = models_response
            else:
                model_list = [models_response]

            model_names = []
            for model in model_list:
                model_obj: Any = model
                if hasattr(model_obj, "model"):
                    model_names.append(model_obj.model)
                elif isinstance(model_obj, dict):
                    model_names.append(model_obj.get("model") or model_obj.get("name"))
                else:
                    model_names.append(str(model_obj))

            target_substrings = ["nomic-embed-text", "all-minilm", "mxbai-embed-large"]
            found_model = None

            for model_name in model_names:
                for target in target_substrings:
                    if target in model_name:
                        found_model = model_name
                        break
                if found_model:
                    break

            if found_model:
                self._embedding_model_type = "ollama"
                self._ollama_model_name = found_model
                logger.info(
                    "Embedding backend active: ollama (%s)",
                    self._ollama_model_name,
                )
                return
        except Exception as exc:
            logger.warning("Ollama check failed: %s", exc)

        if _sentence_transformers_is_importable():
            self._embedding_model_type = "sentence-transformers"
            bundled_model_dir = _resolve_bundled_sentence_transformer_dir()
            model_ref = (
                str(bundled_model_dir)
                if bundled_model_dir is not None
                else _SENTENCE_TRANSFORMER_MODEL
            )
            logger.info(
                "Embedding backend active: sentence-transformers (%s)",
                model_ref,
            )
            return

        logger.warning(
            "No embedding backend available. Retrieval will be limited to always-on tools."
        )
        self._embedding_model_type = "none"

    def _get_embedding(self, text: str) -> Optional[np.ndarray]:
        """Get embedding for a single string, or None on failure."""
        if self._embedding_model_type == "ollama":
            try:
                response = ollama.embeddings(model=self._ollama_model_name, prompt=text)
                return np.asarray(response["embedding"], dtype=np.float32)
            except Exception as exc:
                logger.warning("Ollama embedding failed: %s", exc)
                return None

        if self._embedding_model_type == "sentence-transformers":
            try:
                if (
                    self._st_model is None
                    and _ensure_sentence_transformers_available()
                    and SentenceTransformer is not None
                ):
                    bundled_model_dir = _resolve_bundled_sentence_transformer_dir()
                    model_ref = (
                        str(bundled_model_dir)
                        if bundled_model_dir is not None
                        else _SENTENCE_TRANSFORMER_MODEL
                    )
                    kwargs = {"local_files_only": True} if bundled_model_dir else {}
                    logger.info("Loading sentence-transformers model: %s", model_ref)
                    self._st_model = SentenceTransformer(model_ref, **kwargs)  # type: ignore[arg-type]

                if self._st_model:
                    embedding = self._st_model.encode(
                        text,
                        show_progress_bar=False,
                    )
                    if isinstance(embedding, np.ndarray):
                        return embedding.astype(np.float32, copy=False)
                    return np.asarray(embedding, dtype=np.float32)
            except Exception as exc:
                logger.warning("Sentence-transformers embedding failed: %s", exc)
                return None

        return None

    # ------------------------------------------------------------------
    # Disk cache helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _cache_key(model_name: str, text: str) -> str:
        """Deterministic key: hash of model name + description text."""
        return hashlib.sha256(f"{model_name}|{text}".encode()).hexdigest()

    @staticmethod
    def _tool_document_text(name: str, description: str) -> str:
        """Canonical tool document used by both embeddings and BM25."""
        parts = [name.strip()]
        if description.strip():
            parts.append(description.strip())
        return " ".join(parts)

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        """BM25 tokenization: lowercase + whitespace split."""
        return text.lower().split()

    @staticmethod
    def _flatten_embedding(vector: np.ndarray) -> np.ndarray:
        """Convert embeddings to a contiguous 1D float32 numpy array."""
        return np.asarray(vector, dtype=np.float32).reshape(-1)

    @classmethod
    def _normalize_vector(cls, vector: np.ndarray) -> Optional[np.ndarray]:
        """Return a unit-length 1D vector, or None for zero-norm inputs."""
        flat_vector = cls._flatten_embedding(vector)
        norm = float(np.linalg.norm(flat_vector))
        if norm == 0.0:
            return None
        return flat_vector / norm

    def _load_cache(self) -> None:
        """Load cached embeddings from disk (if file exists)."""
        with self._cache_lock:
            try:
                if os.path.exists(_CACHE_FILE):
                    with np.load(_CACHE_FILE, allow_pickle=False) as data:
                        self._embedding_cache = {
                            key: self._flatten_embedding(data[key])
                            for key in data.files
                        }
                    logger.info(
                        "Loaded %d cached embeddings.", len(self._embedding_cache)
                    )
            except Exception as exc:
                logger.warning("Could not load embedding cache: %s", exc)
                self._embedding_cache = {}

    @staticmethod
    def _write_file_atomically(path: str, payload: bytes) -> None:
        """Write a file via a temporary path, then atomically replace it."""
        directory = os.path.dirname(path) or "."
        fd, temp_path = tempfile.mkstemp(
            dir=directory,
            prefix=f"{os.path.basename(path)}.",
            suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(payload)
            os.replace(temp_path, path)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def _save_cache(self) -> None:
        """Persist current cache dict to disk."""
        with self._cache_lock:
            try:
                os.makedirs(_CACHE_DIR, exist_ok=True)
                buffer = io.BytesIO()
                np.savez(buffer, **self._embedding_cache)
                self._write_file_atomically(_CACHE_FILE, buffer.getvalue())
            except Exception as exc:
                logger.warning("Could not save embedding cache: %s", exc)

    def _load_cache_index(self) -> None:
        """Load the current tool-name-to-cache-key mapping from disk."""
        with self._cache_lock:
            try:
                if os.path.exists(_CACHE_INDEX_FILE):
                    with open(_CACHE_INDEX_FILE, encoding="utf-8") as fh:
                        data = json.load(fh)
                    if isinstance(data, dict) and all(
                        isinstance(name, str) and isinstance(key, str)
                        for name, key in data.items()
                    ):
                        self._tool_cache_index = data
                        logger.info(
                            "Loaded cache index for %d tool description(s).",
                            len(self._tool_cache_index),
                        )
                    else:
                        logger.warning("Embedding cache index is invalid; ignoring it.")
                        self._tool_cache_index = {}
            except Exception as exc:
                logger.warning("Could not load embedding cache index: %s", exc)
                self._tool_cache_index = {}

    def _save_cache_index(self) -> None:
        """Persist the current tool-name-to-cache-key mapping."""
        with self._cache_lock:
            try:
                os.makedirs(_CACHE_DIR, exist_ok=True)
                payload = json.dumps(
                    self._tool_cache_index,
                    indent=2,
                    sort_keys=True,
                ).encode("utf-8")
                self._write_file_atomically(_CACHE_INDEX_FILE, payload)
            except Exception as exc:
                logger.warning("Could not save cache index: %s", exc)

    def _clear_retrieval_index(self) -> None:
        """Clear the active matrix and BM25 index."""
        self._embedding_matrix = np.empty((0, 0), dtype=np.float32)
        self._tool_name_index = []
        self._bm25_index = None

    def _rebuild_retrieval_index(
        self,
        active_entries: List[tuple[str, str, np.ndarray]],
    ) -> None:
        """
        Rebuild the active embedding matrix and BM25 index from embedded tools.

        Any shape mismatch is resolved here once, at build time, rather than on
        every query.
        """
        self._clear_retrieval_index()

        if not active_entries:
            logger.info("No active tool embeddings available for retrieval.")
            return

        flattened_entries: List[tuple[str, str, np.ndarray]] = []
        shape_counts: Dict[int, int] = {}

        for name, document_text, raw_embedding in active_entries:
            flat_embedding = self._flatten_embedding(raw_embedding)
            embedding_dim = int(flat_embedding.shape[0])
            shape_counts[embedding_dim] = shape_counts.get(embedding_dim, 0) + 1
            flattened_entries.append((name, document_text, flat_embedding))

        target_dim = max(shape_counts.items(), key=lambda item: (item[1], item[0]))[0]

        normalized_rows = []
        tool_names = []
        bm25_documents = []
        mismatched_tools = []
        zero_norm_tools = []

        for name, document_text, flat_embedding in flattened_entries:
            if flat_embedding.shape[0] != target_dim:
                mismatched_tools.append((name, flat_embedding.shape[0]))
                continue

            norm = float(np.linalg.norm(flat_embedding))
            if norm == 0.0:
                zero_norm_tools.append(name)
                continue

            normalized_rows.append(
                (flat_embedding / norm).astype(np.float32, copy=False)
            )
            tool_names.append(name)
            bm25_documents.append(document_text)

        if mismatched_tools:
            logger.warning(
                "Skipping %d tool embedding(s) with mismatched dimensions: %s",
                len(mismatched_tools),
                ", ".join(
                    f"{name}({dimension})" for name, dimension in mismatched_tools
                ),
            )

        if zero_norm_tools:
            logger.warning(
                "Skipping %d tool embedding(s) with zero norm: %s",
                len(zero_norm_tools),
                ", ".join(zero_norm_tools),
            )

        if not normalized_rows:
            logger.warning("No valid tool embeddings available after index rebuild.")
            return

        self._embedding_matrix = np.vstack(normalized_rows).astype(
            np.float32, copy=False
        )
        self._tool_name_index = tool_names

        if BM25_AVAILABLE and BM25Okapi is not None:
            self._bm25_index = BM25Okapi(
                [self._tokenize(document) for document in bm25_documents]
            )
        else:
            if not self._bm25_warning_emitted:
                logger.warning("rank_bm25 is unavailable. BM25 scoring is disabled.")
                self._bm25_warning_emitted = True
            self._bm25_index = None

        logger.info(
            "Built retrieval index for %d tool(s) with embedding dim %d.",
            len(self._tool_name_index),
            target_dim,
        )

    def embed_tools(self, tools: List[Dict]):
        """
        Embed tool descriptions, refresh the active matrix, and update cache.

        The disk cache is keyed on (model_name, tool_document). Cached entries are
        only pruned after a replacement embedding has been written successfully.
        """
        if self._embedding_model_type == "none":
            with self._cache_lock:
                self._clear_retrieval_index()
            return

        model_name = (
            self._ollama_model_name
            if self._embedding_model_type == "ollama"
            else _SENTENCE_TRANSFORMER_MODEL
        )

        with self._cache_lock:
            cache_hits = 0
            cache_misses = 0
            stale_prunes = 0
            cache_changed = False
            index_changed = False
            previous_index = self._tool_cache_index.copy()
            current_tool_keys: Dict[str, str] = {}
            active_entries: List[tuple[str, str, np.ndarray]] = []

            for tool in tools:
                func = tool.get("function", {})
                name = func.get("name")
                description = func.get("description", "")

                if not name:
                    continue

                document_text = self._tool_document_text(name, description)
                key = self._cache_key(model_name, document_text)
                previous_key = previous_index.get(name)
                embedding = None

                if key in self._embedding_cache:
                    embedding = self._embedding_cache[key]
                    current_tool_keys[name] = key
                    cache_hits += 1

                    if previous_key and previous_key != key:
                        if self._embedding_cache.pop(previous_key, None) is not None:
                            stale_prunes += 1
                            cache_changed = True
                else:
                    embedding = self._get_embedding(document_text)
                    if embedding is not None:
                        embedding = self._flatten_embedding(embedding)
                        self._embedding_cache[key] = embedding
                        current_tool_keys[name] = key
                        cache_misses += 1
                        cache_changed = True

                        if previous_key and previous_key != key:
                            if (
                                self._embedding_cache.pop(previous_key, None)
                                is not None
                            ):
                                stale_prunes += 1
                    elif previous_key and previous_key in self._embedding_cache:
                        embedding = self._embedding_cache[previous_key]
                        current_tool_keys[name] = previous_key
                        cache_hits += 1
                        logger.warning(
                            "Embedding refresh failed for '%s'; keeping previous cached embedding.",
                            name,
                        )
                    else:
                        logger.warning(
                            "Embedding refresh failed for '%s' and no previous cached embedding exists.",
                            name,
                        )

                if embedding is not None:
                    active_entries.append((name, document_text, embedding))

            updated_index = previous_index.copy()
            updated_index.update(current_tool_keys)

            if updated_index != self._tool_cache_index:
                self._tool_cache_index = updated_index
                index_changed = True

            self._rebuild_retrieval_index(active_entries)

            if cache_changed:
                self._save_cache()
            if index_changed:
                self._save_cache_index()

            total_loaded = cache_hits + cache_misses
            if cache_misses > 0 or stale_prunes > 0:
                logger.info(
                    "Embedded %d new tool(s), %d from cache, pruned %d stale embedding(s) (%d total).",
                    cache_misses,
                    cache_hits,
                    stale_prunes,
                    total_loaded,
                )
            else:
                logger.info("All %d tool embeddings loaded from cache.", cache_hits)

    @staticmethod
    def _build_rank_map(scores_by_name: Dict[str, float]) -> Dict[str, int]:
        """Assign shared rank positions from descending scores."""
        if not scores_by_name:
            return {}

        sorted_items = sorted(
            scores_by_name.items(), key=lambda item: (-item[1], item[0])
        )
        rank_map: Dict[str, int] = {}
        current_rank = 0
        previous_score: Optional[float] = None

        for position, (name, score) in enumerate(sorted_items, start=1):
            if previous_score is None or not np.isclose(
                score, previous_score, rtol=1e-9, atol=1e-12
            ):
                current_rank = position
                previous_score = score
            rank_map[name] = current_rank

        return rank_map

    @staticmethod
    def _format_float(value: Optional[float]) -> str:
        """Format an optional float for debug logging."""
        if value is None:
            return "n/a"
        return f"{value:.4f}"

    @staticmethod
    def _format_rank(value: Optional[int]) -> str:
        """Format an optional rank for debug logging."""
        if value is None:
            return "n/a"
        return str(value)

    def retrieve_tools(
        self, query: str, all_tools: List[Dict], always_on: List[str], top_k: int = 5
    ) -> List[Dict]:
        """
        Select relevant tools for the query.

        Args:
            query: User's chat message
            all_tools: Full list of available tools
            always_on: List of tool names to always include
            top_k: Number of retrieved matches to include, excluding always-on tools

        Returns:
            Filtered list of tool definitions, ordered by fused retrieval score
            with always-on additions appended afterwards.
        """
        tool_lookup = {
            tool.get("function", {}).get("name"): tool
            for tool in all_tools
            if tool.get("function", {}).get("name")
        }
        always_on_names = [name for name in always_on if name in tool_lookup]

        if top_k <= 0 or not query.strip():
            return [tool_lookup[name] for name in always_on_names]

        with self._cache_lock:
            embedding_matrix = self._embedding_matrix.copy()
            tool_name_index = list(self._tool_name_index)
            bm25_index = self._bm25_index

        always_on_set = set(always_on_names)
        candidate_indices = [
            index
            for index, name in enumerate(tool_name_index)
            if name in tool_lookup and name not in always_on_set
        ]

        if not candidate_indices:
            return [tool_lookup[name] for name in always_on_names]

        semantic_scores_by_name: Dict[str, float] = {}
        if embedding_matrix.size > 0:
            query_embedding = self._get_embedding(query)
            if query_embedding is None:
                logger.warning(
                    "Query embedding failed; falling back to BM25-only tool ranking."
                )
            else:
                normalized_query = self._normalize_vector(query_embedding)
                if normalized_query is None:
                    logger.warning(
                        "Query embedding had zero norm; falling back to BM25-only tool ranking."
                    )
                elif normalized_query.shape[0] != embedding_matrix.shape[1]:
                    logger.warning(
                        "Query embedding dimension %d does not match tool matrix dimension %d.",
                        normalized_query.shape[0],
                        embedding_matrix.shape[1],
                    )
                else:
                    semantic_scores = embedding_matrix @ normalized_query
                    semantic_scores_by_name = {
                        tool_name_index[index]: float(semantic_scores[index])
                        for index in candidate_indices
                    }

        bm25_scores_by_name: Dict[str, float] = {}
        if bm25_index is not None:
            query_tokens = self._tokenize(query)
            if query_tokens:
                bm25_scores = np.asarray(
                    bm25_index.get_scores(query_tokens), dtype=float
                )
                bm25_scores_by_name = {
                    tool_name_index[index]: float(bm25_scores[index])
                    for index in candidate_indices
                }

        if not semantic_scores_by_name and not bm25_scores_by_name:
            return [tool_lookup[name] for name in always_on_names]

        if (
            not semantic_scores_by_name
            and bm25_scores_by_name
            and all(
                np.isclose(score, 0.0, atol=1e-12)
                for score in bm25_scores_by_name.values()
            )
        ):
            logger.warning(
                "BM25 produced no keyword matches while semantic retrieval was unavailable."
            )
            return [tool_lookup[name] for name in always_on_names]

        semantic_ranks = self._build_rank_map(semantic_scores_by_name)
        bm25_ranks = self._build_rank_map(bm25_scores_by_name)

        candidate_rows = []
        for index in candidate_indices:
            name = tool_name_index[index]
            semantic_score = semantic_scores_by_name.get(name)
            bm25_score = bm25_scores_by_name.get(name)
            semantic_rank = semantic_ranks.get(name)
            bm25_rank = bm25_ranks.get(name)

            if semantic_rank is None and bm25_rank is None:
                continue

            rrf_score = 0.0
            if semantic_rank is not None:
                rrf_score += 1.0 / (RRF_K + semantic_rank)
            if bm25_rank is not None:
                rrf_score += 1.0 / (RRF_K + bm25_rank)

            candidate_rows.append(
                {
                    "name": name,
                    "semantic_score": semantic_score,
                    "bm25_score": bm25_score,
                    "semantic_rank": semantic_rank,
                    "bm25_rank": bm25_rank,
                    "rrf_score": rrf_score,
                }
            )

        ranked_candidates = sorted(
            candidate_rows,
            key=lambda row: (
                -row["rrf_score"],
                -(
                    row["semantic_score"]
                    if row["semantic_score"] is not None
                    else float("-inf")
                ),
                row["name"],
            ),
        )

        if logger.isEnabledFor(logging.DEBUG) and ranked_candidates:
            debug_limit = min(len(ranked_candidates), max(top_k, DEBUG_SCORE_LOG_LIMIT))
            logger.debug(
                "Tool retriever scores for query %r (top %d of %d candidates):",
                query,
                debug_limit,
                len(ranked_candidates),
            )
            for row in ranked_candidates[:debug_limit]:
                logger.debug(
                    "tool=%s cosine_similarity=%s bm25_score=%s semantic_rank=%s bm25_rank=%s rrf_score=%.6f",
                    row["name"],
                    self._format_float(row["semantic_score"]),
                    self._format_float(row["bm25_score"]),
                    self._format_rank(row["semantic_rank"]),
                    self._format_rank(row["bm25_rank"]),
                    row["rrf_score"],
                )

        retrieved_names = [row["name"] for row in ranked_candidates[:top_k]]
        ordered_names = retrieved_names + [
            name for name in always_on_names if name not in retrieved_names
        ]
        final_tools = [tool_lookup[name] for name in ordered_names]

        logger.debug("Query: '%s'", query)
        logger.debug(
            "Selected %d tools out of %d available.",
            len(final_tools),
            len(all_tools),
        )
        for tool in final_tools:
            logger.debug(" - %s", tool.get("function", {}).get("name"))

        return final_tools


# Lazy-initialised singleton — avoids calling ollama.list() at import time,
# which would add startup latency when Ollama isn’t running.
_retriever_instance: Optional["ToolRetriever"] = None


def _get_retriever() -> "ToolRetriever":
    global _retriever_instance
    if _retriever_instance is None:
        _retriever_instance = ToolRetriever()
    return _retriever_instance


class _LazyRetriever:
    """Proxy that defers ToolRetriever() construction until first attribute access."""

    def retrieve_tools(self, *args, **kwargs):
        return _get_retriever().retrieve_tools(*args, **kwargs)

    def embed_tools(self, *args, **kwargs):
        return _get_retriever().embed_tools(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(_get_retriever(), name)


retriever = _LazyRetriever()  # type: ignore[assignment]

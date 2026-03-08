import os
import hashlib
import logging
import numpy as np
import ollama
from typing import List, Dict, Any, Optional

# logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

try:
    from sentence_transformers import SentenceTransformer

    SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:
    SENTENCE_TRANSFORMERS_AVAILABLE = False
    SentenceTransformer = None


_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_CACHE_DIR = os.path.join(_PROJECT_ROOT, "user_data", "cache")
_CACHE_FILE = os.path.join(_CACHE_DIR, "tool_embeddings.npz")


class ToolRetriever:
    """
    Semantic retriever for MCP tools.

    Dynamically selects relevant tools based on user query similarity
    to tool descriptions.
    """

    def __init__(self):
        self._tool_embeddings: Dict[str, np.ndarray] = {}
        self._embedding_model_type = "unknown"  # "ollama" or "sentence-transformers"
        self._st_model = None
        self._ollama_model_name = "nomic-embed-text"
        self._embedding_cache: Dict[str, np.ndarray] = {}
        self._check_embedding_backend()
        self._load_cache()

    def _check_embedding_backend(self):
        """Determine which embedding backend to use."""
        # 1. Try Ollama
        try:
            # Simple check if ollama is reachable and model exists
            models_response = ollama.list()

            model_list: List[Any] = []
            if hasattr(models_response, "models"):
                model_list = list(models_response.models)
            elif isinstance(models_response, dict) and "models" in models_response:
                model_list = list(models_response["models"])
            elif isinstance(models_response, list):
                model_list = models_response
            else:
                # Fallback: single object or unknown format, wrap in list
                model_list = [models_response]

            model_names = []
            for m in model_list:
                # Handle both object attribute access and dictionary key access
                # Use Any to bypass strict type checking on the loop variable
                model_obj: Any = m
                if hasattr(model_obj, "model"):
                    model_names.append(model_obj.model)
                elif isinstance(model_obj, dict):
                    # Some versions use 'name', some use 'model'
                    model_names.append(model_obj.get("model") or model_obj.get("name"))
                else:
                    # Last resort string conversion
                    model_names.append(str(model_obj))

            # Check for exact match or match with tag
            # We look for "nomic-embed-text" or similar embedding models
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
                    "Using Ollama embedding model: %s", self._ollama_model_name
                )
                return
        except Exception as e:
            logger.warning("Ollama check failed: %s", e)

        # 2. Fallback to SentenceTransformers
        if SENTENCE_TRANSFORMERS_AVAILABLE:
            self._embedding_model_type = "sentence-transformers"
            logger.info("Using sentence-transformers (all-MiniLM-L6-v2)")
            # Load lazily in embed_text to avoid startup delay if not needed
        else:
            logger.warning(
                "No embedding backend available. Retrieval will return all tools."
            )
            self._embedding_model_type = "none"

    def _get_embedding(self, text: str) -> Optional[np.ndarray]:
        """Get embedding for a single string, or None on failure."""
        if self._embedding_model_type == "ollama":
            try:
                response = ollama.embeddings(model=self._ollama_model_name, prompt=text)
                return np.array(response["embedding"])
            except Exception as e:
                logger.warning("Ollama embedding failed: %s", e)
                return None

        elif self._embedding_model_type == "sentence-transformers":
            if (
                self._st_model is None
                and SENTENCE_TRANSFORMERS_AVAILABLE
                and SentenceTransformer
            ):
                logger.info("Loading sentence-transformers model...")
                self._st_model = SentenceTransformer("all-MiniLM-L6-v2")  # type: ignore

            if self._st_model:
                # Ensure we return a numpy array, handling potential Tensor output
                embedding = self._st_model.encode(text)
                if isinstance(embedding, np.ndarray):
                    return embedding
                return np.array(embedding)

        return None

    # ------------------------------------------------------------------
    # Disk cache helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _cache_key(model_name: str, text: str) -> str:
        """Deterministic key: hash of model name + description text."""
        return hashlib.sha256(f"{model_name}|{text}".encode()).hexdigest()

    def _load_cache(self) -> None:
        """Load cached embeddings from disk (if file exists)."""
        try:
            if os.path.exists(_CACHE_FILE):
                data = np.load(_CACHE_FILE, allow_pickle=False)
                self._embedding_cache = {k: data[k] for k in data.files}
                logger.info("Loaded %d cached embeddings.", len(self._embedding_cache))
        except Exception as e:
            logger.warning("Could not load embedding cache: %s", e)
            self._embedding_cache = {}

    def _save_cache(self) -> None:
        """Persist current cache dict to disk."""
        try:
            os.makedirs(_CACHE_DIR, exist_ok=True)
            np.savez(_CACHE_FILE, **self._embedding_cache)
        except Exception as e:
            logger.warning("Could not save embedding cache: %s", e)

    def embed_tools(self, tools: List[Dict]):
        """
        Embed tool descriptions and cache them.

        Uses a disk cache keyed on (model_name, description_text) so only
        new or changed tools require an API call on subsequent launches.
        """
        if self._embedding_model_type == "none":
            return

        model_name = (
            self._ollama_model_name
            if self._embedding_model_type == "ollama"
            else "all-MiniLM-L6-v2"
        )

        self._tool_embeddings.clear()
        cache_hits = 0
        cache_misses = 0

        for tool in tools:
            func = tool.get("function", {})
            name = func.get("name")
            description = func.get("description", "")

            if not name:
                continue

            text_to_embed = f"{name}: {description}"
            key = self._cache_key(model_name, text_to_embed)

            # Use cached embedding if available
            if key in self._embedding_cache:
                self._tool_embeddings[name] = self._embedding_cache[key]
                cache_hits += 1
                continue

            # Cache miss — compute and store
            embedding = self._get_embedding(text_to_embed)
            if embedding is not None:
                self._tool_embeddings[name] = embedding
                self._embedding_cache[key] = embedding
                cache_misses += 1

        if cache_misses > 0:
            self._save_cache()
            logger.info(
                "Embedded %d new tool(s), %d from cache (%d total).",
                cache_misses, cache_hits, cache_hits + cache_misses,
            )
        else:
            logger.info("All %d tool embeddings loaded from cache.", cache_hits)

    def retrieve_tools(
        self, query: str, all_tools: List[Dict], always_on: List[str], top_k: int = 5
    ) -> List[Dict]:
        """
        Select relevant tools for the query.

        Args:
            query: User's chat message
            all_tools: Full list of available tools
            always_on: List of tool names to always include
            top_k: Number of semantic matches to include

        Returns:
            Filtered list of tool definitions
        """
        # 1. Identify always-on tools
        selected_tool_names = set(always_on)

        # 2. Semantic retrieval
        if top_k > 0 and self._embedding_model_type != "none" and query.strip() and self._tool_embeddings:
            query_embedding = self._get_embedding(query)
            if query_embedding is None:
                # Embedding failed — fall through; only always-on tools returned
                pass
            else:
                scores = []
                for name, embedding in self._tool_embeddings.items():
                    if name in selected_tool_names:
                        continue  # Already selected

                    if embedding.shape != query_embedding.shape:
                        continue

                    # Cosine similarity
                    norm_q = np.linalg.norm(query_embedding)
                    norm_t = np.linalg.norm(embedding)

                    if norm_q == 0 or norm_t == 0:
                        sim = 0
                    else:
                        sim = np.dot(query_embedding, embedding) / (norm_q * norm_t)

                    scores.append((sim, name))

                # Sort by similarity desc
                scores.sort(key=lambda x: x[0], reverse=True)

                # Pick top K, filtering out near-zero similarity
                for sim, name in scores[:top_k]:
                    if sim >= MIN_SIMILARITY_THRESHOLD:
                        selected_tool_names.add(name)

        # 3. Filter the full tool list
        final_tools = [
            t
            for t in all_tools
            if t.get("function", {}).get("name") in selected_tool_names
        ]

        logger.debug("Query: '%s'", query)
        logger.debug(
            "Selected %d tools out of %d available.",
            len(final_tools), len(all_tools)
        )
        for t in final_tools:
            logger.debug(" - %s", t.get('function', {}).get('name'))

        return final_tools

# Minimum cosine similarity to include a tool (below this, even top-K tools
# are ignored to prevent irrelevant tool injection).
MIN_SIMILARITY_THRESHOLD = 0.3


# Lazy-initialised singleton — avoids calling ollama.list() at import time,
# which would add startup latency when Ollama isn’t running.
_retriever_instance: Optional["ToolRetriever"] = None


def _get_retriever() -> "ToolRetriever":
    global _retriever_instance
    if _retriever_instance is None:
        _retriever_instance = ToolRetriever()
    return _retriever_instance


# Backward-compatible module-level name that lazily initialises.
class _LazyRetriever:
    """Proxy that defers ToolRetriever() construction until first attribute access."""

    def __getattr__(self, name):
        return getattr(_get_retriever(), name)


retriever = _LazyRetriever()  # type: ignore[assignment]

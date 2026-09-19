"""Runtime configuration.

Everything that used to be a hard-coded absolute path or an inline credential
in the original scripts is resolved here, in this order:

    1. an explicit argument
    2. an environment variable
    3. a JSON config file (``--config`` / ``$G1S_CONFIG``)
    4. a repository-relative default

No credential is stored in this package.  ``config.example.json`` carries
placeholder values only; point ``--config`` at a real file kept outside version
control, or export the environment variables directly.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = PACKAGE_DIR.parent          # <repo>/g1s   -- safe on PYTHONPATH
REPO_ROOT = PROJECT_DIR.parent            # <repo>       -- NOT safe (top-level `src`)

DEFAULT_EVAL_ROOT = (
    "external/11318_MemForest_Efficient_Agen_Supplementary_Material/Mem0/evaluation"
)


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class Endpoint:
    """One OpenAI-compatible endpoint (chat or embeddings)."""

    api_key: str
    base_url: str
    model: str

    def require(self, what: str) -> "Endpoint":
        if not self.api_key:
            raise ConfigError(f"missing API key for the {what} endpoint")
        if not self.model:
            raise ConfigError(f"missing model name for the {what} endpoint")
        return self


@dataclass(frozen=True)
class Settings:
    repo_root: Path
    eval_root: Path
    store_root: Path
    results_root: Path
    cache_root: Path
    dataset_path: Path
    query_embedding_cache: Path | None
    chat: Endpoint
    embedding: Endpoint
    embedding_dim: int
    judge_model: str
    cell_name: str = "tgdpc_bellman_global_temporal"
    python: str = field(default_factory=lambda: sys.executable)

    # ---------------------------------------------------------------- loading

    @classmethod
    def load(cls, config_path: Path | str | None = None, **overrides) -> "Settings":
        raw: dict[str, object] = {}
        path = config_path or os.environ.get("G1S_CONFIG")
        if path:
            path = Path(path).expanduser()
            if not path.is_file():
                raise ConfigError(f"config file not found: {path}")
            raw = json.loads(path.read_text(encoding="utf-8"))

        def value(*names: str, default: str = "") -> str:
            for name in names:
                if os.environ.get(name):
                    return str(os.environ[name])
            for name in names:
                if raw.get(name):
                    return str(raw[name])
            return default

        repo_root = Path(value("G1S_REPO_ROOT", default=str(REPO_ROOT))).resolve()
        eval_root = Path(
            value("G1S_EVAL_ROOT", default=str(repo_root / DEFAULT_EVAL_ROOT))
        ).resolve()
        results_root = Path(
            value("G1S_RESULTS_ROOT", default=str(repo_root / "results"))
        ).resolve()
        query_cache = value("G1S_QUERY_EMBEDDING_CACHE", "QUERY_EMBEDDING_CACHE_PATH")

        settings = cls(
            repo_root=repo_root,
            eval_root=eval_root,
            store_root=Path(
                value(
                    "G1S_STORE_ROOT",
                    default=str(repo_root / "tmp/i07_fulluploaded_stores_20260910"),
                )
            ).resolve(),
            results_root=results_root,
            cache_root=Path(
                value("G1S_CACHE_ROOT", default=str(repo_root / ".runtime_tmp"))
            ).resolve(),
            dataset_path=Path(
                value("G1S_DATASET", default=str(eval_root / "dataset/locomo10.json"))
            ).resolve(),
            query_embedding_cache=Path(query_cache).resolve() if query_cache else None,
            chat=Endpoint(
                api_key=value("G1S_CHAT_API_KEY", "CHAT_API_KEY", "OPENAI_API_KEY"),
                base_url=value("G1S_CHAT_BASE_URL", "CHAT_BASE_URL", "OPENAI_BASE_URL"),
                model=value("G1S_CHAT_MODEL", "CHAT_MODEL", "MODEL", default="gpt-4o-mini"),
            ),
            embedding=Endpoint(
                api_key=value("G1S_EMBEDDING_API_KEY", "EMBEDDING_API_KEY"),
                base_url=value("G1S_EMBEDDING_BASE_URL", "EMBEDDING_BASE_URL"),
                model=value(
                    "G1S_EMBEDDING_MODEL", "EMBEDDING_MODEL", default="text-embedding-3-small"
                ),
            ),
            embedding_dim=int(value("G1S_EMBEDDING_DIM", "LOCOMO_EMBEDDING_DIM", "EMBEDDING_DIM", default="1536")),
            judge_model=value("G1S_JUDGE_MODEL", "JUDGE_MODEL", default="") or value(
                "G1S_CHAT_MODEL", "CHAT_MODEL", "MODEL", default="gpt-4o-mini"
            ),
            cell_name=value(
                "G1S_CELL_NAME", default="tgdpc_bellman_global_temporal"
            ),
        )
        if overrides:
            settings = settings.replace(**overrides)
        return settings

    def replace(self, **overrides) -> "Settings":
        from dataclasses import replace as _replace

        return _replace(self, **overrides)

    # ------------------------------------------------------------ derived paths

    @property
    def project_dir(self) -> Path:
        """Directory to put on a child process's path so ``import g1s`` works."""
        return PROJECT_DIR

    def sample_store(self, sample: int) -> Path:
        """The read-only master qdrant store for one LoCoMo sample."""
        return self.store_root / f"store_{sample}" / "locomo"

    def cell_dir(self, result_dir: Path) -> Path:
        """The single working directory of one experiment arm.

        The original runner derived this directory name from the routing mode
        (``cell_dir()``, 40+ branches).  Under the locked G1S configuration the
        branch taken was always ``tgdpc_bellman_global_temporal``, which is why
        every launcher hard-coded that string.  It is a plain constant here, and
        the legacy value is kept as the default so existing result directories
        can be read and resumed without moving anything.
        """
        return result_dir / self.cell_name

    def grounding_dir(self, tag: str) -> Path:
        return self.results_root / f"locomo_entity_grounding_{tag}"

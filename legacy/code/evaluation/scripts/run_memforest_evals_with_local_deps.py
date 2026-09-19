"""Run MemForest `evals.py` while using already-installed local deps.

The upstream metrics helper calls `nltk.download()` at import time and also
initializes a SentenceTransformer model that LoCoMo BLEU/F1/LLM-judge scoring
does not use. On weak-network servers this can hang before evaluation starts.

This wrapper does not modify MemForest scoring code. It patches only the
import-time dependency bootstrap so installed NLTK resources are used locally
and optional SBERT loading fails fast if not cached.
"""
from __future__ import annotations

import argparse
import os
import runpy
import sys
from pathlib import Path

import nltk


RESOURCE_BY_PACKAGE = {
    "punkt": "tokenizers/punkt",
    "punkt_tab": "tokenizers/punkt_tab",
    "wordnet": "corpora/wordnet",
}


def patch_nltk_download() -> None:
    original_download = nltk.download

    def local_first_download(package, *args, **kwargs):
        resource = RESOURCE_BY_PACKAGE.get(str(package))
        if resource is not None:
            try:
                nltk.data.find(resource)
                return True
            except LookupError:
                pass
        return original_download(package, *args, **kwargs)

    nltk.download = local_first_download


def main() -> None:
    parser = argparse.ArgumentParser(description="Run MemForest evals.py with local dependency bootstrap.")
    parser.add_argument("--eval-dir", required=True)
    parser.add_argument("--input-file", required=True)
    parser.add_argument("--output-file", required=True)
    parser.add_argument("--max-workers", type=int, default=2)
    args = parser.parse_args()

    eval_dir = Path(args.eval_dir).resolve()
    evals_py = eval_dir / "evals.py"
    if not evals_py.exists():
        raise FileNotFoundError(evals_py)
    input_file = Path(args.input_file).resolve()
    output_file = Path(args.output_file).resolve()

    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    patch_nltk_download()
    sys.path.insert(0, str(eval_dir))
    os.chdir(eval_dir)
    sys.argv = [
        str(evals_py),
        "--input_file",
        str(input_file),
        "--output_file",
        str(output_file),
        "--max_workers",
        str(args.max_workers),
    ]
    runpy.run_path(str(evals_py), run_name="__main__")


if __name__ == "__main__":
    main()

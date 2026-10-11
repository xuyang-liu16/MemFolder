# Native MemOS / LoCoMo

[Documentation](README.md)

This optional runner uses native MemOS **2.0.33** at commit
`78a372a4fc853a24d2a78efa3b4bbbd27ab9f7ad`, rather than the older cube-file
loader. It builds an uncompressed bank from raw LoCoMo conversations and runs
native retrieval, QA and scoring. Heavy dependencies stay outside the core
compression package.

The configuration is in
[protocol.json](../src/memfolder/reproduction/memos_locomo/protocol.json):
raw two-turn memory with timestamps and separate speaker tenants; BGE-M3
**1024** dimensions; PostgreSQL **16.10** + pgvector **0.8.1**; native fast search
with **Top20 per speaker**, preference Top6 and no similarity cutoff; fixed
BGE-reranker-v2-m3 weights, **CUDA FP32**, length **1024**, batch **2**, TF32 off;
o compression or AGPR. QA and judge use the pinned official prompts,
`gpt-4o-mini-2024-07-18`, temperature 0, once each. Category 5 is excluded.
Gold answers are available only to the judge.

Use separate Python **3.12** CPU and GPU environments. In the CPU environment:

```bash
python -m pip install torch==2.7.1+cpu --index-url https://download.pytorch.org/whl/cpu
python -m pip install -r requirements/memos-cpu.txt
python -m pip install -e .
```

In the GPU environment:

```bash
python -m pip install torch==2.10.0+cu128 --index-url https://download.pytorch.org/whl/cu128
python -m pip install -r requirements/memos-reranker.txt
python -m pip install -e .
```

Set `MEMFOLDER_CHAT_KEY` and `MEMFOLDER_EMBEDDING_KEY` in the CPU shell.
Provider URLs can be changed with `MEMFOLDER_CHAT_BASE_URL` and
`MEMFOLDER_EMBEDDING_BASE_URL`; defaults match the configured OpenAI-compatible
chat service and BGE-M3 service. Credentials are never part of the configuration.
Prepare downloads the pinned SDK, its LoCoMo dataset and the pinned weights:

```bash
python -m memfolder.reproduction.memos_locomo prepare --run-dir build/memos-locomo --weights
python -m memfolder.reproduction.memos_locomo run --run-dir build/memos-locomo --postgres-bin /your/pgsql/bin --reranker-python /your/gpu-venv/bin/python
```

The supplied PostgreSQL installation must include pgvector 0.8.1. The runner
creates and stops a private loopback database cluster; run it as a normal user.
On Windows, prepare can download PostgreSQL and compile pgvector using x64 MSVC:

```powershell
python -m memfolder.reproduction.memos_locomo prepare --run-dir D:/MemFolderRuns/memos-locomo --weights --postgres --vcvars "D:/Program Files/Microsoft Visual Studio/2022/Community/VC/Auxiliary/Build/vcvars64.bat"
python -m memfolder.reproduction.memos_locomo run --run-dir D:/MemFolderRuns/memos-locomo --reranker-python D:/MemFolderEnvs/gpu/Scripts/python.exe
```

Replace the compiler and environment paths. `--build-workers`, `--qa-workers`,
`--postgres-port`, `--reranker-port`, `--source-dir` and `--model-dir` control
operational resources. All generated data, caches, QA checkpoints, retrieval
traces and scores stay under `--run-dir`. Repeating the same command resumes
compatible checkpoints. Install-time pip and temporary paths are controlled by
your shell separately. API reruns can vary even at temperature zero.

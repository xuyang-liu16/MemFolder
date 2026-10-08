# Third-party source notices

Source revisions and SHA-256 hashes are in `METHOD_PROVENANCE.json`. Archived
files are not imported wholesale; selected pure routines/prompts are ported into
the corresponding modules, and independent characterization tests compare them.

## StreamMeCo

- Repository: https://github.com/Celina-love-sweet/StreamMeCo
- Revision: `67c8e8c74c97e69f625890936754a9f934f3d35a`
- Copyright (c) 2026 Celina
- License: MIT, preserved in `src/memfolder/licenses/StreamMeCo-MIT.txt` and the wheel.
- Derived routines: `planning/_streammeco.py`; graph adaptation: `planning/streammeco.py`.

The copied pure selectors preserve the original formulas and quotas. Canonical
graph projection, protected-node handling and explicit feature-space validation
are integration adaptations. Temporal retrieval is outside this port.

## Authoritative MemFolder release and experiment archives

The user-designated standardized `MemFolder-main.zip` supplies RecordFolder and
ContextFolder. Older experiment archives supply text ToMe, M3 pooled ToMe,
average-linkage MemForest proxy, Random methods and DART memory adaptations.
Their full provenance remains recorded locally. This development checkout does
not assign a new license to those existing sources.

The MemForest MST routines and pair prompt derive from the archived paper
supplement (`11318_MemForest_Efficient_Agen_Supplementary_Material`). The selected
archive does not include a separately verified license grant in this record.
Its release attribution/permission must be resolved with that source before an
open-source distribution license is finalized. This notice does not assert that
all archived material is MIT licensed.

KMeans stages are new implementations of the user's approved definition and use
scikit-learn through an optional dependency; they do not copy scikit-learn source.

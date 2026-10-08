# Third-party sources and attribution

[Documentation](README.md)

MemFolder combines project methods with selected routines and prompts from the sources below. [METHOD_PROVENANCE.json](METHOD_PROVENANCE.json) records source revisions, file hashes, and implementation locations.

## StreamMeCo

| Item | Source |
| --- | --- |
| Repository | [Celina-love-sweet/StreamMeCo](https://github.com/Celina-love-sweet/StreamMeCo) |
| Revision | `67c8e8c74c97e69f625890936754a9f934f3d35a` |
| Copyright | Copyright (c) 2026 Celina |
| License | [MIT notice](../src/memfolder/licenses/StreamMeCo-MIT.txt), included in the package |
| Implementation | `planning/_streammeco.py` and `planning/streammeco.py` |

The selection routines preserve the source formulas and class quotas. MemFolder adds graph conversion, protected-record handling, and vector-space checks. This port covers graph compression; the upstream temporal retrieval stage requires a separate reader.

## RecordFolder, ContextFolder, and archived methods

RecordFolder and ContextFolder come from the project authors' standardized `MemFolder-main.zip` release. Earlier implementation names are G1S and V12, respectively. The archived experiments provide text ToMe, M3 pooled ToMe, the average-linkage MemForest proxy, Random methods, and DART memory adaptations.

The MemForest tree-based routines and pair prompt come from `11318_MemForest_Efficient_Agen_Supplementary_Material`. Release permission for that archive still needs confirmation from the source. Licensing for the historical contributions remains under review, and their existing terms continue to apply.

The KMeans stages are implemented in this project and call scikit-learn through an optional dependency.

## Dataset and framework sources

The following records identify the upstream versions used for parsing, scoring, and framework integration:

- [BENCHMARK_SOURCES.json](BENCHMARK_SOURCES.json): benchmark formats and evaluation code.
- [LOADING_SOURCES.json](LOADING_SOURCES.json): memory-store formats and readers.
- [WRAPPER_SOURCES.json](WRAPPER_SOURCES.json): native output and readback implementations.

Dataset downloads, model access, and upstream libraries remain subject to their own terms. The repository's test-source fetcher uses the recorded revisions and verifies the downloaded file hashes.

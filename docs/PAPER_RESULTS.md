# Paper results

[Documentation](README.md) · [简体中文](zh-CN/PAPER_RESULTS.md) · [README results](../README.md#full-results)

These tables report the manuscript's main experiments on Mem0, MemOS, and M3-Agent. They include every active result row and category score from the supplied LaTeX tables.

## How to read the tables

- **Record reduction** is the percentage removed. A 70% reduction retains 30% of the original records.
- **Accuracy and average accuracy** are percentages. **Retention** is the reported average relative to the corresponding uncompressed system.
- **MemFolder (Ours)** in these tables refers to RecordFolder. The [context-compression figure](assets/paper-context-results.pdf) reports ContextFolder separately.
- Bold and <ins>underlined</ins> values follow the source's best/second-best formatting. Averages and retention use the values reported in the paper.

[Exact table data](assets/paper-results-data.json) · [Method figure](assets/paper-overview.pdf) · [Context results](assets/paper-context-results.pdf) · [Retrieval efficiency](assets/paper-retrieval-efficiency.pdf)

## Mem0

### 30% record-count reduction

| Method | LoCoMo SH | LoCoMo MH | LoCoMo TR | LoCoMo OD | LoCoMo All | LongMemEval SU | LongMemEval SA | LongMemEval SP | LongMemEval MS | LongMemEval KU | LongMemEval TR | LongMemEval All | PersonaMem | Avg. | Retention (%) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Mem0 (uncompressed) | 66.0 | 56.0 | 53.9 | 42.7 | 60.2 | 90.0 | 21.4 | 23.3 | 54.9 | 79.5 | 44.4 | 55.2 | 67.9 | 61.1 | 100.0 |
| Random Pruning | 55.3 | 49.7 | 43.3 | 39.6 | 50.8 | 82.9 | 17.9 | <ins>26.7</ins> | <ins>51.9</ins> | 73.1 | 39.1 | 50.8 | 64.5 | 55.4 | 90.7 |
| KMeans | 61.1 | 54.3 | <ins>52.7</ins> | 40.6 | 56.8 | 84.3 | 17.9 | 20.0 | <ins>51.9</ins> | <ins>75.6</ins> | 41.4 | 52.0 | 65.7 | 58.2 | 95.3 |
| DART | <ins>64.1</ins> | 53.9 | 48.0 | 40.6 | 57.4 | 82.9 | 19.0 | 20.0 | 48.9 | 74.4 | 34.6 | 48.8 | <ins>66.6</ins> | 57.6 | 94.3 |
| Random Merging | 60.9 | 52.1 | 51.1 | 43.8 | 56.2 | **91.4** | **21.4** | 20.2 | 46.6 | 74.4 | 41.4 | 50.8 | 65.2 | 57.4 | 93.9 |
| ToMe | 63.1 | 51.1 | 50.8 | <ins>44.8</ins> | 57.2 | 85.7 | **21.4** | 23.3 | 48.1 | 71.8 | 42.9 | 51.2 | 66.4 | 58.3 | 95.4 |
| MemForest | 63.7 | <ins>54.6</ins> | 52.0 | **45.8** | <ins>58.5</ins> | <ins>90.0</ins> | <ins>19.6</ins> | 20.0 | 49.8 | **76.9** | **49.6** | <ins>54.2</ins> | <ins>66.6</ins> | <ins>59.7</ins> | <ins>97.7</ins> |
| **MemFolder (Ours)** | **67.5** | **56.0** | **56.1** | 41.7 | **61.7** | 88.6 | **21.4** | **36.7** | **52.6** | <ins>75.6</ins> | <ins>46.6</ins> | **55.2** | **67.7** | **61.5** | **100.7** |

### 50% record-count reduction

| Method | LoCoMo SH | LoCoMo MH | LoCoMo TR | LoCoMo OD | LoCoMo All | LongMemEval SU | LongMemEval SA | LongMemEval SP | LongMemEval MS | LongMemEval KU | LongMemEval TR | LongMemEval All | PersonaMem | Avg. | Retention (%) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Mem0 (uncompressed) | 66.0 | 56.0 | 53.9 | 42.7 | 60.2 | 90.0 | 21.4 | 23.3 | 54.9 | 79.5 | 44.4 | 55.2 | 67.9 | 61.1 | 100.0 |
| Random Pruning | 44.4 | 45.4 | 37.1 | **44.8** | 43.1 | 75.7 | 17.9 | <ins>26.7</ins> | 32.3 | 65.4 | 39.8 | 43.6 | 64.3 | 50.3 | 82.3 |
| KMeans | 51.6 | 43.6 | 39.6 | 37.5 | 46.8 | 77.1 | 19.6 | 23.3 | 39.1 | <ins>74.4</ins> | 39.8 | 47.0 | 65.2 | 53.0 | 86.7 |
| DART | 57.4 | 49.6 | 41.7 | <ins>43.8</ins> | 51.9 | 67.1 | 12.5 | 23.3 | 42.9 | 60.3 | 31.6 | 41.4 | 64.3 | 52.5 | 85.9 |
| Random Merging | 56.0 | 48.2 | 46.4 | 37.5 | 51.4 | 85.7 | **23.2** | 20.0 | 42.9 | 70.5 | 39.1 | 48.6 | 64.5 | 54.8 | 89.7 |
| ToMe | 60.2 | 50.4 | 47.4 | <ins>43.8</ins> | 54.7 | 85.7 | <ins>21.4</ins> | 23.3 | <ins>48.1</ins> | 71.8 | 41.4 | 50.8 | 65.9 | 57.1 | 93.5 |
| MemForest | <ins>62.1</ins> | **56.7** | **54.8** | <ins>43.8</ins> | <ins>58.4</ins> | **90.0** | 19.6 | 20.0 | <ins>48.1</ins> | <ins>74.4</ins> | <ins>42.9</ins> | <ins>51.8</ins> | **67.7** | <ins>59.3</ins> | <ins>97.1</ins> |
| **MemFolder (Ours)** | **65.5** | <ins>55.7</ins> | <ins>50.5</ins> | 39.6 | **59.3** | <ins>88.6</ins> | <ins>21.4</ins> | **30.0** | **53.4** | **76.9** | **45.9** | **55.0** | <ins>67.2</ins> | **60.5** | **99.0** |

### 70% record-count reduction

| Method | LoCoMo SH | LoCoMo MH | LoCoMo TR | LoCoMo OD | LoCoMo All | LongMemEval SU | LongMemEval SA | LongMemEval SP | LongMemEval MS | LongMemEval KU | LongMemEval TR | LongMemEval All | PersonaMem | Avg. | Retention (%) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Mem0 (uncompressed) | 66.0 | 56.0 | 53.9 | 42.7 | 60.2 | 90.0 | 21.4 | 23.3 | 54.9 | 79.5 | 44.4 | 55.2 | 67.9 | 61.1 | 100.0 |
| Random Pruning | 35.0 | 36.5 | 25.9 | 31.3 | 33.1 | 47.1 | 7.1 | <ins>30.0</ins> | 16.5 | 42.3 | 31.6 | 28.6 | 63.7 | 41.8 | 68.4 |
| KMeans | 37.9 | 42.6 | 27.4 | 39.6 | 36.7 | 61.4 | 8.9 | <ins>30.0</ins> | 21.8 | 59.0 | 31.6 | 34.8 | 63.8 | 45.1 | 73.8 |
| DART | 46.4 | 44.3 | 36.1 | 41.7 | 43.6 | 44.3 | 10.7 | 16.7 | 21.0 | 43.6 | 27.8 | 30.6 | 61.8 | 45.3 | 74.1 |
| Random Merging | 54.0 | 47.2 | 47.0 | <ins>43.8</ins> | 50.7 | 80.0 | 21.4 | <ins>30.0</ins> | 41.4 | 67.9 | 34.6 | 46.2 | 64.0 | 53.6 | 87.7 |
| ToMe | 56.6 | 51.8 | <ins>47.7</ins> | 38.5 | 52.7 | <ins>84.3</ins> | 21.4 | 20.0 | 45.1 | 70.5 | <ins>42.1</ins> | 49.6 | **65.7** | 56.0 | 91.7 |
| MemForest | <ins>58.1</ins> | <ins>56.4</ins> | 45.2 | **45.8** | <ins>54.4</ins> | <ins>84.3</ins> | **25.0** | 23.3 | **52.6** | <ins>74.4</ins> | 39.8 | <ins>52.2</ins> | 64.4 | <ins>57.0</ins> | <ins>93.3</ins> |
| **MemFolder (Ours)** | **61.2** | **57.0** | **50.7** | 43.4 | **57.1** | **85.7** | <ins>23.2</ins> | **53.3** | <ins>50.4</ins> | **75.6** | **45.1** | **55.0** | <ins>64.9</ins> | **59.0** | **96.6** |

## MemOS

### 50% record-count reduction

| Method | LoCoMo SH | LoCoMo MH | LoCoMo TR | LoCoMo OD | LoCoMo All | LongMemEval SU | LongMemEval SA | LongMemEval SP | LongMemEval MS | LongMemEval KU | LongMemEval TR | LongMemEval All | PersonaMem | Avg. | Retention (%) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| MemOS (uncompressed) | 84.5 | 70.2 | 78.8 | 56.2 | 79.0 | 91.4 | 100.0 | 66.7 | 55.6 | 78.2 | 71.4 | 74.0 | 60.3 | 71.1 | 100.0 |
| Random Pruning | 70.5 | 65.2 | 57.3 | 46.9 | 65.3 | 67.1 | 64.3 | 63.3 | 28.6 | 52.6 | 43.6 | 47.8 | 55.9 | 56.3 | 79.2 |
| KMeans | 75.7 | 59.2 | 57.6 | <ins>57.3</ins> | 67.8 | 72.9 | 69.6 | 66.7 | 20.3 | 51.3 | 45.9 | 47.6 | 54.7 | 56.7 | 79.7 |
| DART | 76.5 | 68.1 | 58.9 | **58.3** | 70.1 | 62.9 | **82.1** | 50.0 | 20.3 | 35.9 | 33.1 | 40.8 | 53.7 | 54.9 | 77.2 |
| Random Merging | 79.4 | <ins>69.9</ins> | 66.0 | 54.2 | 73.3 | 80.0 | 62.5 | **83.3** | **46.6** | 60.3 | 54.9 | 59.6 | <ins>56.2</ins> | 63.0 | 88.7 |
| ToMe | 76.7 | 68.8 | 63.9 | 52.1 | 71.0 | 78.6 | 67.9 | <ins>76.7</ins> | 40.6 | <ins>70.5</ins> | **63.2** | <ins>61.8</ins> | **57.9** | 63.6 | 89.4 |
| MemForest | **82.6** | 68.8 | **70.1** | **58.3** | **76.0** | <ins>81.4</ins> | 76.8 | 66.7 | 40.6 | 65.4 | <ins>56.4</ins> | 60.0 | 54.8 | <ins>63.6</ins> | <ins>89.5</ins> |
| **MemFolder (Ours)** | <ins>81.2</ins> | **70.6** | <ins>69.5</ins> | 56.2 | <ins>75.3</ins> | **85.7** | <ins>78.6</ins> | **83.3** | <ins>45.1</ins> | **75.6** | 54.9 | **64.2** | 54.7 | **64.7** | **91.0** |

### 70% record-count reduction

| Method | LoCoMo SH | LoCoMo MH | LoCoMo TR | LoCoMo OD | LoCoMo All | LongMemEval SU | LongMemEval SA | LongMemEval SP | LongMemEval MS | LongMemEval KU | LongMemEval TR | LongMemEval All | PersonaMem | Avg. | Retention (%) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| MemOS (uncompressed) | 84.5 | 70.2 | 78.8 | 56.2 | 79.0 | 91.4 | 100.0 | 66.7 | 55.6 | 78.2 | 71.4 | 74.0 | 60.3 | 71.1 | 100.0 |
| Random Pruning | 58.5 | 59.9 | 43.0 | 49.0 | 54.9 | 32.9 | 48.2 | 73.3 | 13.5 | 29.5 | 28.6 | 30.2 | 52.8 | 46.0 | 64.7 |
| KMeans | 62.5 | 57.8 | 43.9 | 55.2 | 57.3 | 40.0 | 53.6 | 50.0 | 15.8 | 30.8 | 30.1 | 31.6 | 52.6 | 47.2 | 66.4 |
| DART | 65.6 | 59.9 | 46.1 | 54.2 | 59.8 | 30.0 | 60.7 | 50.0 | 15.0 | 25.6 | 18.0 | 26.8 | 48.9 | 45.2 | 63.5 |
| Random Merging | 73.0 | 64.2 | <ins>61.7</ins> | <ins>57.3</ins> | 68.1 | **75.7** | 39.3 | <ins>83.3</ins> | **39.1** | 60.3 | **52.6** | <ins>53.8</ins> | 54.0 | 58.6 | 82.5 |
| ToMe | 71.7 | <ins>68.8</ins> | 60.7 | 47.9 | 67.4 | 67.1 | **67.9** | 70.0 | 32.3 | <ins>62.8</ins> | <ins>51.9</ins> | 53.4 | <ins>55.4</ins> | 58.7 | 82.6 |
| MemForest | <ins>77.4</ins> | 64.9 | **62.6** | 56.2 | <ins>70.7</ins> | 62.9 | <ins>66.1</ins> | 73.3 | 30.8 | 50.0 | 50.4 | 50.0 | **55.5** | <ins>58.7</ins> | <ins>82.6</ins> |
| **MemFolder (Ours)** | **77.5** | **69.1** | 60.1 | **60.4** | **71.3** | <ins>74.3</ins> | 62.5 | **93.3** | <ins>33.8</ins> | **65.4** | 45.9 | **54.4** | 55.2 | **60.3** | **84.8** |

## M3-Agent

### 50% record-count reduction

| Method | Robot ME | Robot MH | Robot CM | Robot PU | Robot GK | Robot All | Web ME | Web MH | Web CM | Web PU | Web GK | Web All | Avg. | Retention (%) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| M3-Agent (uncompressed) | 30.9 | 29.4 | 29.6 | 41.1 | 22.6 | 30.3 | 44.9 | 25.6 | 44.8 | 58.6 | 53.7 | 47.9 | 39.1 | 100.0 |
| Random Pruning | 28.4 | 25.9 | 27.3 | 38.7 | 19.6 | 28.1 | 35.6 | 23.0 | 34.9 | 52.3 | 44.2 | 41.2 | 34.7 | 88.7 |
| KMeans | 29.1 | 30.6 | 28.4 | 41.4 | 20.8 | 29.2 | 41.1 | 21.7 | 42.5 | 55.0 | 47.4 | 43.9 | 36.6 | 93.6 |
| DART | 28.9 | 25.9 | 29.4 | 39.1 | 22.0 | 29.1 | 39.9 | 23.6 | 39.4 | 52.9 | 47.2 | 43.1 | 36.1 | 92.3 |
| StreamMeCo | 32.3 | 28.2 | 29.8 | 41.4 | 21.1 | 30.6 | 39.7 | 25.2 | 38.9 | 58.4 | 47.3 | 44.7 | 37.7 | 96.2 |
| Random Merging | 33.0 | 32.9 | 31.9 | 44.3 | 19.6 | 30.8 | 41.8 | 21.0 | 40.1 | 58.0 | 46.3 | 44.6 | 37.7 | 96.4 |
| ToMe | 30.5 | 32.9 | 29.6 | 42.3 | 19.9 | 30.9 | 42.7 | 24.7 | 41.7 | 54.3 | 53.1 | 46.1 | 38.5 | 98.5 |
| MemForest | 31.6 | 31.8 | 31.1 | 45.1 | 21.4 | **31.6** | 42.6 | 23.9 | 43.4 | 57.1 | 51.5 | <ins>46.5</ins> | <ins>39.0</ins> | <ins>99.7</ins> |
| **MemFolder (Ours)** | 31.7 | 34.1 | 30.0 | 45.3 | 19.9 | <ins>31.0</ins> | 44.6 | 27.8 | 44.6 | 59.6 | 52.4 | **48.2** | **39.6** | **101.3** |

### 70% record-count reduction

| Method | Robot ME | Robot MH | Robot CM | Robot PU | Robot GK | Robot All | Web ME | Web MH | Web CM | Web PU | Web GK | Web All | Avg. | Retention (%) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| M3-Agent (uncompressed) | 30.9 | 29.4 | 29.6 | 41.1 | 22.6 | 30.3 | 44.9 | 25.6 | 44.8 | 58.6 | 53.7 | 47.9 | 39.1 | 100.0 |
| Random Pruning | 27.3 | 25.9 | 26.7 | 39.2 | 20.8 | 27.7 | 35.0 | 19.9 | 34.9 | 48.7 | 39.5 | 37.3 | 32.5 | 83.1 |
| KMeans | 28.7 | 28.2 | 27.3 | 42.7 | 19.3 | 28.9 | 35.5 | 20.1 | 34.9 | 39.7 | 42.5 | 39.1 | 34.0 | 87.0 |
| DART | 27.8 | 25.9 | 25.4 | 40.0 | 16.2 | 27.2 | 35.4 | 19.5 | 36.6 | 48.2 | 45.0 | 39.2 | 33.2 | 84.9 |
| StreamMeCo | 29.1 | 30.6 | 26.9 | 40.3 | 19.9 | 28.4 | 37.0 | 21.7 | 36.1 | 53.0 | 46.3 | 41.9 | 35.1 | 89.8 |
| Random Merging | 30.6 | 31.8 | 28.8 | 45.1 | 19.0 | 30.4 | 41.1 | 21.9 | 39.6 | 58.6 | 41.5 | 43.2 | 36.8 | 94.1 |
| ToMe | 31.7 | 27.1 | 28.6 | 43.1 | 20.2 | 30.6 | 42.9 | 23.6 | 43.6 | 56.5 | 49.8 | 45.7 | 38.2 | 97.7 |
| MemForest | 31.2 | 32.9 | 32.4 | 43.6 | 17.4 | 30.7 | 44.8 | 23.9 | 38.9 | 57.3 | 50.4 | 46.3 | 38.5 | 98.5 |
| **MemFolder (Ours)** | 32.3 | 29.4 | 30.9 | 45.4 | 19.9 | **31.4** | 44.5 | 28.9 | 44.1 | 60.3 | 51.6 | **48.7** | **40.1** | **102.6** |

<a id="source-consistency"></a>

## Source consistency

The manuscript's main table and context-compression figure use different LongMemEval reference scores at 50% Mem0 record reduction:

| Source | RecordFolder | MemForest | ToMe |
| --- | ---: | ---: | ---: |
| Main result table | 55.0 | 51.8 | 50.8 |
| Context-compression figure | 55.2 | 54.6 | 52.6 |

Each table and figure retains its own reported values. Use the reference scores from the same source when interpreting a comparison.

The table sources are `Tables/main_results_mem0.tex`, `Tables/main_results_memos.tex`, and `Tables/main_results_m3.tex`. The figure sources are `Figures/overview.pdf`, `Figures/context_compression.pdf`, and `Figures/retrieval_latency.pdf`. Their hashes and exact values are recorded in [paper-results-data.json](assets/paper-results-data.json). The README's graphical abstract is taken from the separately supplied manuscript version recorded in [paper-intro-source.json](assets/paper-intro-source.json).

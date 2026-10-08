# Figures and data sources

[Documentation](../README.md) · [Paper results](../PAPER_RESULTS.md)

This directory contains the paper figures displayed in the README, their source records, and an archived illustrated overview.

## Figures used in the README

| Asset | Content and source |
| --- | --- |
| [paper-intro.png](paper-intro.png) | Graphical abstract, Figure 1 on page 2 of `7707_MemFolder_Structure_Guide (2).pdf` |
| [paper-overview.png](paper-overview.png) / [PDF](paper-overview.pdf) | Method overview from `Figures/overview.pdf` |
| [paper-context-results.png](paper-context-results.png) / [PDF](paper-context-results.pdf) | Context-compression results from `Figures/context_compression.pdf` |
| [paper-retrieval-efficiency.png](paper-retrieval-efficiency.png) / [PDF](paper-retrieval-efficiency.pdf) | Retrieval results from `Figures/retrieval_latency.pdf` |
| [paper-results-data.json](paper-results-data.json) | Exact active rows from the three main LaTeX result tables, with source hashes |

The graphical abstract was rendered at 500 dpi and cropped to its figure bounds, producing a 2750 × 1170 image. The crop preserves the figure and excludes the page header, line numbers, caption, and surrounding text. [paper-intro-source.json](paper-intro-source.json) records the source and output hashes and crop coordinates.

The method and experimental figures are PNG renders of the PDFs referenced by the supplied manuscript source. Both language versions display the same figures. Their values retain the source's reporting and rounding; the [results guide](../PAPER_RESULTS.md#source-consistency) explains the LongMemEval reference-score differences between the table and context figure.

## Software diagram

[memfolder-architecture.svg](memfolder-architecture.svg) describes the software components from loading through evaluation. The SVG is editable and includes an accessible description. It shows how configuration selects components and how repeated compression updates memory before the next round.

## Archived illustrated overview

[memfolder-hero.png](memfolder-hero.png) is the earlier 1920 × 1080 watercolor overview. Its layout plate and replacement scenes were generated on 2026-10-08 with the configured `gpt-image-2` model at high quality. The plate was requested and returned at 3840 × 2160. Titles and charts were added as editable PowerPoint objects before rendering.

The artwork combines the authors' robot and memory illustrations with generated scenes for record growth, grouping, context compression, historical debugging, and retrieval. Its title and footer use Forte lettering, and the footer illustrations use fading edges.

Production records are preserved in the [layout prompt](hero-prompt.txt), [scene prompts](hero-scene-prompts.md), [refinement prompts](hero-refinement-prompts.md), and [chart data](hero-data.json). These files document the archived artwork.

## Reading the archived charts

The latency values and maximum 5.34× speedup come from the supplied manuscript artwork. Benchmark bars use a separate scale within each row, with labels in milliseconds. The maximum speedup follows the manuscript's value before label rounding.

The storage chart transcribes the supplied LME memory-store measurement:

| Records | Vector and index storage (MB) |
| ---: | ---: |
| 1,000 | 14 |
| 5,000 | 69 |
| 10,000 | 138 |
| 50,000 | 686 |
| 100,000 | 1,371 |
| 200,000 | 2,743 |
| 310,120 | 4,873 |

Its record-count axis follows the source's ordered categories. The simple-summary illustration depicts the reading burden caused by a longer single-record context. These charts and scenes present the supplied measurements and method explanation.

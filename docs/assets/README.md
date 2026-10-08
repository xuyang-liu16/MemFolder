# README artwork

- `memfolder-hero.png` presents the paper in three columns: memory growth before
  compression, RecordFolder / ContextFolder, and retrieval after compression.
  The warm watercolor illustrations, assistant characters and source numerical
  labels were supplied by the project authors. The README preview is 1920 × 1080.
- `memfolder-architecture.svg` describes the software interfaces. It is editable
  SVG source with an accessible description. Projection and feature refresh also
  occur between compression rounds; native materialization is the final output
  step. Gold labels enter only the Evaluator.

## Hero production

The decorative layout plate was generated on 2026-10-08 using the project owner's
configured image API with **`model=gpt-image-2`**, **`quality=high`** and requested
size **3840 × 2160**. The response also identified `gpt-image-2`; the downloaded
plate has those pixel dimensions. The API key is not stored in this repository.

The generated paper, ribbons, frames and upper-left vignette were placed as
separate layers. The other three corner stories and the method scenes reuse the
author-supplied illustrations. Titles and all six data charts were authored as
editable PowerPoint objects, then rendered for the README. This avoids asking an
image model to reproduce scientific numbers or enforce exact text placement.

Academic layout examples informed visual hierarchy and spacing; their figures,
labels, logos and research results are not reproduced in the final artwork.
The design uses ivory paper, navy lettering, coral, teal and sage accents.
See [the generation prompt](hero-prompt.txt) and
[the supplied chart values](hero-data.json).

## Data interpretation

The latency values and 5.34× callout reproduce the supplied manuscript artwork;
they are not new measurements from this refactored release. The benchmark bars
have separate scales for each row, with labels in milliseconds. The 5.34× maximum
is manuscript-reported and should not be reconstructed from rounded bar labels.
The storage-cost illustration is qualitative.

The editable export was checked for package integrity, slide bounds, font policy,
six native charts with embedded data workbooks, and successful reimport/rendering.
This does not establish native PowerPoint application compatibility or independent
reproduction of the paper's measurements.

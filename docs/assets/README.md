# README artwork

- `memfolder-hero.png` presents the paper in three columns: memory growth before
  compression, RecordFolder / ContextFolder, and retrieval after compression.
  The warm watercolor style, assistant characters and source numerical labels
  originate in the authors' artwork. Scenes were recomposed for their panel
  dimensions with GPT-IMAGE-2. The README preview is 1920 × 1080.
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
separate layers. A subsequent refinement used the same configured model and high
quality for seven scenes: memory growth, RecordFolder, two ContextFolder panels,
successful retrieval, a panoramic debugging story and a panoramic burden-relief
story. The top-right research vignette retains the author-supplied artwork.
The latest refinement replaced four scenes: precise historical version retrieval
for debugging, the reading burden of an expanding single-node context, verified
compact memory, and memory burden relief. Footer scenes use fading watercolor
edges, and the title lockup and footer summary use larger Forte display lettering.
Titles and all seven data charts were authored as editable PowerPoint objects,
then rendered for the README.

Academic layout examples informed visual hierarchy and spacing; their figures,
labels, logos and research results are not reproduced in the final artwork.
The design uses ivory paper, navy lettering, coral, teal and sage accents.
See [the framework prompt](hero-prompt.txt),
[the initial scene prompts](hero-scene-prompts.md),
[the latest refinement prompts](hero-refinement-prompts.md) and
[the supplied chart values](hero-data.json).

## Data interpretation

The latency values and 5.34× callout reproduce the supplied manuscript artwork;
they are not new measurements from this refactored release. The benchmark bars
have separate scales for each row, with labels in milliseconds. The 5.34× maximum
is manuscript-reported and should not be reconstructed from rounded bar labels.
The storage chart transcribes the owner's measured LME memory-bank `du` plot:
1,000 / 5,000 / 10,000 / 50,000 / 100,000 / 200,000 / 310,120 nodes correspond to
14 / 69 / 138 / 686 / 1,371 / 2,743 / 4,873 MB of vectors plus index storage.
The node-count axis is ordered categorical, matching the supplied chart. These
measurements were not independently rerun for this artwork revision.

The naive-summary panel depicts a growing context within one memory node and its
reading burden; it makes no retrieval-latency claim.

The editable export was checked for package integrity, slide bounds, font policy,
seven native charts with embedded data workbooks, and successful reimport/rendering.
This does not establish native PowerPoint application compatibility or independent
reproduction of the paper's measurements.

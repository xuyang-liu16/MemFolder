# RecallFlow-URB Random Node Probe Response Snapshot

> Date: 2026-07-09  
> Dataset/store: LoCoMo `sample0`, full Mem0 local Qdrant snapshot  
> Sample: 15 random memory nodes from 733 sample0 nodes  
> Random seed: `20260709`  
> Purpose: inspect whether URB 10-dimensional response scores align with memory-node metadata/text types.

## One-Screen Takeaway

The random sample suggests that single-node URB responses carry useful but soft signals. Several nodes align intuitively with their strongest dimensions, such as event-like memories scoring high on `event`, art/object memories scoring high on `loc_obj/detail`, and transition-time memories scoring high on `time`. However, most random nodes are not sharply assigned to one dimension: top-1 scores are often only around 13%-17%.

This means node-level top-1 URB role should not be used as a hard label. A safer next step is to aggregate responses at the cell/cluster level and use response-preservation loss to guide budget allocation.

## Dimensions

| Short name | URB family |
|---|---|
| `profile` | `profile_identity` |
| `pref` | `preference_habit` |
| `goal` | `goal_plan` |
| `event` | `event_action` |
| `time` | `temporal_change` |
| `rel` | `relationship_role` |
| `loc_obj` | `location_object` |
| `task` | `commitment_task` |
| `need` | `constraint_need` |
| `detail` | `specific_exception` |

## Random Nodes

| # | idx | user | timestamp | memory text |
|---:|---:|---|---|---|
| 1 | 27 | Caroline_0 | 12:09 am on 13 September, 2023 | Caroline is thankful for the support of her friends, family, and mentors, which inspires her to continue making art |
| 2 | 41 | Melanie_0 | 3:19 pm on 28 August, 2023 | Caroline is organizing a talent show for the kids at the LGBTQ+ youth center in September 2023, looking forward to seeing everyone have fun. |
| 3 | 109 | Melanie_0 | 10:31 am on 13 October, 2023 | Caroline drew artwork inspired by the transgender poetry reading that stands for freedom and being real. |
| 4 | 118 | Melanie_0 | 1:14 pm on 25 May, 2023 | Melanie expressed confidence in Caroline, saying she has a caring heart and that the children will receive love and stability. |
| 5 | 161 | Melanie_0 | 7:55 pm on 9 June, 2023 | Caroline and Melanie met up around June 2-3, 2023, and Caroline shared a photo from their meetup. |
| 6 | 174 | Caroline_0 | 2:31 pm on 17 July, 2023 | Caroline finds her mentoring program going great, having met amazing young folks and supported them along the way. |
| 7 | 196 | Caroline_0 | 3:19 pm on 28 August, 2023 | Caroline is organizing a talent show for the kids at the youth center in September 2023 and looks forward to seeing them have fun. |
| 8 | 286 | Melanie_0 | 10:31 am on 13 October, 2023 | Melanie has been painting to keep busy while recovering from her injury in October 2023. |
| 9 | 356 | Melanie_0 | 3:31 pm on 23 August, 2023 | Melanie created a horse painting around late August 2023 and shared a photo of it. |
| 10 | 373 | Caroline_0 | 6:55 pm on 20 October, 2023 | Melanie's family enjoyed visiting the Grand Canyon during their roadtrip in October 2023. |
| 11 | 416 | Melanie_0 | 1:33 pm on 25 August, 2023 | Melanie finds the colors of Caroline's stained glass window incredible and the story it tells inspiring. |
| 12 | 432 | Caroline_0 | 1:51 pm on 15 July, 2023 | Caroline attended a council meeting for adoption on July 14, 2023, finding it inspiring and emotional. |
| 13 | 496 | Caroline_0 | 1:56 pm on 8 May, 2023 | Melanie goes swimming with her kids as a family activity around May 8, 2023. |
| 14 | 662 | Caroline_0 | 1:33 pm on 25 August, 2023 | Melanie praised Caroline's courage and maturity for apologizing after the hiking conflict. |
| 15 | 689 | Caroline_0 | 7:55 pm on 9 June, 2023 | Caroline started transitioning around 2020, approximately three years before June 2023. |

## Top-3 URB Dimensions

| # | idx | top1 | top2 | top3 |
|---:|---:|---|---|---|
| 1 | 27 | `rel` 15.9% | `need` 12.3% | `task` 11.6% |
| 2 | 41 | `task` 13.5% | `goal` 12.8% | `rel` 10.2% |
| 3 | 109 | `need` 15.1% | `time` 11.5% | `loc_obj` 10.8% |
| 4 | 118 | `need` 17.2% | `task` 12.9% | `pref` 12.0% |
| 5 | 161 | `rel` 15.0% | `task` 13.4% | `event` 12.8% |
| 6 | 174 | `rel` 15.4% | `event` 11.7% | `task` 11.0% |
| 7 | 196 | `goal` 16.7% | `task` 15.8% | `rel` 10.3% |
| 8 | 286 | `event` 16.5% | `task` 12.1% | `need` 10.8% |
| 9 | 356 | `event` 15.5% | `time` 13.0% | `detail` 11.7% |
| 10 | 373 | `event` 14.5% | `time` 12.1% | `task` 10.4% |
| 11 | 416 | `loc_obj` 17.8% | `detail` 15.6% | `time` 11.3% |
| 12 | 432 | `need` 13.4% | `event` 12.4% | `task` 12.0% |
| 13 | 496 | `event` 17.1% | `task` 12.6% | `need` 11.5% |
| 14 | 662 | `time` 15.0% | `event` 13.0% | `task` 11.9% |
| 15 | 689 | `time` 30.2% | `task` 10.3% | `profile` 10.1% |

## Full 10-Dimensional Response Distribution

Each row is normalized within the node and sums to approximately 100.

| # | idx | profile | pref | goal | event | time | rel | loc_obj | task | need | detail |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 27 | 10.2 | 7.7 | 11.4 | 6.5 | 7.6 | 15.9 | 9.5 | 11.6 | 12.3 | 7.3 |
| 2 | 41 | 10.2 | 9.1 | 12.8 | 9.1 | 7.8 | 10.2 | 9.1 | 13.5 | 9.4 | 8.7 |
| 3 | 109 | 9.5 | 7.0 | 10.1 | 10.3 | 11.5 | 7.2 | 10.8 | 8.3 | 15.1 | 10.2 |
| 4 | 118 | 11.2 | 12.0 | 8.8 | 5.2 | 8.5 | 6.9 | 8.4 | 12.9 | 17.2 | 9.0 |
| 5 | 161 | 9.5 | 5.5 | 8.1 | 12.8 | 11.1 | 15.0 | 9.4 | 13.4 | 6.5 | 8.7 |
| 6 | 174 | 9.9 | 5.8 | 10.5 | 11.7 | 10.6 | 15.4 | 8.9 | 11.0 | 8.3 | 7.8 |
| 7 | 196 | 7.9 | 9.2 | 16.7 | 9.1 | 6.8 | 10.3 | 8.4 | 15.8 | 8.4 | 7.3 |
| 8 | 286 | 8.7 | 4.7 | 10.1 | 16.5 | 10.0 | 8.4 | 8.6 | 12.1 | 10.8 | 10.2 |
| 9 | 356 | 8.2 | 6.3 | 10.2 | 15.5 | 13.0 | 6.9 | 9.8 | 11.4 | 6.8 | 11.7 |
| 10 | 373 | 7.8 | 8.2 | 9.1 | 14.5 | 12.1 | 9.0 | 8.5 | 10.4 | 10.3 | 10.3 |
| 11 | 416 | 7.5 | 6.7 | 8.5 | 8.9 | 11.3 | 7.4 | 17.8 | 9.1 | 7.2 | 15.6 |
| 12 | 432 | 9.1 | 8.6 | 8.3 | 12.4 | 8.1 | 9.8 | 9.0 | 12.0 | 13.4 | 9.3 |
| 13 | 496 | 6.9 | 7.0 | 8.0 | 17.1 | 8.2 | 9.1 | 9.8 | 12.6 | 11.5 | 9.9 |
| 14 | 662 | 8.8 | 6.8 | 7.0 | 13.0 | 15.0 | 6.1 | 11.4 | 11.9 | 9.0 | 10.9 |
| 15 | 689 | 10.1 | 5.3 | 5.5 | 9.9 | 30.2 | 5.7 | 6.2 | 10.3 | 8.5 | 8.2 |

## Interpretation

- The response vectors are not hard labels. Most random nodes have broad distributions, with top-1 values around 13%-17%.
- Some alignments are intuitive: family trips and activities lean toward `event`; art objects lean toward `loc_obj/detail`; the transition-year memory has a strong `time` response.
- This supports using URB responses as soft signals. It argues against routing cells by node-level top-1 role alone.
- The next method design should aggregate these signals at the cell level and allocate compression budget by estimated response-preservation loss rather than hand-written role rules.

## Provenance

This card summarizes a read-only inspection over cached URB response arrays:

```text
external/cache/visualizations/sample0/full_sample0_urb_response.npy
external/cache/visualizations/sample0/urb_centroids.npy
```

The raw Qdrant store and cache files are not committed.

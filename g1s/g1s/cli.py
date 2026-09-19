"""Command line entry point.

    python -m g1s run                          # the locked main line, all 10 samples
    python -m g1s run --keep 0.3 --samples 0,1
    python -m g1s run --until chaining         # stop before spending merge tokens
    python -m g1s run --matching greedy        # an ablation arm
    python -m g1s inspect --sample 0           # what a finished plan looks like
    python -m g1s compare --keep 0.3 0.5 0.7   # finished arms, side by side

Configuration (endpoints, paths, keys) comes from ``--config`` or the
environment; see :mod:`g1s.settings`.  No credential is ever read from this
package.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .pipeline import ALL_SAMPLES, STEPS, Layout, RunConfig, compare, run
from .plan import Plan, group_size_stats
from .settings import ConfigError, Settings
from .steps.s4_chaining import ChainingConfig


def parse_samples(text: str) -> tuple[int, ...]:
    """``"0-9"``, ``"0,3,5"`` or ``"0-4,7"``."""
    samples: list[int] = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part[1:]:
            start, _, end = part.partition("-")
            samples.extend(range(int(start), int(end) + 1))
        else:
            samples.append(int(part))
    if not samples:
        raise argparse.ArgumentTypeError(f"no samples in {text!r}")
    return tuple(dict.fromkeys(samples))


def config_of(args: argparse.Namespace) -> RunConfig:
    return RunConfig(
        keep_ratio=args.keep,
        samples=args.samples,
        grounding_tag=args.grounding_tag,
        grounding_dir=args.grounding_dir,
        chaining=ChainingConfig(
            window=args.window,
            topk=args.topk,
            affinity=args.affinity,
            gating=args.gating,
            matching=args.matching,
        ),
        merge_workers=args.merge_workers,
        judge_workers=args.judge_workers,
        top_k=args.top_k,
    )


def add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", type=Path, default=None, help="JSON config file")
    parser.add_argument("--keep", type=float, default=0.5, help="fraction of memories kept")
    parser.add_argument("--samples", type=parse_samples, default=ALL_SAMPLES)
    parser.add_argument("--grounding-tag", default="v2rm")
    parser.add_argument("--grounding-dir", type=Path, default=None,
                        help="reuse an existing grounding directory (skips steps 1-2)")
    parser.add_argument("--window", type=int, default=ChainingConfig.window)
    parser.add_argument("--topk", type=int, default=ChainingConfig.topk)
    # The three ablation switches. The main line is full/anchor/hungarian.
    parser.add_argument("--affinity", choices=("full", "no_entity", "no_semantic"), default="full")
    parser.add_argument("--gating", choices=("anchor", "none"), default="anchor")
    parser.add_argument("--matching", choices=("hungarian", "greedy"), default="hungarian")
    parser.add_argument("--merge-workers", type=int, default=8)
    parser.add_argument("--judge-workers", type=int, default=4)
    parser.add_argument("--top-k", type=int, default=30, help="retrieval depth at QA time")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="g1s", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)

    runner = commands.add_parser("run", help="run the pipeline for one arm")
    add_common(runner)
    runner.add_argument("--until", choices=STEPS, default="evaluate")

    inspector = commands.add_parser("inspect", help="summarise a finished plan")
    add_common(inspector)
    inspector.add_argument("--sample", type=int, required=True)

    comparer = commands.add_parser("compare", help="put finished arms side by side")
    add_common(comparer)
    comparer.add_argument("--keeps", type=float, nargs="+", default=[0.3, 0.5, 0.7],
                          help="one arm per keep ratio; the first is the reference")

    args = parser.parse_args(argv)
    try:
        settings = Settings.load(args.config)
    except ConfigError as exc:
        print(f"g1s: {exc}", file=sys.stderr)
        return 2

    if args.command == "run":
        summary = run(settings, config_of(args), until=args.until)
        print(json.dumps(summary.get("scores", summary["config"]), indent=2))
        return 0

    if args.command == "inspect":
        layout = Layout(settings, config_of(args))
        path = layout.plan(args.sample)
        if not path.exists():
            print(f"g1s: no plan at {path}", file=sys.stderr)
            return 1
        plan = Plan.read(path)
        print(
            json.dumps(
                {
                    "plan": str(path),
                    "sample_id": plan.sample_id,
                    "nodes_before": plan.num_nodes_before,
                    "units_after": plan.num_units_after,
                    "compression_ratio": plan.compression_ratio,
                    "merged": plan.merged,
                    "merge_api_calls": plan.api_calls(),
                    "group_sizes": group_size_stats(plan.groups),
                    "metadata": plan.metadata,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0

    # compare: same chaining variant, one arm per keep ratio
    base = config_of(args)
    arms = [
        RunConfig(
            keep_ratio=keep,
            samples=base.samples,
            grounding_tag=base.grounding_tag,
            grounding_dir=base.grounding_dir,
            chaining=base.chaining,
            top_k=base.top_k,
        )
        for keep in args.keeps
    ]
    print(json.dumps(compare(settings, arms), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

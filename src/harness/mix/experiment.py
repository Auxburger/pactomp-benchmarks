"""The mixed workload experiment: draw one schedule, replay it per arm.

Both arms share the same NUMA node and the same CPU set, and run one after the
other rather than side by side — the whole point is that a single arm's job mix
saturates the domain on its own, so there is no second domain to compare
against in the same instant. The seed is what makes the two arms comparable.
"""

from __future__ import annotations

import time

from .. import children
from ..coordinator import Coordinator, NoCoordinator
from ..cpu_layout import LayoutError, current_mask, pick_domain
from ..logging_utils import fmt_cpus, log
from . import schedule as schedule_mod
from .config import Config, make_config, parse_args
from .record import append_iterations, summarize_arm, write_manifest, write_summary
from .runner import STOP, run_arm


def build_schedule(cfg: Config, threads: int) -> schedule_mod.Schedule:
    if cfg.schedule_file:
        loaded = schedule_mod.load(cfg.schedule_file)
        log(f"schedule    : replayed from {cfg.schedule_file} (seed {loaded.seed})")
        return loaded
    return schedule_mod.generate(
        seed=cfg.seed,
        n_jobs=cfg.jobs,
        algorithms=cfg.algorithms,
        offset_range=cfg.offset_range,
        duration_range=cfg.duration_range,
        threads=threads,
    )


def describe(cfg: Config, sched: schedule_mod.Schedule, cpus: "list[int]", rm_cpu: int) -> None:
    log(f"output dir  : {cfg.out_dir}")
    log(f"workload    : {len(cpus)} CPUs ({fmt_cpus(cpus)}), coordinator on CPU {rm_cpu}")
    log(f"arms        : {', '.join(cfg.arms)}" + (f" × {cfg.repeats} repeats, alternating" if cfg.repeats > 1 else ""))
    log(f"seed        : {sched.seed}   jobs: {len(sched.jobs)}   span: {sched.span:.1f}s")
    for line in sched.table():
        log(f"  {line}")


def check_binaries(cfg: Config, sched: schedule_mod.Schedule) -> None:
    missing = sorted(
        {str(cfg.binary_for(job.algorithm)) for job in sched.jobs if not cfg.binary_for(job.algorithm).is_file()}
    )
    if missing:
        raise SystemExit(
            "NPB binaries not found: " + ", ".join(missing) + "\nBuild them with experiments/build_npb.sh"
        )


def arm_order(arms: "list[str]", repeat: int) -> "list[str]":
    """Alternate the arm order each repeat: drm,nodrm | nodrm,drm | drm,nodrm …

    The arms run one after the other, so anything that drifts over the job —
    a co-tenant arriving on the shared node, a thermal ramp — would otherwise
    land entirely on whichever arm goes second. Alternating cancels the linear
    part of that drift across repeats.
    """
    return list(arms) if repeat % 2 else list(reversed(arms))


def arm_dir_name(arm: str, repeat: int) -> str:
    """`drm/` for a single run, `drm_r2/` and up once --repeats is used."""
    return arm if repeat == 1 else f"{arm}_r{repeat}"


def run(cfg: Config, sched: schedule_mod.Schedule, cpus: "list[int]", rm_cpu: int) -> int:
    iterations_csv = cfg.out_dir / "iterations.csv"
    per_arm: "dict[str, list]" = {arm: [] for arm in cfg.arms}
    order_log = []
    first = True

    for repeat in range(1, cfg.repeats + 1):
        order = arm_order(cfg.arms, repeat)
        order_log.append({"repeat": repeat, "arms": order})
        if cfg.repeats > 1:
            log(f"=== repeat {repeat}/{cfg.repeats}: {' then '.join(order)} ===")

        for arm in order:
            if STOP.is_set():
                break
            if not first and cfg.settle_seconds > 0:
                log(f"settling {cfg.settle_seconds:.0f}s before arm {arm}")
                if STOP.wait(cfg.settle_seconds):
                    break
            first = False

            capacity = cfg.capacity or len(cpus)
            coordinator = (
                Coordinator(
                    cfg.drm_binary,
                    capacity,
                    cpus,
                    cfg.out_dir / "rm.log",
                    cfg.drm_socket,
                    pin_cpu=rm_cpu,
                )
                if arm == "drm"
                else NoCoordinator()
            )
            with coordinator:
                results = run_arm(
                    cfg, sched, arm, cpus, cfg.out_dir / arm_dir_name(arm, repeat), repeat
                )

            append_iterations(iterations_csv, results)
            per_arm[arm].extend(results)

    summaries = [summarize_arm(arm, per_arm[arm]) for arm in cfg.arms if per_arm[arm]]
    payload = write_summary(cfg.out_dir / "summary.json", sched, summaries, order_log)
    for arm_summary in payload["arms"]:
        log(
            f"arm {arm_summary['arm']}: {arm_summary['iterations']} iterations "
            f"over {arm_summary['repeats']} repeat(s), "
            f"mean {arm_summary['mean_time_seconds']}s, "
            f"mean threads {arm_summary['mean_total_threads']}, "
            f"makespan {arm_summary['makespan_seconds']}s"
        )
    if payload["comparison"]:
        c = payload["comparison"]
        log(
            f"DRM vs none: {c['iterations_gain_pct']:+.2f}% iterations completed"
            + (f", {c.get('mean_time_speedup')}× per iteration" if c.get("mean_time_speedup") else "")
        )
    log(f"done — results in {cfg.out_dir}")
    return 0


def main(argv: "list[str] | None" = None) -> int:
    args = parse_args(argv)
    cfg = make_config(args)

    try:
        domain = pick_domain(current_mask(), cfg.domain_cpus, strict=cfg.strict_domain)
    except LayoutError as exc:
        raise SystemExit(f"CPU layout: {exc}")

    if len(domain.cpus) < cfg.domain_cpus:
        # cm4_tiny shares a node between jobs, so the allocation can straddle
        # both sockets and leave no node big enough for the full request.
        log(
            f"WARNING: node {domain.node} offers only {len(domain.cpus)} cores beside the "
            f"coordinator, not the {cfg.domain_cpus} requested — the domain shrinks to fit. "
            f"Both arms use it, so they stay comparable; --strict-domain aborts instead."
        )

    sched = build_schedule(cfg, cfg.threads or len(domain.cpus))
    describe(cfg, sched, domain.cpus, domain.rm_cpu)

    if "drm" in cfg.arms and not cfg.drm_binary.is_file():
        raise SystemExit(
            f"DRM binary not found: {cfg.drm_binary} (pass --arms nodrm to run the baseline only)"
        )
    check_binaries(cfg, sched)

    if args.dry_run:
        log(
            f"dry run: {cfg.repeats} repeat(s) × {len(cfg.arms)} arms × {len(sched.jobs)} jobs, "
            f"~{sched.span:.0f}s per arm"
        )
        return 0

    children.install_signal_handlers(log, on_signal=STOP.set)
    cfg.out_dir.mkdir(parents=True, exist_ok=True)
    sched.save(cfg.out_dir / "schedule.json")
    write_manifest(cfg, cfg.out_dir / "manifest.json", sched, domain.cpus, domain.rm_cpu)

    started = time.monotonic()
    status = run(cfg, sched, domain.cpus, domain.rm_cpu)
    log(f"total wall time: {(time.monotonic() - started) / 60:.1f} min")
    return status

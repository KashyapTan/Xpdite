#!/usr/bin/env python
"""
Benchmark script for websearch read_website tool.

Measures timing, success rates, and content length across all tiers
for a diverse set of URLs. Results are saved to JSON and a markdown report.

Usage:
    uv run scripts/benchmark_websearch.py [--concurrency N] [--timeout N] [--output-dir DIR]

Example:
    uv run scripts/benchmark_websearch.py --concurrency 10 --timeout 20
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any

# Add project root to path for imports
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Suppress noisy library output
_DEVNULL = open(os.devnull, "w")


@dataclass
class TierResult:
    """Result from a single tier attempt."""

    tier: str
    success: bool
    content_length: int
    elapsed_seconds: float
    error: str | None = None
    content_preview: str = ""  # First 200 chars for debugging


@dataclass
class URLBenchmarkResult:
    """Complete benchmark result for a single URL."""

    url: str
    category: str
    timestamp: str
    tier_results: dict[str, TierResult] = field(default_factory=dict)
    best_tier: str | None = None
    best_content_length: int = 0
    total_elapsed_seconds: float = 0.0


@dataclass
class BenchmarkStats:
    """Aggregated statistics for a tier or mode."""

    total_urls: int = 0
    successful: int = 0
    failed: int = 0
    timeouts: int = 0

    latencies: list[float] = field(default_factory=list)
    content_lengths: list[int] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        return self.successful / max(self.total_urls, 1) * 100

    @property
    def p50_latency(self) -> float:
        return statistics.median(self.latencies) if self.latencies else 0.0

    @property
    def p90_latency(self) -> float:
        if not self.latencies:
            return 0.0
        sorted_latencies = sorted(self.latencies)
        idx = int(len(sorted_latencies) * 0.90)
        return sorted_latencies[min(idx, len(sorted_latencies) - 1)]

    @property
    def p95_latency(self) -> float:
        if not self.latencies:
            return 0.0
        sorted_latencies = sorted(self.latencies)
        idx = int(len(sorted_latencies) * 0.95)
        return sorted_latencies[min(idx, len(sorted_latencies) - 1)]

    @property
    def p99_latency(self) -> float:
        if not self.latencies:
            return 0.0
        sorted_latencies = sorted(self.latencies)
        idx = int(len(sorted_latencies) * 0.99)
        return sorted_latencies[min(idx, len(sorted_latencies) - 1)]

    @property
    def avg_content_length(self) -> float:
        return statistics.mean(self.content_lengths) if self.content_lengths else 0.0

    @property
    def median_content_length(self) -> float:
        return statistics.median(self.content_lengths) if self.content_lengths else 0.0


class WebsearchBenchmark:
    """Benchmark runner for websearch tiers."""

    def __init__(
        self,
        urls_file: Path,
        concurrency: int = 10,
        tier_timeout: float = 15.0,
        output_dir: Path | None = None,
        enable_browser_tiers: bool = False,
    ):
        self.urls_file = urls_file
        self.concurrency = concurrency
        self.tier_timeout = tier_timeout
        self.output_dir = output_dir or PROJECT_ROOT / "scripts" / "benchmark_results"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.enable_browser_tiers = enable_browser_tiers

        self.results: list[URLBenchmarkResult] = []
        self.tier_stats: dict[str, dict[str, BenchmarkStats]] = {
            "precision": {},
            "full": {},
        }

        # Initialize stats for each tier
        for mode in self.tier_stats:
            self.tier_stats[mode] = {
                "tier1_curl": BenchmarkStats(),
                "tier2_camoufox": BenchmarkStats(),
                "tier3_nodriver": BenchmarkStats(),
                "concurrent_all": BenchmarkStats(),
            }

        # Semaphore for limiting concurrent URL tests
        self._url_semaphore: asyncio.Semaphore | None = None

        # Import websearch functions
        self._import_websearch()

    def _import_websearch(self):
        """Import websearch functions for benchmarking."""
        from mcp_servers.servers.websearch import server as ws

        self.ws = ws

        # Enable tier 3 for benchmarking
        os.environ[ws._UNSAFE_TIER3_ENV] = "1"

    def load_urls(self) -> dict[str, list[str]]:
        """Load URLs from JSON file."""
        with open(self.urls_file) as f:
            data = json.load(f)
        return data["urls"]

    async def _run_tier_with_timeout(
        self,
        tier_fn,
        url: str,
        mode: str,
        tier_name: str,
    ) -> TierResult:
        """Run a single tier function with timeout."""
        start = time.perf_counter()

        try:
            async with asyncio.timeout(self.tier_timeout):
                with redirect_stdout(_DEVNULL), redirect_stderr(_DEVNULL):
                    result = await tier_fn(url, mode)

            elapsed = time.perf_counter() - start

            if result is None:
                return TierResult(
                    tier=tier_name,
                    success=False,
                    content_length=0,
                    elapsed_seconds=elapsed,
                    error="No content returned",
                )

            # Handle tuple return (text, raw_html) from tier1_curl
            content = result[0] if isinstance(result, tuple) else result
            content_length = len(content) if content else 0

            return TierResult(
                tier=tier_name,
                success=content_length > 0,
                content_length=content_length,
                elapsed_seconds=elapsed,
                content_preview=content[:200] if content else "",
            )

        except asyncio.TimeoutError:
            elapsed = time.perf_counter() - start
            return TierResult(
                tier=tier_name,
                success=False,
                content_length=0,
                elapsed_seconds=elapsed,
                error=f"Timeout after {self.tier_timeout}s",
            )
        except Exception as e:
            elapsed = time.perf_counter() - start
            return TierResult(
                tier=tier_name,
                success=False,
                content_length=0,
                elapsed_seconds=elapsed,
                error=str(e)[:200],
            )

    async def benchmark_url(
        self,
        url: str,
        category: str,
        mode: str,
    ) -> URLBenchmarkResult:
        """Benchmark a single URL against all tiers concurrently."""
        result = URLBenchmarkResult(
            url=url,
            category=category,
            timestamp=datetime.now().isoformat(),
        )

        start_total = time.perf_counter()

        # Run all tiers concurrently
        # Note: tier2 (camoufox) and tier3 (nodriver) require browser dependencies
        tier_tasks = [
            self._run_tier_with_timeout(self.ws.tier1_curl, url, mode, "tier1_curl"),
        ]

        # Only add browser tiers if enabled
        if self.enable_browser_tiers:
            tier_tasks.extend(
                [
                    self._run_tier_with_timeout(
                        self.ws.tier2_camoufox, url, mode, "tier2_camoufox"
                    ),
                    self._run_tier_with_timeout(
                        self.ws.tier3_nodriver, url, mode, "tier3_nodriver"
                    ),
                ]
            )

        tier_results = await asyncio.gather(*tier_tasks, return_exceptions=True)

        result.total_elapsed_seconds = time.perf_counter() - start_total

        # Process results
        best_length = 0
        best_tier = None

        for tier_result in tier_results:
            if isinstance(tier_result, (Exception, BaseException)):
                continue

            # Type guard: tier_result is now TierResult
            tr: TierResult = tier_result

            result.tier_results[tr.tier] = tr

            # Update stats
            stats = self.tier_stats[mode][tr.tier]
            stats.total_urls += 1

            if tr.success and tr.content_length > 0:
                stats.successful += 1
                stats.latencies.append(tr.elapsed_seconds)
                stats.content_lengths.append(tr.content_length)

                if tr.content_length > best_length:
                    best_length = tr.content_length
                    best_tier = tr.tier
            else:
                stats.failed += 1
                if tr.error and "Timeout" in tr.error:
                    stats.timeouts += 1

        result.best_tier = best_tier
        result.best_content_length = best_length

        # Update concurrent stats
        concurrent_stats = self.tier_stats[mode]["concurrent_all"]
        concurrent_stats.total_urls += 1
        if best_tier:
            concurrent_stats.successful += 1
            concurrent_stats.latencies.append(result.total_elapsed_seconds)
            concurrent_stats.content_lengths.append(best_length)
        else:
            concurrent_stats.failed += 1

        return result

    async def benchmark_url_with_semaphore(
        self,
        url: str,
        category: str,
        mode: str,
        progress_counter: dict,
    ) -> URLBenchmarkResult:
        """Wrapper that respects concurrency limit."""
        if self._url_semaphore is None:
            self._url_semaphore = asyncio.Semaphore(self.concurrency)
        async with self._url_semaphore:
            result = await self.benchmark_url(url, category, mode)
            progress_counter["done"] += 1
            total = progress_counter["total"]
            done = progress_counter["done"]
            print(f"  [{done}/{total}] {url[:60]}... ({result.best_tier or 'FAILED'})")
            return result

    async def run_benchmark(self, mode: str = "full") -> list[URLBenchmarkResult]:
        """Run benchmark for all URLs with specified mode."""
        urls_by_category = self.load_urls()

        # Flatten URLs with category info
        all_urls: list[tuple[str, str]] = []
        for category, urls in urls_by_category.items():
            for url in urls:
                all_urls.append((url, category))

        print(f"\n{'=' * 60}")
        print(f"Running benchmark: mode={mode}, concurrency={self.concurrency}")
        print(f"Total URLs: {len(all_urls)}")
        print(f"Tier timeout: {self.tier_timeout}s")
        print(f"{'=' * 60}\n")

        self._url_semaphore = asyncio.Semaphore(self.concurrency)

        progress = {"done": 0, "total": len(all_urls)}

        tasks = [
            self.benchmark_url_with_semaphore(url, category, mode, progress)
            for url, category in all_urls
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Filter out exceptions
        valid_results = [r for r in results if isinstance(r, URLBenchmarkResult)]
        self.results.extend(valid_results)

        return valid_results

    def generate_report(self) -> str:
        """Generate markdown report from benchmark results."""
        lines = [
            "# Websearch Benchmark Report",
            "",
            f"**Generated:** {datetime.now().isoformat()}",
            f"**Total URLs tested:** {len(self.results)}",
            f"**Concurrency:** {self.concurrency}",
            f"**Tier timeout:** {self.tier_timeout}s",
            "",
        ]

        for mode in ["precision", "full"]:
            lines.append(f"## Mode: {mode.upper()}")
            lines.append("")

            for tier_name, stats in self.tier_stats[mode].items():
                if stats.total_urls == 0:
                    continue

                lines.append(f"### {tier_name}")
                lines.append("")
                lines.append("| Metric | Value |")
                lines.append("|--------|-------|")
                lines.append(f"| Total URLs | {stats.total_urls} |")
                lines.append(
                    f"| Successful | {stats.successful} ({stats.success_rate:.1f}%) |"
                )
                lines.append(f"| Failed | {stats.failed} |")
                lines.append(f"| Timeouts | {stats.timeouts} |")
                lines.append(f"| P50 Latency | {stats.p50_latency:.2f}s |")
                lines.append(f"| P90 Latency | {stats.p90_latency:.2f}s |")
                lines.append(f"| P95 Latency | {stats.p95_latency:.2f}s |")
                lines.append(f"| P99 Latency | {stats.p99_latency:.2f}s |")
                lines.append(
                    f"| Avg Content Length | {stats.avg_content_length:,.0f} chars |"
                )
                lines.append(
                    f"| Median Content Length | {stats.median_content_length:,.0f} chars |"
                )
                lines.append("")

            # Content length distribution
            lines.append("### Content Length Distribution (Successful Extractions)")
            lines.append("")

            all_lengths = []
            for tier_name, stats in self.tier_stats[mode].items():
                all_lengths.extend(stats.content_lengths)

            if all_lengths:
                buckets = {
                    "< 100 chars (sparse/failed)": 0,
                    "100-300 chars (minimal)": 0,
                    "300-1000 chars (short)": 0,
                    "1000-3000 chars (acceptable)": 0,
                    "3000-10000 chars (good)": 0,
                    "> 10000 chars (excellent)": 0,
                }

                for length in all_lengths:
                    if length < 100:
                        buckets["< 100 chars (sparse/failed)"] += 1
                    elif length < 300:
                        buckets["100-300 chars (minimal)"] += 1
                    elif length < 1000:
                        buckets["300-1000 chars (short)"] += 1
                    elif length < 3000:
                        buckets["1000-3000 chars (acceptable)"] += 1
                    elif length < 10000:
                        buckets["3000-10000 chars (good)"] += 1
                    else:
                        buckets["> 10000 chars (excellent)"] += 1

                lines.append("| Bucket | Count |")
                lines.append("|--------|-------|")
                for bucket, count in buckets.items():
                    lines.append(f"| {bucket} | {count} |")
                lines.append("")

        # Category breakdown
        lines.append("## Results by Category")
        lines.append("")

        category_stats: dict[str, dict[str, Any]] = {}
        for result in self.results:
            cat = result.category
            if cat not in category_stats:
                category_stats[cat] = {
                    "total": 0,
                    "successful": 0,
                    "best_lengths": [],
                }
            category_stats[cat]["total"] += 1
            if result.best_tier:
                category_stats[cat]["successful"] += 1
                category_stats[cat]["best_lengths"].append(result.best_content_length)

        lines.append("| Category | Total | Successful | Success Rate | Avg Content |")
        lines.append("|----------|-------|------------|--------------|-------------|")
        for cat, stats in sorted(category_stats.items()):
            success_rate = stats["successful"] / max(stats["total"], 1) * 100
            avg_content = (
                statistics.mean(stats["best_lengths"]) if stats["best_lengths"] else 0
            )
            lines.append(
                f"| {cat} | {stats['total']} | {stats['successful']} | "
                f"{success_rate:.1f}% | {avg_content:,.0f} |"
            )
        lines.append("")

        # Recommendations
        lines.append("## Recommendations")
        lines.append("")

        # Calculate recommended thresholds
        all_successful_lengths = []
        for mode in ["precision", "full"]:
            for stats in self.tier_stats[mode].values():
                all_successful_lengths.extend(stats.content_lengths)

        if all_successful_lengths:
            p10_content = sorted(all_successful_lengths)[
                int(len(all_successful_lengths) * 0.10)
            ]
            p25_content = sorted(all_successful_lengths)[
                int(len(all_successful_lengths) * 0.25)
            ]
            lines.append(
                f"- **Sparse content threshold:** {p10_content} chars (P10 of successful extractions)"
            )
            lines.append(
                f"- **Success threshold:** {p25_content} chars (P25 of successful extractions)"
            )

        # Timeout recommendations
        all_latencies = []
        for mode in ["precision", "full"]:
            for stats in self.tier_stats[mode].values():
                all_latencies.extend(stats.latencies)

        if all_latencies:
            p95_latency = sorted(all_latencies)[int(len(all_latencies) * 0.95)]
            p99_latency = sorted(all_latencies)[int(len(all_latencies) * 0.99)]
            lines.append(
                f"- **Recommended tier timeout:** {p95_latency:.1f}s (P95 latency)"
            )
            lines.append(
                f"- **Maximum tier timeout:** {p99_latency:.1f}s (P99 latency)"
            )

        lines.append("")

        return "\n".join(lines)

    def save_results(self):
        """Save results to JSON and markdown files."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Save raw results as JSON
        results_file = self.output_dir / f"benchmark_results_{timestamp}.json"
        results_data = {
            "metadata": {
                "timestamp": timestamp,
                "concurrency": self.concurrency,
                "tier_timeout": self.tier_timeout,
                "total_urls": len(self.results),
            },
            "results": [
                {
                    "url": r.url,
                    "category": r.category,
                    "best_tier": r.best_tier,
                    "best_content_length": r.best_content_length,
                    "total_elapsed_seconds": r.total_elapsed_seconds,
                    "tier_results": {k: asdict(v) for k, v in r.tier_results.items()},
                }
                for r in self.results
            ],
            "tier_stats": {
                mode: {
                    tier: {
                        "total_urls": s.total_urls,
                        "successful": s.successful,
                        "failed": s.failed,
                        "timeouts": s.timeouts,
                        "success_rate": s.success_rate,
                        "p50_latency": s.p50_latency,
                        "p90_latency": s.p90_latency,
                        "p95_latency": s.p95_latency,
                        "p99_latency": s.p99_latency,
                        "avg_content_length": s.avg_content_length,
                        "median_content_length": s.median_content_length,
                    }
                    for tier, s in tiers.items()
                }
                for mode, tiers in self.tier_stats.items()
            },
        }

        with open(results_file, "w") as f:
            json.dump(results_data, f, indent=2)
        print(f"\nResults saved to: {results_file}")

        # Save markdown report
        report_file = self.output_dir / f"benchmark_report_{timestamp}.md"
        report = self.generate_report()
        with open(report_file, "w") as f:
            f.write(report)
        print(f"Report saved to: {report_file}")

        # Also save latest versions
        latest_results = self.output_dir / "benchmark_results_latest.json"
        latest_report = self.output_dir / "benchmark_report_latest.md"

        with open(latest_results, "w") as f:
            json.dump(results_data, f, indent=2)
        with open(latest_report, "w") as f:
            f.write(report)


async def main():
    parser = argparse.ArgumentParser(
        description="Benchmark websearch read_website tool"
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=10,
        help="Number of URLs to test concurrently (default: 10)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=15.0,
        help="Timeout per tier in seconds (default: 15.0)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Output directory for results (default: scripts/benchmark_results)",
    )
    parser.add_argument(
        "--mode",
        choices=["precision", "full", "both"],
        default="both",
        help="Extraction mode to benchmark (default: both)",
    )
    parser.add_argument(
        "--urls-file",
        type=Path,
        default=PROJECT_ROOT / "scripts" / "benchmark_urls.json",
        help="Path to URLs JSON file",
    )
    parser.add_argument(
        "--enable-browser-tiers",
        action="store_true",
        help="Enable tier2 (camoufox) and tier3 (nodriver) browser tiers (slower, requires browser deps)",
    )

    args = parser.parse_args()

    benchmark = WebsearchBenchmark(
        urls_file=args.urls_file,
        concurrency=args.concurrency,
        tier_timeout=args.timeout,
        output_dir=args.output_dir,
        enable_browser_tiers=args.enable_browser_tiers,
    )

    modes = ["precision", "full"] if args.mode == "both" else [args.mode]

    for mode in modes:
        print(f"\n{'#' * 60}")
        print(f"# Benchmarking mode: {mode.upper()}")
        print(f"{'#' * 60}")
        await benchmark.run_benchmark(mode)

    benchmark.save_results()

    # Print summary
    print("\n" + "=" * 60)
    print("BENCHMARK COMPLETE")
    print("=" * 60)
    print(benchmark.generate_report())


if __name__ == "__main__":
    asyncio.run(main())

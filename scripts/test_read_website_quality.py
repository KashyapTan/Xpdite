#!/usr/bin/env python
"""
Quality test script for the improved read_website MCP tool.

Tests the actual read_website tool (not internal functions) against benchmark URLs,
measures speed, evaluates error handling quality, and generates a detailed report.

Usage:
    uv run scripts/test_read_website_quality.py [--limit N] [--concurrency N]

Example:
    uv run scripts/test_read_website_quality.py --limit 50 --concurrency 5
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

# Add project root to path for imports
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


@dataclass
class QualityMetrics:
    """Metrics for evaluating response quality."""

    # Timing
    elapsed_seconds: float = 0.0

    # Success indicators
    success: bool = False
    content_length: int = 0

    # Error handling quality (0-5 scale)
    has_clear_error_message: bool = False
    has_actionable_suggestion: bool = False
    has_context_about_failure: bool = False
    detected_access_restriction: bool = False
    detected_sparse_content: bool = False

    # Content quality
    has_metadata_header: bool = False
    has_warnings_section: bool = False
    has_suggestions_section: bool = False

    # Raw data
    raw_response: str = ""
    error_message: str = ""


@dataclass
class TestResult:
    """Complete test result for a single URL."""

    url: str
    category: str
    timestamp: str
    metrics: QualityMetrics
    quality_score: float = 0.0  # 0-100 scale


class ReadWebsiteQualityTester:
    """Tests the read_website tool and evaluates response quality."""

    def __init__(
        self,
        urls_file: Path,
        output_dir: Path,
        concurrency: int = 5,
        limit: int | None = None,
    ):
        self.urls_file = urls_file
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.concurrency = concurrency
        self.limit = limit

        self.results: list[TestResult] = []
        self._semaphore: asyncio.Semaphore | None = None

        # Import the read_website tool
        self._import_tool()

    def _import_tool(self):
        """Import the read_website tool function."""
        from mcp_servers.servers.websearch import server as ws

        self.read_website = ws.read_website
        # Enable tier 3 for comprehensive testing
        os.environ[ws._UNSAFE_TIER3_ENV] = "1"

    def load_urls(self) -> list[tuple[str, str]]:
        """Load URLs from JSON file, returning (url, category) tuples."""
        with open(self.urls_file) as f:
            data = json.load(f)

        all_urls = []
        for category, urls in data["urls"].items():
            for url in urls:
                all_urls.append((url, category))

        if self.limit:
            all_urls = all_urls[: self.limit]

        return all_urls

    def _evaluate_response_quality(
        self, response: str, elapsed: float
    ) -> QualityMetrics:
        """Evaluate the quality of a read_website response."""
        metrics = QualityMetrics(
            elapsed_seconds=elapsed,
            raw_response=response[:5000] if response else "",  # Truncate for storage
        )

        if not response:
            metrics.error_message = "Empty response"
            return metrics

        response_lower = response.lower()

        # Check for metadata header
        metrics.has_metadata_header = (
            "---" in response[:500] or "url:" in response_lower[:500]
        )

        # Check for warnings section
        metrics.has_warnings_section = "warning" in response_lower[:1000]

        # Check for suggestions section
        metrics.has_suggestions_section = (
            "suggestion" in response_lower[:1500]
            or "try " in response_lower[:1500]
            or "consider " in response_lower[:1500]
        )

        # Check for access restriction detection
        access_signals = [
            "login required",
            "paywall",
            "access restricted",
            "authentication required",
            "sign in",
            "captcha",
            "subscription required",
        ]
        metrics.detected_access_restriction = any(
            s in response_lower for s in access_signals
        )

        # Check for sparse content detection
        metrics.detected_sparse_content = (
            "sparse" in response_lower[:1000]
            or "minimal content" in response_lower[:1000]
        )

        # Determine success
        # Success = has substantial content (not just error messages)
        # Look for actual content after metadata section
        content_start = response.find("\n\n", 200)  # Skip metadata
        if content_start > 0:
            actual_content = response[content_start:]
            metrics.content_length = len(actual_content)
            metrics.success = len(actual_content) > 500
        else:
            metrics.content_length = len(response)
            metrics.success = len(response) > 1000

        # Check error handling quality
        error_indicators = [
            "failed",
            "error",
            "could not",
            "unable to",
            "timed out",
            "no content",
        ]

        is_error_response = any(ind in response_lower[:500] for ind in error_indicators)

        if is_error_response or not metrics.success:
            # For error responses, check quality of error handling
            metrics.has_clear_error_message = any(
                phrase in response_lower
                for phrase in [
                    "failed to",
                    "could not",
                    "unable to",
                    "error:",
                    "timed out",
                    "all tiers failed",
                ]
            )

            metrics.has_actionable_suggestion = any(
                phrase in response_lower
                for phrase in [
                    "try ",
                    "consider ",
                    "suggestion:",
                    "you can ",
                    "alternatively",
                    "check ",
                    "verify ",
                ]
            )

            metrics.has_context_about_failure = any(
                phrase in response_lower
                for phrase in [
                    "tier",
                    "timeout",
                    "blocked",
                    "restricted",
                    "javascript",
                    "dynamic content",
                ]
            )

        return metrics

    def _calculate_quality_score(self, metrics: QualityMetrics) -> float:
        """Calculate overall quality score (0-100) based on metrics."""
        score = 0.0

        if metrics.success:
            # Successful scrape - base score
            score += 50

            # Content length bonus (up to 20 points)
            if metrics.content_length > 10000:
                score += 20
            elif metrics.content_length > 5000:
                score += 15
            elif metrics.content_length > 2000:
                score += 10
            elif metrics.content_length > 500:
                score += 5

            # Speed bonus (up to 15 points)
            if metrics.elapsed_seconds < 1.0:
                score += 15
            elif metrics.elapsed_seconds < 2.0:
                score += 12
            elif metrics.elapsed_seconds < 5.0:
                score += 8
            elif metrics.elapsed_seconds < 10.0:
                score += 4

            # Metadata quality (up to 15 points)
            if metrics.has_metadata_header:
                score += 5
            if metrics.has_warnings_section and metrics.detected_sparse_content:
                score += 5  # Correctly warned about sparse content
            if metrics.detected_access_restriction:
                score += 5  # Correctly detected access restriction

        else:
            # Failed scrape - evaluate error handling quality
            # Base score for attempting (5 points)
            score += 5

            # Clear error message (up to 25 points)
            if metrics.has_clear_error_message:
                score += 25

            # Actionable suggestion (up to 25 points)
            if metrics.has_actionable_suggestion:
                score += 25

            # Context about failure (up to 20 points)
            if metrics.has_context_about_failure:
                score += 20

            # Access restriction detection (up to 15 points)
            if metrics.detected_access_restriction:
                score += 15

            # Speed consideration - even failures should be fast (up to 10 points)
            if metrics.elapsed_seconds < 5.0:
                score += 10
            elif metrics.elapsed_seconds < 10.0:
                score += 5

        return min(100, score)

    async def test_url(self, url: str, category: str, progress: dict) -> TestResult:
        """Test a single URL and evaluate response quality."""
        timestamp = datetime.now().isoformat()

        start = time.perf_counter()
        try:
            # Call the actual read_website tool
            response = await self.read_website(url=url, mode="full")
            elapsed = time.perf_counter() - start
        except Exception as e:
            elapsed = time.perf_counter() - start
            response = f"Exception: {type(e).__name__}: {str(e)}"

        # Evaluate response quality
        metrics = self._evaluate_response_quality(response, elapsed)

        # Calculate quality score
        quality_score = self._calculate_quality_score(metrics)

        result = TestResult(
            url=url,
            category=category,
            timestamp=timestamp,
            metrics=metrics,
            quality_score=quality_score,
        )

        # Update progress
        progress["done"] += 1
        status = "OK" if metrics.success else "FAIL"
        print(
            f"  [{progress['done']}/{progress['total']}] {status} {url[:50]}... "
            f"({elapsed:.2f}s, score={quality_score:.0f})"
        )

        return result

    async def test_url_with_semaphore(
        self, url: str, category: str, progress: dict
    ) -> TestResult:
        """Wrapper that respects concurrency limit."""
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self.concurrency)

        async with self._semaphore:
            return await self.test_url(url, category, progress)

    async def run_tests(self) -> list[TestResult]:
        """Run tests for all URLs."""
        urls = self.load_urls()

        print(f"\n{'=' * 70}")
        print("Testing read_website tool quality")
        print(f"Total URLs: {len(urls)}")
        print(f"Concurrency: {self.concurrency}")
        print(f"{'=' * 70}\n")

        self._semaphore = asyncio.Semaphore(self.concurrency)
        progress = {"done": 0, "total": len(urls)}

        # Run tests sequentially in batches to avoid asyncio issues
        batch_size = self.concurrency
        valid_results = []

        for i in range(0, len(urls), batch_size):
            batch = urls[i : i + batch_size]
            tasks = [
                self.test_url_with_semaphore(url, category, progress)
                for url, category in batch
            ]

            batch_results = await asyncio.gather(*tasks, return_exceptions=True)

            for j, r in enumerate(batch_results):
                if isinstance(r, TestResult):
                    valid_results.append(r)
                elif isinstance(r, Exception):
                    # Create a failed result for the exception
                    url, category = batch[j]
                    metrics = QualityMetrics(
                        elapsed_seconds=0,
                        success=False,
                        error_message=f"{type(r).__name__}: {str(r)}",
                        raw_response=f"Exception: {type(r).__name__}: {str(r)}",
                    )
                    valid_results.append(
                        TestResult(
                            url=url,
                            category=category,
                            timestamp=datetime.now().isoformat(),
                            metrics=metrics,
                            quality_score=0,
                        )
                    )
                    print(f"  [ERROR] {url[:40]}... failed: {type(r).__name__}")

        self.results = valid_results
        return valid_results

        return valid_results

    def generate_report(self) -> str:
        """Generate markdown report from test results."""
        lines = [
            "# read_website Quality Test Report",
            "",
            f"**Generated:** {datetime.now().isoformat()}",
            f"**Total URLs tested:** {len(self.results)}",
            f"**Concurrency:** {self.concurrency}",
            "",
        ]

        # Overall statistics
        successful = [r for r in self.results if r.metrics.success]
        failed = [r for r in self.results if not r.metrics.success]

        avg_score = sum(r.quality_score for r in self.results) / max(
            len(self.results), 1
        )
        avg_time = sum(r.metrics.elapsed_seconds for r in self.results) / max(
            len(self.results), 1
        )

        lines.extend(
            [
                "## Overall Statistics",
                "",
                "| Metric | Value |",
                "|--------|-------|",
                f"| Success Rate | {len(successful)}/{len(self.results)} ({len(successful) / max(len(self.results), 1) * 100:.1f}%) |",
                f"| Average Quality Score | {avg_score:.1f}/100 |",
                f"| Average Response Time | {avg_time:.2f}s |",
                "",
            ]
        )

        # Success metrics
        if successful:
            avg_success_time = sum(r.metrics.elapsed_seconds for r in successful) / len(
                successful
            )
            avg_content_len = sum(r.metrics.content_length for r in successful) / len(
                successful
            )
            lines.extend(
                [
                    "### Successful Scrapes",
                    "",
                    "| Metric | Value |",
                    "|--------|-------|",
                    f"| Count | {len(successful)} |",
                    f"| Average Time | {avg_success_time:.2f}s |",
                    f"| Average Content Length | {avg_content_len:,.0f} chars |",
                    f"| With Access Restriction Warning | {sum(1 for r in successful if r.metrics.detected_access_restriction)} |",
                    f"| With Sparse Content Warning | {sum(1 for r in successful if r.metrics.detected_sparse_content)} |",
                    "",
                ]
            )

        # Failure metrics (error handling quality)
        if failed:
            lines.extend(
                [
                    "### Failed Scrapes - Error Handling Quality",
                    "",
                    "| Metric | Value |",
                    "|--------|-------|",
                    f"| Count | {len(failed)} |",
                    f"| With Clear Error Message | {sum(1 for r in failed if r.metrics.has_clear_error_message)} ({sum(1 for r in failed if r.metrics.has_clear_error_message) / len(failed) * 100:.0f}%) |",
                    f"| With Actionable Suggestion | {sum(1 for r in failed if r.metrics.has_actionable_suggestion)} ({sum(1 for r in failed if r.metrics.has_actionable_suggestion) / len(failed) * 100:.0f}%) |",
                    f"| With Context About Failure | {sum(1 for r in failed if r.metrics.has_context_about_failure)} ({sum(1 for r in failed if r.metrics.has_context_about_failure) / len(failed) * 100:.0f}%) |",
                    f"| Detected Access Restriction | {sum(1 for r in failed if r.metrics.detected_access_restriction)} |",
                    "",
                ]
            )

        # Category breakdown
        lines.extend(["## Results by Category", ""])

        category_stats: dict[str, dict[str, Any]] = {}
        for result in self.results:
            cat = result.category
            if cat not in category_stats:
                category_stats[cat] = {
                    "total": 0,
                    "successful": 0,
                    "scores": [],
                    "times": [],
                }
            category_stats[cat]["total"] += 1
            if result.metrics.success:
                category_stats[cat]["successful"] += 1
            category_stats[cat]["scores"].append(result.quality_score)
            category_stats[cat]["times"].append(result.metrics.elapsed_seconds)

        lines.append("| Category | Total | Success Rate | Avg Score | Avg Time |")
        lines.append("|----------|-------|--------------|-----------|----------|")
        for cat, stats in sorted(category_stats.items()):
            success_rate = stats["successful"] / max(stats["total"], 1) * 100
            avg_score = sum(stats["scores"]) / max(len(stats["scores"]), 1)
            avg_time = sum(stats["times"]) / max(len(stats["times"]), 1)
            lines.append(
                f"| {cat} | {stats['total']} | {success_rate:.0f}% | {avg_score:.0f} | {avg_time:.2f}s |"
            )
        lines.append("")

        # Speed distribution
        lines.extend(
            [
                "## Speed Distribution",
                "",
                "| Bucket | Count | Percentage |",
                "|--------|-------|------------|",
            ]
        )

        time_buckets = {
            "< 1s (excellent)": 0,
            "1-2s (good)": 0,
            "2-5s (acceptable)": 0,
            "5-10s (slow)": 0,
            "> 10s (very slow)": 0,
        }

        for result in self.results:
            t = result.metrics.elapsed_seconds
            if t < 1:
                time_buckets["< 1s (excellent)"] += 1
            elif t < 2:
                time_buckets["1-2s (good)"] += 1
            elif t < 5:
                time_buckets["2-5s (acceptable)"] += 1
            elif t < 10:
                time_buckets["5-10s (slow)"] += 1
            else:
                time_buckets["> 10s (very slow)"] += 1

        for bucket, count in time_buckets.items():
            pct = count / max(len(self.results), 1) * 100
            lines.append(f"| {bucket} | {count} | {pct:.1f}% |")
        lines.append("")

        # Quality score distribution
        lines.extend(
            [
                "## Quality Score Distribution",
                "",
                "| Score Range | Count | Percentage |",
                "|-------------|-------|------------|",
            ]
        )

        score_buckets = {
            "90-100 (excellent)": 0,
            "70-89 (good)": 0,
            "50-69 (acceptable)": 0,
            "30-49 (poor)": 0,
            "0-29 (very poor)": 0,
        }

        for result in self.results:
            s = result.quality_score
            if s >= 90:
                score_buckets["90-100 (excellent)"] += 1
            elif s >= 70:
                score_buckets["70-89 (good)"] += 1
            elif s >= 50:
                score_buckets["50-69 (acceptable)"] += 1
            elif s >= 30:
                score_buckets["30-49 (poor)"] += 1
            else:
                score_buckets["0-29 (very poor)"] += 1

        for bucket, count in score_buckets.items():
            pct = count / max(len(self.results), 1) * 100
            lines.append(f"| {bucket} | {count} | {pct:.1f}% |")
        lines.append("")

        # Sample responses (good and bad)
        lines.extend(
            [
                "## Sample Responses",
                "",
                "### High Quality Responses (Score >= 80)",
                "",
            ]
        )

        high_quality = sorted(
            [r for r in self.results if r.quality_score >= 80],
            key=lambda r: r.quality_score,
            reverse=True,
        )[:5]

        for result in high_quality:
            lines.extend(
                [
                    f"**URL:** `{result.url}`",
                    f"- Category: {result.category}",
                    f"- Score: {result.quality_score:.0f}",
                    f"- Time: {result.metrics.elapsed_seconds:.2f}s",
                    f"- Content Length: {result.metrics.content_length:,} chars",
                    "",
                    "```",
                    result.metrics.raw_response[:500] + "..."
                    if len(result.metrics.raw_response) > 500
                    else result.metrics.raw_response,
                    "```",
                    "",
                ]
            )

        lines.extend(
            [
                "### Low Quality / Failed Responses (Score < 50)",
                "",
            ]
        )

        low_quality = sorted(
            [r for r in self.results if r.quality_score < 50],
            key=lambda r: r.quality_score,
        )[:5]

        for result in low_quality:
            lines.extend(
                [
                    f"**URL:** `{result.url}`",
                    f"- Category: {result.category}",
                    f"- Score: {result.quality_score:.0f}",
                    f"- Time: {result.metrics.elapsed_seconds:.2f}s",
                    f"- Has Clear Error: {result.metrics.has_clear_error_message}",
                    f"- Has Suggestion: {result.metrics.has_actionable_suggestion}",
                    f"- Has Context: {result.metrics.has_context_about_failure}",
                    "",
                    "```",
                    result.metrics.raw_response[:800] + "..."
                    if len(result.metrics.raw_response) > 800
                    else result.metrics.raw_response,
                    "```",
                    "",
                ]
            )

        # Final assessment
        lines.extend(
            [
                "## Final Assessment",
                "",
            ]
        )

        if avg_score >= 80:
            grade = "A"
            assessment = "Excellent - The tool provides high-quality responses with good error handling."
        elif avg_score >= 70:
            grade = "B"
            assessment = "Good - The tool works well for most sites with reasonable error messages."
        elif avg_score >= 60:
            grade = "C"
            assessment = (
                "Acceptable - The tool works but error handling could be improved."
            )
        elif avg_score >= 50:
            grade = "D"
            assessment = (
                "Below Average - Significant improvements needed in error handling."
            )
        else:
            grade = "F"
            assessment = "Poor - Major issues with both scraping and error handling."

        lines.extend(
            [
                f"**Overall Grade: {grade}**",
                "",
                f"**Assessment:** {assessment}",
                "",
                "### Strengths",
                "",
            ]
        )

        # Identify strengths
        if len(successful) / max(len(self.results), 1) > 0.8:
            lines.append("- High success rate (>80%)")
        if avg_time < 3.0:
            lines.append("- Fast response times (<3s average)")
        if failed:
            error_msg_rate = sum(
                1 for r in failed if r.metrics.has_clear_error_message
            ) / len(failed)
            if error_msg_rate > 0.7:
                lines.append("- Clear error messages when failures occur")
            suggestion_rate = sum(
                1 for r in failed if r.metrics.has_actionable_suggestion
            ) / len(failed)
            if suggestion_rate > 0.5:
                lines.append("- Provides actionable suggestions on failure")

        lines.extend(
            [
                "",
                "### Areas for Improvement",
                "",
            ]
        )

        if len(successful) / max(len(self.results), 1) < 0.7:
            lines.append("- Success rate could be higher")
        if avg_time > 5.0:
            lines.append("- Response times are slow")
        if failed:
            error_msg_rate = sum(
                1 for r in failed if r.metrics.has_clear_error_message
            ) / len(failed)
            if error_msg_rate < 0.5:
                lines.append("- Error messages could be clearer")
            suggestion_rate = sum(
                1 for r in failed if r.metrics.has_actionable_suggestion
            ) / len(failed)
            if suggestion_rate < 0.3:
                lines.append("- More actionable suggestions needed on failure")

        lines.append("")

        return "\n".join(lines)

    def save_results(self):
        """Save results to JSON and markdown files."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Save detailed JSON log
        log_file = self.output_dir / f"quality_test_log_{timestamp}.json"
        log_data = {
            "metadata": {
                "timestamp": timestamp,
                "total_urls": len(self.results),
                "concurrency": self.concurrency,
            },
            "results": [
                {
                    "url": r.url,
                    "category": r.category,
                    "timestamp": r.timestamp,
                    "quality_score": r.quality_score,
                    "metrics": {
                        "elapsed_seconds": r.metrics.elapsed_seconds,
                        "success": r.metrics.success,
                        "content_length": r.metrics.content_length,
                        "has_clear_error_message": r.metrics.has_clear_error_message,
                        "has_actionable_suggestion": r.metrics.has_actionable_suggestion,
                        "has_context_about_failure": r.metrics.has_context_about_failure,
                        "detected_access_restriction": r.metrics.detected_access_restriction,
                        "detected_sparse_content": r.metrics.detected_sparse_content,
                        "has_metadata_header": r.metrics.has_metadata_header,
                        "has_warnings_section": r.metrics.has_warnings_section,
                        "has_suggestions_section": r.metrics.has_suggestions_section,
                    },
                    "raw_response": r.metrics.raw_response,
                }
                for r in self.results
            ],
        }

        with open(log_file, "w", encoding="utf-8") as f:
            json.dump(log_data, f, indent=2, ensure_ascii=False)
        print(f"\nDetailed log saved to: {log_file}")

        # Save markdown report
        report_file = self.output_dir / f"quality_test_report_{timestamp}.md"
        report = self.generate_report()
        with open(report_file, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"Report saved to: {report_file}")

        # Save latest versions
        latest_log = self.output_dir / "quality_test_log_latest.json"
        latest_report = self.output_dir / "quality_test_report_latest.md"

        with open(latest_log, "w", encoding="utf-8") as f:
            json.dump(log_data, f, indent=2, ensure_ascii=False)
        with open(latest_report, "w", encoding="utf-8") as f:
            f.write(report)

        return report_file


async def main():
    parser = argparse.ArgumentParser(
        description="Test read_website tool quality and error handling"
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=5,
        help="Number of URLs to test concurrently (default: 5)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of URLs to test (default: all)",
    )
    parser.add_argument(
        "--urls-file",
        type=Path,
        default=PROJECT_ROOT / "scripts" / "benchmark_urls.json",
        help="Path to URLs JSON file",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "scripts" / "quality_test_results",
        help="Output directory for results",
    )

    args = parser.parse_args()

    tester = ReadWebsiteQualityTester(
        urls_file=args.urls_file,
        output_dir=args.output_dir,
        concurrency=args.concurrency,
        limit=args.limit,
    )

    await tester.run_tests()
    tester.save_results()

    # Print summary
    print("\n" + "=" * 70)
    print("QUALITY TEST COMPLETE")
    print("=" * 70)
    print(tester.generate_report())


if __name__ == "__main__":
    asyncio.run(main())

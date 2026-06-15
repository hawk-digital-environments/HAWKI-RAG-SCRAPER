"""
SummaryManager - Job Summary Export
====================================
This class manages the creation and export of job summaries.
It generates comprehensive summary JSON files with statistics and results.

Why this exists:
- Provides a persistent summary of scrape jobs
- Enables post-scrape analysis and reporting
- Documents job execution details for debugging and auditing

Summary Structure:
{
    "job_id": "unique-job-id",
    "status": "completed|failed",
    "stage": "completed|failed",
    "timing": {
        "started_at": "ISO-8601",
        "completed_at": "ISO-8601",
        "duration_seconds": 123.45
    },
    "urls": {
        "total": 100,
        "completed": 95,
        "failed": 5,
        "processing": 0,
        "success_rate": 95.00
    },
    "statistics": {
        "sessions": 10,
        "requests": 500,
        "errors": 15,
        "warnings": 25,
        "pdfs_downloaded": 20,
        "images_downloaded": 450
    },
    "output_directory": "/path/to/output",
    "error": "error message if failed"
}

Lifecycle:
- Created when a crawl job starts
- Updated when job completes or fails
- Writes summary.json to job directory
"""

import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional
import aiofiles

LOGGER = logging.getLogger("crawler.summary")


class SummaryManager:
    """
    Manages job summary creation and export.

    Provides methods to:
    - Generate comprehensive summaries
    - Save summaries as JSON files
    - Format summary data for display
    """

    def __init__(self, job_id: str, base_path: str = "/var/www/html/shared"):
        """
        Initialize summary manager.

        Args:
            job_id: Unique identifier for the job
            base_path: Base directory for job data (default: /var/www/html/shared)
        """
        self.job_id = job_id
        self.base_path = Path(base_path)
        self.job_dir = self.base_path / job_id
        self.summary_file = self.job_dir / "summary.json"

    async def save_summary(self, summary: Dict[str, Any]):
        """
        Save summary to JSON file.

        Args:
            summary: Summary dictionary to save
        """
        # Ensure job directory exists
        self.job_dir.mkdir(parents=True, exist_ok=True)

        # Add job_id to summary if not present
        if "job_id" not in summary:
            summary["job_id"] = self.job_id

        try:
            async with aiofiles.open(self.summary_file, 'w', encoding='utf-8') as f:
                await f.write(json.dumps(summary, indent=2, ensure_ascii=False))
        except Exception as e:
            LOGGER.error("Error saving summary for %s: %s", self.job_id, e, extra={"job_id": self.job_id})

    async def read_summary(self) -> Optional[Dict[str, Any]]:
        """
        Read summary from file.

        Returns:
            Summary dictionary or None if file doesn't exist
        """
        try:
            if self.summary_file.exists():
                async with aiofiles.open(self.summary_file, 'r', encoding='utf-8') as f:
                    content = await f.read()
                    return json.loads(content)
        except Exception as e:
            LOGGER.error("Error reading summary for %s: %s", self.job_id, e, extra={"job_id": self.job_id})

        return None

    @staticmethod
    def format_summary(
        job_id: str,
        stage: str,
        progress: Dict[str, Any],
        output_directory: str,
        error: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Format a complete summary from progress data.

        Args:
            job_id: Job identifier
            stage: Current stage (completed|failed)
            progress: Progress data from ProgressTracker
            output_directory: Output directory path
            error: Optional error message

        Returns:
            Formatted summary dictionary
        """
        summary = {
            "job_id": job_id,
            "status": stage,
            "stage": stage,
            "timing": {
                "started_at": progress.get("started_at"),
                "completed_at": progress.get("completed_at"),
                "duration_seconds": progress.get("duration_seconds")
            },
            "urls": {
                "total": progress.get("total_urls", 0),
                "completed": progress.get("completed_urls", 0),
                "failed": progress.get("failed_urls", 0),
                "processing": progress.get("processing_urls", 0),
                "success_rate": progress.get("success_rate", 0.0)
            },
            "statistics": progress.get("stats", {}),
            "output_directory": output_directory,
            "error": error
        }

        return summary

    @staticmethod
    def format_text_summary(summary: Dict[str, Any]) -> str:
        """
        Format summary as human-readable text.

        Args:
            summary: Summary dictionary

        Returns:
            Formatted text string
        """
        lines = [
            f"Job Summary - {summary['job_id']}",
            "=" * 60,
            f"Status: {summary['status']}",
            ""
        ]

        # Timing
        if summary.get("timing"):
            timing = summary["timing"]
            lines.append("Timing:")
            if timing.get("started_at"):
                lines.append(f"  Started: {timing['started_at']}")
            if timing.get("completed_at"):
                lines.append(f"  Completed: {timing['completed_at']}")
            if timing.get("duration_seconds"):
                duration = timing["duration_seconds"]
                minutes = int(duration // 60)
                seconds = duration % 60
                lines.append(f"  Duration: {minutes}m {seconds:.2f}s")
            lines.append("")

        # URLs
        if summary.get("urls"):
            urls = summary["urls"]
            lines.append("URLs:")
            lines.append(f"  Total: {urls['total']}")
            lines.append(f"  Completed: {urls['completed']}")
            lines.append(f"  Failed: {urls['failed']}")
            lines.append(f"  Success Rate: {urls['success_rate']:.2f}%")
            lines.append("")

        # Statistics
        if summary.get("statistics"):
            stats = summary["statistics"]
            lines.append("Statistics:")
            for key, value in stats.items():
                formatted_key = key.replace("_", " ").title()
                lines.append(f"  {formatted_key}: {value}")
            lines.append("")

        # Output
        if summary.get("output_directory"):
            lines.append(f"Output Directory: {summary['output_directory']}")
            lines.append("")

        # Error
        if summary.get("error"):
            lines.append(f"Error: {summary['error']}")
            lines.append("")

        return "\n".join(lines)

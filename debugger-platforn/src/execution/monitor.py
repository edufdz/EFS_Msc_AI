"""
RealTimeMonitor: Rich live dashboard that consumes the event queue
from the TestExecutionEngine.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn
from rich.table import Table


class RealTimeMonitor:
    """Displays a live CLI dashboard while tests execute."""

    def __init__(self, total_tests: int, console: Console | None = None):
        self.total_tests = total_tests
        self.console = console or Console()

        # Counters
        self.completed = 0
        self.passed = 0
        self.failed = 0
        self.errors = 0
        self.timeouts = 0
        self.running = 0

        # Cost / duration
        self.total_cost = 0.0
        self.total_duration = 0.0

        # Recent events
        self.recent_failures: List[Dict] = []
        self.recent_passes: List[Dict] = []

        self.start_time = time.time()

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def monitor(self, event_queue: asyncio.Queue) -> None:
        """Consume events and update dashboard until run_completed."""
        with Live(
            self._render(),
            refresh_per_second=4,
            console=self.console,
        ) as live:
            while True:
                try:
                    event = await asyncio.wait_for(event_queue.get(), timeout=0.25)
                    self._process(event)
                    live.update(self._render())
                    if event.get("type") == "run_completed":
                        break
                except asyncio.TimeoutError:
                    live.update(self._render())

    # ------------------------------------------------------------------
    # Event processing
    # ------------------------------------------------------------------

    def _process(self, event: Dict[str, Any]) -> None:
        etype = event.get("type")

        if etype == "test_started":
            self.running += 1

        elif etype == "test_completed":
            self.running = max(0, self.running - 1)
            self.completed += 1
            self.total_cost += event.get("cost_usd", 0)
            self.total_duration += event.get("duration_sec", 0)

            status = event.get("status", "")
            if status == "passed":
                self.passed += 1
                self._add_recent(self.recent_passes, event)
            elif status == "failed":
                self.failed += 1
                self._add_recent(self.recent_failures, event)
            elif status == "error":
                self.errors += 1
                self._add_recent(self.recent_failures, event)
            elif status == "timeout":
                self.timeouts += 1
                self._add_recent(self.recent_failures, event)

    @staticmethod
    def _add_recent(lst: List[Dict], event: Dict) -> None:
        lst.insert(0, event)
        del lst[5:]  # keep last 5

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _render(self) -> Panel:
        elapsed = time.time() - self.start_time
        pct = (self.completed / self.total_tests * 100) if self.total_tests else 0
        pass_rate = (self.passed / self.completed * 100) if self.completed else 0
        eta_sec = (
            ((elapsed / self.completed) * (self.total_tests - self.completed))
            if self.completed > 0 else 0
        )

        grid = Table.grid(padding=(0, 2))

        # Progress bar (text-based)
        bar_width = 30
        filled = int(bar_width * pct / 100)
        bar = f"[green]{'█' * filled}[/green][dim]{'░' * (bar_width - filled)}[/dim]"

        grid.add_row(
            "[bold]Progress[/bold]",
            f"{bar}  {self.completed}/{self.total_tests} ({pct:.1f}%)",
        )
        grid.add_row(
            "[bold]Running[/bold]",
            f"[cyan]{self.running}[/cyan] workers active",
        )
        grid.add_row(
            "[bold]Elapsed[/bold]",
            f"{elapsed:.0f}s   ETA: {eta_sec:.0f}s",
        )
        grid.add_row("")

        grid.add_row(
            "[green]Passed[/green]",
            f"[green]{self.passed}[/green]  ({pass_rate:.1f}%)",
        )
        grid.add_row(
            "[red]Failed[/red]",
            f"[red]{self.failed}[/red]",
        )
        grid.add_row(
            "[yellow]Errors[/yellow]",
            f"[yellow]{self.errors}[/yellow]",
        )
        grid.add_row(
            "[magenta]Timeouts[/magenta]",
            f"[magenta]{self.timeouts}[/magenta]",
        )
        grid.add_row("")

        grid.add_row(
            "[bold]Cost[/bold]",
            f"${self.total_cost:.3f}",
        )

        # Recent failures
        if self.recent_failures:
            grid.add_row("")
            grid.add_row("[bold red]Recent failures:[/bold red]", "")
            for f in self.recent_failures[:5]:
                num = f.get("test_number", "?")
                scenario = f.get("scenario", "")[:30]
                reason = (f.get("failure_reason") or f.get("status", ""))[:40]
                grid.add_row(
                    f"  [dim]#{num}[/dim]",
                    f"[dim]{scenario}[/dim] → [red]{reason}[/red]",
                )

        return Panel(
            grid,
            title="[bold cyan]Phase C: Test Execution[/bold cyan]",
            border_style="cyan",
        )

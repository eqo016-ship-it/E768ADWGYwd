"""Progress bar timeline untuk status unduh/upload di Telegram."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Callable, Literal

from pyrogram import Client
from pyrogram.enums import ParseMode
from pyrogram.types import Message

logger = logging.getLogger(__name__)

TRACK_WIDTH = 20
MIN_EDIT_INTERVAL = 1.2


def format_timeline_bar(pct: int, width: int = TRACK_WIDTH) -> str:
    """
    Bar gaya timeline: ⏱️━━━━━━● 88%
    ● = posisi progres, ━ = sudah lewat, spasi = belum.
    """
    pct = max(0, min(100, pct))
    if pct >= 100:
        track = "━" * width + "●"
    else:
        pos = max(0, min(width - 1, round(pct * (width - 1) / 100)))
        track = "━" * pos + "●" + " " * (width - pos - 1)
    return f"⏱️{track} {pct}%"


def format_bytes(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    if n < 1024 * 1024 * 1024:
        return f"{n / (1024 * 1024):.1f} MB"
    return f"{n / (1024 * 1024 * 1024):.2f} GB"


PhaseKind = Literal["download", "upload", "resolve"]


class TelegramProgress:
    """Update satu pesan status: proses download/upload + bar ⏱️━━●."""

    def __init__(
        self,
        client: Client,
        status_msg: Message | None,
        chat_id: int,
        loop: asyncio.AbstractEventLoop,
        job_index: int = 1,
        job_total: int = 1,
    ):
        self.client = client
        self.status_msg = status_msg
        self.chat_id = chat_id
        self.loop = loop
        self.job_index = job_index
        self.job_total = job_total
        self._last_edit = 0.0
        self._last_pct = -1
        self._lock = asyncio.Lock()
        self._video_title = ""

    def set_job(self, index: int, total: int) -> None:
        self.job_index = index
        self.job_total = total
        self.reset_pct()

    def set_title(self, title: str) -> None:
        self._video_title = (title or "")[:80]

    def _phase_label(self, kind: PhaseKind) -> str:
        if kind == "resolve":
            return f"proses persiapan {self.job_index}/{self.job_total}"
        if kind == "download":
            return f"proses download {self.job_index}/{self.job_total}"
        return f"proses upload {self.job_index}/{self.job_total}"

    def _build_text(
        self,
        kind: PhaseKind,
        pct: int,
        *,
        current: int = 0,
        total: int = 0,
        note: str = "",
    ) -> str:
        lines = [self._phase_label(kind), format_timeline_bar(pct)]
        if self._video_title:
            lines.append(f"<i>{self._video_title}</i>")
        if total > 0:
            lines.append(f"<i>{format_bytes(current)} / {format_bytes(total)}</i>")
        if note:
            lines.append(f"<i>{note}</i>")
        return "\n".join(lines)

    async def show(
        self,
        kind: PhaseKind,
        pct: int,
        *,
        current: int = 0,
        total: int = 0,
        note: str = "",
    ) -> Message:
        text = self._build_text(kind, pct, current=current, total=total, note=note)
        async with self._lock:
            try:
                if self.status_msg:
                    self.status_msg = await self.status_msg.edit_text(
                        text, parse_mode=ParseMode.HTML
                    )
                    return self.status_msg
            except Exception:
                pass
            self.status_msg = await self.client.send_message(
                self.chat_id, text, parse_mode=ParseMode.HTML
            )
            return self.status_msg

    async def _maybe_show(
        self,
        kind: PhaseKind,
        pct: int,
        current: int,
        total: int,
        note: str,
    ) -> None:
        now = time.monotonic()
        if pct < 100 and pct <= self._last_pct + 4 and (now - self._last_edit) < MIN_EDIT_INTERVAL:
            return
        if pct == self._last_pct and pct < 100:
            return
        self._last_pct = pct
        self._last_edit = now
        await self.show(kind, pct, current=current, total=total, note=note)

    def thread_callback(
        self,
        kind: PhaseKind,
        note: str = "",
    ) -> Callable[[int, int], None]:
        def on_progress(current: int, total: int) -> None:
            if total <= 0:
                return
            pct = min(100, int(current * 100 / total))
            coro = self._maybe_show(kind, pct, current, total, note)

            def _done(t: asyncio.Task) -> None:
                if t.cancelled():
                    return
                exc = t.exception()
                if exc:
                    logger.debug("Progress edit gagal: %s", exc)

            try:
                fut = asyncio.run_coroutine_threadsafe(coro, self.loop)
                fut.add_done_callback(_done)
            except Exception as e:
                logger.debug("Schedule progress gagal: %s", e)

        return on_progress

    def reset_pct(self) -> None:
        self._last_pct = -1
        self._last_edit = 0.0

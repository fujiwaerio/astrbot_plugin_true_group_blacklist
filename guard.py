"""Instance-local ingress guard, without global patches or AstrBot dependencies."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any


def normalize_id(value: Any) -> str:
    """Keep opaque IDs intact; never confuse booleans with integer IDs."""
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return ""
    return str(value).strip()


class GroupRules:
    def __init__(self, entries: list, enabled: bool = True) -> None:
        if not isinstance(entries, list) or not isinstance(enabled, bool):
            raise ValueError("enabled 必须是布尔值，blocked_groups 必须是列表")
        self.enabled = enabled
        self.global_ids: set[str] = set()
        self.scoped_ids: set[tuple[str, str]] = set()
        for entry in entries:
            rule = normalize_id(entry)
            if not rule or any(c.isspace() for c in rule):
                raise ValueError("黑名单每项必须是非空群 ID 或 平台实例ID|群ID，不可包含空白")
            if "|" in rule:
                parts = rule.split("|")
                if len(parts) != 2 or not all(parts):
                    raise ValueError("定向黑名单格式应为 平台实例ID|群ID")
                self.scoped_ids.add((parts[0], parts[1]))
            else:
                self.global_ids.add(rule)

    def matches(self, event: Any) -> bool:
        if not self.enabled:
            return False
        # Structured identifiers only: no substring searches in text, forwards,
        # sender IDs, or unique_session IDs (which may contain user suffixes).
        get_group = getattr(event, "get_group_id", None)
        if not callable(get_group):
            return False
        ids = {normalize_id(get_group())}
        message = getattr(event, "message_obj", None)
        raw = getattr(message, "raw_message", None)
        # Some OneBot notices/requests carry a group only in the raw envelope.
        if isinstance(raw, Mapping):
            ids.add(normalize_id(raw.get("group_id")))
        ids.discard("")
        if ids & self.global_ids:
            return True
        get_platform = getattr(event, "get_platform_id", None)
        platform = normalize_id(get_platform()) if callable(get_platform) else ""
        return any((platform, group) in self.scoped_ids for group in ids)


class QueueGuard:
    """Wrap both put variants; restore only our own attributes on termination.

    An inactive wrapper still referenced by another plugin is a transparent
    pass-through. It does not overwrite another plugin's newer wrapper.
    """

    def __init__(self, queue: asyncio.Queue, rules: GroupRules, logger: Any) -> None:
        if not isinstance(queue, asyncio.Queue):
            raise RuntimeError("不兼容的 AstrBot：Context._event_queue 不是 asyncio.Queue")
        self.queue = queue
        self.rules = rules
        self.logger = logger
        self.active = False
        self.blocked_count = 0
        self._warned = False
        self._installed = False
        self._original_put = queue.put
        self._original_nowait = queue.put_nowait
        self._saved_attrs = {
            name: (name in vars(queue), vars(queue).get(name)) for name in ("put", "put_nowait")
        }

        def put_nowait(item: Any) -> Any:
            if self._drop(item):
                return None
            return self._original_nowait(item)

        async def put(item: Any) -> Any:
            # Drop before waiting for free capacity on a bounded queue.
            if self._drop(item):
                return None
            return await self._original_put(item)

        self._put = put
        self._nowait = put_nowait

    def _drop(self, event: Any) -> bool:
        if not self.active:
            return False
        try:
            blocked = self.rules.matches(event)
        except Exception:  # noqa: BLE001 - isolate third-party event callbacks
            # Broken third-party events must not break the adapter receive loop.
            # Never log the raw event, message text, or exception contents.
            if not self._warned:
                self.logger.warning(
                    "真正的群黑名单：遇到无法识别的事件，已放行；请检查适配器兼容性。"
                )
                self._warned = True
            return False
        if not blocked:
            return False
        self.blocked_count += 1
        cleanup = getattr(event, "cleanup_temporary_local_files", None)
        if callable(cleanup):
            try:
                cleanup()
            except Exception:  # noqa: BLE001 - isolate third-party event callbacks
                self.logger.warning("真正的群黑名单：被拦截事件的临时文件清理失败。")
        return True

    def install(self) -> None:
        if self._installed:
            return
        # No await: the event loop cannot observe a half-installed guard.
        self.queue.put_nowait = self._nowait
        self.queue.put = self._put
        self.active = True
        self._installed = True

    def uninstall(self) -> None:
        self.active = False
        if not self._installed:
            return
        for name, wrapper in (("put", self._put), ("put_nowait", self._nowait)):
            if getattr(self.queue, name) is wrapper:
                existed, previous = self._saved_attrs[name]
                if existed:
                    setattr(self.queue, name, previous)
                else:
                    delattr(self.queue, name)
        self._installed = False

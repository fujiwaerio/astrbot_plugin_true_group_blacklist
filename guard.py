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
    def __init__(
        self,
        entries: list,
        enabled: bool = True,
        *,
        mode: str = "blacklist",
        allowed_groups: list | None = None,
    ) -> None:
        if not isinstance(entries, list) or not isinstance(enabled, bool):
            raise ValueError("enabled 必须是布尔值，blocked_groups 必须是列表")
        if mode not in ("blacklist", "whitelist"):
            raise ValueError("mode 必须是 blacklist 或 whitelist")
        self.enabled = enabled
        self.mode = mode
        self.global_ids, self.scoped_ids = self._parse(entries, "黑名单")
        self.allowed_ids, self.allowed_scoped_ids = self._parse(
            [] if allowed_groups is None else allowed_groups, "白名单"
        )

    @staticmethod
    def _parse(entries: list, label: str) -> tuple[set[str], set[tuple[str, str]]]:
        if not isinstance(entries, list):
            raise ValueError(f"{label}必须是列表")
        global_ids: set[str] = set()
        scoped_ids: set[tuple[str, str]] = set()
        for entry in entries:
            rule = normalize_id(entry)
            if not rule or any(c.isspace() for c in rule):
                raise ValueError(
                    f"{label}每项必须是非空群 ID 或 平台实例ID|群ID，不可包含空白"
                )
            if "|" in rule:
                parts = rule.split("|")
                if len(parts) != 2 or not all(parts):
                    raise ValueError(f"定向{label}格式应为 平台实例ID|群ID")
                scoped_ids.add((parts[0], parts[1]))
            else:
                global_ids.add(rule)
        return global_ids, scoped_ids

    def blocks_group(self, group_id: Any, platform_id: Any = "") -> bool:
        """Use the same policy at both ingress points; private events pass."""
        group = normalize_id(group_id)
        if not self.enabled or not group:
            return False
        scoped = (normalize_id(platform_id), group)
        if self.mode == "whitelist":
            # An empty whitelist blocks every known group only in this mode.
            # The blacklist is inactive, including entries present in both lists.
            return (
                group not in self.allowed_ids and scoped not in self.allowed_scoped_ids
            )
        return group in self.global_ids or scoped in self.scoped_ids

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
        if self.mode == "blacklist" and ids & self.global_ids:
            return True
        if not ids or (self.mode == "whitelist" and ids <= self.allowed_ids):
            return False
        get_platform = getattr(event, "get_platform_id", None)
        platform = normalize_id(get_platform()) if callable(get_platform) else ""
        return any(self.blocks_group(group, platform) for group in ids)


class OneBotGuard:
    """Filter the SDK bus before ANY notice/message subscriber can run."""

    def __init__(self, bus: Any, platform_id: str, rules: GroupRules, logger: Any):
        if not callable(getattr(bus, "emit", None)):
            raise RuntimeError("不兼容的 OneBot SDK：缺少事件分发接口")
        self.bus = bus
        self.platform_id = normalize_id(platform_id)
        self.rules = rules
        self.active = False
        self.blocked_count = 0
        self._installed = False
        self._original = bus.emit
        self._existed = "emit" in vars(bus)
        self._previous = vars(bus).get("emit")

        async def emit(event_name, *args, **kwargs):
            # OneBot Event is a dict. Ignore non-inbound bus events safely.
            payload = args[0] if args else kwargs.get("event")
            if (
                self.active
                and isinstance(payload, Mapping)
                and rules.blocks_group(payload.get("group_id"), self.platform_id)
            ):
                self.blocked_count += 1
                # SDK emit returns a list of handler results; [] also
                # prevents quick-operation replies from dropped notices.
                return []
            return await self._original(event_name, *args, **kwargs)

        self._emit = emit

    def install(self):
        if not self._installed:
            self.bus.emit = self._emit
            self.active = True
            self._installed = True

    def uninstall(self):
        self.active = False
        if self._installed and self.bus.emit is self._emit:
            if self._existed:
                self.bus.emit = self._previous
            else:
                delattr(self.bus, "emit")
        self._installed = False


class QueueGuard:
    """Wrap both put variants; restore only our own attributes on termination.

    An inactive wrapper still referenced by another plugin is a transparent
    pass-through. It does not overwrite another plugin's newer wrapper.
    """

    def __init__(self, queue: asyncio.Queue, rules: GroupRules, logger: Any) -> None:
        if not isinstance(queue, asyncio.Queue):
            raise RuntimeError(
                "不兼容的 AstrBot：Context._event_queue 不是 asyncio.Queue"
            )
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
            name: (name in vars(queue), vars(queue).get(name))
            for name in ("put", "put_nowait")
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

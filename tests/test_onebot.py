"""Integration with the real OneBot SDK bus; never connects to QQ."""

import importlib.util
import logging
import unittest
from pathlib import Path

try:
    from aiocqhttp.bus import EventBus
except ImportError:
    EventBus = None

SPEC = importlib.util.spec_from_file_location(
    "blacklist_guard", Path(__file__).resolve().parents[1] / "guard.py"
)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


@unittest.skipIf(EventBus is None, "Requires AstrBot's aiocqhttp SDK")
class OneBotTests(unittest.IsolatedAsyncioTestCase):
    async def test_other_groups_and_uninstall_preserve_welcome(self):
        bus = EventBus()
        received = []

        @bus.on("notice.group_increase")
        async def welcome(event):
            received.append(event["group_id"])
            return {"reply": "welcome"}

        guard = module.OneBotGuard(
            bus, "qq1", module.GroupRules(["qq1|123"]), logging.getLogger("test")
        )
        guard.install()
        guard.install()
        result = await bus.emit("notice.group_increase.approve", {"group_id": 456})
        self.assertEqual(result, [{"reply": "welcome"}])
        await bus.emit("notice.group_increase.approve", {"group_id": 123})
        guard.uninstall()
        guard.uninstall()
        await bus.emit("notice.group_increase.approve", {"group_id": 123})
        self.assertEqual(received, [456, 123])

    async def test_private_heartbeat_other_platform_and_disabled_pass(self):
        bus = EventBus()
        received = []

        @bus.on("notice")
        async def receive(event):
            received.append(event)

        guard = module.OneBotGuard(
            bus, "qq2", module.GroupRules(["qq1|123"]), logging.getLogger("test")
        )
        guard.install()
        for payload in ({}, {"user_id": 123}, {"group_id": 123}):
            await bus.emit("notice", payload)
        guard.uninstall()
        disabled = module.OneBotGuard(
            bus, "qq1", module.GroupRules(["123"], False), logging.getLogger("test")
        )
        disabled.install()
        await bus.emit("notice", {"group_id": 123})
        disabled.uninstall()
        self.assertEqual(
            received, [{}, {"user_id": 123}, {"group_id": 123}, {"group_id": 123}]
        )

    async def test_blacklisted_join_does_not_reach_welcome(self):
        bus = EventBus()
        received = []

        @bus.on("notice.group_increase")
        async def welcome(event):
            received.append(event["group_id"])

        guard = module.OneBotGuard(
            bus, "qq1", module.GroupRules(["123"]), logging.getLogger("test")
        )
        guard.install()
        try:
            result = await bus.emit("notice.group_increase.approve", {"group_id": 123})
            self.assertEqual(received, [])
            self.assertEqual(result, [])
        finally:
            guard.uninstall()

    async def test_whitelist_message_notice_request_and_private(self):
        bus = EventBus()
        received = []

        async def receive(event):
            received.append(event)
            return {"reply": "ok"}

        for kind in ("message", "notice", "request", "meta_event"):
            bus.on(kind)(receive)
        guard = module.OneBotGuard(
            bus,
            "qq1",
            module.GroupRules(["123"], mode="whitelist", allowed_groups=["123"]),
            logging.getLogger("test"),
        )
        guard.install()
        try:
            for kind in (
                "message.group.normal",
                "notice.group_increase",
                "request.group",
            ):
                allowed = {"group_id": 123, "post_type": kind}
                self.assertEqual(await bus.emit(kind, allowed), [{"reply": "ok"}])
                self.assertEqual(await bus.emit(kind, {"group_id": 456}), [])
            await bus.emit("message.private.friend", {"user_id": 456})
            await bus.emit("meta_event.heartbeat", {})
            self.assertEqual(len(received), 5)
            self.assertEqual(guard.blocked_count, 3)
        finally:
            guard.uninstall()
        await bus.emit("notice.group_increase", {"group_id": 456})
        self.assertEqual(received[-1], {"group_id": 456})

    async def test_whitelist_scoped_platform_empty_and_disabled(self):
        for platform, enabled, allowed, expected in (
            ("qq1", True, ["qq1|123"], [123]),
            ("qq2", True, ["qq1|123"], []),
            ("qq1", True, [], []),
            ("qq1", False, [], [123, 456]),
        ):
            with self.subTest(platform=platform, enabled=enabled, allowed=allowed):
                bus = EventBus()
                received = []

                @bus.on("notice")
                async def receive(event, received=received):
                    received.append(event["group_id"])

                guard = module.OneBotGuard(
                    bus,
                    platform,
                    module.GroupRules(
                        [], enabled, mode="whitelist", allowed_groups=allowed
                    ),
                    logging.getLogger("test"),
                )
                guard.install()
                try:
                    for group in (123, 456):
                        await bus.emit("notice.group_increase", {"group_id": group})
                    self.assertEqual(received, expected)
                finally:
                    guard.uninstall()

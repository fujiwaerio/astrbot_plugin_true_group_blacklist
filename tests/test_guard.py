"""Offline tests: no AstrBot installation, network, account or model required."""

import asyncio
import importlib.util
import logging
import unittest
from pathlib import Path
from types import SimpleNamespace

SPEC = importlib.util.spec_from_file_location(
    "blacklist_guard", Path(__file__).resolve().parents[1] / "guard.py"
)
guard_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guard_module)
GroupRules = guard_module.GroupRules
QueueGuard = guard_module.QueueGuard


class Event:
    def __init__(self, group="123", platform="qq1", raw=None, text="hello"):
        self.group = group
        self.platform = platform
        self.message_obj = SimpleNamespace(raw_message=raw)
        self.message_str = text
        self.role = "admin"
        self.cleaned = 0

    def get_group_id(self):
        return self.group

    def get_platform_id(self):
        return self.platform

    def cleanup_temporary_local_files(self):
        self.cleaned += 1


class RulesTests(unittest.TestCase):
    def test_exact_match(self):
        rules = GroupRules([123, " -100456 "])
        for group in (123, "123", "-100456"):
            self.assertTrue(rules.matches(Event(group)))
        for group in ("", None, "1234", "12", "0123", True):
            self.assertFalse(rules.matches(Event(group)))

    def test_platform_scope(self):
        rules = GroupRules(["qq1|123"])
        self.assertTrue(rules.matches(Event()))
        self.assertFalse(rules.matches(Event(platform="qq2")))

    def test_raw_group_notice_and_request(self):
        rules = GroupRules(["123"])
        for kind in ("notice", "request"):
            self.assertTrue(
                rules.matches(Event("", raw={"post_type": kind, "group_id": 123}))
            )

    def test_text_sender_and_private_not_inspected(self):
        rules = GroupRules(["123"])
        self.assertFalse(rules.matches(Event("", text="group 123")))
        self.assertFalse(rules.matches(Event("", raw={"user_id": "123"})))
        self.assertFalse(rules.matches(object()))

    def test_empty_and_disabled(self):
        self.assertFalse(GroupRules([]).matches(Event()))
        self.assertFalse(GroupRules(["123"], False).matches(Event()))

    def test_invalid_configuration(self):
        for entries in ("123", [True], [None], [""], ["a||b"], ["a|"], ["a b"]):
            with self.subTest(entries=entries), self.assertRaises(ValueError):
                GroupRules(entries)
        with self.assertRaises(ValueError):
            GroupRules([], "false")


class QueueTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.queue = asyncio.Queue()
        self.guard = QueueGuard(
            self.queue, GroupRules(["123"]), logging.getLogger("test")
        )
        self.guard.install()

    async def asyncTearDown(self):
        self.guard.uninstall()

    async def test_all_message_content_and_admin_are_blocked(self):
        for text in ("hi", "/help", "/draw x", "@bot", "[image]", "[voice]", ""):
            event = Event(text=text)
            self.queue.put_nowait(event)
            self.assertEqual(event.cleaned, 1)
        self.assertTrue(self.queue.empty())
        self.assertEqual(self.guard.blocked_count, 7)
        await asyncio.wait_for(self.queue.join(), 1)

    async def test_async_put_and_allowed_fifo(self):
        first, second = Event("456"), Event("")
        await self.queue.put(first)
        await self.queue.put(Event())
        self.queue.put_nowait(second)
        self.assertIs(await self.queue.get(), first)
        self.queue.task_done()
        self.assertIs(await self.queue.get(), second)
        self.queue.task_done()
        self.assertTrue(self.queue.empty())
        await asyncio.wait_for(self.queue.join(), 1)

    async def test_full_queue_drops_without_wait_or_queuefull(self):
        queue = asyncio.Queue(maxsize=1)
        gate = QueueGuard(queue, GroupRules(["123"]), logging.getLogger("test"))
        gate.install()
        try:
            queue.put_nowait(Event("456"))
            queue.put_nowait(Event())
            await asyncio.wait_for(queue.put(Event()), 1)
            with self.assertRaises(asyncio.QueueFull):
                queue.put_nowait(Event("456"))
            self.assertEqual(queue.qsize(), 1)
        finally:
            gate.uninstall()

    async def test_uninstall_idempotence_and_class_unchanged(self):
        self.guard.install()
        self.guard.uninstall()
        self.guard.uninstall()
        self.assertNotIn("put_nowait", vars(self.queue))
        self.assertNotIn("put", vars(self.queue))
        self.queue.put_nowait(Event())
        self.assertEqual(self.queue.qsize(), 1)
        other = asyncio.Queue()
        other.put_nowait(Event())
        self.assertEqual(other.qsize(), 1)

    async def test_multiple_guards_unload_out_of_order(self):
        newer = QueueGuard(self.queue, GroupRules(["456"]), logging.getLogger("test"))
        newer.install()
        self.guard.uninstall()
        self.queue.put_nowait(Event())
        self.queue.put_nowait(Event("456"))
        self.assertEqual(self.queue.qsize(), 1)
        newer.uninstall()
        self.queue.put_nowait(Event("456"))
        self.queue.put_nowait(Event())
        self.assertEqual(self.queue.qsize(), 3)

    async def test_other_plugin_new_wrapper_not_overwritten(self):
        original = self.queue.put_nowait
        calls = []

        def newer(item):
            calls.append(item)
            return original(item)

        self.queue.put_nowait = newer
        self.guard.uninstall()
        self.assertIs(self.queue.put_nowait, newer)
        self.queue.put_nowait(Event())
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.queue.qsize(), 1)

    async def test_existing_instance_method_restored(self):
        queue = asyncio.Queue()
        original = queue.put_nowait
        queue.put_nowait = original
        gate = QueueGuard(queue, GroupRules([]), logging.getLogger("test"))
        gate.install()
        gate.uninstall()
        self.assertIs(queue.put_nowait, original)

    async def test_unrecognized_event_passes_with_one_warning(self):
        event = Event()
        event.get_group_id = lambda: 1 / 0
        with self.assertLogs("test", "WARNING") as logs:
            self.queue.put_nowait(event)
            self.queue.put_nowait(event)
        self.assertEqual(len(logs.output), 1)
        self.assertEqual(self.queue.qsize(), 2)

    async def test_cleanup_failure_does_not_leak_event(self):
        event = Event()
        event.cleanup_temporary_local_files = lambda: 1 / 0
        with self.assertLogs("test", "WARNING"):
            self.queue.put_nowait(event)
        self.assertTrue(self.queue.empty())

    async def test_wrong_queue_fails_visibly(self):
        with self.assertRaises(RuntimeError):
            QueueGuard(object(), GroupRules([]), logging.getLogger("test"))


class WhitelistRulesTests(unittest.TestCase):
    def test_only_exact_whitelisted_groups_pass(self):
        rules = GroupRules([], mode="whitelist", allowed_groups=[123, " -100456 "])
        for group in (123, "123", "-100456"):
            self.assertFalse(rules.matches(Event(group)))
        for group in ("456", "1234", "12", "0123"):
            self.assertTrue(rules.matches(Event(group)))

    def test_scope_only_exempts_selected_platform(self):
        rules = GroupRules([], mode="whitelist", allowed_groups=["qq1|123"])
        self.assertFalse(rules.matches(Event("123", "qq1")))
        self.assertTrue(rules.matches(Event("123", "qq2")))
        self.assertTrue(rules.matches(Event("123", "")))
        self.assertTrue(rules.matches(Event("456", "qq1")))

    def test_global_id_exempts_all_platforms(self):
        rules = GroupRules([], mode="whitelist", allowed_groups=["123"])
        for platform in ("qq1", "qq2", ""):
            self.assertFalse(rules.matches(Event("123", platform)))

    def test_empty_whitelist_blocks_all_known_groups(self):
        rules = GroupRules([], mode="whitelist", allowed_groups=[])
        self.assertTrue(rules.matches(Event("123")))
        self.assertTrue(rules.matches(Event("456")))
        self.assertFalse(rules.matches(Event("")))

    def test_blacklist_is_inactive_in_whitelist_mode(self):
        rules = GroupRules(["123"], mode="whitelist", allowed_groups=["123"])
        self.assertFalse(rules.matches(Event("123")))
        self.assertTrue(rules.matches(Event("456")))

    def test_whitelist_is_inactive_in_default_blacklist_mode(self):
        rules = GroupRules(["123"], allowed_groups=["123"])
        self.assertTrue(rules.matches(Event("123")))
        self.assertFalse(rules.matches(Event("456")))

    def test_disabled_whitelist_passes_all_groups(self):
        rules = GroupRules([], False, mode="whitelist", allowed_groups=["123"])
        for group in ("123", "456", ""):
            self.assertFalse(rules.matches(Event(group)))

    def test_raw_notice_and_request_apply_the_same_policy(self):
        rules = GroupRules([], mode="whitelist", allowed_groups=["123"])
        for kind in ("notice", "request"):
            self.assertFalse(
                rules.matches(Event("", raw={"post_type": kind, "group_id": 123}))
            )
            self.assertTrue(
                rules.matches(Event("", raw={"post_type": kind, "group_id": 456}))
            )

    def test_private_text_user_ids_and_unrecognized_events_pass(self):
        rules = GroupRules([], mode="whitelist", allowed_groups=["123"])
        self.assertFalse(rules.matches(Event("", text="group 456")))
        self.assertFalse(rules.matches(Event("", raw={"user_id": 456})))
        for group in ("", None, True, {}):
            self.assertFalse(rules.matches(Event(group)))
        self.assertFalse(rules.matches(object()))

    def test_conflicting_structured_ids_do_not_exempt_other_groups(self):
        rules = GroupRules([], mode="whitelist", allowed_groups=["123"])
        self.assertTrue(rules.matches(Event("123", raw={"group_id": 456})))
        self.assertTrue(rules.matches(Event("456", raw={"group_id": 123})))

    def test_invalid_configuration_fails_before_installing(self):
        for entries in ("123", {}, [True], [None], [""], ["a||b"], ["a|"], ["a b"]):
            with self.subTest(entries=entries), self.assertRaises(ValueError):
                GroupRules([], mode="whitelist", allowed_groups=entries)
        for mode in ("", "allowlist", None, True, []):
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                GroupRules([], mode=mode)


class WhitelistQueueTests(unittest.IsolatedAsyncioTestCase):
    async def test_both_put_methods_pass_only_whitelist_and_private(self):
        queue = asyncio.Queue()
        guard = QueueGuard(
            queue,
            GroupRules(["123"], mode="whitelist", allowed_groups=["123"]),
            logging.getLogger("test"),
        )
        guard.install()
        try:
            allowed, private = Event("123"), Event("")
            queue.put_nowait(allowed)
            await queue.put(private)
            for text in ("hi", "/help", "/draw x", "@bot", "[image]", ""):
                for put in (queue.put_nowait, queue.put):
                    blocked = Event("456", text=text)
                    result = put(blocked)
                    if result is not None:
                        await result
                    self.assertEqual(blocked.cleaned, 1)
            self.assertEqual(guard.blocked_count, 12)
            self.assertIs(await queue.get(), allowed)
            queue.task_done()
            self.assertIs(await queue.get(), private)
            queue.task_done()
            self.assertEqual(allowed.cleaned, 0)
            self.assertEqual(private.cleaned, 0)
            await asyncio.wait_for(queue.join(), 1)
        finally:
            guard.uninstall()
        queue.put_nowait(Event("456"))
        self.assertEqual(queue.qsize(), 1)

    async def test_full_queue_drops_other_groups_without_waiting(self):
        queue = asyncio.Queue(maxsize=1)
        guard = QueueGuard(
            queue,
            GroupRules([], mode="whitelist", allowed_groups=["123"]),
            logging.getLogger("test"),
        )
        guard.install()
        try:
            queue.put_nowait(Event("123"))
            queue.put_nowait(Event("456"))
            await asyncio.wait_for(queue.put(Event("456")), 1)
            with self.assertRaises(asyncio.QueueFull):
                queue.put_nowait(Event("123"))
            self.assertEqual(queue.qsize(), 1)
            self.assertEqual(guard.blocked_count, 2)
        finally:
            guard.uninstall()


if __name__ == "__main__":
    unittest.main()

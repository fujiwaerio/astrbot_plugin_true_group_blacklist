"""Offline lifecycle check using real AstrBot APIs and simulated adapters.

Run with AstrBot's Python environment, optionally supplying --astrbot-source.
This never starts a platform connection, database, model or application server.
"""

import argparse
import asyncio
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace


async def check(root: Path) -> None:
    import astrbot
    from aiocqhttp.bus import EventBus
    from astrbot.api import AstrBotConfig
    from astrbot.api.event import AstrMessageEvent
    from astrbot.api.star import Context
    from astrbot.core.platform.astrbot_message import AstrBotMessage, MessageMember
    from astrbot.core.platform.message_type import MessageType
    from astrbot.core.platform.platform_metadata import PlatformMetadata
    from astrbot_plugin_true_group_blacklist.main import TrueGroupBlacklistPlugin

    schema = json.loads((root / "_conf_schema.json").read_text(encoding="utf-8"))
    meta = PlatformMetadata("aiocqhttp", "offline fixture", "qq1")
    bus = EventBus()
    notices = []

    @bus.on("notice.group_increase")
    async def welcome(event):
        notices.append(event["group_id"])

    # Only the context queue and adapter discovery are used by this plugin.
    context = Context.__new__(Context)
    context._event_queue = asyncio.Queue()
    adapters = [SimpleNamespace(meta=lambda: meta, bot=SimpleNamespace(_bus=bus))]
    context.platform_manager = SimpleNamespace(get_insts=lambda: adapters)
    queue = context.get_event_queue()

    def event(group):
        message = AstrBotMessage()
        message.group_id = group
        message.type = (
            MessageType.GROUP_MESSAGE if group else MessageType.FRIEND_MESSAGE
        )
        message.sender = MessageMember("42", "offline")
        message.message = []
        message.raw_message = {"group_id": group} if group else {"user_id": "42"}
        return AstrMessageEvent("/help", message, meta, group or "42")

    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "data" / "config" / "blacklist_config.json"
        path.parent.mkdir(parents=True)
        # Emulate an upgrade: the old configuration has no mode/whitelist keys.
        path.write_text(
            json.dumps({"enabled": True, "blocked_groups": ["123"]}),
            encoding="utf-8",
        )
        config = AstrBotConfig(str(path), schema=schema)
        assert config["mode"] == "blacklist" and config["allowed_groups"] == []
        plugin = TrueGroupBlacklistPlugin(context, config)
        await plugin.initialize()
        try:
            await queue.put(event("123"))
            assert queue.empty(), "Upgrade must preserve the old blacklist"
        finally:
            await plugin.terminate()

        config.update(mode="whitelist", allowed_groups=["qq1|123"])
        config.save_config()
        config = AstrBotConfig(str(path), schema=schema)
        plugin = TrueGroupBlacklistPlugin(context, config)
        await plugin.initialize()
        try:
            await plugin.initialize()
            await plugin.on_platform_loaded()
            await plugin.on_astrbot_loaded()
            assert len(plugin._onebot_guards) == 1, (
                "Lifecycle hooks must not wrap twice"
            )
            allowed, private = event("123"), event("")
            await queue.put(allowed)
            await queue.put(event("456"))
            queue.put_nowait(private)
            assert queue.qsize() == 2
            assert await queue.get() is allowed
            queue.task_done()
            assert await queue.get() is private
            queue.task_done()
            await asyncio.wait_for(queue.join(), 1)
            for group in (123, 456):
                await bus.emit("notice.group_increase", {"group_id": group})
            assert notices == [123]
        finally:
            await plugin.terminate()
        await plugin.terminate()
        assert "put" not in vars(queue) and "put_nowait" not in vars(queue)
        assert "emit" not in vars(bus)
        queue.put_nowait(event("456"))
        assert queue.qsize() == 1
    print(
        f"AstrBot {astrbot.__version__}: config upgrade, persistence, real events, "
        "whitelist, OneBot and lifecycle checks passed."
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--astrbot-source", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root.parent))
    if args.astrbot_source:
        sys.path.insert(0, str(args.astrbot_source.resolve()))
    asyncio.run(check(root))


if __name__ == "__main__":
    main()

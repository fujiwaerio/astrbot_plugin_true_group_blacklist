"""真正的群黑名单：在消息进入 AstrBot 事件总线前丢弃。"""

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import filter
from astrbot.api.star import Context, Star

from .guard import GroupRules, OneBotGuard, QueueGuard


class TrueGroupBlacklistPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig) -> None:
        super().__init__(context)
        self.config = config
        self._guard: QueueGuard | None = None
        self._onebot_guards: list[OneBotGuard] = []

    async def initialize(self) -> None:
        if self._guard is not None:
            return
        rules = GroupRules(
            self.config.get("blocked_groups", []),
            self.config.get("enabled", True),
            mode=self.config.get("mode", "blacklist"),
            allowed_groups=self.config.get("allowed_groups", []),
        )
        # Runtime wrapping is intentional: ordinary message handlers run too late.
        # Use the public accessor; fail visibly rather than silently downgrade.
        guard = QueueGuard(self.context.get_event_queue(), rules, logger)
        guard.install()
        self._guard = guard
        try:
            self._attach_onebot()
        except Exception:
            await self.terminate()
            raise
        logger.info(
            "真正的群黑名单：入口拦截已加载，启用=%s，模式=%s，黑名单=%d，白名单=%d；"
            "名单在管理面板修改。",
            rules.enabled,
            rules.mode,
            len(rules.global_ids) + len(rules.scoped_ids),
            len(rules.allowed_ids) + len(rules.allowed_scoped_ids),
        )

    def _attach_onebot(self) -> None:
        if self._guard is None:
            return
        manager = getattr(self.context, "platform_manager", None)
        if manager is None:
            return
        for platform in manager.get_insts():
            meta = platform.meta()
            if meta.name != "aiocqhttp":
                continue
            client = getattr(platform, "bot", None)
            bus = getattr(client, "_bus", None)
            if any(g.bus is bus for g in self._onebot_guards):
                continue
            gate = OneBotGuard(bus, meta.id, self._guard.rules, logger)
            gate.install()
            self._onebot_guards.append(gate)
            logger.info("真正的群黑名单：OneBot 原始事件拦截已加载，平台=%s", meta.id)

    @filter.on_platform_loaded()
    async def on_platform_loaded(self):
        # Called for startup and newly loaded/replaced adapters; no polling gap.
        self._attach_onebot()

    @filter.on_astrbot_loaded()
    async def on_astrbot_loaded(self):
        self._attach_onebot()

    async def terminate(self) -> None:
        for guard in reversed(self._onebot_guards):
            guard.uninstall()
        self._onebot_guards.clear()
        if self._guard is not None:
            self._guard.uninstall()
            self._guard = None

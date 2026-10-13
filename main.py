"""真正的群黑名单：在消息进入 AstrBot 事件总线前丢弃。"""

from astrbot.api import AstrBotConfig, logger
from astrbot.api.star import Context, Star

from .guard import GroupRules, QueueGuard


class TrueGroupBlacklistPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig) -> None:
        super().__init__(context)
        self.config = config
        self._guard: QueueGuard | None = None

    async def initialize(self) -> None:
        if self._guard is not None:
            return
        rules = GroupRules(
            self.config.get("blocked_groups", []),
            self.config.get("enabled", True),
        )
        # Runtime wrapping is intentional: ordinary message handlers run too late.
        # Use the public accessor; fail visibly rather than silently downgrade.
        guard = QueueGuard(self.context.get_event_queue(), rules, logger)
        guard.install()
        self._guard = guard
        logger.info(
            "真正的群黑名单：入口拦截已加载，启用=%s，规则数=%d；名单在管理面板修改。",
            rules.enabled,
            len(rules.global_ids) + len(rules.scoped_ids),
        )

    async def terminate(self) -> None:
        if self._guard is not None:
            self._guard.uninstall()
            self._guard = None

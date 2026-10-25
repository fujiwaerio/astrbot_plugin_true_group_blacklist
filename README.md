# 真正的群黑名单（含群白名单）

版本：v1.1.0 · 维护者：fujiwaerio · MIT License

在消息进入 AstrBot 处理流程前拦截指定群事件。支持黑名单和白名单两种模式，覆盖普通消息、指令以及可识别的群通知和请求。

## 安装与配置

1. 在 AstrBot WebUI 的插件管理页面通过仓库链接安装，或通过本地 ZIP 上传安装。仓库链接：`https://github.com/fujiwaerio/astrbot_plugin_true_group_blacklist`。
2. 打开插件配置，保持启用。
3. 要实现“仅这个群不拦截，其他群全部拦截”，把“群拦截模式”设为 `whitelist`。
4. 在“群白名单”填入需要放行的群号；仅放行一个群时只填一项。
5. 保存并重载插件，在白名单群、其他群和普通私聊中做对照测试。

```json
{
  "enabled": true,
  "mode": "whitelist",
  "allowed_groups": ["123456789"],
  "blocked_groups": []
}
```

请将示例群号替换成实际群号。

## 配置项

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `enabled` | `true` | 是否启用入口拦截 |
| `mode` | `blacklist` | `blacklist` 仅拦截黑名单；`whitelist` 仅放行白名单群 |
| `allowed_groups` | `[]` | 白名单模式中放行的群；为空时拦截所有可识别群 |
| `blocked_groups` | `[]` | 黑名单模式中拦截的群 |

- 群 ID 按字符串精确匹配。不要填写群名、用户 QQ 号或带用户后缀的会话 ID。
- 群号如 `123456789` 会匹配所有连接上同号的群；`平台实例ID|群ID` 仅匹配指定连接。平台实例 ID 不是适配器类型 `aiocqhttp`。
- 白名单模式中黑名单不参与拦截判断；同一群在两个名单中时仍放行。
- 普通私聊与无群 ID 的心跳放行。正文提及群号不会影响判断。
- 发送者权限不构成例外；管理员的群消息也受当前模式约束。
- 默认仍使用黑名单模式，升级保留已有黑名单。切换模式后保存并重载。
- 配置使用 `_conf_schema.json` 和 `AstrBotConfig`，由 AstrBot 保存到 `data/config`。

## 拦截范围与兼容性

在共享队列入口以及 OneBot SDK 总线分发前拦截。白名单群放行后，是否回复仍取决于唤醒、权限、其他插件和 AstrBot 设置。本插件的群白名单与 AstrBot 会话级插件白名单/插件集不同。

不拦截主动或定时推送、直接平台 API 调用、绕过这两处入口的监听器；不能阻止上游平台接收消息，也不撤销已排队或已开始处理的事件。无法识别群信息的异常事件可能放行。

原有队列运行时包装与 aiocqhttp 内部总线不是官方保证稳定的过滤扩展点，需要随核心/SDK 更新验证。声明版本范围 `>=4.28.1,<5`；本次真实 API 离线检查使用 AstrBot 4.29.1，未进行真实 QQ 群验收。不增加运行依赖。

## 开发验证

```sh
python -m unittest discover -s tests -v
python tests/smoke_astrbot.py --astrbot-source /path/to/AstrBot
```

34 项回归测试通过，涵盖规则、同步/异步队列和真实 aiocqhttp EventBus；配置迁移、保存读取、真实事件对象及生命周期离线检查通过。详见 `VALIDATION.md`。

## 仓库与许可证

[GitHub 仓库](https://github.com/fujiwaerio/astrbot_plugin_true_group_blacklist)

v1.1.0 新增群白名单模式，并包含 OneBot 群通知的入口拦截。MIT 许可证的完整版权和许可声明见 [LICENSE](LICENSE)。

开发参考：[AstrBot 插件开发指南](https://docs.astrbot.app/dev/star/plugin-new.html)、[插件配置](https://docs.astrbot.app/dev/star/guides/plugin-config.html)。

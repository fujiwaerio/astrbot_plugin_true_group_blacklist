# v1.1.0 本地验证记录


## 环境与结果

- Windows / Python 3.13.12。
- `python -m unittest discover -s tests -v`：34 项全部通过，无跳过；29 项规则和队列测试，5 项真实 aiocqhttp EventBus 测试。
- AstrBot 4.29.1 本地源码的真实 API 冒烟检查通过：schema 加载、旧配置自动补齐且保留黑名单模式、白名单保存/重新读取、真实 AstrMessageEvent 群消息和私聊、OneBot 通知、重复初始化和生命周期回调、卸载恢复。
- 冒烟检查使用真实 Context 的队列访问器；仅为本插件需要的队列和适配器发现构造离线测试夹具。未启动完整 AstrBot 应用。
- Ruff 0.17.2 格式检查和静态检查通过，使用隔离配置以及 `E4,E7,E9,F,I,UP,B,SIM` 规则。

## 复现命令

在插件目录运行：

```sh
python -m unittest discover -s tests -v
python tests/smoke_astrbot.py --astrbot-source /path/to/AstrBot
ruff format --isolated --check .
ruff check --isolated --select E4,E7,E9,F,I,UP,B,SIM .
```

若 AstrBot 已在当前 Python 环境中安装，可省略 `--astrbot-source`。SDK 测试需要 aiocqhttp，缺失时会明确跳过；冒烟检查需要 AstrBot 的完整依赖。以上依赖仅用于开发验证，不是此次扩展新增的插件运行依赖。

## 覆盖的关键行为

- 白名单群放行、其他群拦截；整数/字符串、空白裁剪、负数群 ID 和精确匹配。
- 全局群号豁免全部同号连接；`平台实例ID|群ID` 仅豁免指定连接。
- 白名单模式不使用黑名单决策，同一群同时出现在两个名单仍放行。
- 默认仍为黑名单模式；关闭 `enabled` 后全部放行。
- 空白名单在白名单模式下拦截所有可识别群，普通私聊和无群 ID 的心跳放行。
- 正文或用户 ID 出现群号不会影响决定；相互冲突的结构化群 ID 不会豁免其他群。
- 同步/异步入队、满队列、临时文件清理、队列计数与 join、卸载及其他包装器共存。
- OneBot 消息、入群通知和群请求使用相同的白名单规则，卸载后正常恢复分发。

## 与开发指南的对应

新增配置采用官方 `_conf_schema.json`、`AstrBotConfig` 与已有生命周期；持久化由 AstrBot 管理，插件不往自身目录保存用户配置。代码有注释及异常隔离，无新增网络请求或运行依赖，已执行测试和 Ruff，完整保留原 MIT 版权声明。继续扩展原插件，没有另建一个同功能插件或修改 AstrBot 核心文件。

- [AstrBot 插件开发指南](https://docs.astrbot.app/dev/star/plugin-new.html)
- [插件配置](https://docs.astrbot.app/dev/star/guides/plugin-config.html)

## 验证边界

未连接真实 QQ、NapCat 或其他平台，未发送消息，未调用模型；安装后仍需在白名单群、其他群和私聊中进行实际对照验收。

原插件已使用的运行时队列包装、aiocqhttp 内部 `_bus` 继续保留；这些不是官方保证稳定的过滤扩展点，不能据此宣称对所有未来版本兼容。元数据的版本兼容声明为 `>=4.28.1,<5`，本次实际 API 检查仅针对本机 4.29.1。

主动/定时推送、直接平台 API、绕过两处入口的监听器、上游接收、既有排队/运行任务不在此次白名单功能的控制范围。

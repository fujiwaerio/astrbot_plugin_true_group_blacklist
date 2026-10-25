# v1.1.0

维护者：fujiwaerio。

新增群白名单模式：指定群不执行本插件的入站拦截，其他可识别群全部拦截，普通私聊放行。

上传安装后，将“群拦截模式”改为 `whitelist`，在“群白名单”填写实际群号，保存并重载。空白名单会拦截所有可识别群；默认仍保留黑名单模式。

共享队列和 OneBot 总线共用规则；支持 `平台实例ID|群ID`。不增加运行依赖。34 项回归测试及 AstrBot 4.29.1 真实 API 离线检查通过，尚未实群测试。

仓库：https://github.com/fujiwaerio/astrbot_plugin_true_group_blacklist。MIT 版权及许可声明见 LICENSE。

# Lizvik 的 Dalamud 插件订阅仓库

用一个固定订阅地址管理多个 FF14 / Dalamud 插件。每个插件继续在自己的 GitHub 仓库发布，本仓库读取 Release 安装包，自动生成 `pluginmaster.json`。

## 玩家安装

订阅地址如下，后续插件更新和新增插件均使用同一地址：

```text
https://raw.githubusercontent.com/lizvik/DalamudPlugins/main/pluginmaster.json
```

在 Dalamud 设置中找到「实验性 / Experimental」下的「自定义插件仓库 / Custom Plugin Repositories」，添加并启用此地址，然后在插件安装器中搜索插件。具体界面文案以使用中的客户端为准。

| 插件 | 说明 | 发布来源 |
| --- | --- | --- |
| IINACT_CN | 国服战斗解析插件，集成 Overlay Plugin | `lizvik/IINACT_CN` |
| AutoHudLayout | 根据游戏窗口客户区分辨率自动切换 HUD 布局 | `lizvik/AutoHudLayout` |

后续新增插件仍使用同一订阅地址。

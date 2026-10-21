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

## 管理插件来源

所有来源统一维护在根目录的 `plugins.json` 中，每个数组元素对应一个插件。新增插件时，在数组中追加一项：

```json
{
  "enabled": true,
  "repository": "lizvik/YourPlugin",
  "internal_name": "YourPlugin",
  "release_tag": "latest",
  "zip_asset": "latest.zip"
}
```

`internal_name` 必须与安装包中的插件标识一致，`zip_asset` 是 Release 附件的完整文件名。`release_tag` 使用 `latest` 跟踪正式版本，也可填写固定标签。将 `enabled` 改为 `false` 可停止分发该插件。

本地校验和生成：

```powershell
python scripts/generate_repo.py --validate-config
python scripts/generate_repo.py
```

需要使用其他来源文件时，可指定 `--config 文件路径`。`pluginmaster.json` 是自动生成的订阅清单。提交来源配置后会触发更新，定时任务也会在每小时整点触发。

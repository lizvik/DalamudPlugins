# Lizvik 的 Dalamud 插件订阅仓库

用一个固定订阅地址管理多个 FF14 / Dalamud 插件。每个插件继续在自己的 GitHub 仓库发布，本仓库读取各插件仓库根目录的 `repo.json`，自动生成 `pluginmaster.json`。

## 玩家安装

订阅地址如下，后续插件更新和新增插件均使用同一地址：

```text
https://raw.githubusercontent.com/lizvik/DalamudPlugins/main/pluginmaster.json
```

在 Dalamud 设置中找到「实验性 / Experimental」下的「自定义插件仓库 / Custom Plugin Repositories」，添加并启用此地址，然后在插件安装器中搜索插件。具体界面文案以使用中的客户端为准。

当前配置的插件来源如下，实际可安装列表以订阅清单 `pluginmaster.json` 为准：

| 插件 | 说明 | 发布来源 |
| --- | --- | --- |
| IINACT_CN | 国服战斗解析插件，集成 Overlay Plugin | `lizvik/IINACT_CN` |
| AutoHudLayout | 根据游戏窗口客户区分辨率自动切换 HUD 布局 | `lizvik/AutoHudLayout` |
| Visland | 无人岛自动化，支持采集路线执行和工坊生产安排 | [lizvik/ffxiv_visland](https://github.com/lizvik/ffxiv_visland) |

后续新增插件仍使用同一订阅地址。

### Visland 使用说明

Visland 提供无人岛采集和工坊安排等自动化功能。安装后输入 `/visland` 打开采集界面，可按名称执行已保存的采集路线：

| 命令 | 用途 |
| --- | --- |
| `/visland exec <路线名称>` | 循环执行指定路线 |
| `/visland execonce <路线名称>` | 执行指定路线一次 |
| `/visland pause` | 暂停当前路线 |
| `/visland resume` | 恢复当前路线 |
| `/visland stop` | 停止当前路线 |

功能与命令可参阅[插件仓库](https://github.com/lizvik/ffxiv_visland)和[命令实现](https://github.com/lizvik/ffxiv_visland/blob/master/ffxiv_visland/Plugin.cs)。显示名称为 `Visland`，来源配置的 `internal_name` 必须填写小写的 `visland`，与上游 [repo.json](https://github.com/lizvik/ffxiv_visland/blob/master/repo.json) 完全一致。

## 管理插件来源

所有来源统一维护在 `plugins/plugins.json` 中，每个数组元素对应一个插件。新增插件时，在数组中追加一项：

```json
{
  "enabled": true,
  "repository": "lizvik/YourPlugin",
  "internal_name": "YourPlugin"
}
```

`internal_name` 必须与仓库 `repo.json` 中的 `InternalName` 一致。生成器直接使用 `repo.json` 中的版本和下载链接，不比较安装包或其他文件的版本。将 `enabled` 改为 `false` 可停止分发该插件。

本地使用 Python 3.12（与 CI 一致），无需安装第三方依赖。校验配置、运行测试并生成订阅清单：

```powershell
python scripts/generate_repo.py --validate-config
python -m unittest discover -s tests -v
python scripts/generate_repo.py
```

`--validate-config` 只检查本地来源配置，不访问网络；生成清单时需要访问 GitHub API，可通过环境变量 `GITHUB_TOKEN` 提供令牌。

需要使用其他来源文件或输出位置时，可指定 `--config 文件路径`、`--output 文件路径`。生成器在全部启用的来源解析成功后才写入清单，失败时保留原文件。若要清空已有的非空清单，需显式指定 `--allow-empty`。

`pluginmaster.json` 是自动生成的稳定版订阅清单，不包含上游的测试版字段，也不接受仅测试版插件。向 `main` 分支推送来源配置、生成脚本或更新工作流的变更后会触发更新，定时任务在每小时整点触发，也可在 GitHub Actions 中手动运行 `Update plugin repository`。工作流仅在清单有变化时自动提交并推送更新。

# World Studio

用持续讨论构建可追溯的虚拟世界，再从世界中创作独立作品。本地 Codex 插件，包含世界输入和作品写作两个 Skill，以及可编辑地图。

## 开发启动

需要 Python 3.11+、uv；地图开发还需要 Node.js 22+。

```sh
cd world-studio
uv sync --group dev
uv run world-studio --data ../data doctor
uv run pytest
uv run ruff check .
```

正式数据必须位于插件之外。示例使用仓库根目录 `data/`（Git 已忽略）；未配置时使用 `~/.local/share/world-studio`，也可设置 `WORLD_STUDIO_DATA`。不会把插件安装目录当作用户数据目录。

## 地图与写作

```sh
cd world-studio/web
npm ci
npm run build
cd ..
uv run world-studio --data ../demo-data demo
uv run world-studio --data ../demo-data serve
```

打开终端显示的本地链接即可体验：空白画布或图片底图、地点与实体关联、折线路线、多边形区域、缩放拖动、草稿与版本提交、行程查询、PNG/SVG 导出。演示目录包含两张地图与两部作品，不污染正式资料。

接入 Codex、数据备份与恢复见 [安装与使用](docs/installation.md)。插件源码位于 `world-studio/`；两个 Skill 分别处理世界输入和作品写作。也可通过安装脚本直接连接本地 MCP 与 Skill，无需远程服务或额外模型 API。

更多设计说明：[世界资料库](docs/world-repository.md)、[资料导入](docs/importing.md)、[地图](docs/maps.md)、[作品连续性](docs/writing.md)、[架构边界](docs/architecture.md)。

检查命令、端到端流程及实际浏览器结果见[验收记录](docs/acceptance.md)。

## 分批交付

1. 工程基础
2. 世界资料库
3. 资料导入与检索
4. 地图后端
5. 地图页面
6. 作品与写作核心
7. MCP、双 Skill、备份恢复、演示与安装

每批检查通过后独立推送 `main`。模型负责提取、语义冲突审阅及写作；程序负责结构、引用、版本和确定性约束。参考资料、候选假设和作品草稿不自动成为公共世界事实。

## 数据与适用范围

面向桌面、本地、单用户创作。世界和作品采用独立修订链，正文与图片按内容地址保存。世界更新不自动升级作品；草稿只有经作者采纳才推进连续性。完整快照和 Unicode 扫描检索优先保证可追溯性，超大世界需要后续存储优化。

地图坐标不是实际距离，未知通行条件不是可达结论。文学质量与隐含语义冲突由模型和作者审阅。首版不提供云同步、远程 ChatGPT 部署、GIS 或自动抓取账户历史聊天。

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

## 分批交付

1. 工程基础
2. 世界资料库
3. 资料导入与检索
4. 地图后端
5. 地图页面
6. 作品与写作核心
7. MCP、双 Skill、备份恢复、演示与安装

每批检查通过后独立推送 `main`。模型负责提取、语义冲突审阅及写作；程序负责结构、引用、版本和确定性约束。参考资料、候选假设和作品草稿不自动成为公共世界事实。

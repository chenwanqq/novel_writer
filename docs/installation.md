# 安装与诊断

## 本地运行

需要 Python 3.11+、uv 和 Node.js 22+。在仓库目录运行：

```sh
cd world-studio
uv sync --frozen --group dev
cd web
npm ci
npm run build
cd ..
uv run world-studio --data ../data doctor
uv run world-studio --data ../data serve
```

终端显示私有回环 URL。把整条 URL 在 Codex 内置浏览器或本机浏览器中打开；页面立即移除地址栏 token，并只在当前浏览器会话保存。输入和确认采用页面内对话框，可在内置浏览器使用。

## 将本地工具与 Skill 接入 Codex

提供两种入口，二选一，避免重复加载同名工具。

**直接本地连接**：适合本项目开发和个人使用。安装脚本通过官方 `codex mcp add` 注册 stdio 服务，并将两个 Skill 链接到 `~/.agents/skills/`。它不会改写已有同名连接或非本项目的 Skill。

```sh
python3 world-studio/scripts/install.py --data /absolute/path/to/world-data --dry-run
python3 world-studio/scripts/install.py --data /absolute/path/to/world-data
```

`--codex` 可以指定可用 CLI 的绝对路径。如果 npm 安装的 Codex 报二进制 ENOENT，可显式选择桌面应用捆绑的可用 CLI，无需本项目修改系统安装。例如 macOS 的某些版本位于 `/Applications/ChatGPT.app/Contents/Resources/codex`；以本机实际路径为准。

**插件包入口**：`world-studio/` 是完整 Codex 兼容插件，包含 `.codex-plugin/plugin.json`、`.mcp.json` 和双 Skill。使用 Codex 的 `plugin-creator` 将此目录加入个人 marketplace，然后在插件目录安装并新建任务。插件入口使用本机捆绑插件同样的 `cwd: "."` 规则，在插件根目录运行本地 stdio，不依赖未核实的根目录变量替换。不支持本地 stdio 的宿主可用上面的直接连接。构建后的 `web/dist` 必须随本地安装副本保留，Python依赖通过锁文件安装。

个人 marketplace 的具体路径解析和加载方式由宿主版本决定；项目不自动覆写用户 marketplace。官方说明：[插件打包](https://developers.openai.com/plugins/build/plugins)、[使用插件](https://learn.chatgpt.com/docs/plugins)。本项目采用插件创建器支持的兼容布局，而非远程 ChatGPT 发布格式。

## 首次使用

新建 Codex 任务后可直接说：

- “用 world-input 创建世界‘北境’，把这份设定集作为基线导入；先列冲突。”
- “继续北境，假设地方银行能发行票据，先推演，不改正式设定。”
- “打开地图，从空白画布建立首都和东港，信使通行三至五天。”
- “用 world-write，从东港记账员的角度建立作品，先构思开头两场。”

## 演示与数据维护

演示只能写入没有世界数据的独立目录：

```sh
cd world-studio
uv run world-studio --data ../demo-data demo
uv run world-studio --data ../demo-data serve
uv run world-studio --data ../data backup
uv run world-studio --data /absolute/path/to/empty-restored --archive /path/to/backup.zip restore
uv run world-studio --data ../data --world northern export
uv run world-studio --data ../demo-data --work ledger export
```

备份结果返回 ZIP 路径，包含数据库、来源、正文、图片及校验清单；不包含运行令牌。恢复不覆盖非空目录。世界与作品均可导出 Markdown；作品导出按阅读顺序排列已采纳正文，可用 `--revision` 指定历史修订。数据默认位置为 `~/.local/share/world-studio`，设置 `WORLD_STUDIO_DATA` 可覆盖；不要把个人资料提交 Git。

## 故障定位

- 工具缺失：确认 MCP 已注册并新建任务；运行 `uv run world-studio mcp` 应等待 stdio 协议，不打印普通诊断信息。
- 地图 404：运行前端构建，确认使用的是同一个安装副本。
- 地图 403：使用服务新生成的完整 token URL，检查端口和主机是否一致；不要把 127.0.0.1 改成其他主机。
- 版本冲突：草稿仍在，先比较再重新应用；同对象冲突需要明确取舍。
- 引用或耗时校验：按错误中的对象 ID 修复；耗时必须成对填写。
- 备份失败：保留原数据和错误信息，不以重新初始化数据库处理。

# 世界资料库

`Repository(root)` 是 HTTP、MCP 和 CLI 的共用业务入口。`create_world` 建立 main；`branch` 从固定修订分叉。`propose` 接收 put/delete 列表，`preview` 给出结构冲突，`commit` 要求作者采用依据。`restore` 生成恢复提案，不删除旧修订。

记录以 `kind` 表示实体、事实、事件等类型，以 `nature` 表示虚构、参考、推演或作者决策，以 `status` 表示候选、采用、否决或废弃。有效时间为可选的作者定义数值轴，区间采用左闭右开；不能把任意历法字符串擅自转成真实日期。可在 `data` 保存历法说明与叙述文本。

事实的 `data.subject/attribute/value` 参与明确属性冲突检查；没有这些字段的自然语言冲突由模型审阅。实体引用放入 `refs`，因果依赖放入 `depends_on`，修订关系放入 `supersedes`。重要设定应附 `sources`，直接聊天决策也可在提交说明中留证。

每个世界修订保存完整不可变快照。首版优先可重建性，超大世界可能需要后续增量存储优化。并发提交采用 SQLite BEGIN IMMEDIATE 和基础修订检查。变更集可以保存为候选，但只有明确提交才改变分支头。

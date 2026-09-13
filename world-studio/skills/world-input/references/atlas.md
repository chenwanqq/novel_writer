# 地图与空间

使用 `atlas_open` 打开本地编辑器。可导入图片或从空白画布创建地图，支持地点、路线、区域与下级地图。返回的 token URL 只在本机打开，不当作可分享链接。

对话修改可使用 `atlas_new_draft` → `atlas_save_draft` → `atlas_propose` → `world_preview` → 明确采用后的 `atlas_commit`；也可用 `world_propose` 更新空间记录。使用读取到的实体 ID，避免同名地点重复建模。

数据示例：

```json
{"id":"port","kind":"place","name":"东港","status":"accepted","data":{"map":"continent","entity":"port_entity","x":400,"y":250,"child_map":null}}
```

map.data 为 width、height、可选 asset、units_per_km。place.data 为 map、entity、x、y、可选 child_map。route.data 为 map、from、to、mode、bidirectional、min_days、max_days、availability、conditions、points。region.data 为 map、points（三点以上）、color、可选 entity。

无比例尺时不将画面距离解释为公里，不根据直线距离擅自生成通行时间。路线耗时由作者设定或已验证依据给出；条件不明返回信息不足。`atlas_route` 使用具体修订与明确满足的条件，行程检查须区分人、物和信息的移动。

草稿若过期，先比较当前世界，再明确调用 `atlas_rebase`。同对象冲突保留草稿；读取报告中的双方内容，和作者解决后保存新草稿。旧地图只读，修改形成新版本。

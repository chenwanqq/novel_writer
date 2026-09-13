# 正文与连续性对账

`prose_save` 只保存草稿。作者采用后，从实际正文提取 continuity，再 `prose_adopt` 原子提交正文选择和状态变化。证据必须是稿件精确摘录，但摘录存在不代表其陈述为世界真相：区分人物话语、误解、梦境、计划和叙述确立的事件。

连续性类别：event、character_knowledge、reader_knowledge、belief、setup、payoff、relationship。人物知识和信念指定 holder；读者信息按 reading_order，人物信息按作者数值时间轴，倒叙不得让过去人物提前获知未来。

大纲计划“已经妥协”，正文只写“答应明天见面”时，以正文为准；不得推进不存在的情节。作者修订前文后，检查 needs_review，逐场重新阅读并对账，不把旧连续性直接复制回来。

修改世界先 `work_world_impact` 比较目标修订，报告显式依赖和仍需语义检查的影响。用户明确要求升级才 `work_upgrade_world`；它保留正文并标记连续性待审阅。另一部作品不会被自动升级。

所有写操作传最新作品 base 与稳定 key。基础版本过期先读差异；同一逻辑重试用原 key，内容改变则换 key。

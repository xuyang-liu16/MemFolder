# 统一的 MemForest 提示词协议

[项目 README](../../README.zh-CN.md) · [实验 skill](../../skills/memfolder-exp/SKILL.md)

记录合并、最终 benchmark QA 和最终 judge 统一采用 `memforest.shared.v1`。
唯一模板源是 `src/memfolder/prompt_templates.py`，填入输入数据和记录版本的逻辑
在 `src/memfolder/prompt_protocol.py`。三份模板从已存档的 MemForest 代码中按
字面提取，记录原文件和模板的 SHA-256。

| 环节 | 统一规则 |
| --- | --- |
| merge | MemForest 的 summary 提示词；user 消息，temperature=0 |
| QA | MemForest 的 `ANSWER_PROMPT`；system 消息，temperature=0 |
| judge | MemForest 的 `ACCURACY_PROMPT`；user 消息，temperature=0，JSON 输出 |

RecordFolder、MemForest、ToMe 收到相同的两条记忆时，会发送完全一致的 merge
请求。RecordFolder 仍按 planner 给出的分组做一次多条合并；多条输入只替换
MemForest 模板中的条数及 Memory/Timestamp 槽位。ToMe 默认复用公共 `TextOperator`；
时间二分和重复吸收由 planner 选择，较新时间戳和目的节点 ID 由公共构建器保留，
下一次匹配前由引擎的公共语义特征提供器重新编码当前文本。

所有 context 压缩方法和未压缩对照使用同一套最终 QA、judge。
最终 benchmark QA 不启用 AGPR，也不追加压缩方法专属的解码指令。
`contextfolder-qa-prompt` 保留为兼容别名，行为与 `qa-prompt`、
`memforest-qa-prompt` 相同，取消了专属解码说明。
`chat-judge` 与 `memforest-judge` 使用同一份 JSON CORRECT/WRONG 判分模板。
公开选项、问题时间、记忆时间戳和说话人身份作为输入保留；适配规则不随 baseline 变化。

PersonaMem/M3 的时间模板在公共 member resolver 中声明原生排序。创建时间和
clip 坐标属于标明来源的输入数据，不追加方法专属指令。历史前缀和 clip 截断
同样作用于未压缩对照，再执行相同的 QA/judge。

ContextFolder 内部的事实提取、编码、盲恢复检查、修订属于 operator 的算法步骤，
保留它们的可替换接口。它们与最终 benchmark QA/judge 分开；其中普通 summary
fallback 也使用公共 MemForest 模板。LLMLingua2 是本地 token 分类器，不调用
LLM merge 提示词。BabelTele 压缩插件保留自己的编码指令；LLMLingua2 与
BabelTele 的最终 benchmark QA/judge 仍使用同一份公共 MemForest 模板。

配置示例和详细规则见 [英文协议文档](../PROMPT_PROTOCOL.md)。实验模板已明确
使用 `memforest-qa-prompt` 和 `memforest-judge`。模型、检索设置、预算也应在同一
对比矩阵内固定。贡献新的 planner/operator 无需修改公共评测协议。

请求及缓存包含提示词版本、消息角色、JSON 格式，manifest 记录模板哈希。
旧结果保留其原协议；merge 改动后，新对比需要新压缩库和 embedding。
仅改变 QA/judge 时可以复用已验证的库，并使用新的评测身份。

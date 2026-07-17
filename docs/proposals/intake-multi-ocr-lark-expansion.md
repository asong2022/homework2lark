# Proposal: 自动框题、多 OCR 与飞书多维表格

## 出现的问题

自动候选、多选、手动补框已进入实现，但真实页面证明题目级 Provider 仍可能把一道含文字与插图的题误切成两个候选题框。若未经教师确认就按框建题，会错误创建两道错题。与此同时，扫描只是输入路径，系统仍需要把教师确认修订的题目发布到飞书并支持长期复用、组卷和变式练习。

## 为什么超出当前范围

原 Phase 1 明确禁止自动切题、两个以上 OCR Provider、自动路由/投票和外部协作存储。新需求同时触发了三个 Proposal 边界，且涉及第三方传输、新数据模型、多题交互和外部同步失败语义，不应作为单次小修补加入。

## 建议方案

1. 把“题目区域检测”与“OCR”分开。Yescan 每个 `StructureInfo` 生成一个候选题框，不从题内 `Detail` 拆题；Provider 误切时教师可把多个来源框显式合并为一道题，确认后才创建一个正式 `ProblemRegion`。
2. 先用匿名样本评测 PaddleOCR、MinerU 和 Yescan。PaddleOCR 倾向作为本地默认；MinerU 用于复杂布局/公式的显式对比；Yescan 的官方标准 API 已验证，可优先评测试题切分、公式和手写识别，但仍需用匿名页确认真实题目坐标结构。
3. 把全局单 Provider 改为“配置过的 Provider Registry + 每次请求显式选择”。不做自动投票或静默合并，教师选择某次 OCRRun 作为修订基线。
4. 保留 SQLite + 本地文件为真实源。飞书 Base 只保存教师确认修订后的可搜索投影，支持视图、筛选、标签和未来组卷选题。
5. 本地人工修订先保存，教师再显式发布到飞书。飞书失败可重试，不回滚本地数据。
6. AI 可用于整页布局分析、候选框、OCR/公式对比和结构化字段提取，但必须经过 Provider 契约、保留 raw output，并经教师确认。
7. 增加 Hermes 兼容 CLI/Skill 作为另一客户端，但只调用同一 API 与当前修订发布门，不维护第二套数据模型。

## 已确认决策与已完成外部准备

- 用户允许整页作业/试卷上传到 MinerU 和 Yescan；界面仍需在云端调用前明示提示。
- Yescan CLI 1.0.5 已安装，标准 API 与 AI Agent 两套凭据已在 Git 忽略的本机配置中分开保存；官方 endpoint、标准 API 的 SHA3-256 签名协议、Base64/URL 输入和相关场景已确认。`BACK_` 身份仅供后端标准 API，`AI_` 身份仅供 Agent/CLI，后端优先采用标准 API，CLI 只用于诊断。
- 两张用户批准的真实作业页已用于 Yescan 验证：第一页 7 题返回 7 个候选；第二页 6 题返回 7 个候选，其中第 4 题被 Provider 误切为文字框和人物图框。这直接确定了“多个 Provider 来源框可由教师合并为一个逻辑题目”的模型约束。
- 飞书 `小学数学错题学习库` 已创建：包含 `pages` / `questions`、双向页面-题目关联，以及页面目录、全部题目、待复核、组卷候选视图。尚未写入题目或附件。

## 对数据模型的影响

- 新增 `RegionDetectionRun`：保存检测 Provider、模型、raw response、状态、耗时与候选框。
- `ProblemRegion` 增加来源说明：`manual` 或来自某个 detection run/candidate；保存教师确认后的最终坐标。
- `OCRRun` 现有结构可继续保存多 Provider 运行，无需合并记录；API 需增加 Provider 选择。
- 新增 `ExternalPublication` 或 `LarkBasePublication`：记录本地 revision、Base/table/record ID、同步状态、错误码和时间。
- 不将 `ProblemAsset` 或本地版本历史迁移到 Base 作为唯一存储。

## 对技术栈的影响

- Web：单矩形 Selector 升级为候选覆盖层、点击多选、手动新增/编辑和多题保存。
- API：新增检测端点、批量区域确认、Provider Registry 和按请求 OCR 选择。
- Provider：新增 detection 抽象、MinerU Adapter；Paddle 安装与实测；Yescan 使用独立标准 API Adapter，并保留匿名样本返回契约门。
- 飞书：单教师本地阶段可先使用已授权的 `lark-cli base` Adapter；未来服务化/多用户时需迁移到正式 OAuth/OpenAPI Adapter。
- 仍不需要引入微服务、Redis、Kafka 或向量数据库。

## 实施成本

| 子阶段 | 粗略成本 | 主要不确定性 |
|---|---:|---|
| 真实 OCR 基准 + Paddle/MinerU/Yescan 可行性 | 2-4 开发日 + 教师标注样本 | 题目坐标返回、公式/图形评价 |
| 自动候选框 + 点击多选 + 手动编辑 | 5-8 开发日 | 题目分割准确率、复杂排版 |
| 按请求多 OCR + 对比确认 | 3-5 开发日 | Provider 返回异构、耗时/费用 |
| 飞书 Base 发布投影 | 2-4 开发日 | 表结构、附件隐私、CLI 稳定性 |

总体建议按 12-21 个开发日分段验收，不作为一次大合并实现。

## 是否建议进入下一阶段

建议进入 **Phase 2A**，但第一个实现任务应是“匿名数学页/单题基准与真实 Provider 验证”，而不是盲目同时接入三家。紧接着实现本地自动候选框和多选交互，然后再接飞书题目投影。

整页云端传输政策和 Yescan 官方接入协议均已明确。下一步是在用户确认本 Proposal 后，先创建“匿名数学页的自动框题与三 Provider 基准”实现任务，再进入产品代码改造。

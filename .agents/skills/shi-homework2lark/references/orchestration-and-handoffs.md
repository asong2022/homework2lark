# 智能错题工作流编排与交接合约

## 1. 为什么只有一个入口

收题、错情、变式、练习和反馈共享同一题目谱系、Base 表和练习批次。它们是一个学习闭环的阶段，不是五个相互独立的产品。`shi-homework2lark` 负责调度；具体飞书、OCR、题图和文档能力继续由对应 Skill 负责。

工作流可以从任一已有阶段开始，也可以在任一阶段停止。不要因为本文件列出完整闭环，就强迫教师每次从上传原卷重新开始。

## 2. 最小任务卡

从对话已有信息中填写。只有会改变本轮执行路径的空项才追问。

```markdown
## [homework/task]
- 目标：收集入库 / 错情整理 / 题生变式 / 个人练习 / 班级练习 / 再练反馈 / 完整闭环
- 收集方式：未涉及 / 1 教师精选 / 2 匿名批改统计 / 3 实名绑定统计
- 收集方式决定者：用户 / 未选择
- 起点：原始材料 / 已审核本地题目 / Base 原题 / Base 错题记录 / 变式题 / 练习批次 / 批改反馈
- 本轮终点：
- 输入材料：图片 / PDF / Word / 单题截图 / 教师描述 / Base 选择 / 班级名单 / 已批改练习
- 处理范围：页、题目、学生或批次的明确范围
- 教师已有判断：无 / 错题选择 / 真实作答 / 错因 / 选题意图 / 掌握判断
- 第三方上传授权：未涉及 / 已授权给具体 Provider / 待确认
- 外部写入授权：只读 / 已授权明确范围 / 待确认
```

教师一句话已经给全时，直接填卡并执行，不用为了模板逐项发问。

## 3. 收集方式门与阶段路由

从收集阶段开始时先读 `collection-modes.md`。用户未选择时只展示固定 1/2/3，不能自动判断；已有选择必须在任务卡中写 `收集方式决定者：用户`。收集方式决定材料和身份边界，下面的 A～F 决定本轮学习阶段，两者不能混用。

| 模式 | 起点 | 核心阶段 | 默认停点 |
|---|---|---|---|
| A 收集入库 | 图片/PDF/Word/单题图 | source → questions（可选 Web 框题）→ Agent OCR/质量门 → Base | `[homework/base]` 原题已发布 |
| B 错情整理 | 空白模板 + 已批改稿，或教师描述 | source/questions → observed mistakes → grouped Base records | `[homework/mistakes]` 与 `[homework/base]` |
| C 题生变式 | Base 原题 | fact card → generate/check → optional diagram → Base write | `[homework/variants]` |
| D 精准练习 | Base 原题/错题记录/变式 | select → immutable manifest → Word | `[homework/practice]` |
| E 再练反馈 | 练习批次与批改证据 | locate → observe → teacher judgment → event/Base projection | `[homework/feedback]` |
| F 完整闭环 | 任意材料 | A/B → C → D；收到再练后 E | 用户指定终点 |

## 4. 阶段交接块

交接块是教师可读的会话状态，不是数据库。只放续跑所需的最小事实；完整图片、学生名单、作答正文、远端 record ID 和绝对路径保存在教师私有文件中。

### 4.1 来源

```markdown
## [homework/source]
- 来源类型：
- 材料角色：空白模板 / 已批改作业 / 单题截图 / 教师描述
- 页数与已处理范围：
- 页面化状态：未需要 / 已完成 / 失败待补材料
- 本地私有清单：相对路径或“当前会话附件”
- 已调用第三方：无 / MinerU / PaddleOCR / Yescan
- 来源备注：
```

### 4.2 完整题目

```markdown
## [homework/questions]
- 候选题数：
- 教师选择题数：
- 已创建 problemId：只列本地稳定 ID 或写入私有清单
- 图文一体检查：通过 / 待补题图 / 待人工框选
- OCR 状态：未运行 / 已完成 / 部分失败
- 修订与审核：未开始 / 部分完成 / 全部 reviewed
- Base 发布：未发布 / 部分发布 / 全部发布
```

### 4.3 错情分组

```markdown
## [homework/mistakes]
- 作业/批次：
- 批改样本人数：
- 已观察学生数：
- 全对人数：
- 错误发现数：
- 建议分组数：
- 教师已确认分组数：
- 典型真实作答：保存在私有结果 / 已在对话预览
- Base 写入：未写 / 已写 / 部分失败
```

先记录 `observedResponse` 和 `markEvidence`，再形成 `错误表现`，最后才提出 `错误原因`。不得把 AI 推测写进真实作答。

### 4.4 Base 状态

```markdown
## [homework/base]
- Base：教师可读名称
- 当前涉及表：错题页面 / 错题题目 / 错题记录 / 变式题
- 原题结果：创建 / 复用 / 未写
- 错题分组结果：创建 / 合并 / 未写
- 变式结果：创建 / 复用 / 未写
- 需人工处理：数量与教师可读原因
- 幂等回读：通过 / 未执行 / 失败
```

不要把 Base token、table/field/record ID 放进普通交接块；确定性脚本和私有 manifest 自己保存完成写入所需的稳定关系。

### 4.5 变式

```markdown
## [homework/variants]
- 来源原题：本地稳定题目 ID 或私有选择清单
- 生成数量：
- 使用的主要变式轴：
- 独立验算：全部通过 / 未通过并停止
- 题图：无需 / 已调用题图 Skill / 待补
- Base 写回：未写 / 已创建 / 幂等复用 / 部分异常
```

### 4.6 练习

```markdown
## [homework/practice]
- 练习类型：全班共用 / 单生个人 / 整班个人化 / 学号子集
- 批次码：YYYYMMDD-NN
- 目标题量：
- 实际题量或生成份数：
- 无合格题学生数：
- manifest：私有相对位置
- Word：私有相对位置
- 渲染检查：未检查 / 通过 / 发现问题
```

Word 不预估物理页，不插人工分页符；实际页面码由 Word `PAGE` 字段生成。

### 4.7 再练反馈

```markdown
## [homework/feedback]
- 练习批次：
- 已识别页面/学生范围：
- 已定位题目数：
- 观察结果：保存在私有反馈清单
- 教师判断：已提供 / 待补
- 本地事件：未写 / 已追加 / 幂等复用
- Base 投影：未更新 / 已更新 / 失败可重试
- 下一轮建议：
```

## 5. 阶段依赖与读取顺序

进入阶段时，按以下顺序加载，避免把所有文档一次塞入上下文：

Web 若被调用，只完成题目区域保存和公开 `problemId` 交接；OCR、修订、质量门与 Base 操作仍在本阶段的 Agent 对话中继续。

### 收集入库

1. `source-routing.md`
2. `question-asset-contract.md`
3. `intake-contract.md`
4. 需要 OCR 时读取 `../shi-ocr/SKILL.md`
5. 写 Base 前读取 `lark-base/SKILL.md`

### 错情整理

1. `intake-contract.md`
2. 多人多页时 `staged-intake.md`
3. `base-contract.md`
4. 识别辅助按需读取 `shi-ocr`
5. 写入前读取 `lark-base`

### 题生变式

1. `base-contract.md`
2. `variant-generation-prompt.md`
3. 写入前读取 `lark-base`
4. 只有新题依赖视觉条件时读取 `diagram-contract.md` 与 `wumu-jihe-html`

### 精准练习

1. `learning-loop.md`
2. `practice-sheet-template.md`
3. 个人/班级时 `personal-practice.md`
4. Base 查询前读取 `lark-base`
5. 生成后使用文档能力实际渲染检查

### 再练反馈

1. `learning-loop.md`
2. `retry-feedback.md`
3. `base-contract.md`
4. 批改图像按需读取 `shi-ocr`
5. Base 更新前读取 `lark-base`

## 6. 授权门与续跑

一个明确授权可以覆盖一段已预览、边界不变的连续动作，例如“把这 6 道审核后发布 Base，并把确认的 3 个错情分组写入”。以下变化会使旧授权失效：

- 增加新的学生、页面、题目或 Base 表；
- 从只读变为写入；
- 从新增变为覆盖/删除；
- 更换要上传材料的第三方；
- 数学或身份冲突导致内容实质改变。

阶段失败时保留已完成交接块，并把状态写成“部分失败 + 可重试步骤”。下次先核对稳定 ID/manifest，再只重跑失败步骤。

## 7. 进度与收工模板

```markdown
### 错题学习进度
| 阶段 | 状态 | 结果 |
|---|---|---|
| 收集入库 | ✅/🔄/⏳/⏭ | 题目数、审核/发布状态 |
| 错情整理 | ✅/🔄/⏳/⏭ | 样本数、错误组数 |
| 题生变式 | ✅/🔄/⏳/⏭ | 变式数、题图异常 |
| 精准练习 | ✅/🔄/⏳/⏭ | 批次、份数、实际题量 |
| 再练反馈 | ✅/🔄/⏳/⏭ | 已反馈范围、下一轮 |
```

收工时列出：已形成的学习资产、实际外部写入、私有文件、真实异常、未做阶段和下一条最小任务。不要把“可以以后做”写成已经实现。

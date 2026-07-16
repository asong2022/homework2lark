# 收集方式：必须由用户三选一

## 固定选择

从收集错题开始且对话中尚无明确选择时，只展示以下三项并等待用户选择。不得调用 OCR、Web、Base 或根据材料替用户判断。

| 选择 | 稳定值 | 需要的材料 | 身份处理 |
|---|---|---|---|
| 1 教师精选 | `teacher_selected` | 空白卷、整页材料或单题图；教师明确选题 | 不需要学生身份 |
| 2 匿名批改统计 | `anonymous_corrected` | 空白卷 + 已批改作业 | 不绑定姓名/学号，保留匿名实例、人数和典型作答 |
| 3 实名绑定统计 | `identified_corrected` | 空白卷 + 已批改作业 + 私有名单 | 用学号 + 姓名核对，Base 默认只写姓名 |

用户原话明确说“我自己选题”“匿名/不实名”或“实名/名单绑定”就是本人选择，不再重复问。AI 可以说明差异，但不能写“我判断你适合模式 2”并直接开始。

## 确定性入口

无选择时读取选项，不产生文件：

```powershell
python <skill-root>/scripts/workflow.py choices
```

用户选择后创建状态：

```powershell
python <skill-root>/scripts/workflow.py start `
  --collection-mode 1|2|3 `
  --output <私有任务状态.json>
```

状态固定 `decidedBy=user`。Agent 把 `collectionMode` 写入 `[homework/task]`，再按下表自动推进：

| 收集方式 | 自动流程 |
|---|---|
| 教师精选 | 页面化/展示 → 教师在对话或 Web 手动/自动框题 → Web 返回公开题目 ID → Agent OCR/整理/质量门 → Base 原题 |
| 匿名批改统计 | 空白模板题目只识别一次 → 批改页作答/红笔证据 → 匿名错情分组 → Base 题目与统计 |
| 实名绑定统计 | 匿名统计流程 + 私有名单核对 → 同题同错因姓名多选 → Base 题目与错题记录 |

外部上传与写 Base 可以由用户对明确批次一次性授权；数学矛盾、身份冲突、识别不确定和覆盖/删除仍必须停下。

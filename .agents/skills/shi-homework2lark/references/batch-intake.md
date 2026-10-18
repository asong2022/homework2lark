# 可续跑批量收题

## 教师入口

教师不需要制作状态文件，只要在对话中说明材料角色，例如：

```text
这 8 张图片每张都是一道完整错题，请批量收录；中间有一张失败也继续，之后只补失败项。
```

或者：

```text
这 4 张都是整页作业，请逐页列出完整题目候选，不要自动替我选择。
```

Agent 把 1～20 张已经页面化的 JPG/JPEG/PNG 写成私有输入清单，再调用确定性脚本。单题图整批使用 `single`；整页图整批使用 `chat`。一份状态不混用两种语义。

## 输入契约

```json
{
  "schemaVersion": "intake-batch-v1",
  "mode": "single",
  "items": [
    {"itemCode": "I01", "path": "C:/teacher/q1.jpg"},
    {"itemCode": "I02", "path": "C:/teacher/q2.jpg"}
  ]
}
```

- `itemCode` 从 `I01` 连续排列，最多 `I20`。
- 输入图片可以使用教师提供的绝对路径；相对路径以输入清单所在目录为准。
- 每项在调用前计算文件名、字节数、SHA-256 和不可逆路径指纹。内容或路径身份改变后必须使用新状态文件，不能误续跑；状态不保存输入路径。

## 命令

```powershell
python -X utf8 <skill-root>/scripts/intake_batch.py start `
  --input <私有批量输入.json> `
  --state <私有批量状态.json>

python -X utf8 <skill-root>/scripts/intake_batch.py status `
  --state <私有批量状态.json>
```

`start` 复用现有 `IntakeService.start`，不新增后端 API：

- `single` 成功项保存一个公开 `problemId`；
- `chat` 成功项保存候选会话，不自动选择候选；
- 每项会话原子写入状态文件旁的 `sessions/<批次摘要>/Ixx.json`，不同批次互不覆盖；
- 每项结束立即原子写主状态；普通失败记录安全错误码后继续下一项；
- 重试时，持久状态为 `created` 的项返回运行结果 `no_change`，不再次上传；只重试 `failed` 或 `pending`。

## 状态与隐私

持久状态只有 `pending / created / failed`。`no_change` 只是某次运行的结果，不覆盖成功状态。

状态只保存：批次版本、模式、输入摘要、`itemCode`、文件名、SHA-256、大小、相对会话文件、公开本地题目 ID 和安全错误摘要。不得保存绝对路径、图片字节/base64、题干、学生姓名/学号、密钥、Provider 原始响应或飞书远端 ID。

状态损坏、输入摘要冲突、会话文件无法落盘或主状态无法原子替换时停止整批。已经成功落盘的项目保持不变；后续 OCR、教师确认修订和飞书发布仍按 `intake-contract.md` 逐题推进。

会话已经写好而主状态写入失败时，重跑会从原会话恢复，不再次上传。如果服务端已创建题目但会话未保存，状态会保留公开的来源/题目 ID；`status` 可取回这些 ID，Agent 修复会话后再继续。该错误不能作为普通上传失败重试，避免重复创建。

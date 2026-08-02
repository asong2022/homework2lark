# 夸克扫描王错题本新增同步

## 适用范围

当教师明确说“从夸克扫描王/试卷宝错题本收题”时使用本入口。它只把夸克当作单题图片来源，导入后仍走本 Skill 已有的 `single -> OCR -> 教师确认修订 -> 飞书 Base`。它不是新的题目模型、OCR Provider 或自动发布流程。

该入口使用夸克 App 的私有接口，可能随 App 更新而变化。不要描述成夸克官方稳定开放 API；接口变化时保留本地状态，报告稳定错误并等待适配器更新。

## 最重要的历史隔离规则

第一次使用必须先运行 `baseline`：

```powershell
python <skill-root>/scripts/quark_wrongbook.py baseline
```

`baseline` 只读取当前全部 question ID 并标记为 `baseline_excluded`。它不下载图片、不创建本地 SourceAsset/ProblemAsset、不运行 OCR、不写飞书。当前夸克错题本里已经存在的题以后也不会自动变成 pending。

重复 `baseline` 是本地 `no_change`，不重新联网，也不能用来把后来新增的题隐藏进历史基线。若教师确实想收录基线前的旧题，改走普通单题截图/图片收题，不手改增量状态。

## Agent 操作顺序

1. 用户仍先选择收集方式 1/2/3。夸克错题本当前只提供单题来源，不提供班级实名批改证据；通常由用户明确选择“1 教师精选”。
2. 首次执行 `baseline`，只告诉教师排除了多少道历史题，以及下载/建题/飞书写入均为 0。
3. 以后执行 `sync`。它只把相对本地状态新增的 ID 标为 `pending`：

   ```powershell
   python <skill-root>/scripts/quark_wrongbook.py sync
   python <skill-root>/scripts/quark_wrongbook.py status
   ```

4. 向教师报告新增数量和安全候选 ID，等待教师说“全部导入”或明确选择 ID。未选择的 pending 保留下次继续显示。
5. 教师选择后执行其一：

   ```powershell
   python <skill-root>/scripts/quark_wrongbook.py import --all-pending
   python <skill-root>/scripts/quark_wrongbook.py import --question-id <id> --question-id <id>
   python <skill-root>/scripts/quark_wrongbook.py ignore --question-id <id>
   ```

6. `import` 返回公开本地 `problemId` 后，从同一 ID 继续 OCR、修订、题图检查和授权后的 Base 发布。它本身不自动 OCR 或写飞书。

## 凭据与私有状态

只在运行命令的私有进程环境中提供：

```powershell
$env:QK_UT='<private>'
$env:QK_KP='<private>'
python <skill-root>/scripts/quark_wrongbook.py sync
Remove-Item Env:QK_UT
Remove-Item Env:QK_KP
```

不要把 `QK_UT/QK_KP` 放进命令参数、聊天回显、仓库 `.env`、日志、Base 或状态文件。普通 `status/ignore` 不需要凭据；重复 baseline、重复导入已成功题目也不触发联网或重新索取凭据。

默认状态保存在用户目录 `.shi-homework2lark/quark-wrongbook-state.json`。Agent 可用 `SHI_HOMEWORK2LARK_QUARK_STATE` 或 `--state` 指定其他私有位置，但普通回复不回显绝对路径。状态只保存：

- question ID；
- `baseline_excluded | pending | imported | ignored`；
- 首次发现/更新时间；
- imported 对应的本地公开 `problemId`。

不保存题干、学生身份、图片、长期图片 URL、鉴权 URL、Provider 原文或飞书远端 ID。

## 失败恢复

- `baseline_required`：先建立首次历史基线；
- `quark_*_unavailable/http_error`：保留原状态，稍后重试，不静默切换来源；
- `quark_pagination_repeated/page_limit/invalid_response`：私有接口结构或分页异常，停止，不把不完整目录当成功；
- `question_unavailable`：所选 pending 已从夸克列表消失，保持 pending；
- `quark_image_*`：不创建本地题目，保持 pending；
- 本地 FastAPI 错误：保持 pending，修复 API 后重试；
- `state_write_failed` 且返回 problem ID：题已进入本地证据层，不要重复导入；保留该 ID 并修复私有状态。

批量导入逐题提交。前面的题成功、后面的题失败时，已成功题保持 imported；运行 `status` 后只重试仍为 pending 的题。

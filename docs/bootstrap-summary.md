# Bootstrap Summary

## 1. Trellis 与产品边界

- profile：`llm-app`
- preset：`standard`
- adoption：L1 项目 Spec + L2 Trellis 任务
- phase：Phase 1 / MVP
- 用户：单教师、本机、无账号
- 唯一入口：Codex、Hermes 等 AI Agent 对话

教师不需要安装或打开图形界面。Skill 负责流程编排，FastAPI 保存本地证据，飞书 Base 负责长期目录、筛选和复用。

## 2. 主要目录

```text
.agents/skills/shi-homework2lark/  唯一用户入口、确定性脚本和模板
apps/api/                          FastAPI、领域/应用/基础设施、Alembic、测试
packages/contracts/                FastAPI OpenAPI 快照
docs/                              产品与架构文档
storage/                           原图、裁图和 Provider 私有证据
data/                              SQLite 运行数据
.trellis/spec/                     L1 项目知识
```

## 3. 技术栈

- Python 3.11/3.12、FastAPI、Pydantic v2、SQLAlchemy 2、Alembic、Pillow、Uvicorn。
- SQLite + Repository/Unit of Work。
- 本地文件系统 + `StorageAdapter`，数据库只保存不透明 storage key。
- 托管 `PaddleOCR-VL-1.6` 为默认 OCR；本地 PaddleOCR 3.x 是可选回退。
- 教师用户身份下的 `lark-cli` 操作飞书 Base。

## 4. 当前端到端流程

```text
教师把图片/PDF/Word/单题截图发给 Agent
或从已完成首次基线的夸克错题本选择未来新增题目
→ 教师选择三种收集方式之一
→ 文档页面化
→ manual + frame / Yescan 候选 / 单题整图
→ FastAPI 保存 SourceAsset、ProblemRegion 和裁图
→ 追加 OCRRun
→ 教师确认非空修订，成为 ProblemAsset 当前版本
→ 显式发布到飞书错题页面/错题题目
→ 整理错题记录
→ 生成并写回变式题
→ 生成班级/个人练习
→ 再练反馈回到学习闭环
```

一道题始终是一个逻辑资产；文字、选项和题图不会按 OCR block 拆开。题号单独保存，不重复进入题干。

## 5. OCR 与题图

- 生产默认：`PaddleOCRVLAPIProvider` / `PaddleOCR-VL-1.6`。
- 自动化测试：测试目录内注入 stub/transport，不作为教师配置出现。
- 真实云端测试：只在显式授权、私有 Token 和样本存在时运行。
- OCR 负责文字证据；原始高清页面负责视觉边界和题图真值。
- 完整题图、题干图片上传后必须回读检查。

## 6. 已实现能力

- 图片原始证据、区域、裁图、OCR、不可变修订、当前题目资产和幂等飞书发布。
- PDF/Word 的 Agent 层页面化与分批批改作业录入。
- 四表空白 Base 模板、Schema/视图契约和一键初始化。
- 错题记录按“同题、同次作业、同一错误原因”分组学生和典型真实作答。
- 变式题独立表、班级/个人练习纸、再练事件与 Base 投影。
- 夸克扫描王错题本可选入口：首次只建立排除基线，后续只发现新增题，经教师选择后复用单题录入。

## 7. 未实现与风险

- 不包含学生账号、班级权限、多教师协作、后台队列、微服务、向量库或自动整卷判分。
- 没有图形界面；Agent 无法可靠确定完整边界时必须请求单题截图。
- 托管 OCR 依赖外网、额度和 Token，并涉及题目裁图发送到第三方。
- SQLite 与单进程只适合当前单教师 MVP。
- 班级名单、作业原件、OCR 原文、练习 manifest 和反馈文件都必须保持私有。
- 夸克错题本入口依赖非公开接口与教师本机登录态，接口可能变化；失败时不会自动导入历史题或扩大范围。

## 8. 下一步

Agent-only 收题与“只同步夸克错题本未来新增题目”的可选入口完成后，下一项独立工作是精简并验证公开 CI；本轮不提前处理 CI。

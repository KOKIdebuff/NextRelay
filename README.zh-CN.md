<p align="center">
  <img src="docs/readme/assets/hero.svg" alt="NextRelay 续程——让项目在多个 AI 会话之间持续推进" width="100%">
</p>

<h2 align="center">Conversations end. Progress continues.</h2>

<p align="center">通用 AI 工作管理与协调平台。<br>把多个会话中的项目成果、任务进展和工作上下文放在一起。</p>

<p align="center">
  <a href="#看看工作流程">演示</a> ·
  <a href="#nextrelay-的实现结构">系统架构</a> ·
  <a href="README.md">English</a>
</p>

<p align="center">
  <a href="docs/ui/t11-real/tasks-real.png"><img src="docs/ui/t11-real/tasks-real.png" alt="真实本地工作台：任务状态、验收依据与精确版本资料阅读器" width="100%"></a>
</p>

## 下一段会话，应该接得住已经做过的工作

新开一个 AI 会话，又要解释一遍项目背景。几个会话同时推进，成果却散落在不同地方。改了什么？哪个任务被阻塞？之前的决定还有效吗？

**NextRelay 的产品目标，是让这些项目历史真正服务于后续工作。** 主动带入你选择分享的成果，了解项目现状，为下一步做好准备。

- **继续使用熟悉的 AI 工具。** 同一平台或多个平台、一个或多个会话均可。无须由 NextRelay 启动会话，也不强制采用特定 Prompt 或 Skill。
- **把工作成果放回项目。** 产品设计将成果、文档、版本和证据关联到所属项目。
- **看清下一步。** 通过任务与依赖了解进展、阻塞以及可以并行的工作。
- **让关键决定保持明确。** 会话结束不等于任务验收；候选变更、审查与正式提交是不同步骤。

项目状态只反映已提供的资料及其证据情况。NextRelay 不静默采集对话，也不持续监控外部会话。

## 看看工作流程

### 1. 把会话成果带回项目

选择资料，核对处理范围，逐项查看导入结果。

[![合成原型：选择导入批次、核对授权范围并查看逐项结果](video/out/gifs/01-import-results.gif)](video/out/gifs/01-import-results.gif)

*当前本地版本支持文件上传与格式解析。*

### 2. 先核对，再更新项目

查看建议状态、来源依据与影响，再确认变更。

[![合成原型：确认前检查候选变更与来源依据](video/out/gifs/02-review-changes.gif)](video/out/gifs/02-review-changes.gif)

*原型中的确认仅到“待验收”。真实本地工作台将保存候选、审查、正式提交分为独立操作；原生提取是独立操作，会保存有来源依据的候选。*

### 3. 看清依赖，找到下一步

在任务列表与任务图之间切换，检查前置条件、阻塞和可执行工作。

[![合成原型：检查任务依赖并筛选下一步可执行工作](video/out/gifs/03-task-dependencies.gif)](video/out/gifs/03-task-dependencies.gif)

## 当前能做什么

当前代码：**nextrelay 0.8.0 · schema v8**。目前为使用合成资料的本地开发实现，另保留独立的内存交互原型。

| 范围 | 当前交付 |
| --- | --- |
| 项目与文件 | 创建／选择项目、上传本地文件、逐项查看结果、重试失败项。本地格式支持 TXT、Markdown、协议 JSON 和静态 HTML。 |
| 资料与证据 | 阅读已保存正文、具名来源、精确成果版本及关联证据。 |
| 原生组织 | 提取实际格式正文、匹配多任务／Session／Attempt、保留独立来源、归并互补内容、提示冲突与自动识别修订，支持纠正。 |
| 变更与历史 | 使用既有服务保存候选、审查、正式提交已批准变更，查看历史与单次补偿撤销。 |
| 任务与依赖 | 读取任务列表／任务图和依赖状态；既有服务支持任务生命周期、复核、有限检查及人工验收。 |
| 持久化 | 真实本地模式使用 SQLite 与明确选择的原件目录；合成预览使用内存，刷新后重置。 |
| 尚未接通 | 模型处理、GitHub 仓库读取、云端保存与 Context Sync。删除／恢复及完整开发准备流程也尚未完成。 |

本地子集不等于完整 MVP 或生产服务，不构成性能或生产就绪承诺。

## 三个模块，接续同一个项目

### Project Black Box — 留下工作经过与依据

负责归并用户主动提供的会话成果，保留来源、决策和变更历史。输出可追溯的候选更新，不静默改写正式状态。

**当前：** 本地导入、正文／来源／版本阅读和变更审查服务提供了部分基础。已接入原生提取、可解释匹配、互补视图、冲突检测与可纠正版本关系。

### Control Tower — 看清工作推进到哪里

负责管理任务关系、进度、依赖和阻塞。任务是图节点，前置依赖是连线；会话、工作回合和成果可以关联任务。

**当前：** 本地工作台提供任务列表、任务图、依赖状态及既有生命周期／复核服务。任务图描述工作关系，不负责执行外部 AI Agent。

### Context Sync — 为下一段会话准备上下文

规划中的按需交接模块，用于读取项目当前状态，提供后续工作所需上下文。设计上区分有效正文与未决提醒。

**状态：** 目前仅有合成交互原型；真实本地工作台没有 Context Sync 生成或复制服务。[查看原型片段](video/out/gifs/04-context-handoff.gif)。

## 这些环节如何衔接

[![产品流程图：明确区分当前本地步骤与规划中的语义处理、上下文交接](docs/readme/assets/workflow.zh-CN.svg)](docs/readme/assets/workflow.zh-CN.svg)

闭环为：在 AI 工具中工作 → 主动提供成果 → 整理候选更新 → 审查变更 → 了解项目状态 → 继续推进；需要时获取上下文交接。本地原生整理已接通；真实 Context Sync 仍属于规划能力。

## NextRelay 的实现结构

| 层次 | 当前实现 |
| --- | --- |
| 工作台 | HTML/CSS 与原生 JavaScript；真实 `LocalAdapter` 与独立内存 `SyntheticAdapter`。 |
| 本地应用 | Python 3.14 标准库 WSGI 服务，仅绑定 `127.0.0.1`，使用临时开发 Bearer 凭据。 |
| 业务状态 | SQLite 事务、项目版本检查、独立候选／审查／正式提交及持久请求收据。 |
| 原件 | 明确选择的本地目录，保留逐文件处理与重试历史。 |

三个机制直接影响使用体验：

- **来源与精确版本：** 可以检查某项状态或决定具体依据哪份资料。
- **审查后再改正式状态：** 建议更新不等于已经接受的事实。
- **明确表达不确定性：** 导入不完整、能力不可用、写入结果待确认时，保留可见提示。

**许可证：** 当前工作副本没有根项目许可证文件，尚未在此声明项目整体的再分发条款。


## T08 原生提取本地入口

使用 Python 3.14，在仓库与 OneDrive 以外创建独立合成测试库和既有原件目录。配置 `NEXTRELAY_ENV=development`、`NEXTRELAY_AUTH_MODE=dev-token`、新生成的 `NEXTRELAY_DEV_TOKEN`、`NEXTRELAY_DB_PATH`、`NEXTRELAY_LOCAL_ROOT` 和空闲 `NEXTRELAY_PORT`，显式执行 `python -m nextrelay init-db`，再运行 `python -m nextrelay serve`。启动服务不会自动迁移；现有库升级须先停止其服务并明确执行初始化／升级。本轮没有修改既有用户数据库。

真实模式的资料页上传 TXT／Markdown／协议 JSON／静态 HTML 后，可点击“执行／恢复原生提取”，检查输入版本、SHA-256、具名来源、行号／JSON Pointer、匹配依据、互补与冲突、自动版本关系。可填写项目内 Task／Session／Attempt ID 列表纠正归属；多任务／多回合且多会话时须提供 contributions 三元组（task_id、session_id、attempt_id），未知项用 null，系统不会从身份列表猜测全部配对；版本关系 JSON 的 family_id 与 parent_version_id 均填 null 可分离为独立成果。已有子版本的父版本须先处理子版本。纠正追加历史并使旧候选批准失效；正式效力的纠正仍走既有单次撤销和新候选。保存、批准审查、正式提交彼此独立。

识别规则支持 Task／任务、Session／会话、Attempt／回合、Goal／目标、Completion conditions／完成条件、结论、决策、风险、缺口及键值事实；多个身份以分号分隔。稳定 ID、项目内唯一标题和 namespace::external_id 可用于匹配。`# Task 描述性标题` 或未匹配的描述性任务名称可恢复最小任务候选；未知 ID、歧义或项目冲突保留待确认。普通正文与章节完整保留，不声称任意自然语言推理。JSON 沿用 nextrelay.import v1，声明放在 text 中；身份、授权、测试通过等导入声明不具权威。

HTML原生正文包含惰性的标题级别与表格单元格结构，带源行及单元格指针，不同列划分不会错误去重。原生处理器为 nextrelay-native/2，旧结果不覆盖。相同正文复用不可变版本且保留独立来源；同标题、词元三元组 Jaccard >=0.80 且唯一成果族时自动识别修订。互补视图保留组成版本和来源，矛盾事实明确标记冲突；仅相似、缺少结构依据的正文保持未归并。自动版本关系不切换主基线、不使成果适用，也不触发验收。

原生处理上限：每输入100个文档／2 MiB，单文档256 KiB UTF-8／40,000词元／500字段或章节，每类身份声明100项，项目比较版本（含本次文档）200项。超限显式失败且原生事务回滚，不截断冒充成功，T07原件保留。API与持久化契约见 Architecture 9.7。后端全量命令为 `python -B -W error::ResourceWarning -m unittest discover -s tests -q`；前端执行 `npm run check`、`npm test`、`npm run build`；真实浏览器探针为 frontend/tests/native-browser.mjs（参数 --python、--playwright、可选 --browser）。模型、GitHub、云端保存、Context Sync 和整项 T11 仍未完成。

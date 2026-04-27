# 代码仓库内容分析（youtube-script）

## 1) 仓库目标与定位

该仓库是一个**本地实验型**项目，核心目标是把 WhisperX 的词级时间戳转录结果切成“句子/语义单元”，同时严格保证：

- 不丢词、不重词、不改词序；
- 每个词被且仅被分配到一个输出单元；
- 输出单元保留可用于音频裁切的时间范围（含前后 padding）。

README 也明确当前主线是“语法优先（Stanza）”的本地方案，并把 LLM 方案定位为 cut-point 实验。 

## 2) 主要数据与文件角色

- 输入主数据：`transcribe-whisperx_result.json`（WhisperX 原始转录，含 `segments` 与 `word_segments`）。
- 主输出（当前候选）：`sentence_units_pure_grammar_fine_30_quality_v9.json`。
- 主粗分块输出：`coarse_blocks_pure_grammar.json`。
- LLM 实验链路文件：
  - `make_llm_cutpoint_payload.py`（构造给 LLM 的切分载荷）；
  - `llm_cutpoints_one_shot.json`（LLM 返回切点）；
  - `apply_llm_cutpoints.py`（按切点还原为单元）；
  - `sentence_units_llm_one_shot.json`（LLM 路线输出）。
- 质量/审计：
  - `verify_coarse_nonoverlap.py`（粗分块覆盖、重叠、空洞检查）；
  - `audit_boundaries_stanza.py`、`audit_segments_stanza.py`（句法边界审计）。

## 3) 代码结构与演进轨迹（从文件命名推断）

仓库存在多代切分实现：

1. `split_sentences.py`：较早的启发式版本（标点、停顿、最大长度控制等）。
2. `split_sentences_general.py`：更通用规则版（更多 fragment merge/split/rebalance 逻辑）。
3. `split_sentences_stanza_dp.py`：引入 Stanza 与 DP（动态规划）代价函数。
4. `split_sentences_grammar_coarse.py`：当前主线，采用“先粗分块，再块内细分”的语法优先方案。

从 README 与输出命名看，当前基线是第 4 类方案。

## 4) 当前主线算法（grammar_coarse）

`split_sentences_grammar_coarse.py` 体现出两阶段设计：

- 阶段 A：利用 Stanza 句法/句子信息得到 coarse ranges，并做修复、列表项合并等处理；
- 阶段 B：在每个 coarse block 内做 DP 细分，代价函数综合：
  - 边界奖励（停顿、源段边界等）；
  - 词法惩罚（弱起始词、危险结尾词、功能词边界惩罚）；
  - 句法跨边界惩罚（dependency crossing）；
  - 时长/词数目标与上限约束。

这种设计优点是：先保证宏观语义完整，再局部优化时长与可切性。

## 5) LLM cut-point 方案定位

LLM 链路非常“克制”：

- `make_llm_cutpoint_payload.py` 只输出词序列与硬规则，不要求 LLM 改写文本；
- 输出 schema 只接受 `cut_after_word_indices`；
- `apply_llm_cutpoints.py` 会验证切点合法性（排序、去重、是否覆盖最后词、是否越界），然后机械重建单元。

因此该方案本质上是“LLM 只决策切点，程序负责确定性落地”。这是一个对生产稳定性更友好的接口边界。

## 6) 数据规模与现状（基于现有 JSON 统计）

仓库现有样本显示：

- 原始词数：6239（`transcribe-whisperx_result.json`）；
- grammar 主线输出：421 单元，`all_words_assigned = true`；
- LLM 一次性切点输出：209 单元，`all_words_assigned = true`。

说明两条链路都能完成“全覆盖分配”，但粒度明显不同（LLM 结果更粗）。

## 7) 工程特征

- 依赖极简：`requirements.txt` 当前仅声明 `stanza`；
- 大量实验快照 JSON（v2~v9、audit/report）保留在仓库中，便于回溯参数与效果；
- 脚本多为单文件 CLI，适合离线迭代与对比实验。

## 8) 可能的改进点（不改代码，仅分析建议）

1. **实验管理**：将结果快照按 `runs/<date>-<strategy>/...` 归档，降低根目录噪音。
2. **统一评估**：增加统一评估脚本，汇总每个输出的时长分布、词数分布、疑似坏边界比例。
3. **可复现实验配置**：把关键参数固化到 YAML/JSON 配置，减少命令行漂移。
4. **依赖与环境文档**：补充 Stanza 模型下载、Python 版本、运行顺序说明。
5. **回归检查**：对“全词覆盖、无重叠、无空洞”设置自动化检查入口。

---

如果你愿意，我下一步可以给你一份“从输入到最终可裁剪片段”的**建议标准流水线**（含命令顺序、推荐参数和结果验收阈值）。

# 不依赖词表的语法切分策略总结

本文档总结当前二阶段 clause-level 切分实验中已经验证有效的通用方法。核心目标是：

> 在不依赖 LLM、不改写原文、尽量不使用词表兜底的前提下，把超长复合句拆成语法安全、语义相对完整、适合单独播放的片段。

## 1. 总体结论

我们当前最重要的成功经验是：**不要直接用单词本身判断能不能切，而要用这个单词在句法结构中的角色判断。**

不推荐的规则形式：

```text
because 不能开头
and 不能结尾
to 不能结尾
of 不能结尾
```

推荐的规则形式：

```text
如果边界切断 aux / det / case / mark / acl / nsubj / obj 等关键依存关系，则禁止。
如果片段边缘的 mark / case / aux / det / cc 等角色依附到片段外，则认为片段不完整。
如果新片段内部有独立 root / predicate，则它更可能是安全切点。
```

这样做的好处是：

- `because / when / if` 可以统一成 `mark`。
- `of / in / for / with` 可以统一成 `case`。
- `the / a / my / your` 可以统一成 `det`。
- `do`、`that`、`and` 这类多义词不再按词面一刀切，而是看它在 Stanza 分析中的真实角色。

## 2. 两类判断必须分开

切分系统里有两个不同问题，不能混在一起：

```text
boundary dependency safety:
  这个切点有没有切断强语法依存关系？

segment completeness:
  切出来的片段自己是否是闭合、可单独播放的单位？
```

当前推荐结构：

```text
1. dependency_candidate_boundaries()
   只生成语法上值得考虑的候选切点。

2. dependency_boundary_verdict()
   判断候选切点是否切断关键依存关系。
   这一层可以 hard forbid。

3. segment_completeness_cost()
   判断片段自身是否完整。
   这一层不生成新切点，也不重复做 crossing 判断。
   它只给 DP 增加强惩罚。

4. DP 全局选择
   在安全候选点之间选择总成本最低的切分方案。
   当完整性和长度冲突时，完整性优先。
```

## 3. 候选切点：从语法结构生成

候选切点不应该只来自标点，也不应该来自手写词表。当前有效的通用候选来源包括：

### 3.1 并列结构

Stanza 中 `cc` 表示 coordinating conjunction，即并列连词关系。

例子：

```text
..., but I just want to emphasize ...
..., and you're in your country ...
```

候选点可以放在 `cc` 前：

```text
... / but I just want ...
... / and you're ...
```

但不能把 `cc` 留在左边结尾：

```text
bad:
... and /
... but /
```

所以当前策略是：

```text
cc_before_connector 可以作为候选。
stranded cc hard forbid。
```

### 3.2 从属结构

Stanza 中 `mark` 是从属标记或不定式标记，比如：

```text
because ...
when ...
if ...
to do ...
```

候选点可以放在 `mark` 前：

```text
... / because ...
... / if ...
```

但这类候选需要完整性层继续判断右侧是否能独立播放。

### 3.3 clause 子树

当前作为候选来源的 clause-level 依存关系包括：

```text
advcl
acl
ccomp
conj
parataxis
```

它们分别覆盖：

- `advcl`: 状语从句，如 `if you listen carefully`
- `acl`: 名词修饰性从句，如 `the word do`
- `ccomp`: 补足从句，如 `I think that...`
- `conj`: 并列谓语或并列句
- `parataxis`: 松散并列、插入说明、口语转述

### 3.4 独立 root 起点

这是最近一次实验中很重要的改进。

问题样本：

```text
By the way guys, if you are looking for more ways to improve your English to speak like a native speaker, I have created a workbook in English which has All of the rules that you can think of. We have idioms there.
```

这里不应该靠句号生成候选，而应该靠 Stanza 识别出的第二个独立 root：

```text
have -> root
We -> nsubj
idioms -> obj
there -> advmod
```

因此新增候选类型：

```text
independent_root_start
```

规则：

```text
对每个 root 取它的依存子树范围。
如果这个 root 子树不是从当前 block 开头开始，则在该子树起点前加入候选切点。
```

效果：

```text
... think of. / We have idioms there.
```

这个切点来自语法 root，不来自标点。

## 4. 禁切判断：只处理边界依存安全

边界层的职责是回答：

> 这里切开会不会破坏强语法关系？

当前有效的分层策略：

### 4.1 强绑定关系：直接禁止

```text
aux
case
cop
det
fixed
flat
mark
```

典型例子：

```text
can / speak        aux
in / America      case
is / useful       cop
the / word        det
because / of      fixed
New / York        flat
to / learn        mark
```

这些关系被切断时，通常不是“片段不优雅”，而是语法结构已经坏了。

### 4.2 核心关系：用结构闭合代替固定距离

```text
nsubj
csubj
obj
iobj
xcomp
ccomp
```

典型例子：

```text
They / speak       nsubj
I like / music     obj
I want / to learn  xcomp
He said / that...  ccomp
```

早期策略曾经使用固定距离阈值：

```text
距离较近时 hard forbid。
距离较远时加高成本。
```

但这个规则适应性差，因为：

```text
距离近 ≠ 一定强绑定
距离远 ≠ 一定可以切
```

更通用的做法是看语法结构是否被切开、以及被切开的那一侧是否能在片段内部闭合：

```text
核心论元关系跨边界：
  nsubj / obj / iobj / xcomp
  => 默认禁切

核心从句关系跨边界：
  ccomp / csubj
  => 检查 child 所在侧的 head 链
     如果能在当前片段内部闭合到 independent anchor，则可加成本
     如果一路依附到片段外，则禁切
```

也就是说，我们不再问：

```text
child 和 head 相隔几个词？
```

而是问：

```text
切开后，每一侧有没有自己的结构闭合点？
```

这比固定数字更通用，也更符合语法结构本身。

### 4.3 acl 的经验

`acl` 是 adnominal clause，即修饰名词的从句或动词性结构。

关键样本：

```text
at the beginning of the word do
```

Stanza 分析：

```text
do -> word    deprel=acl
```

错误切法：

```text
at the beginning of the word / do
```

经验：

```text
不要只用 local_acl_distance 判断。
如果 acl 修饰的是 NOUN / PROPN / PRON，且切点把名词和 acl 子树切开，应禁切。
```

这个规则的重点不是距离，而是：

```text
名词中心语 + acl 修饰子树
```

是否被切成两段。

如果被切开，即使距离不是固定阈值内，也可能是不安全的；如果没有切开，则不应该因为关系名本身过度惩罚。

### 4.4 去固定距离阈值的原则

当前更推荐的结构化 policy 是：

```text
A. tight function relations
   aux / case / cop / det / fixed / flat / mark
   => 无条件禁切

B. core argument relations
   nsubj / obj / iobj / xcomp
   => 跨边界默认禁切

C. core clause relations
   ccomp / csubj
   => 用 child 侧 head 链是否在片段内闭合来区分

D. nominal acl relations
   acl 修饰 NOUN / PROPN / PRON
   => 名词中心语和 acl 子树被切开时禁切

E. looser clause relations
   advcl / conj / parataxis 等
   => 不直接禁切，交给成本和完整性判断
```

这套方法的普适思想是：

> 用语法结构类型和闭合性判断替代固定词距。

固定距离规则是表面近似；结构闭合规则才是我们真正想判断的东西。

## 5. 完整性判断：只看片段自身是否闭合

完整性层不再回答“有没有切断依赖”，因为那是边界层的职责。

它只回答：

> 这个 span 自己能不能作为一个闭合片段播放？

当前有效画像包括：

```text
clause anchors
independent anchors
dependent anchors
first syntactic role
last syntactic role
external edge roles
```

### 5.1 predicate / clause anchor

片段内部需要有自己的主干。当前使用：

```text
VERB / AUX
root / conj / parataxis / advcl / ccomp / acl / xcomp
```

同时考虑系表结构：

```text
ADJ / NOUN / PRON + cop
```

### 5.2 independent anchor

更适合作为独立片段主干的关系：

```text
root
conj
parataxis
```

如果片段只有：

```text
advcl
acl
ccomp
xcomp
```

而没有独立主干，就可能只是从属结构。

### 5.3 dangling start / dangling end

早期错误做法：

```text
只要片段首尾 token 是 case / mark / cc / det，就惩罚。
```

这个太粗，会误伤：

```text
By the way ...
think of.
```

因为 `By` 和 `of` 虽然是 `case`，但它们的 head 在当前片段内部，并不悬空。

修正后的经验：

```text
只有当片段边缘 token 的 head 在片段外时，才认为它是悬空角色。
```

也就是：

```text
role in {mark, case, aux, det, cc, cop, fixed, flat}
and head outside current span
=> dangling edge
```

### 5.4 短引入碎片

短片段如果没有 predicate，且以软标点结尾，通常不是完整片段。

例子：

```text
By the way guys,
For example,
And another thing,
```

当前处理：

```text
无 predicate
且 word_count >= min_words
且以软标点结尾
=> intro_fragment_no_predicate 强惩罚
```

这避免了把导入语单独切出去。

### 5.5 head 链闭合原则

这是完整性判断里非常通用的一条规则：

> 不要只看片段最后一个结构的关系名，而要看它沿 head 链最终是否在当前片段内部闭合。

错误的粗规则：

```text
最后一个 clause anchor 是 advcl / acl / ccomp / xcomp
=> 片段不完整
```

这个规则会误伤完整的关系从句或补足结构。

更好的规则：

```text
最后一个 clause anchor 是 advcl / acl / ccomp / xcomp
沿 head 链向上查找
如果能在当前片段内部找到 root / conj / parataxis 等 independent anchor
=> 这个片段内部闭合

如果 head 链一路跑到当前片段外
=> 这个片段依赖后面的主干，可能是不完整的 intro_ending
```

完整例子：

```text
I have created a workbook which has all of the rules that you can think of. / We have idioms there.
```

最后的关系从句是：

```text
that you can think of
```

它的依存链可以在当前片段内部闭合：

```text
think -> rules -> All -> has -> workbook -> created(root)
```

所以 `think of.` 虽然属于关系从句的一部分，但它最终回到了当前片段内部的主句 `created(root)`。这个片段是完整的，可以在后面切出：

```text
... think of. / We have idioms there.
```

不完整例子：

```text
And another thing that you might have noticed, when we say what do, / so we have T ...
```

左片段结尾结构是：

```text
when we say what do
```

它的依存链是：

```text
do -> say -> have
```

但这个 `have` 在切点右边：

```text
左片段: And another thing ..., when we say what do,
右片段: so we have T ...
```

所以左片段最后结构的上级主干不在当前片段内。它没有闭合，属于真正的引入式未完成结构。

因此 `intro_ending` 不应该定义为：

```text
最后是 advcl / acl / ccomp / xcomp
```

而应该定义为：

```text
最后是 dependent clause anchor
并且它的 head 链无法在当前片段内部落到 independent anchor
```

## 6. DP 的作用

DP 不是语法模型，而是全局组合算法。

它负责：

```text
在所有安全候选切点之间，选择总成本最低的一组切法。
```

成本来源包括：

- 长度/时长成本
- boundary dependency cost
- candidate reason cost
- segment completeness cost

当前原则：

```text
依赖切断：硬禁止
完整性问题：强惩罚
长度/时长：次要优化
```

因此当切短和保持完整冲突时，DP 会宁可保留较长复合句。

成功样本：

```text
And another thing that you might have noticed, when we say what do, so we have T at the end of the word what and we have D at the beginning of the word do, we kind of invent a new sound here.
```

这里可疑切点是：

```text
... when we say what do, / so we have ...
```

但左侧是未完成的引入结构。完整性强惩罚后，DP 选择保留 43 词整句，这是合理结果。

## 7. 当前实验效果

加入 `independent_root_start` 和修正 dangling 判断后，测试结果：

```text
output units: 483
split units: 39
all words assigned: True
max words: 43
max duration: 13.207
independent_root_start candidates: 15
completeness_penalty_count: 1
```

对比早期结果：

- 最大词数从 48 降到 43。
- `We have idioms there.` 可以通过独立 root 被切出。
- `By the way guys,` 不再被单独切成碎片。
- `word / do` 这种 `acl` 局部切断被拦住。
- `when we say what do, / so we have...` 这种不完整引入片段被避免。

## 8. 仍需继续评估的方向

### 8.1 句首 cc 的处理

`and / but / so` 不应该因为是 `cc` 就一律惩罚。

如果它后面有完整主谓结构：

```text
but I just want to emphasize ...
and you're in your country ...
so you can get a sense ...
```

这种片段可能可以单独播放。

推荐方向：

```text
cc 开头 + 后续存在 independent anchor => 降低惩罚或允许。
cc 开头但没有完整主干 => 继续强惩罚。
```

### 8.2 片段末尾从属结构

有些片段结尾是条件/从属结构，虽然不一定有逗号，但仍可能不完整：

```text
... if they're getting like ten thousand dollars a month
```

推荐方向：

```text
如果片段最后一个 dependent clause anchor 的 head 链跑到片段外，
且无法在当前片段内部闭合到 independent anchor，
则提高完整性惩罚。
```

### 8.3 教学例子模式

英语教学视频里经常出现短例子：

```text
what do you do?
pet turtle.
social life.
```

这些不一定有完整主谓结构，但作为音频片段是合理的。

推荐方向：

```text
不要用 hard forbid 处理无 predicate。
只在明显引入碎片、悬空边缘、从属结构时强惩罚。
```

## 9. 可复用原则

这套方法的通用性来自四个原则：

```text
1. 用语法角色代替词表。
2. 候选点来自依存结构，不来自表面标点。
3. 禁切判断和完整性判断分层。
4. 完整性参与 DP 评分，而不是一刀切硬禁止。
```

换句话说，我们不是在写“英语单词规则”，而是在写“句法结构规则”。

这也是当前方案能够减少词表兜底、提升可解释性和通用性的根本原因。

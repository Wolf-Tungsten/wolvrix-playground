# GrhSIM 仿真模型形式化定义

状态：初稿。本文定义 GrhSIM 的参考执行语义，不规定具体分区、调度或 C++ 实现。

## 1. 五元组

定义一个 GrhSIM 仿真模型为：

$$
M = (G, I, O, S, E)
$$

为避免混淆，$I$、$O$ 和 $S$ 表示取值空间，$i$、$o$ 和 $s$ 表示一次执行中的具体取值。

| 符号 | 定义 |
| --- | --- |
| $G$ | 仿真流图；其语义由状态转移 $\llbracket G \rrbracket$ 给出 |
| $I$ | 外部输入状态空间 |
| $O$ | 对外发布的输出状态空间 |
| $S$ | 仿真器内部状态空间 |
| $E : S \to Q$ | 从内部状态提取用于判断是否静止的签名 |

$S$ 包含 RTL register、latch、memory，以及边沿判定所需的历史状态。临时结果和调度数据不是 $S$ 的组成部分。

初始状态 $s_{\mathrm{init}} \in S$ 由独立的初始化规则给出，并在第一次 $\operatorname{eval}$ 之前写入内部状态。初始化不属于 $\operatorname{eval}$ 的语义，也不增加到五元组中。

## 2. 流图语义

流图 $G$ 诱导一个确定的状态转移：

$$
\begin{aligned}
\llbracket G \rrbracket &: I \times S \to O \times S, \\
(o_{n+1}, s_{n+1}) &= \llbracket G \rrbracket(i, s_n).
\end{aligned}
$$

对任意输入 $i$ 和状态 $s_n$，$\llbracket G \rrbracket$ 唯一确定配对的输出 $o_{n+1}$ 与状态 $s_{n+1}$。该映射只规定求值结果，不规定内部阶段、执行顺序或中间表示。完整的 $\operatorname{eval}$ 语义见第 4 节。

## 3. 静止签名 $E$

$E(s)$ 是内部状态中与边沿事件或输出变化相关的投影：

$$
(e_{\mathrm{edge}}, e_{\mathrm{out}}) = E(s)
$$

- $e_{\mathrm{edge}}$：所有可能引起边沿事件的状态；
- $e_{\mathrm{out}}$：所有可能引起输出 $O$ 变化的状态。

$E$ 只有这两个分量。二者都取在 $G$ 上的传递依赖闭包：如果一个状态通过若干中间状态间接影响边沿或输出，它仍归入对应分量，不构成第三类。边沿事件的判定属于 $G$ 的语义。

定义投影等价关系：

$$
s \sim_E t \quad\Longleftrightarrow\quad E(s) == E(t)
$$

$E$ 必须是充分而非猜测性的投影。令：

$$
(\operatorname{out}_i(s), \operatorname{next}_i(s))
= \llbracket G \rrbracket(i, s)
$$

则对任意 $i \in I$ 及 $s,t \in S$，应满足：

$$
s \sim_E t
\quad\Longrightarrow\quad
\operatorname{out}_i(s) == \operatorname{out}_i(t)
\;\land\;
E(\operatorname{next}_i(s)) == E(\operatorname{next}_i(t))
$$

这保证静止签名相同的状态具有相同输出，并在再次应用 $\llbracket G \rrbracket$ 后得到相同的静止签名。$E$ 是模型语义的一部分，必须恰好由边沿事件和输出的依赖闭包定义；随意加入无关状态可能改变收敛性，遗漏相关状态则可能过早结束 $\operatorname{eval}$。

## 4. $\operatorname{eval}$ 语义

模型 $M$ 的一次 $\operatorname{eval}$ 调用定义为偏映射：

$$
\operatorname{Eval}_M : I \times S \rightharpoonup O \times S
$$

对任意已定义的结果

$$
(o, s') = \operatorname{Eval}_M(i, s),
$$

$\operatorname{Eval}_M$ 满足以下性质：

1. 输入 $i$ 在整个调用期间保持不变。
2. 令 $s_0 = s$，输出和状态序列满足

   $$
   (o_{n+1}, s_{n+1}) = \llbracket G \rrbracket(i, s_n),
   \qquad n \ge 0.
   $$

3. 令 $k$ 为满足静止条件的最小正整数：

   $$
   k = \min \{n \ge 1 \mid E(s_n) == E(s_{n-1})\}.
   $$

   则返回输出和保存状态分别为

   $$
   o = o_k,
   \qquad
   s' = s_k.
   $$

等价伪代码如下，其中 `eval_G(i, s)` 表示求值 $\llbracket G \rrbracket(i,s)$：

```text
while (true) {
    (o, s_next) = eval_G(i, s)
    if (E(s_next) == E(s)) {
        s = s_next
        return o
    }
    s = s_next
}
```

根据 $E$ 的充分性，再次应用 $\llbracket G \rrbracket$ 不会改变输出或静止签名，因此 $s'$ 是一个投影不动点。

如果不存在有限的 $k$，$\operatorname{Eval}_M(i,s)$ 未定义，即模型在该输入和状态下不收敛。

## 5. 对外执行边界

一次调用遵循以下约束：

1. 调用方在 $\operatorname{eval}$ 前写入输入 $i$；多次写入以调用时的最终值为准。
2. 输入在 $\operatorname{eval}$ 内不可变化；异步外部交互必须显式建模为新的输入或环境状态。
3. $\operatorname{eval}$ 求稳过程中产生的中间输出 $o_n$ 不对外发布；调用方只读取收敛后的 $o_k$。
4. $s_k$ 保存为下一次 $\operatorname{eval}$ 的起始状态。
5. $\operatorname{eval}$ 本身只完成当前仿真时刻的求稳。时钟、复位等时间推进由调用方改变相应输入后再次调用 $\operatorname{eval}$ 表达。

## 6. 小例子

对一个上升沿寄存器：

```text
eval_G(i, s) {
    (clk, d) = i
    (q, prev_clk) = s

    fire = (prev_clk == 0 && clk == 1)
    q_next = fire ? d : q

    o = q_next
    s_next = (q_next, clk)
    return (o, s_next)
}

E(s) {
    (q, prev_clk) = s
    return (prev_clk, q)
}
```

当 $\mathit{clk}$ 从 $0$ 变为 $1$，首次应用 $\llbracket G \rrbracket$ 时识别边沿并更新 $q$ 和 $\mathit{prev\_clk}$；由于 $E$ 改变，$\operatorname{eval}$ 继续求值。再次应用 $\llbracket G \rrbracket$ 时不再产生同一边沿，$E$ 保持不变，$\operatorname{eval}$ 返回稳定的 $q$。

# Ano：版本化运算定义、性质与应用边界

## 1. 对象和版本

逻辑载体为 S = {N（反）, P（正）, U（未知）}，映射 N=0、P=1。
`ano.boolean.v1` 定义：输入包含 U 时 Merge、Cross 均输出 U；其余输入
Merge(a,b)=a XOR b，Cross(a,b)=NOT(a XOR b)。这是自定义有限代数的定义，
不是新颖性或密码安全性的证明。

`ano.refined-equality.v0` 为旧 refined 文件的**有限域比较模型**：
Merge(a,b) 在 a=b 时返回 N，否则返回 P；Cross 在 a=b 时返回 P，否则 N。
旧函数也接受任意 Python 对象；比较模型只研究 S，不执行原始文件或其导入副作用。
集成文件里的 `ano_addition` 和 `ano_multiplication` 另有 0/字符串混用规则，
与 refined 文件不相同，不能用同一版本名称或同一公理说明。

## 2. 两份真值表

| a | b | v1 Merge | v1 Cross | v0 Merge | v0 Cross |
|---|---|---|---|---|---|
| N | N | N | P | N | P |
| N | P | P | N | P | N |
| P | N | P | N | P | N |
| P | P | N | P | N | P |
| N | U | U | U | P | N |
| P | U | U | U | P | N |
| U | N | U | U | P | N |
| U | P | U | U | P | N |
| U | U | U | U | N | P |

## 3. 成立的性质和反例

v1 两运算均封闭、交换、结合。证明结合性可以分两种情况：
三输入中存在 U，则任意括号位置均输出 U；否则回到二值 XOR/XNOR，
直接展开得到同一结果。Merge 的单位元是 N，Cross 的单位元是 P。
U 是两者的吸收元。此处的证明仅对应上述固定有限域定义。

v0 Merge 不结合：Merge(Merge(P,P),U)=P，
Merge(P,Merge(P,U))=N。因而用户提出的括号问题对该版本成立。
v0 的其他性质由 `laws` 报告给出反例，不能从二值子集外推到第三态。

v1 不满足乘法对加法的分配律：
Cross(N,Merge(N,N))=P，而 Merge(Cross(N,N),Cross(N,N))=N。
因此不能把两运算直接称为通常意义上的环运算。

## 4. 数值组合

现代 `AnoNumber` 为 Q(i) × S：数值部分使用精确有理复数，
加法和乘法分别在数值分量与 v1 逻辑分量上逐分量计算。
不存在自动引入的交叉项，也不是把 j 当作具有未知平方关系的传统虚数单位。

在无资源限制的数学模型中，加法和乘法分别结合、交换；分配律受 S 的反例破坏。
实现限制分子、分母各 4096 位，超限抛出错误，因此实现是带资源边界的部分运算。
“所有中间结果均在边界内”是有限数值性质测试的前提，不可将其写成无条件闭包定理。
`ZDANumber` 的 infinity/bottom 是另一套标签扩展，不属于 Q(i) 的域公理。

## 5. 三类验证分别执行

1. 形式性质：固定载体与版本，报告所有 9 对或 27 个三元输入的穷举结果及反例。
2. 实现正确性：独立测试真值表、精确数值组合、版本差异、边界和错误。
3. 应用安全性：Ziokt 的 `defence` 策略仅在全部必需声明为正时 allow，
   未知为 hold，反为 deny；声明必须来自调用层已验证的证据。
   Merge/XOR、投票多数和数学等式都不能替代身份、签名、授权或 AEAD 验证。

`defence` 固定使用 v1 的保守语义，不允许切换到 v0。
输出明确包含 `cryptographic_assurance: false`。

## 6. 可复现接口

```sh
python -m ziokt companion ano truth-table --include-unknown
python -m ziokt companion ano laws
python -m ziokt companion ano laws --profile ano.refined-equality.v0
python -m unittest discover -s tests -p test_ano_laws.py -v
```

穷举只证明被枚举的有限载体上的这些等式；不是对所有可能扩展版本、
无限数值域、程序运行时或网络攻击者的安全证明。

"""
零除算术体系 (Zero-Division Arithmetic, ZDA) 完整实现
===================================================

1. 体系介绍 (Introduction)
--------------------------

ZDA是一种革命性的数学扩展体系，旨在解决传统数学中的除零问题和无限运算困境。它通过三个核心创新：

1. 显式无穷大 (Explicit Infinity): 引入∞符号明确表示无限量
2. 未定义值 (Bottom Value): 用⊥表示真正无意义的运算结果
3. 运算扩展 (Extended Operations): 重新定义所有基础运算使其在这些特殊值上具有明确行为

ZDA is a revolutionary mathematical extension system designed to solve division-by-zero 
and infinite operation problems in conventional mathematics. It introduces three core innovations:

1. Explicit Infinity: Introduces ∞ symbol to explicitly represent infinite quantities
2. Bottom Value: Uses ⊥ to represent truly meaningless operation results
3. Extended Operations: Redefines all basic operations to have well-defined behavior on these special values

2. 哲学基础 (Philosophical Foundation)
------------------------------------

ZDA建立在以下哲学原则上：

• 数学包容性 (Mathematical Inclusivity): 
  所有运算都应被允许，而非禁止"危险"运算
  All operations should be permitted rather than prohibiting "dangerous" ones

• 显式表达 (Explicit Representation):
  特殊状态应该被明确标记，而非隐藏或忽略
  Special states should be explicitly marked rather than hidden or ignored

• 实用一致性 (Practical Consistency):
  系统应在自身框架内保持自洽，同时为实际问题提供解决方案
  The system should remain self-consistent within its framework while providing solutions to practical problems

3. 数学创新 (Mathematical Innovations)
-------------------------------------

3.1 数字系统 (Number System):
- 扩展复数: a + bi (常规复数 | regular complex)
- ∞ : 表示所有类型的无限大 (represents all types of infinity)
- ⊥ : 表示真正未定义的运算结果 (represents truly undefined results)

3.2 运算规则 (Operation Rules):
• 除法 (Division):
  a/0 = ∞ 当 a ≠ 0 (when a ≠ 0)
  0/0 = ⊥ (真正未定义 | truly undefined)
  ∞/∞ = ⊥ (需要进一步分析 | requires further analysis)

• 乘法 (Multiplication):
  0 × ∞ = ⊥ (不确定形式 | indeterminate form)
  ∞ × a = ∞ 当 a ≠ 0 (when a ≠ 0)

4. 应用领域 (Application Domains)
-------------------------------

4.1 计算机图形学 (Computer Graphics):
- 处理透视变换中的除零情况
- Handling division-by-zero in perspective transformations

4.2 物理模拟 (Physics Simulation):
- 模拟奇异点行为 (如黑洞奇点)
- Simulating singular point behavior (e.g., black hole singularities)

4.3 人工智能 (Artificial Intelligence):
- 构建更鲁棒的数值计算系统
- Building more robust numerical computation systems

4.4 金融工程 (Financial Engineering):
- 处理极端市场条件下的数学建模
- Mathematical modeling under extreme market conditions

5. 逻辑系统 (Logic Systems)
--------------------------

ZDA包含四套完整的逻辑体系：

5.1 二值逻辑 (Binary Logic):
- 传统真/假系统，但明确处理∞和⊥
- Traditional true/false system with explicit handling of ∞ and ⊥

5.2 三值逻辑 (Ternary Logic):
- 真/假/未知系统，其中未知表示∞或⊥
- True/false/unknown system where unknown represents ∞ or ⊥

5.3 辩证法逻辑 (Dialectical Logic):
- 正题/反题/合题系统，用于矛盾分析
- Thesis/antithesis/synthesis system for contradiction analysis

5.4 结构逻辑 (Structural Logic):
- 直接映射到ZDA算术运算的逻辑系统
- Logic system directly mapped to ZDA arithmetic operations

它们还有衍生，如蕴含运算扩展，模糊逻辑，量子逻辑等。

6. 实现特点 (Implementation Features)
-----------------------------------

• 完整类型系统 (Complete Type System):
  - 严格的类型检查和转换
  - Strict type checking and conversion

• 数学完备性 (Mathematical Completeness):
  - 实现所有基础运算和高级函数
  - Implements all basic operations and advanced functions

• 实际可用性 (Practical Usability):
  - 提供矩阵运算等高级功能
  - Provides advanced features like matrix operations

7. 示例 (Examples)
-----------------

>>> from zda import ZDANumber
>>> a = ZDANumber(3, 4)  # 3+4i
>>> b = ZDANumber(0)     # 0
>>> a / b                # 结果为∞
∞
>>> b / b                # 结果为⊥
⊥
>>> import zda_logic
>>> logic = zda_logic.ZDABinaryLogic(a/b)  # ∞在逻辑系统中的表现
>>> print(bool(logic))    # 根据逻辑系统设置返回True或False

8. 引用与参考 (References)
------------------------

[1] ZDA白皮书: 《零除算术体系的理论基础》
[2] Smith, J. (2023). "Extended Mathematics for Computational Systems"
[3] 李华 (2022). 《超越极限的数学》科技出版社

[1] ZDA Whitepaper: "Theoretical Foundations of Zero-Division Arithmetic"
[2] Smith, J. (2023). "Extended Mathematics for Computational Systems"
[3] Li, H. (2022). "Mathematics Beyond Limits". Science Press
"""

"""
此文件包含：
1. 扩展的复数系统（含∞和⊥）
2. 完整的算术运算体系
3. 四套逻辑系统（二值、三值、辩证、结构）
4. 高级数学函数
5. 矩阵运算支持
6. 物理量单位支持
"""

import math
from typing import Union, Tuple, List, Any, Optional
import numpy as np
from numbers import Number

class ZDANumber:

    """
    ZDA 数字类 - 表示零除算术体系中的数字
    ZDA Number class - represents numbers in the Zero-Division Arithmetic system
    
    这个类可以表示:
    - 常规复数 (a + bi)
    - 无穷大 (∞)
    - 未定义值 (⊥)
    
    This class can represent:
    - Regular complex numbers (a + bi)
    - Infinity (∞)
    - Undefined values (⊥)
    
    哲学基础:
    - 承认数学运算中的所有可能性，包括传统上认为"无意义"的运算
    - 通过明确的符号表示特殊状态，而非隐藏或禁止它们
    - 构建一个更具包容性和表现力的数学体系
    
    Philosophical foundation:
    - Acknowledge all possibilities in mathematical operations, including those 
      traditionally considered "meaningless"
    - Represent special states with explicit symbols rather than hiding or prohibiting them
    - Build a more inclusive and expressive mathematical system
    """
    
    def __init__(self, real: float = 0.0, imag: float = 0.0, 
                 is_inf: bool = False, is_bot: bool = False):
                 
        """
        初始化一个ZDA数字
        Initialize a ZDA number
        
        参数 Parameters:
        - real: 实部 (Real part)
        - imag: 虚部 (Imaginary part)
        - is_inf: 是否为无穷大 (Whether this is infinity)
        - is_bot: 是否为未定义值 (Whether this is bottom/undefined)
        
        注意: 如果is_bot为True，将忽略其他所有参数
        Note: If is_bot is True, all other parameters are ignored
        """
        
        self.is_bot = is_bot # 未定义状态 Undefined state
        self.is_inf = is_inf and not is_bot # 无穷大状态 Infinity state
        self.real = float(real) if not (is_inf or is_bot) else 0.0 # 实部 Real part
        self.imag = float(imag) if not (is_inf or is_bot) else 0.0 # 虚部 Imaginary part
        
        # 类型检查 Type checking
        if not isinstance(real, (int, float)) or not isinstance(imag, (int, float)):
            raise TypeError("实部和虚部必须是数值类型 Real and imaginary parts must be numeric")
            
        # 规范化处理
        if abs(self.real) < 1e-10:
            self.real = 0.0
        if abs(self.imag) < 1e-10:
            self.imag = 0.0
    
    @classmethod
    def from_complex(cls, c: complex):
        """
        从Python复数创建ZDA数字
        Create ZDA number from Python complex number
        
        参数 Parameters:
        - c: Python复数 (Python complex number)
        
        返回 Returns:
        - 对应的ZDA数字 (Corresponding ZDA number)
        """
        return cls(c.real, c.imag)
    
    @classmethod
    def inf(cls):
        """创建正无穷大 Create positive infinity"""
        return cls(is_inf=True)
    
    @classmethod
    def bot(cls):
        """创建未定义值 Create undefined value"""
        return cls(is_bot=True)
    
    def __repr__(self):
        """
        返回对象的正式字符串表示
        Return formal string representation of the object
        
        格式 Format:
        - 常规复数: (a+bi) 或 a (当虚部为0时)
        - 无穷大: ∞
        - 未定义值: ⊥
        """
        if self.is_bot:
            return "⊥"
        if self.is_inf:
            return "∞"
        if self.imag == 0:
            return f"{self.real}"
        return f"({self.real}{'+' if self.imag >= 0 else ''}{self.imag}i)"
    
    def __str__(self):
        """返回用户友好的字符串表示 Return user-friendly string representation"""
        return self.__repr__()
        
    # ===== 算术运算 Arithmetic Operations =====
    def __add__(self, other):
        """
        加法运算 Addition
        
        规则 Rules:
        1. 任何操作数未定义(⊥) → 结果为⊥
           Any operand undefined (⊥) → result is ⊥
        2. 任何操作数是无穷大(∞) → 结果为∞
           Any operand is infinity (∞) → result is ∞
        3. 两个无穷大相加 → ∞
           Two infinities added → ∞
        4. 常规复数加法
           Regular complex addition
        """
        other = self._convert(other)
        if self.is_bot or other.is_bot:
            return ZDANumber.bot()
        if self.is_inf or other.is_inf:
            if self.is_inf and other.is_inf:
                return ZDANumber.inf()
            return ZDANumber.inf()
        return ZDANumber(self.real + other.real, self.imag + other.imag)
    
    def __sub__(self, other):
        other = self._convert(other)
        if self.is_bot or other.is_bot:
            return ZDANumber.bot()
        if self.is_inf and other.is_inf:
            return ZDANumber.bot()
        if self.is_inf:
            return ZDANumber.inf()
        if other.is_inf:
            return ZDANumber.inf()
        return ZDANumber(self.real - other.real, self.imag - other.imag)
    
    def __mul__(self, other):
        other = self._convert(other)
        if self.is_bot or other.is_bot:
            return ZDANumber.bot()
        if (self.is_inf and other.real == 0 and other.imag == 0) or \
           (other.is_inf and self.real == 0 and self.imag == 0):
            return ZDANumber.bot()
        if self.is_inf or other.is_inf:
            return ZDANumber.inf()
        real = self.real * other.real - self.imag * other.imag
        imag = self.real * other.imag + self.imag * other.real
        return ZDANumber(real, imag)
    
    def __truediv__(self, other):
        other = self._convert(other)
        if self.is_bot or other.is_bot:
            return ZDANumber.bot()
        if other.is_inf:
            return ZDANumber(0)
        if other.real == 0 and other.imag == 0:
            if self.real == 0 and self.imag == 0:
                return ZDANumber.bot()
            return ZDANumber.inf()
        if self.is_inf:
            return ZDANumber.inf()
        denom = other.real**2 + other.imag**2
        real = (self.real * other.real + self.imag * other.imag) / denom
        imag = (self.imag * other.real - self.real * other.imag) / denom
        return ZDANumber(real, imag)
    
    def __pow__(self, other):
        other = self._convert(other)
        if self.is_bot or other.is_bot:
            return ZDANumber.bot()
        if self.real == 0 and self.imag == 0:
            if other.real > 0:
                return ZDANumber(0)
            elif other.real < 0:
                return ZDANumber.inf()
            else:
                return ZDANumber.bot()
        if self.is_inf:
            if other.real > 0:
                return ZDANumber.inf()
            elif other.real < 0:
                return ZDANumber(0)
            else:
                return ZDANumber.bot()
        c = complex(self.real, self.imag) ** complex(other.real, other.imag)
        return ZDANumber.from_complex(c)
    
    # ===== 比较运算 Comparison Operations =====
        """
        相等性比较 Equality comparison
        
        注意: 在ZDA体系中，相等性有特殊含义
        Note: In ZDA system, equality has special meaning
        
        规则 Rules:
        1. ⊥ 只等于 ⊥
           ⊥ only equals to ⊥
        2. ∞ 只等于 ∞
           ∞ only equals to ∞
        3. 常规复数比较
           Regular complex comparison
        """
    def __eq__(self, other):
        other = self._convert(other)
        if self.is_bot or other.is_bot:
            return self.is_bot and other.is_bot
        if self.is_inf or other.is_inf:
            return self.is_inf and other.is_inf
        return math.isclose(self.real, other.real) and math.isclose(self.imag, other.imag)
    
    def __lt__(self, other):
        other = self._convert(other)
        if self.is_bot or other.is_bot or self.is_inf or other.is_inf:
            return False
        return (self.real, self.imag) < (other.real, other.imag)
    
    # ===== 其他魔术方法 =====
    def __neg__(self):
        if self.is_bot:
            return ZDANumber.bot()
        if self.is_inf:
            return ZDANumber.inf()
        return ZDANumber(-self.real, -self.imag)
    
    def __abs__(self):
        if self.is_bot:
            return ZDANumber.bot()
        if self.is_inf:
            return ZDANumber.inf()
        return ZDANumber(math.sqrt(self.real**2 + self.imag**2))
    
    def conjugate(self):
        if self.is_bot or self.is_inf:
            return self
        return ZDANumber(self.real, -self.imag)
    
    def _convert(self, other):
        if isinstance(other, ZDANumber):
            return other
        if isinstance(other, (int, float)):
            return ZDANumber(other)
        if isinstance(other, complex):
            return ZDANumber.from_complex(other)
        raise TypeError(f"无法转换类型 {type(other)} 为 ZDANumber")

# ===== 数学函数 Mathematical Functions  =====
def zda_exp(x: ZDANumber) -> ZDANumber:
    """
    ZDA 指数函数
    ZDA Exponential Function
    
    定义 Definition:
    - exp(⊥) = ⊥
    - exp(∞) = ∞
    - exp(a+bi) = e^a * (cos(b) + i*sin(b))
    
    参数 Parameters:
    - x: ZDA数字 (ZDA number)
    
    返回 Returns:
    - 计算结果 (Computation result)
    
    异常 Exceptions:
    - 如果输入不是ZDANumber → TypeError
      If input is not ZDANumber → TypeError
    """
    if not isinstance(x, ZDANumber):
        raise TypeError("输入必须是ZDANumber Input must be ZDANumber")
    if x.is_bot:
        return ZDANumber.bot()
    if x.is_inf:
        return ZDANumber.inf()
    return ZDANumber.from_complex(math.exp(complex(x.real, x.imag)))

def zda_log(x: ZDANumber, base: ZDANumber = None) -> ZDANumber:
    if x.is_bot or (base and base.is_bot):
        return ZDANumber.bot()
    if x.is_inf:
        return ZDANumber.inf()
    if x.real == 0 and x.imag == 0:
        return ZDANumber(-math.inf)
    result = math.log(complex(x.real, x.imag))
    if base:
        base_val = complex(base.real, base.imag)
        result /= math.log(base_val)
    return ZDANumber.from_complex(result)

# ===== 逻辑系统 Logic Systems =====
class ZDALogic:
    """
    ZDA 逻辑系统基类
    ZDA Logic System Base Class
    
    这是所有ZDA逻辑变体的抽象基类，定义了通用接口
    This is the abstract base class for all ZDA logic variants, defining common interfaces
    """
    
    """
    没错，这里什么都不需要，只需要pass
    """
    
    pass

class ZDABinaryLogic(ZDALogic):
    """
    ZDA 二值逻辑系统
    ZDA Binary Logic System
    
    这个系统将ZDA数字映射到传统的布尔值(真/假)，但包含对∞和⊥的特殊处理
    This system maps ZDA numbers to traditional Boolean values (True/False), 
    but includes special handling for ∞ and ⊥
    """
    def __init__(self, value, conservative=True):
        """
        初始化二值逻辑值
        Initialize binary logic value
        
        参数 Parameters:
        - value: 输入值，可以是布尔值、字符串或ZDA数字
                 Input value, can be bool, str or ZDANumber
        - conservative: 如果为True，∞/⊥映射为False；否则∞映射为True
                       If True, map ∞/⊥ to False; else map ∞ to True
        
        注意: 在保守模式下，⊥总是映射为False
        Note: In conservative mode, ⊥ is always mapped to False
        """
        if isinstance(value, ZDANumber):
            if value.is_bot:
                self.value = False
            elif value.is_inf:
                self.value = not conservative
            else:
                self.value = bool(value.real or value.imag)
        else:
            self.value = bool(value)
    
    def __and__(self, other):
        """逻辑与运算 Logical AND"""
        if not isinstance(other, ZDABinaryLogic):
            other = ZDABinaryLogic(other)
        return ZDABinaryLogic(self.value and other.value)
    
    def __or__(self, other):
        if not isinstance(other, ZDABinaryLogic):
            other = ZDABinaryLogic(other)
        return ZDABinaryLogic(self.value or other.value)
    
    def __invert__(self):
        return ZDABinaryLogic(not self.value)
    
    def __bool__(self):
        return self.value

class ZDATernaryLogic(ZDALogic):
    """三值逻辑系统（真/假/未知）"""
    VALUES = {'T': 0, 'F': 1, 'U': 2}
    INV_VALUES = {0: 'T', 1: 'F', 2: 'U'}
    
    def __init__(self, value):
        if isinstance(value, ZDANumber):
            if value.is_bot or value.is_inf:
                self.value = 'U'
            else:
                self.value = 'T' if (value.real or value.imag) else 'F'
        else:
            val = str(value).upper()[0]
            self.value = val if val in ['T', 'F', 'U'] else 'U'
    
    def __and__(self, other):
        if not isinstance(other, ZDATernaryLogic):
            other = ZDATernaryLogic(other)
        table = [['T', 'F', 'U'], ['F', 'F', 'F'], ['U', 'F', 'U']]
        return ZDATernaryLogic(table[self.VALUES[self.value]][self.VALUES[other.value]])
    
    def __or__(self, other):
        if not isinstance(other, ZDATernaryLogic):
            other = ZDATernaryLogic(other)
        table = [['T', 'T', 'T'], ['T', 'F', 'U'], ['T', 'U', 'U']]
        return ZDATernaryLogic(table[self.VALUES[self.value]][self.VALUES[other.value]])

class ZDADialecticalLogic(ZDALogic):
    """辩证法逻辑系统（正题/反题/合题）"""
    def __init__(self, value):
        if isinstance(value, ZDANumber):
            if value.is_bot:
                self.value = 'D'
            elif value.is_inf:
                self.value = 'T'
            else:
                self.value = 'T' if (value.real or value.imag) else 'F'
        else:
            val = str(value).upper()[0]
            self.value = val if val in ['T', 'F', 'D'] else 'D'
    
    def synthesize(self):
        """合题运算"""
        if self.value == 'D':
            return ZDADialecticalLogic('T')
        return self

class ZDAStructuralLogic(ZDALogic):
    """
    ZDA 结构逻辑系统 - 直接映射到算术运算
    ZDA Structural Logic System - directly mapped to arithmetic operations
    
    特点 Features:
    - 逻辑运算直接对应ZDA算术运算
      Logical operations directly correspond to ZDA arithmetic operations
    - AND运算 = 取分量最小值
      AND operation = component-wise minimum
    - OR运算 = 取分量最大值
      OR operation = component-wise maximum
    - 蕴含运算 = 特殊定义的算术关系
      Implication operation = specially defined arithmetic relation
    - 保留∞和⊥的完整语义
      Preserves full semantics of ∞ and ⊥
    """
    
    def __init__(self, value):
        """
        初始化结构逻辑值
        Initialize structural logic value
        
        参数 Parameters:
        - value: 可以是ZDANumber、数字、复数或布尔值
                 Can be ZDANumber, number, complex or bool
        """
        if not isinstance(value, ZDANumber):
            if isinstance(value, (int, float)):
                value = ZDANumber(value)
            elif isinstance(value, complex):
                value = ZDANumber.from_complex(value)
            elif isinstance(value, bool):
                value = ZDANumber(1.0 if value else 0.0)
            else:
                raise TypeError("不支持的输入类型 Unsupported input type")
        self.value = value
    
    def __and__(self, other):
        """
        结构逻辑AND运算
        Structural logic AND operation
        
        规则 Rules:
        - ⊥ AND x = ⊥
        - ∞ AND x = x
        - x AND ∞ = x
        - 其他情况: 取分量最小值
          Otherwise: component-wise minimum
        """
        if not isinstance(other, ZDAStructuralLogic):
            other = ZDAStructuralLogic(other)
            
        if self.value.is_bot or other.value.is_bot:
            return ZDAStructuralLogic(ZDANumber.bot())
            
        if self.value.is_inf:
            return ZDAStructuralLogic(other.value)
            
        if other.value.is_inf:
            return ZDAStructuralLogic(self.value)
            
        return ZDAStructuralLogic(ZDANumber(
            min(self.value.real, other.value.real),
            min(self.value.imag, other.value.imag)
        ))
    
    def __or__(self, other):
        """
        结构逻辑OR运算
        Structural logic OR operation
        
        规则 Rules:
        - ⊥ OR x = x
        - ∞ OR x = ∞
        - x OR ∞ = ∞
        - 其他情况: 取分量最大值
          Otherwise: component-wise maximum
        """
        if not isinstance(other, ZDAStructuralLogic):
            other = ZDAStructuralLogic(other)
            
        if self.value.is_bot:
            return ZDAStructuralLogic(other.value)
            
        if other.value.is_bot:
            return ZDAStructuralLogic(self.value)
            
        if self.value.is_inf or other.value.is_inf:
            return ZDAStructuralLogic(ZDANumber.inf())
            
        return ZDAStructuralLogic(ZDANumber(
            max(self.value.real, other.value.real),
            max(self.value.imag, other.value.imag)
        ))
    
    def __invert__(self):
        """
        结构逻辑NOT运算
        Structural logic NOT operation
        
        规则 Rules:
        - ¬⊥ = ⊥
        - ¬∞ = 0
        - ¬(a+bi) = (1-a)+(1-b)i
        """
        if self.value.is_bot:
            return ZDAStructuralLogic(ZDANumber.bot())
        if self.value.is_inf:
            return ZDAStructuralLogic(ZDANumber(0))
        return ZDAStructuralLogic(ZDANumber(
            1 - self.value.real,
            1 - self.value.imag)
        )
    
    def implies(self, other):
        """
        结构逻辑蕴含运算 (→)
        Structural logic implication operation
        
        定义 Definition:
        - a → b ≡ ¬a ∨ b
        - 特殊处理∞和⊥
          Special handling for ∞ and ⊥
        """
        return (~self) | other
    
    def __eq__(self, other):
        """结构逻辑等价比较"""
        if not isinstance(other, ZDAStructuralLogic):
            other = ZDAStructuralLogic(other)
        return self.value == other.value
    
    def __repr__(self):
        return f"ZDAStructuralLogic({self.value})"
    
    def __bool__(self):
        """
        转换为布尔值
        Convert to boolean
        
        规则 Rules:
        - ⊥ → False
        - ∞ → True
        - 其他: 实部或虚部不为0则为True
          Others: True if real or imag part is non-zero
        """
        if self.value.is_bot:
            return False
        if self.value.is_inf:
            return True
        return bool(self.value.real) or bool(self.value.imag)
    
    @property
    def truth_value(self):
        """获取真值(实数部分) Get truth value (real part)"""
        if self.value.is_bot:
            return float('nan')
        if self.value.is_inf:
            return float('inf')
        return self.value.real
        
class ZDAImplicationLogic(ZDALogic):
    """
    ZDA 专门蕴含逻辑系统
    ZDA Specialized Implication Logic System
    
    特点 Features:
    - 专注于蕴含关系及其变体
      Focuses on implication relations and their variants
    - 支持多种蕴含定义
      Supports multiple implication definitions
    """
    
    def __init__(self, antecedent, consequent=None):
        """
        初始化蕴含逻辑
        Initialize implication logic
        
        参数 Parameters:
        - antecedent: 前件 (可以是逻辑值或ZDANumber)
                     Antecedent (can be logic value or ZDANumber)
        - consequent: 后件 (可选，用于预定义蕴含关系)
                     Consequent (optional, for predefined implications)
        """
        if consequent is None:
            if isinstance(antecedent, tuple) and len(antecedent) == 2:
                self.antecedent = ZDAStructuralLogic(antecedent[0])
                self.consequent = ZDAStructuralLogic(antecedent[1])
            else:
                raise ValueError("需要提供前件和后件 Need to provide both antecedent and consequent")
        else:
            self.antecedent = ZDAStructuralLogic(antecedent)
            self.consequent = ZDAStructuralLogic(consequent)
    
    def lukasiewicz_implication(self):
        """
        卢卡西维茨蕴含
        Lukasiewicz implication
        
        定义 Definition:
        - a → b = min(1, 1 - a + b)
        """
        if self.antecedent.value.is_bot or self.consequent.value.is_bot:
            return ZDAStructuralLogic(ZDANumber.bot())
            
        a = self.antecedent.truth_value
        b = self.consequent.truth_value
        
        if math.isinf(a) and a > 0:  # ∞ → b = b
            return self.consequent
        if math.isinf(b) and b > 0:  # a → ∞ = 1
            return ZDAStructuralLogic(ZDANumber(1))
            
        return ZDAStructuralLogic(ZDANumber(min(1, 1 - a + b)))
    
    def kleene_implication(self):
        """
        克林蕴含
        Kleene implication
        
        定义 Definition:
        - a → b = max(1 - a, b)
        """
        if self.antecedent.value.is_bot or self.consequent.value.is_bot:
            return ZDAStructuralLogic(ZDANumber.bot())
            
        a = self.antecedent.truth_value
        b = self.consequent.truth_value
        
        if math.isinf(a) and a > 0:  # ∞ → b = b
            return self.consequent
        if math.isinf(b) and b > 0:  # a → ∞ = 1
            return ZDAStructuralLogic(ZDANumber(1))
            
        return ZDAStructuralLogic(ZDANumber(max(1 - a, b)))
    
    def standard_implication(self):
        """标准蕴含 (¬a ∨ b)"""
        return (~self.antecedent) | self.consequent
    
    def __repr__(self):
        return f"({self.antecedent} → {self.consequent})"
        
class ZDAImplicationLogic(ZDALogic):
    """
    ZDA 专门蕴含逻辑系统
    ZDA Specialized Implication Logic System
    
    特点 Features:
    - 专注于蕴含关系及其变体
      Focuses on implication relations and their variants
    - 支持多种蕴含定义
      Supports multiple implication definitions
    """
    
    def __init__(self, antecedent, consequent=None):
        """
        初始化蕴含逻辑
        Initialize implication logic
        
        参数 Parameters:
        - antecedent: 前件 (可以是逻辑值或ZDANumber)
                     Antecedent (can be logic value or ZDANumber)
        - consequent: 后件 (可选，用于预定义蕴含关系)
                     Consequent (optional, for predefined implications)
        """
        if consequent is None:
            if isinstance(antecedent, tuple) and len(antecedent) == 2:
                self.antecedent = ZDAStructuralLogic(antecedent[0])
                self.consequent = ZDAStructuralLogic(antecedent[1])
            else:
                raise ValueError("需要提供前件和后件 Need to provide both antecedent and consequent")
        else:
            self.antecedent = ZDAStructuralLogic(antecedent)
            self.consequent = ZDAStructuralLogic(consequent)
    
    def lukasiewicz_implication(self):
        """
        卢卡西维茨蕴含
        Lukasiewicz implication
        
        定义 Definition:
        - a → b = min(1, 1 - a + b)
        """
        if self.antecedent.value.is_bot or self.consequent.value.is_bot:
            return ZDAStructuralLogic(ZDANumber.bot())
            
        a = self.antecedent.truth_value
        b = self.consequent.truth_value
        
        if math.isinf(a) and a > 0:  # ∞ → b = b
            return self.consequent
        if math.isinf(b) and b > 0:  # a → ∞ = 1
            return ZDAStructuralLogic(ZDANumber(1))
            
        return ZDAStructuralLogic(ZDANumber(min(1, 1 - a + b)))
    
    def kleene_implication(self):
        """
        克林蕴含
        Kleene implication
        
        定义 Definition:
        - a → b = max(1 - a, b)
        """
        if self.antecedent.value.is_bot or self.consequent.value.is_bot:
            return ZDAStructuralLogic(ZDANumber.bot())
            
        a = self.antecedent.truth_value
        b = self.consequent.truth_value
        
        if math.isinf(a) and a > 0:  # ∞ → b = b
            return self.consequent
        if math.isinf(b) and b > 0:  # a → ∞ = 1
            return ZDAStructuralLogic(ZDANumber(1))
            
        return ZDAStructuralLogic(ZDANumber(max(1 - a, b)))
    
    def standard_implication(self):
        """标准蕴含 (¬a ∨ b)"""
        return (~self.antecedent) | self.consequent
    
    def __repr__(self):
        return f"({self.antecedent} → {self.consequent})"
        
class ZDAFuzzyLogic(ZDALogic):
    """
    ZDA 模糊逻辑系统
    ZDA Fuzzy Logic System
    
    特点 Features:
    - 真值在[0,1]区间连续取值
      Truth values are continuous in [0,1] interval
    - 支持标准模糊逻辑运算
      Supports standard fuzzy logic operations
    - 兼容ZDA的特殊值(∞和⊥)
      Compatible with ZDA special values (∞ and ⊥)
    """
    
    def __init__(self, value):
        """
        初始化模糊逻辑值
        Initialize fuzzy logic value
        
        参数 Parameters:
        - value: 可以是ZDANumber、数字或布尔值
                 Can be ZDANumber, number or bool
        """
        if isinstance(value, ZDANumber):
            if value.is_bot:
                self.value = float('nan')
            elif value.is_inf:
                self.value = 1.0
            else:
                self.value = max(0.0, min(1.0, value.real))
        elif isinstance(value, (int, float)):
            self.value = max(0.0, min(1.0, float(value)))
        elif isinstance(value, bool):
            self.value = 1.0 if value else 0.0
        else:
            raise TypeError("不支持的输入类型 Unsupported input type")
    
    def __and__(self, other):
        """模糊AND (取最小值)"""
        if not isinstance(other, ZDAFuzzyLogic):
            other = ZDAFuzzyLogic(other)
            
        if math.isnan(self.value) or math.isnan(other.value):
            return ZDAFuzzyLogic(float('nan'))
            
        return ZDAFuzzyLogic(min(self.value, other.value))
    
    def __or__(self, other):
        """模糊OR (取最大值)"""
        if not isinstance(other, ZDAFuzzyLogic):
            other = ZDAFuzzyLogic(other)
            
        if math.isnan(self.value) or math.isnan(other.value):
            return ZDAFuzzyLogic(float('nan'))
            
        return ZDAFuzzyLogic(max(self.value, other.value))
    
    def __invert__(self):
        """模糊NOT (1 - value)"""
        if math.isnan(self.value):
            return ZDAFuzzyLogic(float('nan'))
        return ZDAFuzzyLogic(1.0 - self.value)
    
    def implies(self, other, method='standard'):
        """
        模糊蕴含运算
        Fuzzy implication operation
        
        参数 Parameters:
        - method: 蕴含方法，可选'standard', 'lukasiewicz', 'godel'
                  Implication method, options: 'standard', 'lukasiewicz', 'godel'
        """
        if not isinstance(other, ZDAFuzzyLogic):
            other = ZDAFuzzyLogic(other)
            
        if math.isnan(self.value) or math.isnan(other.value):
            return ZDAFuzzyLogic(float('nan'))
            
        if method == 'standard':
            return (~self) | other
        elif method == 'lukasiewicz':
            return ZDAFuzzyLogic(min(1.0, 1.0 - self.value + other.value))
        elif method == 'godel':
            return ZDAFuzzyLogic(1.0 if self.value <= other.value else other.value)
        else:
            raise ValueError("未知的蕴含方法 Unknown implication method")
    
    def __repr__(self):
        return f"ZDAFuzzyLogic({self.value})"
    
    def __float__(self):
        return self.value
    
    def __bool__(self):
        """转换为布尔值 (阈值0.5)"""
        return self.value > 0.5
        
class ZDAQuantumLogic(ZDALogic):
    """
    ZDA 量子逻辑系统
    ZDA Quantum Logic System
    
    特点 Features:
    - 基于量子叠加态的概念
      Based on quantum superposition concept
    - 支持量子纠缠态表示
      Supports entangled state representation
    - 兼容ZDA的特殊值(∞和⊥)
      Compatible with ZDA special values (∞ and ⊥)
    """
    
    def __init__(self, state_vector=None, probability=1.0):
        """
        初始化量子逻辑状态
        Initialize quantum logic state
        
        参数 Parameters:
        - state_vector: 状态向量 (复数列表)
                       State vector (list of complex numbers)
        - probability: 观测概率 (默认为1.0)
                      Observation probability (default 1.0)
        """
        if state_vector is None:
            state_vector = [1.0, 0.0]  # 默认|0⟩状态 Default |0⟩ state
            
        if isinstance(state_vector, ZDANumber):
            if state_vector.is_bot:
                self.state_vector = None
                self.probability = float('nan')
            elif state_vector.is_inf:
                self.state_vector = [0.0, 1.0]  # |1⟩ with infinite amplitude
                self.probability = 1.0
            else:
                # 将ZDANumber转换为量子态
                norm = math.sqrt(state_vector.real**2 + state_vector.imag**2)
                if norm == 0:
                    self.state_vector = [1.0, 0.0]
                else:
                    self.state_vector = [
                        complex(state_vector.real/norm, 0),
                        complex(state_vector.imag/norm, 0)
                    ]
                self.probability = probability
        else:
            self.state_vector = [complex(x) for x in state_vector]
            self.probability = probability
    
    def measure(self):
        """
        量子测量
        Quantum measurement
        
        返回 Returns:
        - 测量结果 (True/False/None for ⊥)
          Measurement result (True/False/None for ⊥)
        - 坍缩后的状态
          Collapsed state
        """
        if self.state_vector is None or math.isnan(self.probability):
            return None, ZDAQuantumLogic(None, float('nan'))
            
        # 计算测量概率
        p_true = abs(self.state_vector[1])**2 * self.probability
        p_false = abs(self.state_vector[0])**2 * self.probability
        
        # 随机选择结果
        if random.random() < p_true / (p_true + p_false):
            return True, ZDAQuantumLogic([0.0, 1.0], 1.0)
        else:
            return False, ZDAQuantumLogic([1.0, 0.0], 1.0)
    
    def __and__(self, other):
        """量子AND (张量积后投影到AND子空间)"""
        if not isinstance(other, ZDAQuantumLogic):
            other = ZDAQuantumLogic(other)
            
        if self.state_vector is None or other.state_vector is None:
            return ZDAQuantumLogic(None, float('nan'))
            
        # 计算张量积
        tensor_product = [
            self.state_vector[0] * other.state_vector[0],
            self.state_vector[0] * other.state_vector[1],
            self.state_vector[1] * other.state_vector[0],
            self.state_vector[1] * other.state_vector[1]
        ]
        
        # AND运算相当于投影到|11⟩态
        and_amplitude = tensor_product[3]
        return ZDAQuantumLogic(
            [0.0, and_amplitude],
            abs(and_amplitude)**2
        )
    
    def __or__(self, other):
        """量子OR (张量积后投影到OR子空间)"""
        if not isinstance(other, ZDAQuantumLogic):
            other = ZDAQuantumLogic(other)
            
        if self.state_vector is None or other.state_vector is None:
            return ZDAQuantumLogic(None, float('nan'))
            
        # 计算张量积
        tensor_product = [
            self.state_vector[0] * other.state_vector[0],
            self.state_vector[0] * other.state_vector[1],
            self.state_vector[1] * other.state_vector[0],
            self.state_vector[1] * other.state_vector[1]
        ]
        
        # OR运算相当于投影到|01⟩, |10⟩和|11⟩态
        or_amplitude = math.sqrt(
            abs(tensor_product[1])**2 + 
            abs(tensor_product[2])**2 + 
            abs(tensor_product[3])**2
        )
        return ZDAQuantumLogic(
            [0.0, or_amplitude],
            or_amplitude**2
        )
    
    def __invert__(self):
        """量子NOT (交换基态系数)"""
        if self.state_vector is None:
            return ZDAQuantumLogic(None, float('nan'))
        return ZDAQuantumLogic(
            [self.state_vector[1], self.state_vector[0]],
            self.probability
        )
    
    def entangle(self, other):
        """
        创建纠缠态
        Create entangled state (Bell state)
        """
        if not isinstance(other, ZDAQuantumLogic):
            other = ZDAQuantumLogic(other)
            
        if self.state_vector is None or other.state_vector is None:
            return ZDAQuantumLogic(None, float('nan'))
            
        # 创建最大纠缠态 (|00⟩ + |11⟩)/√2
        return ZDAQuantumLogic(
            [1/math.sqrt(2), 0, 0, 1/math.sqrt(2)],
            min(self.probability, other.probability)
        )
    
    def __repr__(self):
        if self.state_vector is None:
            return "ZDAQuantumLogic(⊥)"
        return f"ZDAQuantumLogic({self.state_vector}, p={self.probability})"
        
# ===== 高级API Advanced APIs  =====
def zda_matrix_inverse(matrix: List[List[ZDANumber]]) -> List[List[ZDANumber]]:
    """
    ZDA 矩阵求逆
    ZDA Matrix Inversion
    
    这个函数可以处理包含∞和⊥的矩阵求逆运算
    This function can handle matrix inversion containing ∞ and ⊥
    
    参数 Parameters:
    - matrix: 二维列表表示的矩阵
              Matrix represented as 2D list
    
    返回 Returns:
    - 逆矩阵 Inverse matrix
    
    异常 Exceptions:
    - 如果矩阵不可逆(即行列式为⊥) → 返回⊥矩阵
      If matrix is not invertible (determinant is ⊥) → return ⊥ matrix
    """
    n = len(matrix)
    if n == 0 or len(matrix[0]) != n:
        return [[ZDANumber.bot()]]
    
    # 创建增广矩阵 [A|I]
    aug = [row + [ZDANumber(1 if i == j else 0) for j in range(n)] for i, row in enumerate(matrix)]
    
    for col in range(n):
        # 寻找主元
        pivot = col
        while pivot < n and aug[pivot][col] == ZDANumber(0):
            pivot += 1
        if pivot == n:
            return [[ZDANumber.bot() for _ in range(n)] for _ in range(n)]
        
        # 交换行
        aug[col], aug[pivot] = aug[pivot], aug[col]
        
        # 归一化
        pivot_val = aug[col][col]
        for j in range(col, 2*n):
            aug[col][j] /= pivot_val
        
        # 消元
        for i in range(n):
            if i != col and aug[i][col] != ZDANumber(0):
                factor = aug[i][col]
                for j in range(col, 2*n):
                    aug[i][j] -= aug[col][j] * factor
    
    # 提取逆矩阵
    return [row[n:] for row in aug]

# ===== 物理量支持 =====
class ZDAPhysicalQuantity:
    """带单位的物理量"""
    def __init__(self, value: ZDANumber, unit: str = ""):
        self.value = value if isinstance(value, ZDANumber) else ZDANumber(value)
        self.unit = unit
    
    def __repr__(self):
        return f"{self.value} {self.unit}".strip()

# ===== 示例用法 Example usage =====
if __name__ == "__main__":
    print("=== ZDA 基本运算示例 ZDA Basic Operations Examples ===")
    a = ZDANumber(3, 4)
    b = ZDANumber(0)
    inf = ZDANumber.inf()
    bot = ZDANumber.bot()
    
    print(f"a = {a}")
    print(f"b = {b}")
    print(f"a + b = {a + b}")
    print(f"a / b = {a / b}")
    print(f"0 / 0 = {b / b}")
    print(f"∞ * 0 = {inf * b}")
    
    print("\n=== 逻辑系统演示 ===")
    binary_logic = ZDABinaryLogic(inf, conservative=False) # True (∞ mapped to True)
    print(f"∞ 在非保守二值逻辑中，binary_inf (非保守模式) = {binary_logic}") # True
    
    binary_inf_conserv = ZDABinaryLogic(inf)  # False (∞ mapped to False in conservative mode)
    print(f"∞ 在非保守二值逻辑中，binary_inf (保守模式) = {binary_inf_conserv}")  # False
    
    ternary_logic = ZDATernaryLogic(bot)
    print(f"⊥ 在三值逻辑中: {ternary_logic}")
    
    dialectic = ZDADialecticalLogic('D')
    print(f"辩证逻辑合题: {dialectic.synthesize()}")
    
    # 结构逻辑示例
    print("\n=== 结构逻辑示例 ===")
    a = ZDAStructuralLogic(ZDANumber(0.7))
    b = ZDAStructuralLogic(ZDANumber(0.3))
    print(f"{a} AND {b} = {a & b}")
    print(f"{a} OR {b} = {a | b}")
    print(f"{a} → {b} = {a.implies(b)}")
    
    # 蕴含逻辑示例
    print("\n=== 蕴含逻辑示例 ===")
    imp = ZDAImplicationLogic(ZDANumber(0.6), ZDANumber(0.4))
    print(f"卢卡西维茨蕴含: {imp.lukasiewicz_implication()}")
    print(f"克林蕴含: {imp.kleene_implication()}")
    
    # 模糊逻辑示例
    print("\n=== 模糊逻辑示例 ===")
    fuzzy_a = ZDAFuzzyLogic(0.8)
    fuzzy_b = ZDAFuzzyLogic(0.5)
    print(f"{fuzzy_a} AND {fuzzy_b} = {fuzzy_a & fuzzy_b}")
    print(f"{fuzzy_a} → {fuzzy_b} (标准) = {fuzzy_a.implies(fuzzy_b)}")
    print(f"{fuzzy_a} → {fuzzy_b} (卢卡西维茨) = {fuzzy_a.implies(fuzzy_b, 'lukasiewicz')}")
    
    # 量子逻辑示例
    print("\n=== 量子逻辑示例 ===")
    quantum_a = ZDAQuantumLogic([1/math.sqrt(2), 1/math.sqrt(2)])
    quantum_b = ZDAQuantumLogic([0.0, 1.0])
    result, collapsed = quantum_a.measure()
    print(f"测量结果: {result}, 坍缩后状态: {collapsed}")
    print(f"{quantum_a} AND {quantum_b} = {quantum_a & quantum_b}")

    print("\n=== 矩阵运算演示 ===")
    matrix = [
        [ZDANumber(1), ZDANumber(2)],
        [ZDANumber(3), ZDANumber(4)]
    ]
    inv_matrix = zda_matrix_inverse(matrix)
    print("逆矩阵:")
    for row in inv_matrix:
        print(row)
        
"""
ZDA 体系的设计哲学总结:
1. 包容性: 接受所有数学可能性，而非禁止"危险"运算
2. 明确性: 用明确符号表示特殊状态，提高可预测性
3. 一致性: 确保所有运算在体系内自洽
4. 实用性: 为实际问题提供数学工具

ZDA system design philosophy summary:
1. Inclusivity: Accept all mathematical possibilities rather than prohibiting "dangerous" operations
2. Explicitness: Use explicit symbols for special states to improve predictability
3. Consistency: Ensure all operations are self-consistent within the system
4. Practicality: Provide mathematical tools for real-world problems
"""
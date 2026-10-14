"""Compatibility entry for the explicit, tested ano.boolean.v1 truth profile."""
from ziokt.ano import merge,cross,negate,majority,Signal

def _label(v):return '正' if v==Signal.POSITIVE else '反' if v==Signal.NEGATIVE else '未知'
def non_counter_intuitive_merge(a,b):return _label(merge(a,b))
def non_counter_intuitive_cross(a,b):return _label(cross(a,b))
def counter_intuitive_loop(a,b):return _label(merge(merge(a,b),merge(a,b)))
def counter_intuitive_mirror(a,b):return _label(cross(merge(a,b),merge(a,b)))
def counter_intuitive_superposition(a,b):return counter_intuitive_loop(counter_intuitive_mirror(a,b),counter_intuitive_mirror(a,b))
def counter_intuitive_set(*values):return _label(majority(*values))
def proposition_function(value):return _label(negate(value))

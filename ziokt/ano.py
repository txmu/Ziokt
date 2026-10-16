"""Versioned Ano truth operations, bounded exact numbers and defence decisions.

The boolean profile preserves the supplied refined implementation's binary
truth tables and explicitly defines propagation of the unknown state. It is a decision vocabulary, not a substitute for cryptographic proof.
"""
from dataclasses import dataclass
from enum import Enum
from fractions import Fraction
from .protocol import ProtocolError

PROFILE='ano.boolean.v1'
LEGACY_PROFILE='ano.refined-equality.v0'
PROFILES=(PROFILE,LEGACY_PROFILE)

def _profile(value):
    if value not in PROFILES:raise ProtocolError('INVALID_ANO','explicit supported operation profile required')
    return value

class Signal(str,Enum):
    POSITIVE='positive'
    NEGATIVE='negative'
    UNKNOWN='unknown'


def signal(value):
    if type(value) is bool:return Signal.POSITIVE if value else Signal.NEGATIVE
    if value is None:return Signal.UNKNOWN
    if isinstance(value,Signal):return value
    aliases={'正':Signal.POSITIVE,'反':Signal.NEGATIVE,'positive':Signal.POSITIVE,'negative':Signal.NEGATIVE,'unknown':Signal.UNKNOWN}
    if not isinstance(value,str) or value not in aliases:raise ProtocolError('INVALID_ANO','explicit Ano signal required')
    return aliases[value]


def merge(a,b,*,profile=PROFILE):
    _profile(profile);a,b=signal(a),signal(b)
    if profile==PROFILE and Signal.UNKNOWN in (a,b):return Signal.UNKNOWN
    return Signal.NEGATIVE if a==b else Signal.POSITIVE


def cross(a,b,*,profile=PROFILE):
    _profile(profile);a,b=signal(a),signal(b)
    if profile==PROFILE and Signal.UNKNOWN in (a,b):return Signal.UNKNOWN
    return Signal.POSITIVE if a==b else Signal.NEGATIVE


def negate(value):
    value=signal(value)
    return Signal.UNKNOWN if value==Signal.UNKNOWN else Signal.NEGATIVE if value==Signal.POSITIVE else Signal.POSITIVE


def majority(*values):
    if not 1<=len(values)<=128:raise ProtocolError('INVALID_ANO','bounded nonempty evidence list required')
    values=[signal(v) for v in values]
    positive=values.count(Signal.POSITIVE);negative=values.count(Signal.NEGATIVE);unknown=values.count(Signal.UNKNOWN)
    if positive>negative+unknown:return Signal.POSITIVE
    if negative>=positive+unknown:return Signal.NEGATIVE
    return Signal.UNKNOWN


def conjunction(*values):
    if not 1<=len(values)<=128:raise ProtocolError('INVALID_ANO','bounded nonempty claims required')
    values=[signal(v) for v in values]
    if Signal.NEGATIVE in values:return Signal.NEGATIVE
    return Signal.UNKNOWN if Signal.UNKNOWN in values else Signal.POSITIVE


def defence(evidence,required):
    """Only ALL required verified claims may authorize; uncertainty holds."""
    if (not isinstance(evidence,dict) or not isinstance(required,(tuple,list)) or not 1<=len(required)<=32 or
            any(not isinstance(n,str) or n not in evidence for n in required) or len(set(required))!=len(required)):
        raise ProtocolError('INVALID_ANO','exact named independent defensive claims required')
    claims={name:signal(evidence[name]) for name in required}
    decision=conjunction(*claims.values())
    return {'schema':'ziokt.ano-decision.v1','profile':PROFILE,'decision':'allow' if decision==Signal.POSITIVE else 'deny' if decision==Signal.NEGATIVE else 'hold',
        'claims':{k:v.value for k,v in claims.items()},'cryptographic_assurance':False}


def evaluate(tree):
    count=0
    def visit(node,depth=0):
        nonlocal count
        count+=1
        if count>128 or depth>8:raise ProtocolError('ANO_LIMIT','bounded circuit required')
        if isinstance(node,(str,Signal)) or type(node) is bool or node is None:return signal(node)
        if not isinstance(node,dict) or set(node)!={'op','args'} or not isinstance(node['op'],str) or not isinstance(node['args'],list):raise ProtocolError('INVALID_ANO','typed circuit required')
        op=node['op'];args=node['args']
        if op in {'merge','cross','loop','mirror','superposition'} and len(args)!=2 or op=='not' and len(args)!=1 or op in {'and','or','majority'} and not 1<=len(args)<=32:
            raise ProtocolError('INVALID_ANO','bounded operator arity required')
        values=[visit(v,depth+1) for v in args]
        if op=='merge':return merge(*values)
        if op=='cross':return cross(*values)
        if op=='not':return negate(values[0])
        if op=='and':return conjunction(*values)
        if op=='or':return negate(conjunction(*(negate(v) for v in values)))
        if op=='majority':return majority(*values)
        if op=='loop':return merge(merge(*values),merge(*values))
        if op=='mirror':return cross(merge(*values),merge(*values))
        if op=='superposition':return merge(cross(merge(*values),merge(*values)),cross(merge(*values),merge(*values)))
        raise ProtocolError('INVALID_ANO','unknown circuit operation')
    return {'schema':'ziokt.ano-result.v1','profile':PROFILE,'result':visit(tree).value,'nodes':count}


def _fraction(value):
    if type(value) is int:value=Fraction(value)
    if not isinstance(value,Fraction) or value.numerator.bit_length()>4096 or value.denominator.bit_length()>4096:
        raise ProtocolError('ANO_LIMIT','bounded exact rational required; floating state is not authorization evidence')
    return value


def _ratio_document(value):
    return {'numerator':str(value.numerator),'denominator':str(value.denominator)}


def _read_ratio(value):
    import re
    if not isinstance(value,dict) or set(value)!={'numerator','denominator'}:
        raise ProtocolError('INVALID_ZDA','exact rational descriptor required')
    n,d=value['numerator'],value['denominator']
    if (not isinstance(n,str) or not isinstance(d,str) or len(n)>1235 or len(d)>1234 or
            not re.fullmatch(r'0|-?[1-9][0-9]*',n) or not re.fullmatch(r'[1-9][0-9]*',d)):
        raise ProtocolError('INVALID_ZDA','bounded canonical rational required')
    ratio=_fraction(Fraction(int(n),int(d)))
    if _ratio_document(ratio)!=value:raise ProtocolError('INVALID_ZDA','reduced canonical rational required')
    return ratio


@dataclass(frozen=True)
class ZDANumber:
    real:Fraction=Fraction(0)
    imaginary:Fraction=Fraction(0)
    state:str='finite'

    def __post_init__(self):
        if not isinstance(self.state,str) or self.state not in {'finite','infinity','bottom'}:raise ProtocolError('INVALID_ZDA','known tagged numeric state required')
        object.__setattr__(self,'real',_fraction(self.real));object.__setattr__(self,'imaginary',_fraction(self.imaginary))
        if self.state!='finite' and (self.real or self.imaginary):raise ProtocolError('INVALID_ZDA','special state carries no finite coefficient')

    @classmethod
    def from_document(cls,value):
        if not isinstance(value,dict) or set(value)!={'schema','state','real','imaginary'} or value['schema']!='ziokt.zda-number.v1':
            raise ProtocolError('INVALID_ZDA','versioned ZDA number required')
        return cls(_read_ratio(value['real']),_read_ratio(value['imaginary']),value['state'])

    @classmethod
    def infinity(cls):return cls(state='infinity')
    @classmethod
    def bottom(cls):return cls(state='bottom')
    @property
    def zero(self):return self.state=='finite' and self.real==0 and self.imaginary==0
    def _other(self,other):return other if isinstance(other,ZDANumber) else ZDANumber(other)
    def __add__(self,other):
        other=self._other(other)
        if 'bottom' in (self.state,other.state):return self.bottom()
        if self.state==other.state=='infinity':return self.bottom()
        if 'infinity' in (self.state,other.state):return self.infinity()
        return ZDANumber(self.real+other.real,self.imaginary+other.imaginary)
    def __neg__(self):return ZDANumber(-self.real,-self.imaginary) if self.state=='finite' else self
    def __sub__(self,other):return self+-self._other(other)
    def __mul__(self,other):
        other=self._other(other)
        if 'bottom' in (self.state,other.state):return self.bottom()
        if 'infinity' in (self.state,other.state):return self.bottom() if self.zero or other.zero else self.infinity()
        return ZDANumber(self.real*other.real-self.imaginary*other.imaginary,self.real*other.imaginary+self.imaginary*other.real)
    def __truediv__(self,other):
        other=self._other(other)
        if 'bottom' in (self.state,other.state) or self.state==other.state=='infinity':return self.bottom()
        if other.zero:return self.bottom() if self.zero else self.infinity()
        if other.state=='infinity':return ZDANumber()
        if self.state=='infinity':return self.infinity()
        den=other.real**2+other.imaginary**2
        return ZDANumber((self.real*other.real+self.imaginary*other.imaginary)/den,(self.imaginary*other.real-self.real*other.imaginary)/den)
    def document(self):
        def ratio(n):return {'numerator':str(n.numerator),'denominator':str(n.denominator)}
        return {'schema':'ziokt.zda-number.v1','state':self.state,'real':ratio(self.real),'imaginary':ratio(self.imaginary)}


@dataclass(frozen=True)
class AnoNumber:
    real:Fraction=Fraction(0)
    imaginary:Fraction=Fraction(0)
    ano_part:Signal=Signal.NEGATIVE
    def __post_init__(self):
        object.__setattr__(self,'real',_fraction(self.real));object.__setattr__(self,'imaginary',_fraction(self.imaginary));object.__setattr__(self,'ano_part',signal(self.ano_part))
    def document(self):
        return {'schema':'ziokt.ano-number.v1','profile':PROFILE,'real':_ratio_document(self.real),'imaginary':_ratio_document(self.imaginary),'ano_part':self.ano_part.value}
    @classmethod
    def from_document(cls,value):
        if not isinstance(value,dict) or set(value)!={'schema','profile','real','imaginary','ano_part'} or value['schema']!='ziokt.ano-number.v1' or value['profile']!=PROFILE:
            raise ProtocolError('INVALID_ANO','versioned Ano number required')
        return cls(_read_ratio(value['real']),_read_ratio(value['imaginary']),signal(value['ano_part']))
    def __add__(self,other):
        if not isinstance(other,AnoNumber):return NotImplemented
        return AnoNumber(self.real+other.real,self.imaginary+other.imaginary,merge(self.ano_part,other.ano_part))
    def __mul__(self,other):
        if not isinstance(other,AnoNumber):return NotImplemented
        return AnoNumber(self.real*other.real-self.imaginary*other.imaginary,self.real*other.imaginary+self.imaginary*other.real,cross(self.ano_part,other.ano_part))


@dataclass(frozen=True)
class AnoVector:
    x:AnoNumber
    y:AnoNumber
    z:AnoNumber
    def __post_init__(self):
        if any(not isinstance(v,AnoNumber) for v in (self.x,self.y,self.z)):raise ProtocolError('INVALID_ANO','typed vector coefficients required')
    def document(self):
        return {'schema':'ziokt.ano-vector.v1','profile':PROFILE,'coefficients':[value.document() for value in (self.x,self.y,self.z)]}
    @classmethod
    def from_document(cls,value):
        if not isinstance(value,dict) or set(value)!={'schema','profile','coefficients'} or value['schema']!='ziokt.ano-vector.v1' or value['profile']!=PROFILE or not isinstance(value['coefficients'],list) or len(value['coefficients'])!=3:
            raise ProtocolError('INVALID_ANO','three versioned Ano coefficients required')
        return cls(*(AnoNumber.from_document(item) for item in value['coefficients']))
    def __add__(self,other):return AnoVector(self.x+other.x,self.y+other.y,self.z+other.z)
    def dot(self,other):return self.x*other.x+self.y*other.y+self.z*other.z


def truth_table(*,profile=PROFILE,include_unknown=False):
    _profile(profile);rows=[]
    states=tuple(Signal) if include_unknown else (Signal.NEGATIVE,Signal.POSITIVE)
    for a in states:
        for b in states:
            rows.append({'a':a.value,'b':b.value,'merge':merge(a,b,profile=profile).value,'cross':cross(a,b,profile=profile).value,
                         'loop':merge(merge(a,b,profile=profile),merge(a,b,profile=profile),profile=profile).value,'mirror':cross(merge(a,b,profile=profile),merge(a,b,profile=profile),profile=profile).value})
    return {'schema':'ziokt.ano-truth-table.v1','profile':profile,'rows':rows,'exhaustive':True,'cryptographic_proof':False}


def law_report(profile=PROFILE):
    """Exhaustive finite-domain witnesses; not a proof about unbounded numbers or policy."""
    from itertools import product
    _profile(profile)
    states=tuple(Signal)
    m=lambda a,b:merge(a,b,profile=profile)
    x=lambda a,b:cross(a,b,profile=profile)
    def check(arity,predicate):
        cases=list(product(states,repeat=arity))
        failures=[args for args in cases if not predicate(*args)]
        return {'holds':not failures,'cases':len(cases),'counterexample':[v.value for v in failures[0]] if failures else None}
    laws={
        'merge_commutative':check(2,lambda a,b:m(a,b)==m(b,a)),
        'cross_commutative':check(2,lambda a,b:x(a,b)==x(b,a)),
        'merge_associative':check(3,lambda a,b,c:m(m(a,b),c)==m(a,m(b,c))),
        'cross_associative':check(3,lambda a,b,c:x(x(a,b),c)==x(a,x(b,c))),
        'cross_distributes_over_merge':check(3,lambda a,b,c:x(a,m(b,c))==m(x(a,b),x(a,c))),
        'merge_identity_negative':check(1,lambda a:m(a,Signal.NEGATIVE)==a),
        'cross_identity_positive':check(1,lambda a:x(a,Signal.POSITIVE)==a),
        'unknown_absorbs_merge':check(1,lambda a:m(a,Signal.UNKNOWN)==Signal.UNKNOWN),
        'unknown_absorbs_cross':check(1,lambda a:x(a,Signal.UNKNOWN)==Signal.UNKNOWN),
    }
    return {'schema':'ziokt.ano-laws.v1','profile':profile,'domain':[s.value for s in states],
            'method':'exhaustive finite enumeration','laws':laws,'numeric_field_proof':False,'security_policy_proof':False}


def calculate(kind,operation,left,right):
    """Expose existing exact operations without evaluating code or granting authority."""
    types={'zda':ZDANumber,'ano':AnoNumber,'vector':AnoVector}
    operations={'zda':{'add','sub','mul','div'},'ano':{'add','mul'},'vector':{'add','dot'}}
    if not isinstance(kind,str) or kind not in types or not isinstance(operation,str) or operation not in operations[kind]:
        raise ProtocolError('INVALID_ANO','existing typed algebra operation required')
    a,b=types[kind].from_document(left),types[kind].from_document(right)
    if operation=='add':result=a+b
    elif operation=='sub':result=a-b
    elif operation=='mul':result=a*b
    elif operation=='div':result=a/b
    else:result=a.dot(b)
    return {'schema':'ziokt.ano-calculation.v1','result':result.document(),'cryptographic_proof':False}

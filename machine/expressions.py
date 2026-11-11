"""Small, non-executable expression language for reviewed target-weight rules.

No imports, attributes, indexing, comprehensions, assignments or Python eval.
Each expression is evaluated against past completed bars only.
"""
import ast
import math
import operator
from statistics import mean, pstdev

from .common import require, number


class NotReady(Exception):
    pass


def parse(expression):
    require(isinstance(expression,str) and len(expression)<=4000,"Expression must be text under 4000 characters")
    tree=ast.parse(expression,mode="eval")
    require(len(list(ast.walk(tree)))<=250,"Expression is too complex")
    allowed=(ast.Expression,ast.Constant,ast.Name,ast.Load,ast.Call,ast.BinOp,ast.UnaryOp,ast.Compare,ast.BoolOp,ast.IfExp,
             ast.Add,ast.Sub,ast.Mult,ast.Div,ast.Pow,ast.USub,ast.UAdd,ast.Not,ast.And,ast.Or,ast.Gt,ast.GtE,ast.Lt,ast.LtE,ast.Eq,ast.NotEq)
    for node in ast.walk(tree):
        require(isinstance(node,allowed),f"Unsupported expression syntax: {type(node).__name__}")
        if isinstance(node,ast.Call):
            require(isinstance(node.func,ast.Name) and not node.keywords,"Only documented function calls with positional arguments are allowed")
    return tree


def evaluate(expression,history,params,symbol,universe):
    tree=parse(expression)

    def lag_value(s,lag=0,field="close"):
        require(s in universe,"Expression references a symbol outside the universe")
        require(isinstance(lag,(int,float)) and float(lag).is_integer() and lag>=0,"Lag must be a nonnegative integer")
        lag=int(lag)
        if lag>=len(history):
            raise NotReady()
        bar=history[-1-lag][1][s]
        require(field in bar and bar[field] is not None,f"Missing input {s}.{field}; no value inferred")
        return number(bar[field],field)

    def series(s,n):
        require(isinstance(n,(int,float)) and float(n).is_integer() and 2<=n<=10000,"Window must be an integer from 2 to 10000")
        if n>len(history):
            raise NotReady()
        # Raw-price split discontinuities require an explicit strategy-specific convention.
        require(all(f[s]["split"]==1 for _,f in history[-int(n):]),"Expression window crosses a split; provide an action-aware strategy adapter")
        return [lag_value(s,i) for i in range(int(n))]

    def zscore(s,n):
        values=series(s,n)
        sd=pstdev(values)
        return (values[0]-mean(values))/sd if sd else 0.0

    def parameter(name):
        require(name in params,f"Unknown parameter {name}")
        return number(params[name],name)

    functions={"price":lag_value,"sma":lambda s,n:mean(series(s,n)),"std":lambda s,n:pstdev(series(s,n)),
               "momentum":lambda s,n:lag_value(s)/lag_value(s,n)-1,"zscore":zscore,
               "feature":lambda name,s,lag=0:lag_value(s,lag,"feature_"+name),"param":parameter,"abs":abs,"min":min,"max":max}
    binary={ast.Add:operator.add,ast.Sub:operator.sub,ast.Mult:operator.mul,ast.Div:operator.truediv,ast.Pow:operator.pow}
    compare={ast.Gt:operator.gt,ast.GtE:operator.ge,ast.Lt:operator.lt,ast.LtE:operator.le,ast.Eq:operator.eq,ast.NotEq:operator.ne}

    def visit(node):
        if isinstance(node,ast.Expression):
            return visit(node.body)
        if isinstance(node,ast.Constant):
            require(isinstance(node.value,(str,int,float,bool)),"Unsupported literal")
            return node.value
        if isinstance(node,ast.Name):
            require(node.id in ("symbol","n_assets"),f"Unknown name {node.id}")
            return symbol if node.id=="symbol" else len(universe)
        if isinstance(node,ast.Call):
            require(node.func.id in functions,f"Unknown function {node.func.id}")
            return functions[node.func.id](*[visit(a) for a in node.args])
        if isinstance(node,ast.IfExp):
            return visit(node.body if visit(node.test) else node.orelse)
        if isinstance(node,ast.BoolOp):
            if isinstance(node.op,ast.And):
                return all(visit(v) for v in node.values)
            return any(visit(v) for v in node.values)
        if isinstance(node,ast.UnaryOp):
            v=visit(node.operand)
            return -v if isinstance(node.op,ast.USub) else (+v if isinstance(node.op,ast.UAdd) else not v)
        if isinstance(node,ast.BinOp):
            a,b=visit(node.left),visit(node.right)
            number(a,"left operand")
            number(b,"right operand")
            if isinstance(node.op,ast.Pow):
                require(abs(b)<=10 and abs(a)<=1e10,"Exponent outside permitted bounds")
            value=binary[type(node.op)](a,b)
            return number(value,"expression result")
        if isinstance(node,ast.Compare):
            a=visit(node.left)
            for op,bnode in zip(node.ops,node.comparators):
                b=visit(bnode)
                if not compare[type(op)](a,b):
                    return False
                a=b
            return True
        raise ValueError("Unsupported expression")
    try:
        return number(visit(tree),"target weight")
    except NotReady:
        return 0.0

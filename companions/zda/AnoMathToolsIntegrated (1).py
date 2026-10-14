"""Typed compatibility exports; no contradictory operator redefinitions."""
from ziokt.ano import AnoNumber,AnoVector,merge,cross,evaluate,truth_table
AnoNumberRefined=AnoNumber
AnoVectorRefinedV2=AnoVector
ano_addition=merge
ano_multiplication=cross
if __name__=='__main__':
    import json
    print(json.dumps(truth_table(),ensure_ascii=False))

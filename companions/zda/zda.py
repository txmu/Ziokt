"""Bounded exact ZDA numeric states and Ano logic for the Ziokt ecosystem."""
from ziokt.ano import ZDANumber,Signal,evaluate,truth_table,defence
if __name__=='__main__':
    import json
    print(json.dumps(truth_table(),ensure_ascii=False))

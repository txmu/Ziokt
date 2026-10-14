
import React, { useState } from 'react';
import { X, ArrowRightLeft, AlertTriangle } from 'lucide-react';
import { Subscription, OperatorType } from '../types';
import { OPERATOR_TYPES } from '../constants';

interface PortingModalProps {
  subscription: Subscription;
  onConfirm: (subId: string, updates: Partial<Subscription>) => void;
  onClose: () => void;
}

const PortingModal: React.FC<PortingModalProps> = ({ subscription, onConfirm, onClose }) => {
  const [operatorType, setOperatorType] = useState<OperatorType>(subscription.operatorType || 'MNO');
  const [simType, setSimType] = useState<'esim' | 'physical'>(subscription.simType || 'esim');
  const [physicalCardName, setPhysicalCardName] = useState(subscription.physicalCardName || '');
  const [cost, setCost] = useState(subscription.cost.toString());
  const [cycleDays, setCycleDays] = useState(subscription.cycleDays);
  
  const handleSave = () => {
    const today = new Date().toLocaleDateString();
    const historyNote = `[${today}] 🔄 携号转网: 原运营商类型 ${subscription.operatorType}, 原类型 ${subscription.simType}`;
    
    const updates: Partial<Subscription> = {
      operatorType,
      simType,
      physicalCardName: simType === 'physical' ? physicalCardName : undefined,
      eSim: simType === 'esim' ? undefined : subscription.eSim, // Clear eSIM if moving to physical, or keep/reset if moving to eSIM? Usually reset.
      cost: Number(cost),
      cycleDays,
      keepAliveNote: subscription.keepAliveNote ? `${subscription.keepAliveNote}\n${historyNote}` : historyNote
    };
    
    // If moving to eSIM, clear previous physical info. If moving to Physical, clear eSIM info.
    if (simType === 'physical') {
        updates.eSim = undefined;
    } else {
        updates.eSim = undefined; // Reset eSIM association for new provider
    }

    onConfirm(subscription.id, updates);
  };

  return (
    <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-md overflow-hidden animate-fade-in">
        <div className="flex justify-between items-center p-4 border-b border-gray-100 bg-gray-50">
          <h2 className="text-lg font-bold text-gray-800 flex items-center gap-2">
            <ArrowRightLeft className="w-5 h-5 text-indigo-600" />
            携号转网 (MNP)
          </h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600"><X className="w-6 h-6" /></button>
        </div>
        
        <div className="p-6 space-y-4">
           <div className="bg-amber-50 p-3 rounded border border-amber-100 flex gap-2 text-amber-800 text-sm">
             <AlertTriangle className="w-5 h-5 flex-shrink-0" />
             <p>此操作将保留原号码 ID、备注和电话号码，仅变更运营商及套餐计费信息。转网记录将自动添加至备注。</p>
           </div>

           <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">当前号码</label>
              <div className="bg-gray-100 p-2 rounded text-gray-600 font-mono text-sm">{subscription.phoneNumber || '无号码'}</div>
           </div>

           <div>
             <label className="block text-sm font-medium text-gray-700 mb-1">新运营商类型</label>
             <select value={operatorType} onChange={(e) => setOperatorType(e.target.value as OperatorType)} className="w-full px-3 py-2 border rounded-lg bg-white">
                {OPERATOR_TYPES.map(op => <option key={op.value} value={op.value}>{op.label}</option>)}
             </select>
           </div>
           
           <div>
             <label className="block text-sm font-medium text-gray-700 mb-1">新 SIM 卡形式</label>
             <div className="flex gap-2">
               <label className={`flex-1 flex items-center justify-center gap-2 p-2 border rounded cursor-pointer ${simType === 'esim' ? 'bg-indigo-50 border-indigo-500 text-indigo-700' : 'hover:bg-gray-50'}`}>
                  <input type="radio" checked={simType === 'esim'} onChange={() => setSimType('esim')} className="hidden" />
                  <span>eSIM</span>
               </label>
               <label className={`flex-1 flex items-center justify-center gap-2 p-2 border rounded cursor-pointer ${simType === 'physical' ? 'bg-indigo-50 border-indigo-500 text-indigo-700' : 'hover:bg-gray-50'}`}>
                  <input type="radio" checked={simType === 'physical'} onChange={() => setSimType('physical')} className="hidden" />
                  <span>实体卡</span>
               </label>
             </div>
           </div>
           
           {simType === 'physical' && (
              <div>
                 <label className="block text-sm font-medium text-gray-700 mb-1">新卡名称</label>
                 <input type="text" value={physicalCardName} onChange={(e) => setPhysicalCardName(e.target.value)} className="w-full px-3 py-2 border rounded-lg" placeholder="新实体卡名称..." />
              </div>
           )}

           <div className="grid grid-cols-2 gap-4">
              <div>
                 <label className="block text-sm font-medium text-gray-700 mb-1">新费用</label>
                 <input type="number" value={cost} onChange={(e) => setCost(e.target.value)} className="w-full px-3 py-2 border rounded-lg" />
              </div>
              <div>
                 <label className="block text-sm font-medium text-gray-700 mb-1">新周期 (天)</label>
                 <input type="number" value={cycleDays} onChange={(e) => setCycleDays(Number(e.target.value))} className="w-full px-3 py-2 border rounded-lg" />
              </div>
           </div>
        </div>

        <div className="p-4 border-t border-gray-100 flex justify-end gap-3 bg-gray-50">
           <button onClick={onClose} className="px-4 py-2 text-gray-600 hover:bg-gray-200 rounded">取消</button>
           <button onClick={handleSave} className="px-4 py-2 bg-indigo-600 text-white rounded hover:bg-indigo-700">确认转网</button>
        </div>
      </div>
    </div>
  );
};

export default PortingModal;

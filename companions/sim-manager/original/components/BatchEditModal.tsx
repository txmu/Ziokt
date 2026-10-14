import React, { useState } from 'react';
import { X } from 'lucide-react';
import { Subscription, PaymentMethod } from '../types';
import { PAYMENT_METHODS } from '../constants';

interface BatchEditModalProps {
  selectedCount: number;
  onSave: (updates: Partial<Subscription>) => void;
  onClose: () => void;
}

const BatchEditModal: React.FC<BatchEditModalProps> = ({ selectedCount, onSave, onClose }) => {
  const [fieldsToUpdate, setFieldsToUpdate] = useState<Set<string>>(new Set());
  
  const [cycleDays, setCycleDays] = useState(30);
  const [currency, setCurrency] = useState('CNY');
  const [notificationThreshold, setNotificationThreshold] = useState(3);
  const [priority, setPriority] = useState(2);
  const [paymentMethods, setPaymentMethods] = useState<PaymentMethod[]>([]);

  const toggleField = (field: string) => {
    const newSet = new Set(fieldsToUpdate);
    if (newSet.has(field)) newSet.delete(field);
    else newSet.add(field);
    setFieldsToUpdate(newSet);
  };

  const handleSave = () => {
    const updates: Partial<Subscription> = {};
    if (fieldsToUpdate.has('cycleDays')) updates.cycleDays = Number(cycleDays);
    if (fieldsToUpdate.has('currency')) updates.currency = currency;
    if (fieldsToUpdate.has('notificationThreshold')) updates.notificationThreshold = Number(notificationThreshold);
    if (fieldsToUpdate.has('priority')) updates.priority = Number(priority);
    if (fieldsToUpdate.has('paymentMethods')) updates.paymentMethods = paymentMethods;
    
    onSave(updates);
  };

  return (
    <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-md overflow-hidden">
        <div className="flex justify-between items-center p-4 border-b border-gray-100">
          <h2 className="text-lg font-bold text-gray-800">批量编辑 ({selectedCount} 项)</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600"><X className="w-6 h-6" /></button>
        </div>
        
        <div className="p-6 space-y-4 max-h-[70vh] overflow-y-auto">
          <p className="text-sm text-gray-500 mb-4">勾选要统一修改的字段。未勾选的字段将保持原样。</p>

          <div className="flex items-start gap-3 p-3 border rounded bg-gray-50">
             <input type="checkbox" checked={fieldsToUpdate.has('cycleDays')} onChange={() => toggleField('cycleDays')} className="mt-1" />
             <div className="flex-1">
                <label className="text-sm font-medium block">续费周期 (天)</label>
                <input type="number" value={cycleDays} disabled={!fieldsToUpdate.has('cycleDays')} onChange={(e) => setCycleDays(Number(e.target.value))} className="w-full mt-1 px-2 py-1 border rounded disabled:bg-gray-100" />
             </div>
          </div>

          <div className="flex items-start gap-3 p-3 border rounded bg-gray-50">
             <input type="checkbox" checked={fieldsToUpdate.has('currency')} onChange={() => toggleField('currency')} className="mt-1" />
             <div className="flex-1">
                <label className="text-sm font-medium block">货币单位</label>
                <select value={currency} disabled={!fieldsToUpdate.has('currency')} onChange={(e) => setCurrency(e.target.value)} className="w-full mt-1 px-2 py-1 border rounded disabled:bg-gray-100">
                   <option value="CNY">CNY</option><option value="USD">USD</option><option value="HKD">HKD</option><option value="EUR">EUR</option>
                </select>
             </div>
          </div>

           <div className="flex items-start gap-3 p-3 border rounded bg-gray-50">
             <input type="checkbox" checked={fieldsToUpdate.has('notificationThreshold')} onChange={() => toggleField('notificationThreshold')} className="mt-1" />
             <div className="flex-1">
                <label className="text-sm font-medium block">到期提醒阈值 (天)</label>
                <input type="number" value={notificationThreshold} disabled={!fieldsToUpdate.has('notificationThreshold')} onChange={(e) => setNotificationThreshold(Number(e.target.value))} className="w-full mt-1 px-2 py-1 border rounded disabled:bg-gray-100" />
             </div>
          </div>
          
           <div className="flex items-start gap-3 p-3 border rounded bg-gray-50">
             <input type="checkbox" checked={fieldsToUpdate.has('priority')} onChange={() => toggleField('priority')} className="mt-1" />
             <div className="flex-1">
                <label className="text-sm font-medium block">优先级</label>
                 <select value={priority} disabled={!fieldsToUpdate.has('priority')} onChange={(e) => setPriority(Number(e.target.value))} className="w-full mt-1 px-2 py-1 border rounded disabled:bg-gray-100">
                     <option value={1}>⚡ 高</option>
                     <option value={2}>🔵 中</option>
                     <option value={3}>⚪ 低</option>
                   </select>
             </div>
          </div>

          <div className="flex items-start gap-3 p-3 border rounded bg-gray-50">
             <input type="checkbox" checked={fieldsToUpdate.has('paymentMethods')} onChange={() => toggleField('paymentMethods')} className="mt-1" />
             <div className="flex-1">
                <label className="text-sm font-medium block">支付方式 (覆盖)</label>
                 <div className="grid grid-cols-3 gap-2 mt-2">
                  {PAYMENT_METHODS.map(method => (
                    <label key={method} className={`flex items-center gap-2 p-1 border rounded cursor-pointer text-xs ${paymentMethods.includes(method as PaymentMethod) ? 'bg-indigo-50 border-indigo-500' : 'bg-white border-gray-200'} ${!fieldsToUpdate.has('paymentMethods') ? 'opacity-50 cursor-not-allowed' : ''}`}>
                      <input type="checkbox" disabled={!fieldsToUpdate.has('paymentMethods')} checked={paymentMethods.includes(method as PaymentMethod)} onChange={() => {
                          setPaymentMethods(prev => prev.includes(method as PaymentMethod) ? prev.filter(p => p !== method) : [...prev, method as PaymentMethod]);
                      }} className="rounded text-indigo-600 focus:ring-indigo-500" />
                      <span>{method}</span>
                    </label>
                  ))}
                </div>
             </div>
          </div>
        </div>

        <div className="p-4 bg-gray-50 border-t flex justify-end gap-3">
          <button onClick={onClose} className="px-4 py-2 text-gray-600 hover:bg-gray-200 rounded">取消</button>
          <button onClick={handleSave} disabled={fieldsToUpdate.size === 0} className="px-4 py-2 bg-indigo-600 text-white rounded hover:bg-indigo-700 disabled:opacity-50">应用修改</button>
        </div>
      </div>
    </div>
  );
};

export default BatchEditModal;
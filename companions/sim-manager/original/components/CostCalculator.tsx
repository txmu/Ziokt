import React, { useState } from 'react';
import { X, Calculator } from 'lucide-react';
import { Subscription } from '../types';
import { calculateNextRenewal } from '../utils/helpers';

interface CostCalculatorProps {
  subscriptions: Subscription[];
  onClose: () => void;
}

const CostCalculator: React.FC<CostCalculatorProps> = ({ subscriptions, onClose }) => {
  const [startDate, setStartDate] = useState(new Date().toISOString().slice(0, 10));
  const [endDate, setEndDate] = useState(new Date(new Date().setMonth(new Date().getMonth() + 1)).toISOString().slice(0, 10));
  
  const [results, setResults] = useState<Record<string, number> | null>(null);

  const calculate = () => {
    const start = new Date(startDate);
    const end = new Date(endDate);
    start.setHours(0,0,0,0);
    end.setHours(23,59,59,999);

    const currencyTotals: Record<string, number> = {};

    subscriptions.forEach(sub => {
      // Calculate all renewals between start and end
      // 1. Find next renewal relative to 'now' first (standard logic), 
      //    BUT actually we should find first renewal ON or AFTER start date.
      
      // Let's project from subscription startDate
      const subStart = new Date(sub.startDate);
      subStart.setHours(0,0,0,0);
      
      let currentRenewal = new Date(subStart);
      
      // Fast forward to window start
      if (currentRenewal < start) {
         const diffTime = start.getTime() - currentRenewal.getTime();
         const cycleDays = Math.max(sub.cycleDays, 1);
         const cycleMs = cycleDays * 24 * 60 * 60 * 1000;
         const cyclesNeeded = Math.ceil(diffTime / cycleMs);
         currentRenewal = new Date(subStart.getTime() + (cyclesNeeded * cycleMs));
      }

      // Iterate through renewals in window
      let loops = 0;
      while (currentRenewal <= end && loops < 1000) {
        if (currentRenewal >= start) {
           const curr = sub.currency || 'CNY';
           currencyTotals[curr] = (currencyTotals[curr] || 0) + sub.cost;
        }
        // Next cycle
        const cycleDays = Math.max(sub.cycleDays, 1);
        currentRenewal = new Date(currentRenewal.getTime() + (cycleDays * 24 * 60 * 60 * 1000));
        loops++;
      }
    });

    setResults(currencyTotals);
  };

  return (
    <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-sm overflow-hidden">
        <div className="flex justify-between items-center p-4 border-b border-gray-100">
          <h2 className="text-lg font-bold text-gray-800 flex items-center gap-2">
            <Calculator className="w-5 h-5 text-indigo-600" />
            费用计算器
          </h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600"><X className="w-6 h-6" /></button>
        </div>
        
        <div className="p-5 space-y-4">
           <div>
             <label className="block text-sm font-medium text-gray-700 mb-1">开始日期</label>
             <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} className="w-full px-3 py-2 border rounded-lg" />
           </div>
           <div>
             <label className="block text-sm font-medium text-gray-700 mb-1">结束日期</label>
             <input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} className="w-full px-3 py-2 border rounded-lg" />
           </div>

           <button onClick={calculate} className="w-full bg-indigo-600 text-white py-2 rounded-lg font-medium hover:bg-indigo-700 transition-colors">
             计算应付款
           </button>

           {results && (
             <div className="mt-4 pt-4 border-t border-gray-100 animate-fade-in">
               <h3 className="text-sm font-medium text-gray-500 mb-2">计算结果</h3>
               {Object.keys(results).length === 0 ? (
                 <p className="text-gray-400 text-sm">该时间段内无续费。</p>
               ) : (
                 <div className="space-y-2">
                   {Object.entries(results).map(([curr, total]) => (
                     <div key={curr} className="flex justify-between items-center bg-gray-50 p-3 rounded-lg">
                       <span className="font-bold text-gray-700">{curr}</span>
                       <span className="font-mono text-indigo-600 font-bold text-lg">{(total as number).toFixed(2)}</span>
                     </div>
                   ))}
                 </div>
               )}
             </div>
           )}
        </div>
      </div>
    </div>
  );
};

export default CostCalculator;
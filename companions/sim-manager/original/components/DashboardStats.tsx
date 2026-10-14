
import React from 'react';
import { CreditCard, AlertCircle, Layers, Coins, Globe, Trophy } from 'lucide-react';
import { Subscription } from '../types';
import { calculateNextRenewal, getDaysRemaining, getITUZone } from '../utils/helpers';

interface DashboardStatsProps {
  subscriptions: Subscription[];
}

const DashboardStats: React.FC<DashboardStatsProps> = ({ subscriptions }) => {
  // Group monthly costs by currency
  const monthlyCostsByCurrency = subscriptions.reduce((acc, sub) => {
    if (sub.cycleDays <= 0 || sub.isArchived) return acc;
    // Normalize to 30-day "month"
    const monthlyEquivalent = (sub.cost / sub.cycleDays) * 30;
    const currency = sub.currency || 'CNY';
    
    acc[currency] = (acc[currency] || 0) + monthlyEquivalent;
    return acc;
  }, {} as Record<string, number>);

  const activeCount = subscriptions.filter(s => !s.isArchived).length;
  
  const expiringSoon = subscriptions.filter(sub => {
    if (sub.isArchived) return false;
    const renewal = calculateNextRenewal(sub.startDate, sub.cycleDays, sub.cycleType, sub.lastActiveDate);
    const days = getDaysRemaining(renewal);
    return days >= 0 && days <= (sub.notificationThreshold || 7);
  }).length;

  const collectedZones = new Set(subscriptions.map(s => getITUZone(s.countryCode)).filter(z => z !== null));
  const progress = collectedZones.size;

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
      <div className="bg-white p-5 rounded-xl shadow-sm border border-gray-100 flex items-center gap-4">
        <div className="p-3 bg-blue-50 text-blue-600 rounded-lg">
          <Layers className="w-6 h-6" />
        </div>
        <div>
          <p className="text-sm text-gray-500 font-medium">持有套餐总数 (活跃)</p>
          <p className="text-2xl font-bold text-gray-800">{activeCount}</p>
        </div>
      </div>

      <div className="bg-white p-5 rounded-xl shadow-sm border border-gray-100 flex items-center gap-4">
        <div className="p-3 bg-indigo-50 text-indigo-600 rounded-lg">
          <Coins className="w-6 h-6" />
        </div>
        <div className="flex-1">
          <p className="text-sm text-gray-500 font-medium mb-1">预估月均开销 (30天)</p>
          {Object.keys(monthlyCostsByCurrency).length > 0 ? (
            <div className="grid grid-cols-2 gap-x-2 gap-y-0.5">
               {Object.entries(monthlyCostsByCurrency).map(([curr, amount]) => (
                  <div key={curr} className="flex justify-between items-baseline text-xs">
                     <span className="text-gray-500 font-medium">{curr}</span>
                     <span className="font-bold text-gray-800">{(amount as number).toFixed(0)}</span>
                  </div>
               ))}
            </div>
          ) : (
            <p className="text-sm text-gray-400">无活跃开销</p>
          )}
        </div>
      </div>

      <div className="bg-white p-5 rounded-xl shadow-sm border border-gray-100 flex items-center gap-4">
        <div className="p-3 bg-amber-50 text-amber-600 rounded-lg">
          <AlertCircle className="w-6 h-6" />
        </div>
        <div>
          <p className="text-sm text-gray-500 font-medium">即将到期</p>
          <p className="text-2xl font-bold text-gray-800">{expiringSoon}</p>
        </div>
      </div>

      <div className="bg-white p-5 rounded-xl shadow-sm border border-gray-100 flex items-center gap-4">
        <div className={`p-3 rounded-lg ${progress === 9 ? 'bg-yellow-50 text-yellow-600' : 'bg-emerald-50 text-emerald-600'}`}>
          {progress === 9 ? <Trophy className="w-6 h-6" /> : <Globe className="w-6 h-6" />}
        </div>
        <div>
          <p className="text-sm text-gray-500 font-medium">ITU 区域覆盖</p>
          <div className="flex items-baseline gap-1">
             <span className="text-2xl font-bold text-gray-800">{progress}</span>
             <span className="text-sm text-gray-400">/ 9</span>
          </div>
        </div>
      </div>
    </div>
  );
};

export default DashboardStats;

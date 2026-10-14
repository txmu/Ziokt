
import React, { useMemo } from 'react';
import { ChartWidget, Subscription, GlobalIO } from '../types';
import ChartRenderer from './ChartRenderer';
import { ArrowRightLeft, Database, X, Globe, Trophy, Medal } from 'lucide-react';
import { getITUZone, ITU_ZONES } from '../utils/helpers';

interface StatisticsPanelProps {
  subscriptions: Subscription[];
  widgets: ChartWidget[];
  globalIO: GlobalIO;
  onUpdateIO: (io: GlobalIO) => void;
  onRemoveWidget: (id: string) => void;
}

const StatisticsPanel: React.FC<StatisticsPanelProps> = ({ subscriptions, widgets, globalIO, onUpdateIO, onRemoveWidget }) => {
  
  // Prepare native stats
  const costByType = subscriptions.reduce((acc, sub) => {
    const type = sub.numberType || 'Mobile';
    acc[type] = (acc[type] || 0) + sub.cost;
    return acc;
  }, {} as Record<string, number>);

  const costByOperator = subscriptions.reduce((acc, sub) => {
    const type = sub.operatorType || 'MNO';
    acc[type] = (acc[type] || 0) + sub.cost;
    return acc;
  }, {} as Record<string, number>);

  // ITU Collection Stats
  const collectedZones = useMemo(() => {
    const zones = new Set<number>();
    subscriptions.forEach(s => {
      // Consider all subscriptions including archived ones for "Achievement" purposes?
      // Usually achievements include history. Let's include all.
      const z = getITUZone(s.countryCode);
      if (z) zones.add(z);
    });
    return zones;
  }, [subscriptions]);

  const allCollected = collectedZones.size === 9;

  return (
    <div className="space-y-6 animate-fade-in">
      
      {/* ITU Coverage Badge Wall */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-5 overflow-hidden relative">
          <div className="flex justify-between items-start mb-4">
              <div>
                  <h3 className="font-bold text-gray-800 text-lg flex items-center gap-2">
                      <Globe className="w-5 h-5 text-indigo-600" /> ITU 区域全收集挑战
                  </h3>
                  <p className="text-sm text-gray-500 mt-1">
                      点亮来自 ITU 九大区域的号码，解锁全球通成就。
                  </p>
              </div>
              <div className="text-right">
                   <div className="flex items-baseline justify-end gap-1">
                      <span className={`text-3xl font-black ${allCollected ? 'text-amber-500' : 'text-indigo-600'}`}>{collectedZones.size}</span>
                      <span className="text-gray-400 font-medium">/9</span>
                   </div>
                   <div className="text-[10px] text-gray-400 uppercase tracking-wider">Zones Collected</div>
              </div>
          </div>

          {/* Achievement Banner */}
          {allCollected && (
              <div className="mb-6 bg-gradient-to-r from-amber-100 via-yellow-100 to-amber-100 p-4 rounded-xl text-amber-900 flex items-center gap-4 shadow-sm border border-amber-200 animate-fade-in">
                  <div className="bg-white/80 p-3 rounded-full shadow-sm">
                      <Trophy className="w-8 h-8 text-amber-600" />
                  </div>
                  <div>
                      <h4 className="font-bold text-lg flex items-center gap-2">
                         🎉 达成成就：全球通大满贯！
                         <Medal className="w-5 h-5 text-amber-600" />
                      </h4>
                      <p className="text-sm font-medium opacity-80 mt-0.5">太棒了！您已集齐所有 ITU 编号区域的号码。</p>
                  </div>
              </div>
          )}

          {/* Grid */}
          <div className="grid grid-cols-3 sm:grid-cols-5 gap-3">
              {[1,2,3,4,5,6,7,8,9].map(zone => {
                  const has = collectedZones.has(zone);
                  return (
                      <div key={zone} className={`relative p-3 rounded-lg border flex flex-col items-center justify-center text-center transition-all duration-500 group ${
                          has ? 'bg-indigo-50 border-indigo-200 shadow-sm scale-100' : 'bg-gray-50 border-gray-100 grayscale opacity-60'
                      }`}>
                          <div className="flex items-center gap-1 mb-1">
                             <span className={`text-2xl font-black ${has ? 'text-indigo-600' : 'text-gray-300'}`}>{zone}</span>
                          </div>
                          <span className="text-[10px] text-gray-500 font-medium line-clamp-1">{ITU_ZONES[zone]}</span>
                          {has && (
                            <div className="absolute top-2 right-2 w-2 h-2 bg-green-500 rounded-full shadow-[0_0_5px_rgba(34,197,94,0.6)]"></div>
                          )}
                      </div>
                  )
              })}
          </div>
      </div>

      {/* IO Section */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-200 overflow-hidden">
        <div className="px-4 py-3 bg-gray-50 border-b border-gray-100 flex items-center gap-2">
           <ArrowRightLeft className="w-4 h-4 text-indigo-600" />
           <h3 className="font-bold text-gray-700 text-sm">全局 I/O 数据交换区</h3>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 h-40">
           <div className="flex flex-col border-b md:border-b-0 md:border-r border-gray-100">
              <label className="text-[10px] text-gray-400 font-bold px-3 py-1 uppercase">Input</label>
              <textarea 
                value={globalIO.input} 
                onChange={(e) => onUpdateIO({...globalIO, input: e.target.value})}
                className="flex-1 p-3 text-xs font-mono resize-none outline-none" 
                placeholder="在此输入文本，可供脚本 api.readInput() 读取..." 
              />
           </div>
           <div className="flex flex-col bg-gray-50/50">
              <label className="text-[10px] text-gray-400 font-bold px-3 py-1 uppercase">Output</label>
              <textarea 
                value={globalIO.output} 
                readOnly 
                className="flex-1 p-3 text-xs font-mono resize-none outline-none bg-transparent text-gray-600" 
                placeholder="脚本 api.writeOutput() 的结果将显示在此..." 
              />
           </div>
        </div>
      </div>

      {/* Built-in Stats */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
         <div className="h-64">
           <ChartRenderer 
             type="pie" 
             title="费用占比 (按号码类型)" 
             data={{ 
               labels: Object.keys(costByType), 
               values: Object.values(costByType) 
             }} 
           />
         </div>
         <div className="h-64">
           <ChartRenderer 
             type="bar" 
             title="费用占比 (按运营商类型)" 
             data={{ 
               labels: Object.keys(costByOperator), 
               values: Object.values(costByOperator) 
             }} 
           />
         </div>
      </div>

      {/* Custom Widgets */}
      {widgets.length > 0 && (
        <div>
           <h3 className="text-lg font-bold text-gray-800 mb-4 flex items-center gap-2">
             <Database className="w-5 h-5" /> 自定义仪表盘
           </h3>
           <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {widgets.map(w => (
                 <div key={w.id} className="h-60 relative group">
                    <ChartRenderer type={w.type} title={w.title} data={w.data} />
                    <button 
                      onClick={() => onRemoveWidget(w.id)}
                      className="absolute top-2 right-2 p-1 bg-white/80 rounded-full shadow hover:text-red-500 opacity-0 group-hover:opacity-100 transition-opacity"
                    >
                      <X className="w-3 h-3" />
                    </button>
                 </div>
              ))}
           </div>
        </div>
      )}
    </div>
  );
};

export default StatisticsPanel;

import React from 'react';
import { ChartType, ChartData } from '../types';

interface ChartRendererProps {
  type: ChartType;
  title: string;
  data: ChartData;
  height?: number;
}

const ChartRenderer: React.FC<ChartRendererProps> = ({ type, title, data, height = 200 }) => {
  const colors = ['#6366f1', '#ec4899', '#10b981', '#f59e0b', '#3b82f6', '#8b5cf6', '#ef4444', '#14b8a6'];
  
  const renderPie = () => {
    const total = data.values.reduce((a, b) => a + b, 0);
    if (total === 0) return <div className="text-gray-400 text-xs text-center py-10">No Data</div>;

    let currentAngle = 0;
    const slices = data.values.map((val, i) => {
      const percentage = val / total;
      const angle = percentage * 360;
      const slice = (
        <div
          key={i}
          className="absolute inset-0 rounded-full"
          style={{
            background: `conic-gradient(transparent ${currentAngle}deg, ${colors[i % colors.length]} ${currentAngle}deg ${currentAngle + angle}deg, transparent ${currentAngle + angle}deg)`,
            zIndex: data.values.length - i
          }}
        />
      );
      currentAngle += angle;
      return slice;
    });

    return (
      <div className="flex items-center justify-around h-full">
         <div className="relative w-32 h-32 rounded-full shadow-inner bg-gray-50 border border-gray-100">
           {slices}
           <div className="absolute inset-8 bg-white rounded-full z-10 flex items-center justify-center">
             <span className="text-xs font-bold text-gray-500">Total<br/>{total.toFixed(0)}</span>
           </div>
         </div>
         <div className="flex flex-col gap-1 text-xs overflow-y-auto max-h-40">
           {data.labels.map((label, i) => (
             <div key={i} className="flex items-center gap-2">
               <span className="w-2 h-2 rounded-full" style={{ backgroundColor: colors[i % colors.length] }}></span>
               <span className="text-gray-600 truncate max-w-[100px]" title={label}>{label}</span>
               <span className="font-mono font-medium">{data.values[i]}</span>
             </div>
           ))}
         </div>
      </div>
    );
  };

  const renderBar = () => {
    const max = Math.max(...data.values, 1);
    return (
      <div className="h-full flex items-end gap-2 pt-4 pb-6 px-2 overflow-x-auto">
        {data.values.map((val, i) => (
          <div key={i} className="flex-1 min-w-[30px] flex flex-col items-center group relative">
            <div 
              className="w-full bg-indigo-500 rounded-t hover:bg-indigo-400 transition-all relative"
              style={{ height: `${(val / max) * 100}%`, backgroundColor: colors[i % colors.length] }}
            >
               <div className="absolute -top-6 left-1/2 -translate-x-1/2 bg-gray-800 text-white text-[10px] px-1.5 py-0.5 rounded opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap z-10 pointer-events-none">
                 {val}
               </div>
            </div>
            <div className="text-[10px] text-gray-500 mt-1 truncate w-full text-center" title={data.labels[i]}>
              {data.labels[i]}
            </div>
          </div>
        ))}
      </div>
    );
  };

  const renderLine = () => {
    if (data.values.length < 2) return renderBar();
    const max = Math.max(...data.values, 1);
    const min = Math.min(...data.values, 0); // Assume 0 baseline usually
    const range = max - min;
    
    // Generate SVG path
    const points = data.values.map((val, i) => {
      const x = (i / (data.values.length - 1)) * 100;
      const y = 100 - ((val - min) / range) * 100;
      return `${x},${y}`;
    }).join(' ');

    return (
      <div className="h-full relative pt-2 pb-6 px-2">
        <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="w-full h-full overflow-visible">
           {/* Grid lines */}
           <line x1="0" y1="0" x2="100" y2="0" stroke="#e5e7eb" strokeWidth="0.5" />
           <line x1="0" y1="50" x2="100" y2="50" stroke="#e5e7eb" strokeWidth="0.5" />
           <line x1="0" y1="100" x2="100" y2="100" stroke="#e5e7eb" strokeWidth="0.5" />
           
           {/* The Line */}
           <polyline 
             points={points} 
             fill="none" 
             stroke="#6366f1" 
             strokeWidth="2" 
             strokeLinecap="round" 
             strokeLinejoin="round"
             className="path-anim"
           />
           
           {/* Points */}
           {data.values.map((val, i) => {
             const x = (i / (data.values.length - 1)) * 100;
             const y = 100 - ((val - min) / range) * 100;
             return (
               <circle key={i} cx={x} cy={y} r="2" fill="white" stroke="#6366f1" strokeWidth="1" className="hover:r-3 transition-all cursor-pointer">
                 <title>{data.labels[i]}: {val}</title>
               </circle>
             );
           })}
        </svg>
        <div className="flex justify-between text-[10px] text-gray-400 mt-1">
          <span>{data.labels[0]}</span>
          <span>{data.labels[data.labels.length - 1]}</span>
        </div>
      </div>
    );
  };

  return (
    <div className="w-full h-full flex flex-col bg-white rounded-lg border border-gray-200 overflow-hidden">
      <div className="px-4 py-2 border-b border-gray-100 bg-gray-50 flex justify-between items-center">
        <h4 className="text-xs font-bold text-gray-700 uppercase">{title}</h4>
        <span className="text-[10px] text-gray-400 uppercase">{type}</span>
      </div>
      <div className="flex-1 relative" style={{ minHeight: height }}>
        {type === 'pie' && renderPie()}
        {type === 'bar' && renderBar()}
        {type === 'line' && renderLine()}
      </div>
    </div>
  );
};

export default ChartRenderer;
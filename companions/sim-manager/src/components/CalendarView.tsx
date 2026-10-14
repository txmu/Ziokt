
import React, { useMemo, useState } from 'react';
import { ChevronLeft, ChevronRight, X } from 'lucide-react';
import { Subscription } from '../types';
import { calculateNextRenewal } from '../utils/helpers';

interface CalendarViewProps {
  subscriptions: Subscription[];
  onClose: () => void;
}

const CalendarView: React.FC<CalendarViewProps> = ({ subscriptions, onClose }) => {
  const [currentDate, setCurrentDate] = useState(new Date());

  const year = currentDate.getFullYear();
  const month = currentDate.getMonth();

  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const firstDayOfMonth = new Date(year, month, 1).getDay();

  // Generate events map
  const events = useMemo(() => {
     const map: Record<number, Subscription[]> = {};
     subscriptions.forEach(sub => {
        if(sub.isArchived) return;
        const renewal = calculateNextRenewal(sub.startDate, sub.cycleDays);
        // Check if renewal is in current month view
        if (renewal.getFullYear() === year && renewal.getMonth() === month) {
           const day = renewal.getDate();
           if (!map[day]) map[day] = [];
           map[day].push(sub);
        }
     });
     return map;
  }, [subscriptions, year, month]);

  const prevMonth = () => setCurrentDate(new Date(year, month - 1, 1));
  const nextMonth = () => setCurrentDate(new Date(year, month + 1, 1));

  const renderDays = () => {
    const days = [];
    // Padding
    for (let i = 0; i < firstDayOfMonth; i++) {
       days.push(<div key={`empty-${i}`} className="h-24 bg-gray-50/50 border-r border-b border-gray-100"></div>);
    }
    // Days
    for (let d = 1; d <= daysInMonth; d++) {
       const dailyEvents = events[d] || [];
       const isToday = new Date().toDateString() === new Date(year, month, d).toDateString();
       
       days.push(
         <div key={d} className={`h-24 border-r border-b border-gray-100 p-1 relative hover:bg-gray-50 transition-colors ${isToday ? 'bg-indigo-50/30' : ''}`}>
            <span className={`text-xs font-bold p-1 rounded-full w-6 h-6 flex items-center justify-center ${isToday ? 'bg-indigo-600 text-white' : 'text-gray-700'}`}>{d}</span>
            <div className="mt-1 space-y-1 overflow-y-auto max-h-[calc(100%-24px)] custom-scrollbar">
               {dailyEvents.map(sub => (
                  <div key={sub.id} className="text-[9px] px-1 py-0.5 rounded bg-amber-100 text-amber-800 border border-amber-200 truncate" title={`${sub.nickname} - ${sub.cost} ${sub.currency}`}>
                     {sub.nickname}
                  </div>
               ))}
            </div>
         </div>
       );
    }
    return days;
  };

  return (
    <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50 p-4">
       <div className="bg-white rounded-xl shadow-2xl w-full max-w-4xl h-[80vh] flex flex-col overflow-hidden">
          <div className="flex justify-between items-center p-4 border-b border-gray-200">
             <div className="flex items-center gap-4">
                <h2 className="text-lg font-bold text-gray-800">{currentDate.toLocaleDateString('en-US', { month: 'long', year: 'numeric' })}</h2>
                <div className="flex gap-1">
                   <button onClick={prevMonth} className="p-1 hover:bg-gray-100 rounded"><ChevronLeft className="w-5 h-5"/></button>
                   <button onClick={nextMonth} className="p-1 hover:bg-gray-100 rounded"><ChevronRight className="w-5 h-5"/></button>
                </div>
             </div>
             <button onClick={onClose}><X className="w-6 h-6 text-gray-400 hover:text-gray-600"/></button>
          </div>
          
          <div className="grid grid-cols-7 border-b border-gray-200 bg-gray-50 text-center py-2 text-xs font-bold text-gray-500">
             <div>SUN</div><div>MON</div><div>TUE</div><div>WED</div><div>THU</div><div>FRI</div><div>SAT</div>
          </div>
          
          <div className="flex-1 overflow-y-auto">
             <div className="grid grid-cols-7 border-l border-t border-gray-200">
                {renderDays()}
             </div>
          </div>
       </div>
    </div>
  );
};

export default CalendarView;

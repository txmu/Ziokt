
import React from 'react';
import { BookOpen, Cpu, Plus, CheckCircle, Smartphone } from 'lucide-react';

interface OnboardingGuideProps {
  onComplete: () => void;
}

const OnboardingGuide: React.FC<OnboardingGuideProps> = ({ onComplete }) => {
  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4 animate-fade-in">
      <div className="bg-white rounded-2xl shadow-2xl max-w-lg w-full overflow-hidden border border-gray-100">
        <div className="bg-gradient-to-r from-indigo-500 to-purple-600 p-6 text-white text-center">
          <BookOpen className="w-12 h-12 mx-auto mb-3 opacity-90" />
          <h2 className="text-2xl font-bold">欢迎使用全球通套餐管家</h2>
          <p className="text-indigo-100 mt-1 text-sm">3步快速上手指南</p>
        </div>
        
        <div className="p-6 space-y-6">
          <div className="flex gap-4">
            <div className="flex-shrink-0 w-10 h-10 bg-indigo-50 rounded-full flex items-center justify-center text-indigo-600 font-bold">1</div>
            <div>
              <h3 className="font-bold text-gray-800 flex items-center gap-2">
                注册 eSIM 芯片
                <Cpu className="w-4 h-4 text-gray-400" />
              </h3>
              <p className="text-sm text-gray-500 mt-1">
                点击顶部的 <strong>eSIM Manager (芯片图标)</strong>。
                先录入你拥有的实体卡(5ber/Estk等)或原生eSIM设备信息。支持记录换设备方式和历史。
              </p>
            </div>
          </div>

          <div className="flex gap-4">
            <div className="flex-shrink-0 w-10 h-10 bg-indigo-50 rounded-full flex items-center justify-center text-indigo-600 font-bold">2</div>
            <div>
              <h3 className="font-bold text-gray-800 flex items-center gap-2">
                添加套餐
                <Plus className="w-4 h-4 text-gray-400" />
              </h3>
              <p className="text-sm text-gray-500 mt-1">
                点击 <strong>“添加套餐”</strong>。
                如果是 eSIM 套餐，可以关联到第一步创建的芯片。如果是实体卡(Giffgaff等)，直接选择“实体卡”类型即可。
              </p>
            </div>
          </div>

          <div className="flex gap-4">
             <div className="flex-shrink-0 w-10 h-10 bg-indigo-50 rounded-full flex items-center justify-center text-indigo-600 font-bold">3</div>
             <div>
               <h3 className="font-bold text-gray-800 flex items-center gap-2">
                 更多设置
                 <Smartphone className="w-4 h-4 text-gray-400" />
               </h3>
               <p className="text-sm text-gray-500 mt-1">
                 点击右上角的 <strong>设置图标 (Settings)</strong> 可重命名 APP、切换主题及管理通知与日历导出功能。
               </p>
             </div>
          </div>
        </div>

        <div className="p-6 bg-gray-50 border-t border-gray-100 flex justify-center">
          <button 
            onClick={onComplete}
            className="flex items-center gap-2 bg-indigo-600 hover:bg-indigo-700 text-white px-8 py-3 rounded-xl font-bold shadow-lg transition-transform transform hover:scale-105"
          >
            <CheckCircle className="w-5 h-5" />
            我明白了，开始使用
          </button>
        </div>
      </div>
    </div>
  );
};

export default OnboardingGuide;

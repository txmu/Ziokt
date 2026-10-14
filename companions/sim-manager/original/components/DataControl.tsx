
import React, { useRef, useState } from 'react';
import { Download, Upload, AlertTriangle, Check } from 'lucide-react';
import { Subscription, ESimChip, SavedScript, AppData, ThemeType } from '../types';

interface DataControlProps {
  currentData: {
    appTitle: string;
    theme: ThemeType;
    hasReadGuide: boolean;
    subscriptions: Subscription[];
    eSimChips: ESimChip[];
    scripts: SavedScript[];
    chartWidgets?: any[];
  };
  onImport: (data: AppData, method: 'replace' | 'merge') => void;
}

const DataControl: React.FC<DataControlProps> = ({ currentData, onImport }) => {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [importStats, setImportStats] = useState<string | null>(null);

  const handleExport = () => {
    const exportData: AppData = {
      version: 3,
      ...currentData
    };
    const dataStr = JSON.stringify(exportData, null, 2);
    const blob = new Blob([dataStr], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `sim_manager_backup_${currentData.appTitle.replace(/\s+/g, '_')}_${new Date().toISOString().slice(0, 10)}.json`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const handleImportClick = () => {
    fileInputRef.current?.click();
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = (event) => {
      try {
        const json = JSON.parse(event.target?.result as string);
        
        let importedData: AppData;
        
        if (Array.isArray(json)) {
          // V1
          importedData = {
             version: 1,
             appTitle: '全球通套餐管家',
             theme: 'default',
             subscriptions: json,
             eSimChips: [],
             scripts: []
          };
        } else {
          // V2 & V3
          importedData = {
            version: json.version || 2,
            appTitle: json.appTitle || '全球通套餐管家',
            theme: json.theme || 'default',
            hasReadGuide: json.hasReadGuide,
            subscriptions: json.subscriptions || [],
            eSimChips: json.eSimChips || [],
            scripts: json.scripts || [],
            chartWidgets: json.chartWidgets || []
          };
        }

        const confirmMsg = `检测到备份包含:\n` +
          `- 标题: ${importedData.appTitle}\n` +
          `- 主题: ${importedData.theme}\n` +
          `- ${importedData.subscriptions.length} 个套餐\n` +
          `- ${importedData.eSimChips.length} 个芯片\n` +
          `请选择导入方式:`;
          
        if (window.confirm(`${confirmMsg}\n点击“确定”覆盖当前数据 (Replace)。\n点击“取消”尝试合并 (Merge)。`)) {
           onImport(importedData, 'replace');
           setImportStats('已覆盖数据');
        } else {
           onImport(importedData, 'merge');
           setImportStats('已合并数据');
        }

      } catch (err) {
        alert('无法解析文件格式。请确保是本软件导出的 JSON。');
      }
    };
    reader.readAsText(file);
    e.target.value = '';
  };

  return (
    <div className="flex gap-2 items-center">
      {importStats && (
        <div className="hidden sm:flex items-center gap-2 text-xs bg-green-50 text-green-700 px-3 py-1 rounded-full border border-green-200 mr-2 animate-fade-in">
          <Check className="w-3 h-3" />
          <span>{importStats}</span>
          <button onClick={() => setImportStats(null)} className="ml-1 hover:text-green-900"><AlertTriangle className="w-3 h-3" /></button>
        </div>
      )}
      <button
        onClick={handleExport}
        className="flex items-center gap-2 px-3 py-2 bg-white border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 transition-colors text-sm font-medium shadow-sm"
      >
        <Download className="w-4 h-4" />
        <span className="hidden sm:inline">备份</span>
      </button>
      <button
        onClick={handleImportClick}
        className="flex items-center gap-2 px-3 py-2 bg-white border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 transition-colors text-sm font-medium shadow-sm"
      >
        <Upload className="w-4 h-4" />
        <span className="hidden sm:inline">恢复</span>
      </button>
      <input
        type="file"
        ref={fileInputRef}
        onChange={handleFileChange}
        accept=".json"
        className="hidden"
      />
    </div>
  );
};

export default DataControl;

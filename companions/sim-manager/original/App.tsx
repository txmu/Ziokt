
import React, { useState, useEffect, useMemo } from 'react';
import { Plus, Search, Edit, Trash2, Calculator, Cpu, Code, LayoutDashboard, Archive, Settings, BarChart3, List, Filter, Terminal, XCircle, EyeOff, Calendar as CalendarIcon, Grid, Tag, Signal, AlertCircle } from 'lucide-react';
import { Subscription, ESimChip, SavedScript, AppData, ChartWidget, ThemeType, OperatorType, GlobalIO, NotificationSettings, SecuritySettings, SyncSettings, CurrencySettings } from './types';
import SubscriptionForm from './components/SubscriptionForm';
import SubscriptionCard from './components/SubscriptionCard';
import DashboardStats from './components/DashboardStats';
import DataControl from './components/DataControl';
import BatchEditModal from './components/BatchEditModal';
import CostCalculator from './components/CostCalculator';
import ESimManager from './components/ESimManager';
import ScriptPlayground from './components/ScriptPlayground';
import ChartRenderer from './components/ChartRenderer';
import OnboardingGuide from './components/OnboardingGuide';
import SettingsModal from './components/SettingsModal';
import StatisticsPanel from './components/StatisticsPanel';
import PortingModal from './components/PortingModal';
import ConfirmationModal from './components/ConfirmationModal';
import LockScreen from './components/LockScreen';
import CalendarView from './components/CalendarView';
import { calculateNextRenewal, getDaysRemaining, generateBatchICS, webdavClient, convertCurrency, getITUZone, ITU_ZONES, securityHelper, cryptoHelper, generateCSV, shareUtils } from './utils/helpers';
import { OPERATOR_TYPES } from './constants';

// Hack for TypeScript to recognize the experimental API if not globally augmented
declare const TimestampTrigger: any;

const App: React.FC = () => {
  // Core Data
  const [appTitle, setAppTitle] = useState('全球通套餐管家');
  const [theme, setTheme] = useState<ThemeType>('default');
  const [subscriptions, setSubscriptions] = useState<Subscription[]>([]);
  const [eSimChips, setESimChips] = useState<ESimChip[]>([]);
  const [scripts, setScripts] = useState<SavedScript[]>([]);
  const [chartWidgets, setChartWidgets] = useState<ChartWidget[]>([]);
  const [globalIO, setGlobalIO] = useState<GlobalIO>({ input: '', output: '' });
  const [notificationSettings, setNotificationSettings] = useState<NotificationSettings>({ enabled: true, useTriggers: false });
  const [hasReadGuide, setHasReadGuide] = useState(false);
  const [logs, setLogs] = useState<{time: string, msg: string}[]>([]);
  
  const addLog = (msg: string) => {
  const time = new Date().toLocaleTimeString();
  setLogs(prev => [{ time, msg }, ...prev].slice(0, 50)); 
};
  
  // v4 New Data
  const [securitySettings, setSecuritySettings] = useState<SecuritySettings>({ enabled: false, pinHash: '' });
  const [syncSettings, setSyncSettings] = useState<SyncSettings>({});
  const [currencySettings, setCurrencySettings] = useState<CurrencySettings>({ baseCurrency: 'CNY', rates: {} });
  
  // UI States
  const [isDemoMode, setIsDemoMode] = useState(false); 
  const [viewMode, setViewMode] = useState<'cards' | 'stats' | 'calendar'>('cards');
  const [groupBy, setGroupBy] = useState<'none' | 'itu' | 'simType'>('none');
  const [isFormOpen, setIsFormOpen] = useState(false);
  const [editingSub, setEditingSub] = useState<Subscription | undefined>(undefined);
  const [portingSub, setPortingSub] = useState<Subscription | undefined>(undefined);
  const [isBatchEditOpen, setIsBatchEditOpen] = useState(false);
  const [isCalculatorOpen, setIsCalculatorOpen] = useState(false);
  const [isESimManagerOpen, setIsESimManagerOpen] = useState(false);
  const [isScriptOpen, setIsScriptOpen] = useState(false);
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [showArchived, setShowArchived] = useState(false);
  const [showAdvancedFilter, setShowAdvancedFilter] = useState(false); // Controls visibility of the full filter bar
  
  // App Lock State
  const [isLocked, setIsLocked] = useState(false);
  const [hasCheckedLock, setHasCheckedLock] = useState(false);

  // Delete Modal State
  const [deleteTargetId, setDeleteTargetId] = useState<string | null>(null);
  const [isBatchDelete, setIsBatchDelete] = useState(false);

  // Archive Modal State
  const [archiveTargetId, setArchiveTargetId] = useState<string | null>(null);
  
  // Selection
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  
  // Filter/Sort States
  const [searchQuery, setSearchQuery] = useState('');
  const [filterStatus, setFilterStatus] = useState<'all' | 'expiring'>('all');
  const [filterPriority, setFilterPriority] = useState<string>('all'); 
  const [filterType, setFilterType] = useState<'all' | 'esim' | 'physical'>('all');
  const [filterOperator, setFilterOperator] = useState<string>('all');
  const [filterTag, setFilterTag] = useState<string>('all'); 
  const [filterExpression, setFilterExpression] = useState(''); 
  const [sortBy, setSortBy] = useState<'expiry' | 'cost' | 'priority' | 'nickname'>('expiry');

  // Initialization
  useEffect(() => {
    const saved = localStorage.getItem('sim-manager-data-v3');
    if (saved) {
      try {
        const data: AppData = JSON.parse(saved);
        if (data.appTitle) setAppTitle(data.appTitle);
        if (data.theme) setTheme(data.theme);
        if (data.isDemoMode !== undefined) setIsDemoMode(data.isDemoMode);
        setSubscriptions(data.subscriptions || []);
        setESimChips(data.eSimChips || []);
        setScripts(data.scripts || []);
        setChartWidgets(data.chartWidgets || []);
        if (data.globalIO) setGlobalIO(data.globalIO);
        if (data.notificationSettings) setNotificationSettings(data.notificationSettings);
        if (data.hasReadGuide !== undefined) setHasReadGuide(data.hasReadGuide);
        
        // v4 Load
        if (data.securitySettings) {
            setSecuritySettings(data.securitySettings);
            if (data.securitySettings.enabled) {
               setIsLocked(true);
               addLog("🔒 应用已进入安全锁定状态");
            }
        }
        if (data.syncSettings) setSyncSettings(data.syncSettings);
        if (data.currencySettings) setCurrencySettings(data.currencySettings);

      } catch (e) {
        console.error("Failed to load data", e);
      }
    }
    setHasCheckedLock(true);
    
    // Attempt to register a dummy service worker
    if ('serviceWorker' in navigator) {
        // Create a simple SW blob on the fly or register a file
        // For this demo, we assume vite-plugin-pwa or manual file exists, 
        // OR we inject the manifest link here if missing
        let link = document.querySelector("link[rel~='manifest']");
        if (!link) {
          link = document.createElement('link');
          link.rel = 'manifest';
          link.href = 'data:application/json;base64,' + btoa(JSON.stringify({
             name: "Global SIM Manager",
             short_name: "SIM Mgr",
             start_url: "/",
             display: "standalone",
             background_color: "#ffffff",
             theme_color: "#4f46e5",
             icons: [{ src: "https://cdn-icons-png.flaticon.com/512/545/545245.png", sizes: "192x192", type: "image/png" }]
          }));
          document.head.appendChild(link);
        }
     }
  }, []);

  // Save on Change & Sync
  useEffect(() => {
    if (!hasCheckedLock) return;
    
    // Save to LocalStorage (Plaintext locally for performance, assumes device security)
    const data: AppData = { 
        version: 3, 
        appTitle, theme, isDemoMode, hasReadGuide, 
        notificationSettings, securitySettings, syncSettings, currencySettings,
        subscriptions, eSimChips, scripts, chartWidgets, globalIO 
    };
    localStorage.setItem('sim-manager-data-v3', JSON.stringify(data));

    // WebDAV Sync
    const doSync = async () => {
        if (syncSettings.webdavUrl && syncSettings.username && syncSettings.password) {
            let payload = JSON.stringify(data);
            
            // E2EE Logic
            if (syncSettings.isEncrypted && syncSettings.encryptionPassword) {
                try {
                   payload = await cryptoHelper.encrypt(payload, syncSettings.encryptionPassword);
                } catch (e) {
                   console.error("Encryption failed:", e);
                   return;
                }
            }

            // App.tsx 内部的 useEffect
            webdavClient.put(syncSettings.webdavUrl, syncSettings.username, syncSettings.password, payload)
              .then(() => {
                console.log('Auto-sync success');
                addLog("✅ WebDAV 云端备份自动同步完成");
              })
              .catch(err => {
                console.error('Auto-sync failed', err);
                addLog(`❌ WebDAV 同步失败: ${err.message}`);
              });
  

    
    // Debounce sync slightly
    const timer = setTimeout(doSync, 2000);
    return () => clearTimeout(timer);
    
      }
    }
  }, [appTitle, theme, isDemoMode, hasReadGuide, notificationSettings, securitySettings, syncSettings, currencySettings, subscriptions, eSimChips, scripts, chartWidgets, globalIO, hasCheckedLock]);
  
  useEffect(() => {
    // 条件判断：
    // 1. 必须已经从本地加载过数据 (hasCheckedLock)
    // 2. 如果启用了安全锁，必须已经解锁 (isLocked === false)
    if (hasCheckedLock && !isLocked) {
      const params = new URLSearchParams(window.location.search);
      const importData = params.get('import');

      if (importData) {
        try {
          // 使用之前在 helpers.ts 定义的 shareUtils 进行解码
          const decodedData = shareUtils.decodeData(importData);
          
          if (!decodedData) throw new Error("无效的数据");

          const confirmMsg = `发现分享的套餐模板：\n` +
            `------------------------\n` +
            `名称：${decodedData.nickname}\n` +
            `运营商：${decodedData.operatorType}\n` +
            `费用：${decodedData.cost} ${decodedData.currency}\n` +
            `------------------------\n` +
            `注意：隐私数据（号码、PIN/PUK）未包含在内。\n\n` +
            `是否确认导入？`;

          if (window.confirm(confirmMsg)) {
            // 构建新的 Subscription 对象
            const newSub: Subscription = {
              ...decodedData,
              id: crypto.randomUUID(), // 分配新 ID
              phoneNumber: '',         // 强制清空号码隐私
              simPin: '',              // 强制清空 PIN
              simPuk: '',              // 强制清空 PUK
              startDate: new Date().toISOString().slice(0, 10), // 从今天开始
              tags: [...(decodedData.tags || []), '导入模板'],
              priority: 2,
              isArchived: false
            };
            
            // 更新状态
            setSubscriptions(prev => [...prev, newSub]);
            
            // 关键：清除 URL 里的参数，防止刷新页面时再次触发导入
            const newUrl = window.location.origin + window.location.pathname;
            window.history.replaceState({}, document.title, newUrl);
            
            alert('✅ 套餐模板已成功添加至列表！');
          } else {
             // 如果用户取消，也清理掉 URL 参数
             const newUrl = window.location.origin + window.location.pathname;
             window.history.replaceState({}, document.title, newUrl);
          }
        } catch (e) {
          console.error('导入失败:', e);
          alert('❌ 导入失败：分享链接已损坏或格式不正确。');
          // 清理错误的参数
          const newUrl = window.location.origin + window.location.pathname;
          window.history.replaceState({}, document.title, newUrl);
        }
      }
    }
  }, [hasCheckedLock, isLocked]); // 依赖项：当锁检查完成或解锁状态改变时触发

  useEffect(() => {
    document.body.className = '';
    if (theme !== 'default') document.body.classList.add(`theme-${theme}`);
  }, [theme]);

  const renderThemeElements = () => {
    if (theme === 'sakura') return Array.from({length: 12}).map((_,i) => <div key={i} className="sakura-petal" style={{ left: `${Math.random()*100}%`, animationDuration: `${5+Math.random()*5}s`, animationDelay: `-${Math.random()*5}s` }}></div>);
    if (theme === 'snow') return Array.from({length: 30}).map((_,i) => <div key={i} className="snowflake" style={{ left: `${Math.random()*100}%`, animationDuration: `${10+Math.random()*10}s`, animationDelay: `-${Math.random()*10}s`, fontSize: `${10+Math.random()*15}px` }}>❄</div>);
    return null;
  };

  const handleImport = (data: AppData, method: 'replace' | 'merge') => {
    if (method === 'replace') {
      if (data.appTitle) setAppTitle(data.appTitle);
      if (data.theme) setTheme(data.theme);
      setSubscriptions(data.subscriptions);
      setESimChips(data.eSimChips);
      setScripts(data.scripts);
      setChartWidgets(data.chartWidgets || []);
      setGlobalIO(data.globalIO || {input: '', output: ''});
      if (data.notificationSettings) setNotificationSettings(data.notificationSettings);
      if (data.isDemoMode !== undefined) setIsDemoMode(data.isDemoMode);
      if (data.securitySettings) setSecuritySettings(data.securitySettings);
      if (data.currencySettings) setCurrencySettings(data.currencySettings);
      setHasReadGuide(data.hasReadGuide ?? true);
    } else {
      const subIds = new Set(subscriptions.map(s => s.id));
      const chipIds = new Set(eSimChips.map(c => c.id));
      setSubscriptions(prev => [...prev, ...data.subscriptions.filter(s => !subIds.has(s.id))]);
      setESimChips(prev => [...prev, ...data.eSimChips.filter(c => !chipIds.has(c.id))]);
    }
  };

  const handleAddOrUpdateSubscription = (sub: Subscription) => {
    setSubscriptions(prev => {
      const exists = prev.findIndex(s => s.id === sub.id);
      if (exists >= 0) {
        const updated = [...prev];
        updated[exists] = sub;
        return updated;
      }
      return [...prev, sub];
    });
    setEditingSub(undefined);
  };

  const handleArchiveSubscription = (id: string) => {
     setArchiveTargetId(id);
  };
  
  const confirmArchive = () => {
    if (archiveTargetId) {
       setSubscriptions(prev => prev.map(s => s.id === archiveTargetId ? { ...s, isArchived: !s.isArchived } : s));
       setArchiveTargetId(null);
    }
  };
  
  const handlePortingUpdate = (id: string, updates: Partial<Subscription>) => {
     setSubscriptions(prev => prev.map(s => s.id === id ? { ...s, ...updates } : s));
     setPortingSub(undefined);
  };
  
  const handleQuickUpdate = (id: string, updates: Partial<Subscription>) => {
  setSubscriptions(prev => prev.map(s => s.id === id ? { ...s, ...updates } : s));
  addLog(`⚡ 已快速更新套餐 [${id.slice(0,4)}] 的活跃记录`);
};
  
  const confirmDelete = async () => {
    if (isBatchDelete) {
        setSubscriptions(prev => prev.filter(s => !selectedIds.has(s.id)));
        setSelectedIds(new Set());
    } else if (deleteTargetId) {
        setSubscriptions(prev => prev.filter(s => s.id !== deleteTargetId));
    }
    setDeleteTargetId(null);
    setIsBatchDelete(false);
  };

  const initiateDelete = (id: string) => {
    setDeleteTargetId(id);
    setIsBatchDelete(false);
  };

  const initiateBatchDelete = () => {
    if (selectedIds.size === 0) return;
    setIsBatchDelete(true);
    setDeleteTargetId(null); 
  };

  // Filter Logic
  const processedSubscriptions = useMemo(() => {
    let result = subscriptions;
    
    // 1. Archival & Status Logic (Merged)
    // 修改说明：如果筛选器选了“已归档”，则强制显示归档项；否则遵循 showArchived 开关状态
    if (filterStatus === 'archived') {
        result = result.filter(s => s.isArchived === true);
    } else {
        // 默认逻辑：根据 showArchived 开关决定显示 活跃 或 归档
        result = result.filter(s => s.isArchived === showArchived);

        // 仅在非归档模式下应用“即将到期”筛选 (当然归档的也可以算过期，但通常不关注)
        if (filterStatus === 'expiring') {
           result = result.filter(s => {
              const renewal = calculateNextRenewal(s.startDate, s.cycleDays, s.cycleType, s.lastActiveDate);
              const days = getDaysRemaining(renewal);
              return days <= (s.notificationThreshold || 7);
           });
        }
    }

    // 2. Search
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      result = result.filter(s => {
        const basicMatch = s.nickname.toLowerCase().includes(q) || 
          (s.phoneNumber && s.phoneNumber.includes(q)) ||
          (s.countryCode && s.countryCode.includes(q));
        const virtualMatch = s.virtualNumbers?.some(vn => vn.number.includes(q) || vn.note?.toLowerCase().includes(q));
        return basicMatch || virtualMatch;
      });
    }

    // 3. Status (Expiring)
    if (filterStatus === 'expiring') {
       result = result.filter(s => {
          const renewal = calculateNextRenewal(s.startDate, s.cycleDays, s.cycleType, s.lastActiveDate); 
          const days = getDaysRemaining(renewal);
          return days <= (s.notificationThreshold || 7);
       });
    }

    // 4. Type
    if (filterType !== 'all') {
       result = result.filter(s => {
          if (filterType === 'physical') return s.simType === 'physical';
          if (filterType === 'esim') return s.simType !== 'physical';
          return true;
       });
    }

    // 5. Priority
    if (filterPriority !== 'all') {
        if (filterPriority === 'high') result = result.filter(s => s.priority <= 3);
        else if (filterPriority === 'medium') result = result.filter(s => s.priority > 3 && s.priority <= 7);
        else if (filterPriority === 'low') result = result.filter(s => s.priority > 7);
    }

    // 6. Operator
    if (filterOperator !== 'all') {
        result = result.filter(s => s.operatorType === filterOperator);
    }

    // 7. Tag
    if (filterTag !== 'all') {
        result = result.filter(s => s.tags?.includes(filterTag));
    }

    // 8. Script
    if (filterExpression) {
        try {
            // Safe evaluation is hard in JS client side without sandboxing, but we trust user input for self-tool
            // Simple scope providing 'sub' and 'io'
            result = result.filter(sub => {
                const func = new Function('sub', 'io', filterExpression);
                return func(sub, globalIO);
            });
        } catch (e) {
            // Ignore error while typing
        }
    }

    // Sort
    result.sort((a, b) => {
      if (sortBy === 'expiry') {
      const dateA = calculateNextRenewal(a.startDate, a.cycleDays, a.cycleType, a.lastActiveDate).getTime();
      const dateB = calculateNextRenewal(b.startDate, b.cycleDays, b.cycleType, b.lastActiveDate).getTime();
      return dateA - dateB;
  }
      if (sortBy === 'cost') {
          const costA = convertCurrency(a.cost, a.currency, currencySettings.baseCurrency, currencySettings.rates);
          const costB = convertCurrency(b.cost, b.currency, currencySettings.baseCurrency, currencySettings.rates);
          return costB - costA;
      }
      if (sortBy === 'priority') return a.priority - b.priority;
      if (sortBy === 'nickname') return a.nickname.localeCompare(b.nickname);
      return 0;
    });
    return result;
  }, [subscriptions, searchQuery, filterStatus, filterPriority, filterType, filterOperator, filterTag, filterExpression, sortBy, showArchived, currencySettings, globalIO]);

  // Grouping Logic
  const groupedSubscriptions = useMemo((): Record<string, Subscription[]> => {
     if (groupBy === 'none') return { 'All': processedSubscriptions };
     
     const groups: Record<string, Subscription[]> = {};
     processedSubscriptions.forEach(sub => {
        let key = 'Other';
        if (groupBy === 'itu') {
           const zone = getITUZone(sub.countryCode);
           key = zone ? `${zone} - ${ITU_ZONES[zone]}` : 'Unknown Region';
        } else if (groupBy === 'simType') {
           key = sub.simType === 'physical' ? 'Physical SIM' : 'eSIM';
        }
        
        if (!groups[key]) groups[key] = [];
        groups[key].push(sub);
     });
     return groups;
  }, [processedSubscriptions, groupBy]);

  const allTags = useMemo(() => {
     const t = new Set<string>();
     subscriptions.forEach(s => s.tags?.forEach(tag => t.add(tag)));
     return Array.from(t);
  }, [subscriptions]);
  
  if (isLocked) {
  return (
    <LockScreen 
      correctPinHash={securitySettings.pinHash} 
      securitySettings={securitySettings} 
      onUnlock={() => setIsLocked(false)} 
      onLog={addLog} 
    />
  );
}

  return (
    <div className="min-h-screen pb-20 font-sans text-gray-900 relative transition-colors duration-500">
      {renderThemeElements()}
      
      {!hasReadGuide && <OnboardingGuide onComplete={() => setHasReadGuide(true)} />}

      <header className="bg-white/80 backdrop-blur border-b border-gray-200 sticky top-0 z-20 shadow-sm transition-colors duration-300">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className={`w-8 h-8 rounded-lg flex items-center justify-center text-white font-bold text-lg shadow-lg transition-colors duration-500 ${theme === 'matcha' ? 'bg-green-600' : theme === 'geek' ? 'bg-gray-800' : theme === 'sakura' ? 'bg-pink-500' : theme === 'snow' ? 'bg-sky-500' : 'bg-indigo-600'}`}>
              GP
            </div>
            <h1 className="text-xl font-bold tracking-tight text-gray-800 cursor-default hidden sm:block">
               {appTitle}
            </h1>
            {isDemoMode && (
               <span className="flex items-center gap-1 bg-gray-800 text-white text-[10px] px-2 py-0.5 rounded-full font-bold ml-1 animate-pulse">
                  <EyeOff className="w-3 h-3" /> DEMO
               </span>
            )}
          </div>
          
          <div className="flex items-center gap-2">
            <div className="bg-gray-100 p-1 rounded-lg flex gap-1 mr-2">
                <button onClick={() => setViewMode('cards')} className={`p-1.5 rounded-md transition-all ${viewMode === 'cards' ? 'bg-white shadow text-indigo-600' : 'text-gray-500 hover:text-gray-700'}`} title="Card View"><List className="w-4 h-4" /></button>
                <button onClick={() => setViewMode('stats')} className={`p-1.5 rounded-md transition-all ${viewMode === 'stats' ? 'bg-white shadow text-indigo-600' : 'text-gray-500 hover:text-gray-700'}`} title="Stats Dashboard"><BarChart3 className="w-4 h-4" /></button>
                <button onClick={() => setIsSettingsOpen(true)} className={`hidden p-1.5 rounded-md transition-all text-gray-500 hover:text-gray-700`} title="Calendar View (In Modal)"><CalendarIcon className="w-4 h-4" /></button>
            </div>

            <button onClick={() => setIsScriptOpen(true)} className="p-2 text-gray-600 hover:bg-gray-100 rounded-lg" title="Script & Charts"><Code className="w-5 h-5" /></button>
            <button onClick={() => setIsESimManagerOpen(true)} className="p-2 text-gray-600 hover:bg-gray-100 rounded-lg" title="eSIM Manager"><Cpu className="w-5 h-5" /></button>
            <button onClick={() => setIsCalculatorOpen(true)} className="p-2 text-gray-600 hover:bg-gray-100 rounded-lg" title="Calculator"><Calculator className="w-5 h-5" /></button>

            <DataControl currentData={{version: 3, appTitle, theme, hasReadGuide, notificationSettings, subscriptions, eSimChips, scripts, chartWidgets, globalIO, isDemoMode}} onImport={handleImport} />
            
            <div className="w-px h-6 bg-gray-300 mx-1"></div>
            
            <button 
              onClick={() => setIsSettingsOpen(true)} 
              className="p-2 text-gray-600 hover:bg-gray-100 rounded-lg hover:rotate-90 transition-all duration-300" 
              title="设置 / Settings"
            >
              <Settings className="w-5 h-5" />
            </button>
          </div>
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-8 relative z-10">
        <DashboardStats subscriptions={subscriptions} />
        
        {viewMode === 'stats' ? (
           <StatisticsPanel 
             subscriptions={subscriptions} 
             widgets={chartWidgets} 
             globalIO={globalIO}
             onUpdateIO={setGlobalIO}
             onRemoveWidget={(id) => setChartWidgets(prev => prev.filter(w => w.id !== id))}
           />
        ) : (
          <>
            <div className="bg-white p-4 rounded-xl border border-gray-200 shadow-sm mb-6 flex flex-col gap-4 sticky top-20 z-10 transition-colors">
               <div className="flex flex-col md:flex-row gap-4 items-center justify-between">
                 <div className="relative flex-1 w-full md:max-w-sm">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
                    <input type="text" placeholder="搜索套餐、号码..." value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)} className="w-full pl-9 pr-4 py-2 bg-gray-50 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-indigo-500 outline-none" />
                 </div>
                 <div className="flex items-center gap-3 w-full md:w-auto justify-end">
                    <button onClick={() => setViewMode('calendar')} className="p-2 rounded border text-gray-500 hover:bg-gray-50" title="Open Calendar"><CalendarIcon className="w-4 h-4"/></button>
                    <button onClick={() => setShowArchived(!showArchived)} className={`p-2 rounded border transition-colors ${showArchived ? 'bg-indigo-50 text-indigo-600 border-indigo-200' : 'text-gray-500 hover:bg-gray-50'}`} title={showArchived ? "Show Active Only" : "Show Archived Only"}>
                       <Archive className="w-4 h-4" />
                    </button>
                    {selectedIds.size > 0 && (
                       <div className="flex items-center gap-2 mr-2">
                         <span className="text-sm font-medium text-gray-600 bg-gray-100 px-2 py-1 rounded">{selectedIds.size} 选定</span>
                         <button onClick={() => setIsBatchEditOpen(true)} className="p-2 text-indigo-600 hover:bg-indigo-50 rounded border"><Edit className="w-4 h-4" /></button>
                         <button onClick={initiateBatchDelete} className="p-2 text-red-600 hover:bg-red-50 rounded border"><Trash2 className="w-4 h-4" /></button>
                       </div>
                    )}
                    <button onClick={() => { setEditingSub(undefined); setIsFormOpen(true); }} className="flex items-center gap-2 bg-indigo-600 hover:bg-indigo-700 text-white px-4 py-2 rounded-lg font-medium shadow-md whitespace-nowrap"><Plus className="w-5 h-5" /> 添加套餐</button>
                 </div>
               </div>
               
               {/* Basic Filter Row */}
               <div className="flex flex-wrap items-center gap-2 text-sm pt-2 border-t border-gray-100">
                   <div className="flex items-center gap-1 text-gray-400 mr-1"><Filter className="w-3 h-3"/></div>
                   
                   {/* Primary Filters */}
                   <select value={filterStatus} onChange={(e) => setFilterStatus(e.target.value as any)} className={`py-1 px-2 border rounded text-xs outline-none ${filterStatus !== 'all' ? 'bg-indigo-50 border-indigo-200 text-indigo-700' : 'bg-gray-50'}`}>
                      <option value="all">状态: 全部 (Active)</option>
                      <option value="expiring">状态: 即将到期</option>
                      <option value="archived">状态: 已归档 (Archived)</option>
                   </select>

                   <select value={filterType} onChange={(e) => setFilterType(e.target.value as any)} className={`py-1 px-2 border rounded text-xs outline-none ${filterType !== 'all' ? 'bg-indigo-50 border-indigo-200 text-indigo-700' : 'bg-gray-50'}`}>
                      <option value="all">类型: 全部</option>
                      <option value="esim">eSIM</option>
                      <option value="physical">实体卡</option>
                   </select>

                   <select value={filterPriority} onChange={(e) => setFilterPriority(e.target.value)} className={`py-1 px-2 border rounded text-xs outline-none ${filterPriority !== 'all' ? 'bg-indigo-50 border-indigo-200 text-indigo-700' : 'bg-gray-50'}`}>
                      <option value="all">优先级: 全部</option>
                      <option value="high">高 (1-3)</option>
                      <option value="medium">中 (4-7)</option>
                      <option value="low">低 (8-10)</option>
                   </select>

                   {/* Toggle Advanced */}
                   <button 
                     onClick={() => setShowAdvancedFilter(!showAdvancedFilter)} 
                     className={`text-xs flex items-center gap-1 px-2 py-1 rounded transition-colors ${showAdvancedFilter ? 'bg-gray-200 text-gray-700' : 'text-indigo-600 hover:bg-indigo-50'}`}
                   >
                      更多选项 {showAdvancedFilter ? '▲' : '▼'}
                   </button>

                   <div className="flex-1"></div>

                   <select value={groupBy} onChange={(e) => setGroupBy(e.target.value as any)} className="py-1 px-2 bg-white border border-gray-200 text-gray-600 rounded text-xs outline-none">
                      <option value="none">分组: 无</option>
                      <option value="itu">按区域 (ITU)</option>
                      <option value="simType">按类型</option>
                   </select>
                   <select value={sortBy} onChange={(e) => setSortBy(e.target.value as any)} className="py-1 px-2 bg-white border border-gray-200 text-gray-600 rounded text-xs outline-none"><option value="expiry">排序: 到期</option><option value="priority">优先级</option><option value="cost">费用</option><option value="nickname">名称</option></select>
               </div>
               
               {/* Advanced Filter Row (Expandable) */}
               {showAdvancedFilter && (
                 <div className="grid grid-cols-1 md:grid-cols-3 gap-3 pt-2 animate-fade-in border-t border-dashed border-gray-200 mt-1">
                    <div className="flex flex-col gap-1">
                       <label className="text-[10px] text-gray-500 font-bold uppercase">运营商类型</label>
                       <select value={filterOperator} onChange={(e) => setFilterOperator(e.target.value)} className="w-full py-1.5 px-2 bg-gray-50 border rounded text-xs outline-none">
                          <option value="all">全部运营商</option>
                          {OPERATOR_TYPES.map(op => <option key={op.value} value={op.value}>{op.label}</option>)}
                       </select>
                    </div>
                    <div className="flex flex-col gap-1">
                       <label className="text-[10px] text-gray-500 font-bold uppercase flex items-center gap-1"><Tag className="w-3 h-3"/> 标签筛选</label>
                       <select value={filterTag} onChange={(e) => setFilterTag(e.target.value)} className="w-full py-1.5 px-2 bg-gray-50 border rounded text-xs outline-none">
                          <option value="all">全部标签</option>
                          {allTags.map(t => <option key={t} value={t}>{t}</option>)}
                       </select>
                    </div>
                    <div className="flex flex-col gap-1">
                       <label className="text-[10px] text-gray-500 font-bold uppercase flex items-center gap-1"><Terminal className="w-3 h-3"/> 脚本过滤 (Expert)</label>
                       <div className="flex gap-1">
                          <input 
                             type="text" 
                             value={filterExpression} 
                             onChange={(e) => setFilterExpression(e.target.value)} 
                             className="flex-1 bg-gray-50 border rounded text-xs px-2 py-1.5 outline-none font-mono placeholder-gray-400" 
                             placeholder="sub.cost > 100" 
                          />
                          {filterExpression && <button onClick={() => setFilterExpression('')} className="text-gray-400 hover:text-red-500"><XCircle className="w-4 h-4" /></button>}
                       </div>
                    </div>
                 </div>
               )}
            </div>

            {processedSubscriptions.length === 0 ? (
               <div className="text-center py-20 bg-white/80 backdrop-blur rounded-xl border border-dashed border-gray-300">
                  <div className="mb-4 text-gray-300 mx-auto w-12 h-12 flex items-center justify-center bg-gray-50 rounded-full">
                     <Filter className="w-6 h-6" />
                  </div>
                  <h3 className="text-lg font-medium text-gray-900">暂无匹配数据</h3>
                  <p className="text-sm text-gray-500 mt-1">请尝试调整筛选条件或添加新套餐。</p>
                  {showArchived && <p className="text-xs text-indigo-500 mt-2 cursor-pointer" onClick={() => setShowArchived(false)}>返回活跃列表</p>}
               </div>
            ) : (
               <div className="space-y-8">
                  {Object.entries(groupedSubscriptions).map(([groupTitle, subs]: [string, Subscription[]]) => (
                     <div key={groupTitle}>
                        {groupBy !== 'none' && (
                           <h3 className="text-sm font-bold text-gray-500 uppercase tracking-wider mb-3 flex items-center gap-2">
                              <Grid className="w-4 h-4" /> {groupTitle} <span className="text-xs bg-gray-100 px-2 py-0.5 rounded-full">{subs.length}</span>
                           </h3>
                        )}
                        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                            {subs.map(sub => (
                                <SubscriptionCard
                                key={sub.id}
                                subscription={sub}
                                linkedChip={eSimChips.find(c => c.id === sub.eSim?.chipId)}
                                isSelected={selectedIds.has(sub.id)}
                                isDemoMode={isDemoMode}
                                onSelect={(id) => setSelectedIds(prev => { const n = new Set(prev); if(n.has(id)) n.delete(id); else n.add(id); return n; })}
                                onDelete={initiateDelete}
                                onEdit={(s) => { setEditingSub(s); setIsFormOpen(true); }}
                                onArchive={handleArchiveSubscription}
                                onPorting={(s) => setPortingSub(s)}
                                onQuickUpdate={handleQuickUpdate}
                                />
                            ))}
                        </div>
                     </div>
                  ))}
               </div>
            )}
          </>
        )}
      </main>

      {/* Modals */}
      {viewMode === 'calendar' && <CalendarView subscriptions={subscriptions} onClose={() => setViewMode('cards')} />}

      {isSettingsOpen && (
        <SettingsModal 
          logs={logs}           
          onLog={addLog}        
          onClearLogs={() => setLogs([])} 
          currentTitle={appTitle} 
          currentTheme={theme as ThemeType}
          notificationSettings={notificationSettings}
          securitySettings={securitySettings}
          syncSettings={syncSettings}
          currencySettings={currencySettings}
          isDemoMode={isDemoMode}
          onSave={(newTitle, newTheme, newNotifs, newDemoMode, newSecurity, newSync, newCurrency) => {
            setAppTitle(newTitle);
            setTheme(newTheme);
            setNotificationSettings(newNotifs);
            setIsDemoMode(newDemoMode);
            setSecuritySettings(newSecurity);
            setSyncSettings(newSync);
            setCurrencySettings(newCurrency);
          }}
          onExportICS={() => generateBatchICS(subscriptions)}
          onExportCSV={() => generateCSV(subscriptions)} 
          onClose={() => setIsSettingsOpen(false)}
        />
      )}

      {(deleteTargetId || isBatchDelete) && (
         <ConfirmationModal 
           title="确认删除"
           message={isBatchDelete ? `确定要删除选中的 ${selectedIds.size} 个套餐吗？此操作无法撤销。` : "确定要删除此套餐吗？删除后数据将无法恢复。如果您只是想暂时隐藏，建议使用“归档”功能。"}
           confirmText="永久删除"
           isDanger
           onConfirm={confirmDelete}
           onCancel={() => { setDeleteTargetId(null); setIsBatchDelete(false); }}
         />
      )}

      {archiveTargetId && (() => {
          const sub = subscriptions.find(s => s.id === archiveTargetId);
          if (!sub) return null;
          const isArchiving = !sub.isArchived;
          return (
             <ConfirmationModal 
               title={isArchiving ? "确认归档" : "确认恢复"}
               message={isArchiving 
                  ? `确定要归档套餐 "${sub.nickname}" 吗？\n归档后将不再显示在活跃列表中，且不会触发续费提醒。` 
                  : `确定要恢复套餐 "${sub.nickname}" 吗？\n恢复后将显示在活跃列表中。`}
               confirmText={isArchiving ? "归档" : "恢复"}
               onConfirm={confirmArchive}
               onCancel={() => setArchiveTargetId(null)}
             />
          );
      })()}

      {isFormOpen && (
        <SubscriptionForm
          initialData={editingSub}
          availableChips={eSimChips.filter(c => !c.isArchived)}
          onSave={handleAddOrUpdateSubscription}
          onClose={() => setIsFormOpen(false)}
        />
      )}
      
      {portingSub && (
        <PortingModal
           subscription={portingSub}
           onConfirm={handlePortingUpdate}
           onClose={() => setPortingSub(undefined)}
        />
      )}
      
      {isESimManagerOpen && (
        <ESimManager 
           chips={eSimChips} 
           onUpdate={setESimChips} 
           onClose={() => setIsESimManagerOpen(false)} 
        />
      )}

      {isScriptOpen && (
        <ScriptPlayground 
          appData={{version: 3, appTitle, theme, hasReadGuide, notificationSettings, subscriptions, eSimChips, scripts, chartWidgets, globalIO}}
          scripts={scripts}
          globalIO={globalIO}
          onUpdateIO={setGlobalIO}
          onSaveScripts={setScripts}
          onAddWidget={(w) => setChartWidgets(prev => [...prev, w])}
          onClose={() => setIsScriptOpen(false)}
        />
      )}

      {isBatchEditOpen && <BatchEditModal selectedCount={selectedIds.size} onSave={(u) => { setSubscriptions(prev => prev.map(s => selectedIds.has(s.id) ? {...s, ...u} : s)); setIsBatchEditOpen(false); setSelectedIds(new Set()); }} onClose={() => setIsBatchEditOpen(false)} />}
      {isCalculatorOpen && <CostCalculator subscriptions={subscriptions} onClose={() => setIsCalculatorOpen(false)} />}
    </div>
  );
};

export default App;

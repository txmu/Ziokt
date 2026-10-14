import React, { useState, useEffect } from 'react';
import { 
  X, Check, Monitor, Flower, Snowflake, Terminal, Leaf, Palette, 
  Bell, Calendar, Zap, AlertTriangle, Download, Send, Globe, 
  Lock, Eye, EyeOff, Shield, ShieldCheck, RefreshCw, Key, 
  Database, Coins, FileSpreadsheet, CloudLightning, Fingerprint, SmartphoneNfc, Terminal
} from 'lucide-react';
import { ThemeType, NotificationSettings, SecuritySettings, SyncSettings, CurrencySettings } from '../types';
import { ALL_CURRENCIES } from '../constants';
import { webdavClient, securityHelper, fetchExchangeRates, webAuthnHelper } from '../utils/helpers';

interface SettingsModalProps {
  currentTitle: string;
  currentTheme: ThemeType;
  notificationSettings: NotificationSettings;
  securitySettings?: SecuritySettings;
  syncSettings?: SyncSettings;
  currencySettings?: CurrencySettings;
  isDemoMode: boolean;
  onSave: (
      title: string, 
      theme: ThemeType, 
      notifications: NotificationSettings, 
      isDemoMode: boolean,
      security: SecuritySettings,
      sync: SyncSettings,
      currency: CurrencySettings
  ) => void;
  onExportICS: () => void;
  onExportCSV: () => void;
  onClose: () => void;
  logs: {time: string, msg: string}[]; 
  onLog: (msg: string) => void;        
  onClearLogs: () => void;             
}

const SettingsModal: React.FC<SettingsModalProps> = ({ 
    currentTitle, currentTheme, notificationSettings, isDemoMode, securitySettings, syncSettings, currencySettings, logs,
    onLog, onSave, onExportICS, onExportCSV, onClearLogs, onClose 
}) => {
  const [activeTab, setActiveTab] = useState<'general' | 'sync' | 'security' | 'currency' | 'logs'>('general');

  // --- 1. General Settings State ---
  const [title, setTitle] = useState(currentTitle);
  const [theme, setTheme] = useState<ThemeType>(currentTheme);
  const [notifications, setNotifications] = useState<NotificationSettings>(notificationSettings);
  const [demoMode, setDemoMode] = useState(isDemoMode);
  
  // Notification Permissions
  const [permissionStatus, setPermissionStatus] = useState<NotificationPermission>('default');
  const [supportsTriggers, setSupportsTriggers] = useState(false);

  useEffect(() => {
    if ('Notification' in window) {
      setPermissionStatus(Notification.permission);
      setSupportsTriggers('showTrigger' in Notification.prototype);
    }
  }, []);

  const requestPermission = async () => {
    if (!('Notification' in window)) {
      alert('您的浏览器不支持桌面通知。');
      return;
    }
    if (Notification.permission === 'denied') {
        alert('🚫 通知权限已被浏览器阻止。请在浏览器设置中手动开启。');
        return;
    }
    try {
      const result = await Notification.requestPermission();
      setPermissionStatus(result);
      if (result === 'granted') {
        new Notification('全球通套餐管家', { body: '🎉 通知权限已获取成功！' });
      }
    } catch (e) {
      console.error("Permission request error:", e);
    }
  };

  // --- 2. Security Settings State ---
  // 初始化：不再读取旧的 pin 字段，而是读取 pinHash。默认 enabled 为 false。
  const [security, setSecurity] = useState<SecuritySettings>(securitySettings || { enabled: false });
  const [pinInput, setPinInput] = useState(''); // UI 输入暂存
  const [isPinSet, setIsPinSet] = useState(!!securitySettings?.pinHash); // 标记是否已设置过 Hash 密码

  const handleSetPin = async () => {
     if (pinInput.length < 4) {
        alert("为了安全起见，PIN 码至少需要4位数字或字符。");
        return;
     }
     try {
       // 计算 SHA-256 Hash
       const hash = await securityHelper.hashPin(pinInput);
       
       // 更新状态
       setSecurity(prev => ({ ...prev, enabled: true, pinHash: hash }));
       setIsPinSet(true);
       setPinInput(''); // 清空输入框防止偷窥
       alert("安全 PIN 码已设置 (已加密存储)");
     } catch (e) {
       alert("加密失败，请检查浏览器兼容性。");
       console.error(e);
     }
  };
  
  const [isBiometricAvailable, setIsBiometricAvailable] = useState(false);

useEffect(() => {
    webAuthnHelper.isSupported().then(setIsBiometricAvailable);
}, []);

const handleSetupBiometric = async () => {
    try {
        const credId = await webAuthnHelper.register(title || "User");
        setSecurity({ ...security, biometricEnabled: true, webauthnId: credId, enabled: true });
        alert("🎉 生物识别/安全密钥已绑定成功！");
    } catch (e) {
        alert("绑定失败，可能是您取消了操作或设备不支持。");
    }
};

  // --- 3. Sync Settings State ---
  const [sync, setSync] = useState<SyncSettings>(syncSettings || {});
  const [syncStatus, setSyncStatus] = useState<string>('');

  const handleTestWebDAV = async () => {
      setSyncStatus('正在连接服务器...');
      try {
          if (!sync.webdavUrl || !sync.username || !sync.password) {
              throw new Error("请先填写完整的 WebDAV URL、用户名和密码");
          }
          // 测试连接（读取根目录或尝试读取文件）
          await webdavClient.get(sync.webdavUrl, sync.username, sync.password);
          setSyncStatus('✅ 连接成功！凭证有效。');
      } catch (e: any) {
          // 如果是 404，说明连接成功但文件不存在，也算凭证有效
          if (e.message && e.message.includes('404')) {
             setSyncStatus('✅ 连接成功 (文件尚未创建)');
          } else {
             setSyncStatus('❌ 连接失败: ' + e.message);
          }
      }
  };

  // --- 4. Currency Settings State ---
  const [currencyConfig, setCurrencyConfig] = useState<CurrencySettings>(currencySettings || { baseCurrency: 'CNY', rates: {} });
  // API Key 独立管理
  const [apiKey, setApiKey] = useState(currencySettings?.apiKey || '');
  const [isUpdatingRates, setIsUpdatingRates] = useState(false);

  const handleUpdateRates = async () => {
    if (!apiKey) return alert("请先输入 ExchangeRate-API Key");
    setIsUpdatingRates(true);
    
    try {
      const newRates = await fetchExchangeRates(apiKey, currencyConfig.baseCurrency);
      
      if (newRates) {
         setCurrencyConfig(prev => ({ 
            ...prev, 
            rates: newRates, 
            apiKey: apiKey, 
            lastUpdated: new Date().toISOString() 
         }));
         alert("✅ 汇率已更新至最新市场价");
         onLog(`💱 汇率已更新，基准货币: ${currencyConfig.baseCurrency}`);
      } else {
         alert("❌ 更新失败，请检查 API Key 是否正确或额度是否耗尽。");
      }
    } catch (e) {
      alert("网络错误，更新失败");
    } finally {
      setIsUpdatingRates(false);
    }
  };

  // --- Themes Data ---
  const themes: { id: ThemeType; name: string; color: string; icon: React.ElementType; desc: string }[] = [
    { id: 'default', name: '默认白', color: 'bg-indigo-600', icon: Monitor, desc: 'Clean & Professional' },
    { id: 'sakura', name: '樱花粉', color: 'bg-pink-500', icon: Flower, desc: 'Soft & Elegant' },
    { id: 'snow', name: '落雪蓝', color: 'bg-sky-500', icon: Snowflake, desc: 'Cool & Fresh' },
    { id: 'matcha', name: '抹茶绿', color: 'bg-green-600', icon: Leaf, desc: 'Natural & Calm' },
    { id: 'geek', name: '极客黑', color: 'bg-gray-800', icon: Terminal, desc: 'Dark & Coding' },
  ];

  // --- Final Save Handler ---
  const handleSave = () => {
    // 组装并保存
    onSave(title, theme, notifications, demoMode, security, sync, currencyConfig);
    onClose();
  };

  return (
    <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50 p-4 animate-fade-in">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg overflow-hidden border border-gray-100 flex flex-col max-h-[90vh]">
        
        {/* Header */}
        <div className="flex justify-between items-center p-5 border-b border-gray-100 bg-gray-50/50">
          <h2 className="text-xl font-bold text-gray-800 flex items-center gap-2">
            <Palette className="w-5 h-5 text-indigo-600" />
            设置
          </h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 transition-colors">
            <X className="w-6 h-6" />
          </button>
        </div>

        {/* Tabs */}
        <div className="flex border-b border-gray-200">
           {['general', 'security', 'sync', 'currency', 'logs'].map(tab => (
               <button 
                 key={tab}
                 onClick={() => setActiveTab(tab as any)} 
                 className={`flex-1 py-3 text-sm font-medium capitalize transition-colors ${
                    activeTab === tab 
                    ? 'text-indigo-600 border-b-2 border-indigo-600 bg-indigo-50/30' 
                    : 'text-gray-500 hover:text-gray-700 hover:bg-gray-50'
                 }`}
               >
               {tab === 'general' ? '通用' : 
 tab === 'security' ? '安全' : 
 tab === 'sync' ? '同步' : 
 tab === 'currency' ? '汇率' : 
 tab === 'logs' ? '日志' : 
 ''}
               </button>
           ))}
        </div>

        {/* Content Area */}
        <div className="p-6 space-y-6 overflow-y-auto bg-white flex-1">
        
        {/* ================= LOG TAB ================= */}
        {activeTab === 'logs' && (
  <div className="space-y-4 animate-fade-in flex flex-col h-full">
    {/* 日志头部工具栏 */}
    <div className="flex justify-between items-center px-1">
      <div className="flex items-center gap-2">
        <Terminal className="w-4 h-4 text-indigo-600" />
        <h3 className="text-sm font-bold text-gray-700 uppercase tracking-wider">系统运行日志</h3>
      </div>
      <button
        onClick={onClearLogs}
        className="text-[10px] bg-red-50 text-red-600 px-2 py-1 rounded border border-red-100 hover:bg-red-100 transition-all active:scale-95"
      >
        清空日志
      </button>
    </div>

    {/* 终端模拟窗口 */}
    <div className="flex-1 bg-gray-950 rounded-xl border border-gray-800 shadow-2xl overflow-hidden flex flex-col min-h-[380px]">
      {/* 终端内容区 */}
      <div className="flex-1 p-3 font-mono text-[11px] leading-relaxed overflow-y-auto custom-scrollbar selection:bg-green-900 selection:text-white">
        {logs.length === 0 ? (
          <div className="text-gray-600 italic text-center py-24">
            <Terminal className="w-12 h-12 mx-auto mb-3 opacity-10" />
            <p>等待系统事件触发...</p>
            <p className="text-[9px] mt-1 not-italic">所有 WebDAV 同步、安全验证、汇率更新的操作记录将显示在此</p>
          </div>
        ) : (
          <div className="flex flex-col">
            {logs.map((log, i) => (
              <div key={i} className="mb-1.5 pb-1.5 border-b border-gray-900/50 last:border-0 flex gap-2 group">
                <span className="text-gray-500 shrink-0 select-none opacity-50">[{log.time}]</span>
                <span className={`break-all ${
                  log.msg.includes('❌') ? 'text-red-400' : 
                  log.msg.includes('✅') ? 'text-emerald-400' : 
                  log.msg.includes('🔒') ? 'text-amber-400' : 
                  'text-green-400'
                }`}>
                  {log.msg}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* 终端底部状态栏 */}
      <div className="bg-gray-900 px-3 py-1.5 border-t border-gray-800 flex justify-between items-center text-[9px] text-gray-500 font-bold uppercase tracking-widest">
        <div className="flex items-center gap-2">
           <div className="w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse"></div>
           <span>System Status: Active</span>
        </div>
        <span>Total Events: {logs.length}</span>
      </div>
    </div>

    <p className="text-[10px] text-gray-400 text-center italic">
      提示：此日志仅在当前浏览器会话中有效，刷新页面后将重置。
    </p>
  </div>
)}
          
          {/* ================= GENERAL TAB ================= */}
          {activeTab === 'general' && (
            <div className="space-y-6">
              {/* App Title */}
              <div>
                <label className="block text-sm font-bold text-gray-700 mb-2">应用程序名称</label>
                <input
                    type="text"
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                    className="w-full px-4 py-2 border border-gray-200 rounded-xl focus:ring-2 focus:ring-indigo-500 outline-none transition-all"
                    placeholder="全球通套餐管家"
                />
              </div>

              {/* Theme Selection */}
              <div>
                <label className="block text-sm font-bold text-gray-700 mb-3">主题风格</label>
                <div className="grid grid-cols-2 gap-3">
                  {themes.map((t) => (
                    <button
                      key={t.id}
                      onClick={() => setTheme(t.id)}
                      className={`flex items-center gap-3 p-3 rounded-xl border-2 transition-all text-left ${
                        theme === t.id
                          ? 'border-indigo-500 bg-indigo-50 ring-1 ring-indigo-500'
                          : 'border-gray-100 hover:bg-gray-50 hover:border-gray-300'
                      }`}
                    >
                      <div className={`w-8 h-8 rounded-lg flex items-center justify-center text-white shadow-sm ${t.color}`}>
                        <t.icon className="w-4 h-4" />
                      </div>
                      <div>
                         <div className="text-sm font-bold text-gray-800">{t.name}</div>
                         <div className="text-[10px] text-gray-400">{t.desc}</div>
                      </div>
                    </button>
                  ))}
                </div>
              </div>

               {/* Notification & Data */}
                <div>
                   <label className="block text-sm font-bold text-gray-700 mb-3 flex items-center gap-2">
                      <Bell className="w-4 h-4 text-indigo-600" />
                      通知与数据
                   </label>
                   <div className="bg-gray-50 rounded-xl border border-gray-200 p-4 space-y-4">
                      
                      {/* Permission Widget */}
                      <div className="flex justify-between items-center bg-white p-3 rounded-lg border border-gray-100 shadow-sm">
                         <span className="text-sm font-medium text-gray-700">浏览器通知权限</span>
                         {permissionStatus !== 'granted' ? (
                            <button onClick={requestPermission} className="text-xs bg-indigo-600 text-white px-3 py-1.5 rounded hover:bg-indigo-700 transition-colors">开启权限</button>
                         ) : (
                            <span className="text-xs text-green-600 font-bold bg-green-50 border border-green-100 px-2 py-1 rounded flex items-center gap-1">
                               <Check className="w-3 h-3"/> 已授权
                            </span>
                         )}
                      </div>

                      <label className="flex items-center justify-between cursor-pointer">
                         <span className="text-sm text-gray-700">启用过期提醒</span>
                         <input type="checkbox" checked={notifications.enabled} onChange={(e) => setNotifications({...notifications, enabled: e.target.checked})} className="rounded text-indigo-600 focus:ring-indigo-500" />
                      </label>
                      
                       <label className="flex items-center justify-between cursor-pointer">
                         <div className="flex flex-col">
                             <span className="text-sm text-gray-700">使用高级触发器 Notification Trigger (实验特性)</span>
                             <span className="text-[10px] text-gray-400">Supported: {supportsTriggers ? 'Yes' : 'No'}</span>
                         </div>
                         <input type="checkbox" disabled={!supportsTriggers} checked={notifications.useTriggers} onChange={(e) => setNotifications({...notifications, useTriggers: e.target.checked})} className="rounded text-indigo-600 focus:ring-indigo-500" />
                      </label>
                      
                      {/* 新增：Webhook 配置 */}
      <div className="pt-3 border-t border-gray-200 space-y-3">
         <label className="flex items-center justify-between cursor-pointer">
            <span className="text-sm font-medium text-gray-700">启用推送 (Webhook)（需先填写URL才能启用）</span>
            <input 
               type="checkbox" 
               checked={!!notifications.webhookUrl && (notifications as any).webhookEnabled} 
               onChange={(e) => setNotifications({
                  ...notifications, 
                  // 启用必须填URL，但填了不代表一定启用
                  [( 'webhookEnabled' as any)]: e.target.checked 
               })} 
               className="rounded text-indigo-600 focus:ring-indigo-500" 
            />
         </label>
         
         <div className="relative">
            <Send className="absolute left-3 top-2.5 w-4 h-4 text-gray-400" />
            <input 
               type="url" 
               value={notifications.webhookUrl || ''} 
               onChange={(e) => setNotifications({...notifications, webhookUrl: e.target.value})}
               placeholder="https://oapi.dingtalk.com/robot/send?..."
               className="w-full pl-10 pr-3 py-2 border border-gray-300 rounded-lg text-xs outline-none focus:ring-1 focus:ring-indigo-500"
            />
         </div>
         <p className="text-[10px] text-gray-400 leading-tight">
            到期提醒将通过 POST JSON 发送至此地址。支持 Telegram Bot, Bark, 钉钉等。
         </p>
      </div>
                      
                      {/* Export Buttons */}
                      <div className="pt-3 border-t border-gray-200 grid grid-cols-2 gap-3">
                         <button 
                           onClick={onExportICS}
                           className="flex items-center justify-center gap-2 bg-white border border-gray-300 hover:bg-gray-50 text-gray-700 py-2 rounded-lg text-xs font-medium transition-colors"
                         >
                            <Calendar className="w-3.5 h-3.5" /> 导出日历 (.ics)
                         </button>
                         <button 
                           onClick={onExportCSV}
                           className="flex items-center justify-center gap-2 bg-white border border-gray-300 hover:bg-gray-50 text-gray-700 py-2 rounded-lg text-xs font-medium transition-colors"
                         >
                            <FileSpreadsheet className="w-3.5 h-3.5" /> 导出 Excel (.csv)
                         </button>
                      </div>
                   </div>
                </div>

                {/* Demo Mode */}
                <div className="flex items-center justify-between p-3 bg-gray-50 rounded-xl border border-gray-200">
                    <div className="flex items-center gap-2">
                        {demoMode ? <EyeOff className="w-4 h-4 text-gray-500" /> : <Eye className="w-4 h-4 text-gray-500" />}
                        <span className="text-sm font-bold text-gray-700">隐私演示模式 (Demo Mode)</span>
                    </div>
                    <label className="relative inline-flex items-center cursor-pointer">
                      <input type="checkbox" checked={demoMode} onChange={(e) => setDemoMode(e.target.checked)} className="sr-only peer" />
                      <div className="w-9 h-5 bg-gray-200 peer-focus:outline-none peer-focus:ring-4 peer-focus:ring-indigo-300 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-indigo-600"></div>
                    </label>
                </div>
            </div>
          )}
          
{/* ================= SECURITY TAB ================= */}
          {activeTab === 'security' && (
            <div className="space-y-6">
              {/* 1. 安全提示卡片 */}
              <div className="bg-amber-50 p-4 rounded-xl border border-amber-100 text-amber-900 text-sm flex gap-3">
                <Shield className="w-5 h-5 flex-shrink-0 mt-0.5" /> 
                <div>
                  <div className="font-bold mb-1">应用锁 (App Lock)</div>
                  <p className="opacity-90">
                    启用后，每次打开或刷新页面时，必须输入 PIN 码才能查看数据。
                    密码使用 <span className="font-mono bg-amber-100 px-1 rounded">SHA-256</span> 算法加密存储，无法被明文读取。
                  </p>
                </div>
              </div>
              
              {/* 2. PIN 码设置区域 */}
              <div className="space-y-4">
                <label className={`flex items-center justify-between p-4 border rounded-xl transition-all cursor-pointer ${security.enabled ? 'bg-white border-indigo-200 shadow-sm' : 'bg-gray-50 border-gray-200'}`}>
                  <span className="font-bold text-gray-700">启用 PIN 码保护</span>
                  <input 
                    type="checkbox" 
                    checked={security.enabled} 
                    onChange={(e) => {
                      if (!isPinSet && e.target.checked) {
                        alert("请先在下方设置 PIN 码");
                        return;
                      }
                      setSecurity({...security, enabled: e.target.checked});
                    }} 
                    className="w-5 h-5 rounded text-indigo-600 focus:ring-indigo-500"
                  />
                </label>
                
                <div className="p-5 border border-gray-200 rounded-xl bg-white shadow-sm">
                  <label className="block text-sm font-bold text-gray-700 mb-3 flex items-center gap-2">
                    <Key className="w-4 h-4 text-gray-400" />
                    {isPinSet ? "更改 PIN 码" : "设置新 PIN 码"}
                  </label>
                  <div className="flex gap-2">
                    <input 
                      type="password" 
                      value={pinInput} 
                      onChange={(e) => setPinInput(e.target.value)} 
                      className="flex-1 px-4 py-2 border border-gray-300 rounded-lg font-mono text-center tracking-[0.5em] text-lg focus:ring-2 focus:ring-indigo-500 outline-none transition-all"
                      placeholder="••••"
                      maxLength={20}
                    />
                    <button 
                      onClick={handleSetPin} 
                      className="bg-indigo-600 hover:bg-indigo-700 text-white px-5 py-2 rounded-lg text-sm font-medium transition-colors shadow-sm"
                    >
                      {isPinSet ? "更新" : "设置"}
                    </button>
                  </div>
                  
                  <div className="mt-3 flex items-center justify-between">
                    {isPinSet ? (
                      <p className="text-xs text-green-600 flex items-center gap-1.5 bg-green-50 px-2 py-1 rounded-full border border-green-100">
                        <ShieldCheck className="w-3 h-3"/> 密码已加密保护 (Hashed)
                      </p>
                    ) : (
                      <p className="text-xs text-gray-400">当前未设置密码</p>
                    )}
                    {isPinSet && (
                      <button 
                        onClick={() => {
                          if(window.confirm("确定要移除 PIN 码保护吗？")) {
                            setSecurity({ enabled: false, pinHash: undefined });
                            setIsPinSet(false);
                            setPinInput('');
                          }
                        }}
                        className="text-xs text-red-500 hover:underline"
                      >
                        清除密码
                      </button>
                    )}
                  </div>
                </div>
              </div>

              {/* 3. 生物识别设置区域 */}
              <div className="p-5 border border-gray-200 rounded-xl bg-white shadow-sm">
                <label className="block text-sm font-bold text-gray-700 mb-3 flex items-center gap-2">
                  <Fingerprint className="w-4 h-4 text-indigo-500" />
                  生物识别与 FIDO2
                </label>
                
                {!isBiometricAvailable ? (
                  <p className="text-xs text-gray-400 bg-gray-50 p-3 rounded-lg">您的设备或浏览器暂不支持 WebAuthn 生物识别。</p>
                ) : (
                  <div className="space-y-3">
                    <button 
                      onClick={handleSetupBiometric}
                      className={`w-full py-3 px-4 rounded-xl border-2 flex items-center justify-between transition-all ${
                        security.biometricEnabled ? 'border-green-500 bg-green-50 text-green-700' : 'border-dashed border-gray-300 hover:border-indigo-500 text-gray-600'
                      }`}
                    >
                      <div className="flex items-center gap-3">
                        <SmartphoneNfc className="w-5 h-5" />
                        <div className="text-left">
                          <div className="text-sm font-bold">{security.biometricEnabled ? "已绑定生物识别" : "绑定指纹/人脸/密钥"}</div>
                          <div className="text-[10px] opacity-70">支持 FaceID, 指纹, Yubikey</div>
                        </div>
                      </div>
                      {security.biometricEnabled && <Check className="w-4 h-4" />}
                    </button>
                    
                    {security.biometricEnabled && (
                      <button 
                        onClick={() => setSecurity({ ...security, biometricEnabled: false, webauthnId: undefined })}
                        className="text-xs text-red-500 w-full text-center hover:underline"
                      >
                        解除绑定
                      </button>
                    )}
                  </div>
                )}
              </div>
            </div>
          )}

          {/* ================= SYNC TAB ================= */}
          {activeTab === 'sync' && (
              <div className="space-y-6">
                 <div className="bg-blue-50 p-4 rounded-xl border border-blue-100 text-blue-900 text-sm flex gap-3">
                    <CloudLightning className="w-5 h-5 flex-shrink-0 mt-0.5" />
                    <div>
                       <div className="font-bold mb-1">WebDAV 云同步</div>
                       <p className="opacity-90 text-xs">
                          支持坚果云、Nextcloud、Alist 等标准 WebDAV 服务。
                          数据将以 JSON 格式备份到您的私有网盘中。
                       </p>
                    </div>
                 </div>

                 <div className="space-y-4">
                    <div>
                       <label className="block text-xs font-bold text-gray-700 mb-1.5 uppercase">WebDAV URL (完整路径)</label>
                       <input 
                          type="url" 
                          value={sync.webdavUrl || ''} 
                          onChange={(e) => setSync({...sync, webdavUrl: e.target.value})}
                          placeholder="https://dav.jianguoyun.com/dav/sim_manager_backup.json"
                          className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 outline-none transition-all"
                       />
                       <p className="text-[10px] text-gray-400 mt-1">注意：URL 必须包含文件名 (例如 backup.json)</p>
                    </div>
                    <div className="grid grid-cols-2 gap-4">
                       <div>
                          <label className="block text-xs font-bold text-gray-700 mb-1.5 uppercase">用户名</label>
                          <input 
                             type="text" 
                             value={sync.username || ''} 
                             onChange={(e) => setSync({...sync, username: e.target.value})} 
                             className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 outline-none transition-all" 
                          />
                       </div>
                       <div>
                          <label className="block text-xs font-bold text-gray-700 mb-1.5 uppercase">密码 / 应用 Token</label>
                          <input 
                             type="password" 
                             value={sync.password || ''} 
                             onChange={(e) => setSync({...sync, password: e.target.value})} 
                             className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 outline-none transition-all" 
                          />
                       </div>
                    </div>

                    <button 
                       onClick={handleTestWebDAV} 
                       className="w-full py-2.5 bg-white border border-gray-300 rounded-lg text-sm text-gray-700 font-medium hover:bg-gray-50 hover:border-gray-400 transition-all shadow-sm active:scale-95"
                    >
                       测试连接 (Test Connection)
                    </button>
                    {syncStatus && (
                       <div className={`text-xs text-center p-2 rounded ${syncStatus.includes('成功') ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-700'}`}>
                          {syncStatus}
                       </div>
                    )}

                    {/* Encryption Section */}
                    <div className="mt-6 pt-5 border-t border-gray-200">
                       <label className="flex items-center gap-2 text-sm font-bold text-gray-800 cursor-pointer mb-3 select-none">
                          <input 
                             type="checkbox" 
                             checked={sync.isEncrypted} 
                             onChange={(e) => setSync({...sync, isEncrypted: e.target.checked})} 
                             className="w-4 h-4 rounded text-indigo-600 focus:ring-indigo-500" 
                          />
                          <Lock className="w-4 h-4 text-gray-500" /> 启用端对端加密 (E2EE)
                       </label>
                       
                       <div className={`overflow-hidden transition-all duration-300 ${sync.isEncrypted ? 'max-h-40 opacity-100' : 'max-h-0 opacity-0'}`}>
                          <div className="bg-gray-50 p-4 rounded-xl border border-gray-200">
                             <label className="block text-xs font-bold text-gray-700 mb-1.5">主加密密码 (Master Password)</label>
                             <input 
                                type="password" 
                                value={sync.encryptionPassword || ''} 
                                onChange={(e) => setSync({...sync, encryptionPassword: e.target.value})}
                                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:border-indigo-500 outline-none"
                                placeholder="如果不设置此密码，将无法解密您的云端备份！"
                             />
                             <p className="text-[10px] text-red-500 mt-2 flex items-start gap-1.5 leading-tight">
                                <AlertTriangle className="w-3 h-3 flex-shrink-0 mt-0.5"/> 
                                警告：密码用于本地 AES-GCM 加密。若丢失密码，您的云端备份将永久无法恢复。服务器无法帮您找回密码。
                             </p>
                          </div>
                       </div>
                    </div>
                 </div>
              </div>
          )}
          
          {/* ================= CURRENCY TAB ================= */}
          {activeTab === 'currency' && (
             <div className="space-y-6">
                <div className="bg-emerald-50 p-4 rounded-xl border border-emerald-100 text-emerald-900 text-sm flex gap-3">
                   <Coins className="w-5 h-5 flex-shrink-0 mt-0.5" />
                   <div>
                      <div className="font-bold mb-1">多币种汇率管理</div>
                      <p className="opacity-90">
                         设定基准货币后，系统会自动将所有外币开销折算为基准货币进行统计。
                         支持 API 自动更新与手动微调混合模式。
                      </p>
                   </div>
                </div>

                {/* Base Currency */}
                <div>
                   <label className="block text-sm font-bold text-gray-700 mb-2">基准货币 (Base Currency)</label>
                   <select 
                      value={currencyConfig.baseCurrency} 
                      onChange={(e) => setCurrencyConfig({...currencyConfig, baseCurrency: e.target.value})}
                      className="w-full px-3 py-2.5 border border-gray-200 rounded-xl bg-white focus:ring-2 focus:ring-emerald-500 outline-none transition-all cursor-pointer"
                   >
                       {ALL_CURRENCIES.map(c => <option key={c.code} value={c.code}>{c.code} - {c.label}</option>)}
                   </select>
                </div>
                
                {/* API Section */}
                <div className="border border-gray-200 rounded-xl p-4 bg-white shadow-sm">
                    <label className="block text-xs font-bold text-gray-500 uppercase tracking-wider mb-2">自动更新 (API Integration)</label>
                    <div className="flex gap-2">
                       <input 
                          type="text" 
                          value={apiKey} 
                          onChange={(e) => setApiKey(e.target.value)} 
                          className="flex-1 px-3 py-2 border border-gray-300 rounded-lg text-sm font-mono focus:border-emerald-500 outline-none" 
                          placeholder="ExchangeRate-API Key (e.g. 5f3d...)" 
                       />
                       <button 
                          onClick={handleUpdateRates} 
                          disabled={isUpdatingRates} 
                          className="bg-emerald-600 hover:bg-emerald-700 text-white px-4 py-2 rounded-lg text-sm flex items-center gap-2 whitespace-nowrap disabled:opacity-50 transition-colors shadow-sm"
                       >
                          {isUpdatingRates ? <RefreshCw className="w-4 h-4 animate-spin"/> : <RefreshCw className="w-4 h-4"/>} 
                          更新
                       </button>
                    </div>
                    <div className="flex justify-between items-center mt-2.5">
                        <a href="https://www.exchangerate-api.com/" target="_blank" rel="noreferrer" className="text-[10px] text-indigo-500 hover:underline flex items-center gap-1">
                           <Globe className="w-3 h-3"/> 获取免费 API Key
                        </a>
                        {currencyConfig.lastUpdated && (
                           <span className="text-[10px] text-gray-400 bg-gray-50 px-2 py-0.5 rounded border border-gray-100">
                              上次更新: {new Date(currencyConfig.lastUpdated).toLocaleString()}
                           </span>
                        )}
                    </div>
                </div>

                {/* Manual Rates List */}
                <div className="flex flex-col h-64">
                   <label className="block text-sm font-bold text-gray-700 mb-2">
                       实时汇率表 (相对于 1 {currencyConfig.baseCurrency})
                   </label>
                   <div className="flex-1 overflow-y-auto border border-gray-200 rounded-xl p-2 bg-gray-50 custom-scrollbar shadow-inner">
                       {ALL_CURRENCIES.filter(c => c.code !== currencyConfig.baseCurrency).map(c => (
                          <div key={c.code} className="flex items-center justify-between text-sm p-2.5 hover:bg-white rounded-lg transition-colors group border border-transparent hover:border-gray-100 hover:shadow-sm mb-1">
                             <div className="flex items-center gap-3">
                                <span className="font-mono font-bold w-10 text-gray-800">{c.code}</span>
                                <span className="text-gray-400 text-xs hidden sm:inline truncate max-w-[100px]">{c.label.split('-')[1]}</span>
                             </div>
                             <div className="flex items-center gap-2">
                                <span className="text-xs text-gray-400 group-hover:text-gray-600 transition-colors">1 {c.code} =</span>
                                <input 
                                   type="number" 
                                   step="0.0001"
                                   placeholder="1.0"
                                   // 如果有 API 数据则显示，否则显示空或手动值
                                   value={currencyConfig.rates[c.code] !== undefined ? currencyConfig.rates[c.code] : ''}
                                   onChange={(e) => setCurrencyConfig({
                                       ...currencyConfig, 
                                       rates: { ...currencyConfig.rates, [c.code]: parseFloat(e.target.value) }
                                   })}
                                   className="w-24 px-2 py-1 border border-gray-200 rounded text-right focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500 outline-none text-gray-700 font-mono"
                                />
                                <span className="text-xs text-gray-400 w-8">{currencyConfig.baseCurrency}</span>
                             </div>
                          </div>
                       ))}
                   </div>
                   <p className="text-[10px] text-gray-400 mt-2 text-center">
                      提示：您可以手动修改任意货币的汇率，手动修改的值在下次点击“更新”前将一直保留。
                   </p>
                </div>
             </div>
          )}

        </div>

        {/* Footer */}
        <div className="p-5 border-t border-gray-100 bg-gray-50/50 flex justify-end gap-3 backdrop-blur-sm">
          <button
            onClick={onClose}
            className="px-5 py-2.5 text-gray-600 font-medium hover:bg-gray-100 rounded-xl transition-colors text-sm"
          >
            取消
          </button>
          <button
            onClick={handleSave}
            className="px-6 py-2.5 bg-indigo-600 text-white font-bold rounded-xl hover:bg-indigo-700 shadow-lg shadow-indigo-200 transition-all transform active:scale-95 text-sm flex items-center gap-2"
          >
            <Check className="w-4 h-4" /> 保存设置
          </button>
        </div>
      </div>
    </div>
  );
};

export default SettingsModal;
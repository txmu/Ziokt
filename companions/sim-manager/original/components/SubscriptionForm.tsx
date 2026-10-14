
import React, { useState, useEffect } from 'react';
import { X, Plus, Trash2, Globe, Shield, CreditCard, Signal, Smartphone, Cpu, IdCard, Hash, MapPin, Wifi, Archive, ArrowRightLeft, Landmark, UserCheck, StickyNote, Gauge, Info, Wallet, RotateCw, Receipt, Link as LinkIcon, ScanText } from 'lucide-react';
import { Subscription, Scenario, KycType, PaymentMethod, DataUsage, ESimInfo, ScenarioMode, ESimChip, OperatorType, NumberType, VirtualNumber, RoamingPrerequisite, DebitCreditCard, BankAccountDetails, SpeedUnit, Transaction } from '../types';
import { getFlagFromPhoneNumber } from '../utils/helpers';
import { KYC_OPTIONS, PAYMENT_METHODS, OPERATOR_TYPES, NUMBER_TYPES, AMBIGUOUS_REGIONS, ESIM_TRANSFER_METHODS, ALL_CURRENCIES } from '../constants';

interface SubscriptionFormProps {
  initialData?: Subscription;
  availableChips: ESimChip[];
  onSave: (sub: Subscription) => void;
  onClose: () => void;
}

const DEFAULT_MODE_SETTINGS: ScenarioMode = {
  isAvailable: false,
  isActive: false,
  features: { smsIn: false, smsOut: false, callIn: false, callOut: false, voicemail: false, data: false },
  remark: '',
  networkTypes: [],
  operators: [],
  isHotspotSupported: false,
  roamLikeHome: false,
  roamingPrerequisite: 'none',
  vowifiE911Required: false
};

const PHYSICAL_CARD_PRESETS = [
  "Giffgaff (UK)",
  "中国电信 (澳门蓝卡)",
  "游惠宝 (Youhuibao)",
  "CUniq (HK/Macau)",
  "Skinny (NZ)",
  "Ultra Mobile PayGo (USA)",
  "Lycamobile",
  "AIS Sim2Fly",
  "TrueMove H",
  "3HK DIY"
];

const SPEED_UNITS: SpeedUnit[] = ['kbps', 'Mbps', 'Gbps', 'kB/s', 'MB/s', 'GB/s'];

const SubscriptionForm: React.FC<SubscriptionFormProps> = ({ initialData, availableChips, onSave, onClose }) => {
  const [activeTab, setActiveTab] = useState<'basic' | 'details' | 'scenarios' | 'notes' | 'transactions'>('basic');
  const [smartParseOpen, setSmartParseOpen] = useState(false);
  const [smartParseText, setSmartParseText] = useState('');

  // Basic State
  const [nickname, setNickname] = useState(initialData?.nickname || '');
  const [operatorType, setOperatorType] = useState<OperatorType>(initialData?.operatorType || 'MNO');
  
  const [phoneNumber, setPhoneNumber] = useState(initialData?.phoneNumber || '');
  const [numberType, setNumberType] = useState<NumberType>(initialData?.numberType || 'Mobile');
  const [countryCode, setCountryCode] = useState(initialData?.countryCode || '');
  const [adminDivision, setAdminDivision] = useState(initialData?.adminDivision || '');
  const [regionFlagOverride, setRegionFlagOverride] = useState(''); 

  const [tags, setTags] = useState<string[]>(initialData?.tags || []);
  const [tagInput, setTagInput] = useState('');
  
  const [startDate, setStartDate] = useState(initialData?.startDate || new Date().toISOString().slice(0, 10));
  const [cycleDays, setCycleDays] = useState(initialData?.cycleDays || 30);
  const [gracePeriod, setGracePeriod] = useState(initialData?.gracePeriod || 0); 
  const [cost, setCost] = useState(initialData?.cost?.toString() || '');
  const [currency, setCurrency] = useState(initialData?.currency || 'CNY');
  
  // Balance System
  const [balance, setBalance] = useState(initialData?.balance?.toString() || '');
  const [balanceCurrency, setBalanceCurrency] = useState(initialData?.balanceCurrency || initialData?.currency || 'CNY');
  const [simPin, setSimPin] = useState(initialData?.simPin || '');
const [simPuk, setSimPuk] = useState(initialData?.simPuk || '');

  const [notificationThreshold, setNotificationThreshold] = useState(initialData?.notificationThreshold || 3);
  const [priority, setPriority] = useState(initialData?.priority || 2);

  // Virtual Numbers
  const [virtualNumbers, setVirtualNumbers] = useState<VirtualNumber[]>(initialData?.virtualNumbers || []);

  // Advanced State
  const [kycType, setKycType] = useState<KycType>(initialData?.kycType || 'none');
  const [paymentMethods, setPaymentMethods] = useState<PaymentMethod[]>(initialData?.paymentMethods || []);
  const [paymentMethodNote, setPaymentMethodNote] = useState(initialData?.paymentMethodNote || ''); 
  const [website, setWebsite] = useState(initialData?.website || '');
  const [topUpUrl, setTopUpUrl] = useState(initialData?.topUpUrl || '');
  const [keepAliveNote, setKeepAliveNote] = useState(initialData?.keepAliveNote || '');
  
  // Transactions
  const [transactions, setTransactions] = useState<Transaction[]>(initialData?.transactions || []);

  // Independent Payment Sources State
  // Card
  const [hasCard, setHasCard] = useState(!!initialData?.debitCreditCard || (!!initialData?.bankCard && initialData.bankCard.type !== 'Local_Bank'));
  const [cardType, setCardType] = useState(initialData?.debitCreditCard?.type || (initialData?.bankCard?.type !== 'Local_Bank' ? initialData?.bankCard?.type : 'Visa') || 'Visa');
  const [cardBankName, setCardBankName] = useState(initialData?.debitCreditCard?.bankName || (initialData?.bankCard?.type !== 'Local_Bank' ? initialData?.bankCard?.bankName : '') || '');
  const [cardNumber, setCardNumber] = useState(initialData?.debitCreditCard?.cardNumber || (initialData?.bankCard?.type !== 'Local_Bank' ? initialData?.bankCard?.cardNumber : '') || '');
  const [cardIsVirtual, setCardIsVirtual] = useState(initialData?.debitCreditCard?.isVirtual || (initialData?.bankCard?.type !== 'Local_Bank' ? initialData?.bankCard?.isVirtual : false) || false);
  const [cardRemarks, setCardRemarks] = useState(initialData?.debitCreditCard?.remarks || (initialData?.bankCard?.type !== 'Local_Bank' ? initialData?.bankCard?.remarks : '') || '');

  // Bank Account
  const [hasAccount, setHasAccount] = useState(!!initialData?.bankAccount || (!!initialData?.bankCard && initialData.bankCard.type === 'Local_Bank'));
  const [accBankName, setAccBankName] = useState(initialData?.bankAccount?.bankName || (initialData?.bankCard?.type === 'Local_Bank' ? initialData?.bankCard?.bankName : '') || '');
  const [accNumber, setAccNumber] = useState(initialData?.bankAccount?.accountNumber || (initialData?.bankCard?.type === 'Local_Bank' ? initialData?.bankCard?.cardNumber : '') || '');
  const [accRegion, setAccRegion] = useState(initialData?.bankAccount?.regionCode || initialData?.bankCard?.regionCode || '');
  const [accIban, setAccIban] = useState(initialData?.bankAccount?.iban || initialData?.bankCard?.iban || '');
  const [accIdentity, setAccIdentity] = useState<'citizen' | 'non_citizen'>(initialData?.bankAccount?.identityType || initialData?.bankCard?.identityType || 'citizen');
  const [accRemarks, setAccRemarks] = useState(initialData?.bankAccount?.remarks || (initialData?.bankCard?.type === 'Local_Bank' ? initialData?.bankCard?.remarks : '') || '');

  // Data State with Unit and Speed Limits
  const [dataPlans, setDataPlans] = useState<DataUsage[]>(
    initialData?.dataPlans?.map(dp => ({...dp, unit: dp.unit || 'GB'})) || 
    (initialData?.dataUsage ? [{...initialData.dataUsage, id: crypto.randomUUID(), unit: initialData.dataUsage.unit || 'GB'}] : [])
  );
  // UI state for expanding data plan details
  const [expandedDataPlanId, setExpandedDataPlanId] = useState<string | null>(null);
  
  // SIM Type State
  const [simType, setSimType] = useState<'esim' | 'physical'>(initialData?.simType || 'esim');
  const [physicalCardName, setPhysicalCardName] = useState(initialData?.physicalCardName || 'Giffgaff (UK)');
  const [isArchived, setIsArchived] = useState(initialData?.isArchived || false);
  const [cycleType, setCycleType] = useState<CycleType>(initialData?.cycleType || 'daily');
  const [lastActiveDate, setLastActiveDate] = useState(initialData?.lastActiveDate || '');

  // eSIM State
  const [selectedChipId, setSelectedChipId] = useState(initialData?.eSim?.chipId || '');
  const [manualEid, setManualEid] = useState(initialData?.eSim?.eid || '');
  const [eiccid, setEiccid] = useState(initialData?.eSim?.eiccid || '');
  const [profileSize, setProfileSize] = useState(initialData?.eSim?.profileSize || '');
  const [recommendedChip, setRecommendedChip] = useState<ESimChip | null>(null);

  // eSIM Transfer Config
  const [isEsimTransferSupported, setIsEsimTransferSupported] = useState(initialData?.isEsimTransferSupported || false);
  const [esimTransferMethod, setEsimTransferMethod] = useState(initialData?.esimTransferMethod || 'Online Self-Service');
  const [customTransferMethod, setCustomTransferMethod] = useState(initialData?.esimTransferMethod && !ESIM_TRANSFER_METHODS.some(m => m.value === initialData.esimTransferMethod) ? initialData.esimTransferMethod : '');
  const [transferRescanLimit, setTransferRescanLimit] = useState<number | null>(initialData?.transferRescanLimit ?? null);

  // Scenarios State
  const [scenarios, setScenarios] = useState<Scenario[]>(
    initialData?.scenarios?.map(s => ({
      ...s,
      local: s.local || JSON.parse(JSON.stringify(DEFAULT_MODE_SETTINGS)),
      roaming: s.roaming || { ...DEFAULT_MODE_SETTINGS, isAvailable: s.features?.includes('roaming') || false },
      vowifi: s.vowifi || { ...DEFAULT_MODE_SETTINGS, isAvailable: s.features?.includes('vowifi') || false }
    })) || []
  );

  const ambiguousOptions = AMBIGUOUS_REGIONS[countryCode] || null;

  useEffect(() => {
    if (selectedChipId) {
      const chip = availableChips.find(c => c.id === selectedChipId);
      if (chip) {
        setManualEid(chip.eid);
        setRecommendedChip(null);
      }
    }
  }, [selectedChipId, availableChips]);

  useEffect(() => {
    if (!selectedChipId && manualEid.length >= 8) {
      const match = availableChips.find(c => c.eid.startsWith(manualEid));
      if (match) setRecommendedChip(match);
      else setRecommendedChip(null);
    } else {
      setRecommendedChip(null);
    }
  }, [manualEid, selectedChipId, availableChips]);

  const displayedFlag = regionFlagOverride || getFlagFromPhoneNumber(phoneNumber, countryCode);

  // Smart Parse Logic
  const performSmartParse = () => {
     // Simple regex heuristics
     const text = smartParseText;
     
     // 1. Phone Number (Simple E.164-ish)
     const phoneMatch = text.match(/\+(?:[0-9] ?){6,14}[0-9]/);
     if (phoneMatch) setPhoneNumber(phoneMatch[0].replace(/ /g,''));

     // 2. ICCID/EID
     const iccidMatch = text.match(/89[0-9]{18,20}/);
     if (iccidMatch) setEiccid(iccidMatch[0]);

     const eidMatch = text.match(/89[0-9]{30}/);
     if (eidMatch) setManualEid(eidMatch[0]);

     // 3. Balance/Cost (Look for currency symbols or keywords)
     // Very naive, just for demo
     if (text.includes('$') || text.includes('¥')) {
        const moneyMatch = text.match(/([$¥€£])\s?([0-9]+(\.[0-9]{2})?)/);
        if (moneyMatch) {
            setBalance(moneyMatch[2]);
            if(moneyMatch[1] === '$') setBalanceCurrency('USD');
            if(moneyMatch[1] === '¥') setBalanceCurrency('CNY'); // Ambiguous with JPY but ok for default
            if(moneyMatch[1] === '€') setBalanceCurrency('EUR');
            if(moneyMatch[1] === '£') setBalanceCurrency('GBP');
        }
     }

     setSmartParseText('');
     setSmartParseOpen(false);
  };

  // Tags logic
  const handleAddTag = () => {
    if (tagInput.trim() && !tags.includes(tagInput.trim())) {
      setTags([...tags, tagInput.trim()]);
      setTagInput('');
    }
  };
  const removeTag = (t: string) => setTags(tags.filter(tag => tag !== t));

  // Scenario Logic
  const handleAddScenario = () => {
    setScenarios([...scenarios, { 
      id: crypto.randomUUID(), 
      regionCode: '', 
      note: '',
      local: JSON.parse(JSON.stringify(DEFAULT_MODE_SETTINGS)),
      roaming: JSON.parse(JSON.stringify(DEFAULT_MODE_SETTINGS)),
      vowifi: JSON.parse(JSON.stringify(DEFAULT_MODE_SETTINGS))
    }]);
  };

  const updateScenarioField = (index: number, field: keyof Scenario, value: any) => {
    const updated = [...scenarios];
    updated[index] = { ...updated[index], [field]: value };
    setScenarios(updated);
  };
  const updateScenarioMode = (index: number, mode: 'local' | 'roaming' | 'vowifi', updates: Partial<ScenarioMode>) => {
    const updated = [...scenarios];
    const currentMode = updated[index][mode] || JSON.parse(JSON.stringify(DEFAULT_MODE_SETTINGS));
    updated[index] = { ...updated[index], [mode]: { ...currentMode, ...updates } };
    setScenarios(updated);
  };
  const updateScenarioFeature = (index: number, mode: 'local' | 'roaming' | 'vowifi', feature: string, val: boolean) => {
    const updated = [...scenarios];
    const currentMode = updated[index][mode]!;
    updated[index] = { ...updated[index], [mode]: { ...currentMode, features: { ...currentMode.features, [feature]: val } } };
    setScenarios(updated);
  };
  const handleRemoveScenario = (index: number) => {
    setScenarios(scenarios.filter((_, i) => i !== index));
  };

  const togglePaymentMethod = (method: PaymentMethod) => {
    setPaymentMethods(prev => 
      prev.includes(method) ? prev.filter(p => p !== method) : [...prev, method]
    );
  };

  // Transaction Logic
  const handleAddTransaction = () => {
     setTransactions([...transactions, {
        id: crypto.randomUUID(),
        date: new Date().toISOString().slice(0, 10),
        amount: 0,
        currency: currency,
        type: 'topup'
     }]);
  };
  const updateTransaction = (id: string, updates: Partial<Transaction>) => {
     setTransactions(prev => prev.map(t => t.id === id ? { ...t, ...updates } : t));
  };
  const removeTransaction = (id: string) => {
     setTransactions(prev => prev.filter(t => t.id !== id));
  };

  // Data Plan Logic
  const handleAddDataPlan = () => {
    setDataPlans([...dataPlans, { 
      id: crypto.randomUUID(), 
      total: 0, 
      used: 0, 
      unit: 'GB', 
      regionNote: '', 
      expiryDate: '',
      isPayg: false,
      paygCostPerUnit: 0,
      highSpeedQuota: 0,
      throttledSpeed: 128,
      throttledSpeedUnit: 'kbps',
      isThrottledUnlimited: false,
      overallSpeedLimit: 0,
      overallSpeedLimitUnit: 'Mbps'
    }]);
  };
  const updateDataPlan = (index: number, field: keyof DataUsage, value: any) => {
    const updated = [...dataPlans];
    updated[index] = { ...updated[index], [field]: value };
    setDataPlans(updated);
  };
  const removeDataPlan = (index: number) => setDataPlans(dataPlans.filter((_, i) => i !== index));

  const handleAddVirtualNumber = () => setVirtualNumbers([...virtualNumbers, { id: crypto.randomUUID(), number: '', type: 'VoIP', note: '' }]);
  const updateVirtualNumber = (index: number, field: keyof VirtualNumber, value: any) => {
    const updated = [...virtualNumbers];
    updated[index] = { ...updated[index], [field]: value };
    setVirtualNumbers(updated);
  };
  const removeVirtualNumber = (index: number) => setVirtualNumbers(virtualNumbers.filter((_, i) => i !== index));

  // SIM Transfer Logic
  const handleSimTransfer = () => {
    const today = new Date().toLocaleDateString();
    if (simType === 'physical') {
      if (!window.confirm(`确定将此【实体卡】套餐转为 eSIM 吗？\n\n- 原实体卡信息 "${physicalCardName}" 将被记录在备注中。\n- 套餐将保持活跃状态。`)) return;
      const historyNote = `[${today}] 🔀 实体卡转 eSIM: 原卡名 "${physicalCardName || '未命名'}"`;
      setKeepAliveNote(prev => prev ? `${prev}\n${historyNote}` : historyNote);
      setSimType('esim');
      setPhysicalCardName(''); 
      setIsArchived(false); 
    } else {
      const currentChip = availableChips.find(c => c.id === selectedChipId);
      const chipInfo = currentChip ? `${currentChip.nickname}` : (manualEid || '未知芯片');
      if (!window.confirm(`确定将此【eSIM】套餐转为实体卡吗？\n\n- 原 eSIM 关联 "${chipInfo}" 将被解除。\n- 套餐将保持活跃状态。`)) return;
      const historyNote = `[${today}] 🔀 eSIM 转实体卡: 原芯片 "${chipInfo}"`;
      setKeepAliveNote(prev => prev ? `${prev}\n${historyNote}` : historyNote);
      setSimType('physical');
      setSelectedChipId('');
      setManualEid('');
      setProfileSize('');
      setEiccid('');
      setIsArchived(false); 
    }
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    
    // Auto-log eSIM Chip Change
    let finalNote = keepAliveNote;
    if (simType === 'esim' && initialData && initialData.simType === 'esim') {
        const oldChipId = initialData.eSim?.chipId;
        if (oldChipId !== selectedChipId) {
            const oldChipName = availableChips.find(c => c.id === oldChipId)?.nickname || (oldChipId ? '未知ID' : '无');
            const newChipName = availableChips.find(c => c.id === selectedChipId)?.nickname || (selectedChipId ? '未知ID' : '无');
            if (oldChipName !== newChipName) {
                const today = new Date().toLocaleDateString();
                const log = `[${today}] 🔄 eSIM 芯片变更: ${oldChipName} -> ${newChipName}`;
                finalNote = finalNote ? `${finalNote}\n${log}` : log;
            }
        }
    }

    let eSim: ESimInfo | undefined = undefined;
    if (simType === 'esim' && (selectedChipId || manualEid || profileSize || eiccid)) {
      eSim = { chipId: selectedChipId, eid: manualEid, profileSize, eiccid };
    }

    let debitCreditCard: DebitCreditCard | undefined = undefined;
    if (hasCard) {
      debitCreditCard = {
        id: initialData?.debitCreditCard?.id || crypto.randomUUID(),
        type: cardType as any,
        bankName: cardBankName,
        cardNumber: cardNumber,
        isVirtual: cardIsVirtual,
        remarks: cardRemarks
      };
    }

    let bankAccount: BankAccountDetails | undefined = undefined;
    if (hasAccount) {
      bankAccount = {
        id: initialData?.bankAccount?.id || crypto.randomUUID(),
        bankName: accBankName,
        accountNumber: accNumber,
        regionCode: accRegion,
        iban: accIban,
        identityType: accIdentity,
        remarks: accRemarks
      };
    }

    const processedDataPlans = dataPlans.map(dp => ({
       ...dp,
       totalGB: dp.unit === 'GB' ? dp.total : dp.total / 1024,
       usedGB: dp.unit === 'GB' ? dp.used : dp.used / 1024
    }));
    
    // Handle eSIM Transfer Method
    let finalTransferMethod = undefined;
    if (isEsimTransferSupported) {
        finalTransferMethod = esimTransferMethod === 'Other' || !ESIM_TRANSFER_METHODS.some(m => m.value === esimTransferMethod) ? customTransferMethod : esimTransferMethod;
    }

    const newSub: Subscription = {
      id: initialData?.id || crypto.randomUUID(),
      nickname, operatorType, phoneNumber, numberType, countryCode, adminDivision, virtualNumbers, tags,
      cycleType,
      simType, physicalCardName: simType === 'physical' ? physicalCardName : undefined,
      startDate, cycleDays: Number(cycleDays), cost: Number(cost), currency, 
      lastActiveDate: cycleType === 'activity_based' ? (lastActiveDate || startDate) : undefined,
      balance: balance ? Number(balance) : undefined,
      balanceCurrency: balance ? balanceCurrency : undefined,
      notificationThreshold: Number(notificationThreshold), priority: Number(priority), gracePeriod: Number(gracePeriod),
      kycType, paymentMethods, 
      debitCreditCard, bankAccount, 
      bankCard: undefined, // Clear legacy field
      paymentMethodNote, website, topUpUrl,
      keepAliveNote: finalNote, 
      scenarios, 
      dataPlans: processedDataPlans, eSim, 
      isEsimTransferSupported, 
      esimTransferMethod: finalTransferMethod,
      transferRescanLimit: finalTransferMethod === 'Delete & Rescan' ? transferRescanLimit : null,
      isArchived: isArchived,
      transactions: transactions,
      simPin,
      simPuk,
    };
    onSave(newSub);
    onClose();
  };

  // Helper render method for scenario modes (reused)
  const renderScenarioModeConfig = (index: number, mode: 'local' | 'roaming' | 'vowifi', label: string, colorClass: string) => {
    const scenario = scenarios[index];
    const data = scenario[mode] || DEFAULT_MODE_SETTINGS;
    return (
      <div className={`p-3 rounded border transition-all ${data.isAvailable ? colorClass : 'bg-gray-50 border-gray-200'}`}>
         <div className="flex items-center justify-between mb-2">
            <label className="flex items-center gap-2 font-medium text-sm text-gray-700 cursor-pointer">
               <input type="checkbox" checked={data.isAvailable} onChange={(e) => updateScenarioMode(index, mode, { isAvailable: e.target.checked })} />
               {label}
            </label>
            {data.isAvailable && (
               <label className="text-xs flex items-center gap-1 font-bold">
                 <input type="checkbox" checked={data.isActive} onChange={(e) => updateScenarioMode(index, mode, { isActive: e.target.checked })} /> 当前状态: 激活
               </label>
            )}
         </div>
         {data.isAvailable && (
            <div className="space-y-3 animate-fade-in pt-2 border-t border-black/5">
               <div className="flex flex-wrap gap-3 text-xs">
                  {['smsIn', 'smsOut', 'callIn', 'callOut', 'voicemail', ...(mode !== 'vowifi' ? ['data'] : [])].map(k => (
                     <label key={k} className="flex items-center gap-1 text-gray-700 cursor-pointer select-none">
                        <input type="checkbox" checked={(data.features as any)[k]} onChange={(e) => updateScenarioFeature(index, mode, k, e.target.checked)} />
                        {k === 'smsIn' ? '收信' : k === 'smsOut' ? '发信' : k === 'callIn' ? '接听' : k === 'callOut' ? '拨打' : k === 'voicemail' ? '留言' : '数据'}
                     </label>
                  ))}
               </div>
               <div className="mt-2 pt-2 border-t border-dashed border-gray-200">
                  <input
                    type="text"
                    className="w-full px-2 py-1.5 text-xs border rounded bg-yellow-50/50 focus:bg-white transition-colors"
                    placeholder={`${label.split(' ')[0]} 备注: 入网条件, APN设置, 特殊资费等...`}
                    value={data.remark || ''}
                    onChange={(e) => updateScenarioMode(index, mode, { remark: e.target.value })}
                  />
               </div>
            </div>
         )}
      </div>
    );
  };

  return (
    <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-3xl overflow-hidden flex flex-col max-h-[90vh]">
        <div className="flex justify-between items-center p-4 border-b border-gray-100 bg-gray-50">
          <h2 className="text-lg font-bold text-gray-800">
            {initialData ? '编辑套餐' : '添加新套餐'}
          </h2>
          <div className="flex items-center gap-2">
            <button 
                type="button" 
                onClick={() => setSmartParseOpen(!smartParseOpen)}
                className="text-xs flex items-center gap-1 text-indigo-600 bg-indigo-50 px-2 py-1 rounded border border-indigo-200 hover:bg-indigo-100"
            >
                <ScanText className="w-3.5 h-3.5" /> 智能识别
            </button>
            <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
                <X className="w-6 h-6" />
            </button>
          </div>
        </div>
        
        {/* Smart Parse Panel */}
        {smartParseOpen && (
            <div className="bg-indigo-50/50 p-3 border-b border-indigo-100 animate-fade-in">
                <div className="text-xs text-indigo-800 font-bold mb-1">粘贴运营商后台/邮件内容:</div>
                <textarea 
                   className="w-full text-xs p-2 border border-indigo-200 rounded h-16 outline-none resize-none"
                   placeholder="支持识别：手机号, ICCID, EID, 余额等..."
                   value={smartParseText}
                   onChange={(e) => setSmartParseText(e.target.value)}
                />
                <div className="flex justify-end mt-1">
                   <button type="button" onClick={performSmartParse} className="text-xs bg-indigo-600 text-white px-3 py-1 rounded hover:bg-indigo-700">分析并填充</button>
                </div>
            </div>
        )}

        <div className="flex border-b border-gray-200 overflow-x-auto">
          {[
            { id: 'basic', label: '基础', icon: Smartphone },
            { id: 'details', label: '详情', icon: Shield },
            { id: 'scenarios', label: '场景', icon: Globe },
            { id: 'transactions', label: '账单', icon: Receipt },
            { id: 'notes', label: '管理', icon: Signal },
          ].map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id as any)}
              className={`flex-1 min-w-[70px] py-3 text-sm font-medium flex items-center justify-center gap-2 transition-colors whitespace-nowrap ${
                activeTab === tab.id
                  ? 'text-indigo-600 border-b-2 border-indigo-600 bg-indigo-50/50'
                  : 'text-gray-500 hover:text-gray-700 hover:bg-gray-50'
              }`}
            >
              <tab.icon className="w-4 h-4" />
              {tab.label}
            </button>
          ))}
        </div>

        <form onSubmit={handleSubmit} className="flex-1 overflow-y-auto p-6 bg-gray-50/30">
          {activeTab === 'basic' && (
            <div className="space-y-5">
              {/* Basic Fields */}
              <div className="grid grid-cols-2 gap-4">
                 <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">套餐昵称 *</label>
                  <input required type="text" value={nickname} onChange={(e) => setNickname(e.target.value)} className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 outline-none" placeholder="例如：香港主力卡" />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">运营商类型</label>
                  <select value={operatorType} onChange={(e) => setOperatorType(e.target.value as OperatorType)} className="w-full px-3 py-2 border border-gray-300 rounded-lg outline-none bg-white">
                    {OPERATOR_TYPES.map(op => (
                      <option key={op.value} value={op.value}>{op.label}</option>
                    ))}
                  </select>
                </div>
              </div>
              
              {/* SIM Selection Block */}
              <div className="bg-white p-3 rounded-lg border border-gray-200">
                 <div className="flex items-center justify-between mb-2">
                   <label className="block text-sm font-medium text-gray-700">SIM 卡类型</label>
                   {initialData && (
                     <button type="button" onClick={handleSimTransfer} className={`text-xs flex items-center gap-1.5 px-2 py-1 rounded border transition-colors ${simType === 'physical' ? 'bg-purple-50 text-purple-700 border-purple-200 hover:bg-purple-100' : 'bg-emerald-50 text-emerald-700 border-emerald-200 hover:bg-emerald-100'}`}>
                       <ArrowRightLeft className="w-3 h-3" />
                       {simType === 'physical' ? '转为 eSIM' : '转为实体卡'}
                     </button>
                   )}
                 </div>
                 <div className="flex gap-4">
                    <label className={`flex-1 flex items-center gap-2 p-3 border rounded-lg cursor-pointer ${simType === 'esim' ? 'bg-indigo-50 border-indigo-500 text-indigo-700' : 'hover:bg-gray-50'}`}>
                       <input type="radio" name="simType" value="esim" checked={simType === 'esim'} onChange={() => setSimType('esim')} className="text-indigo-600" />
                       <Cpu className="w-4 h-4" />
                       <div className="flex-1">
                          <div className="font-bold text-sm">eSIM</div>
                          <div className="text-xs opacity-70">需要关联芯片</div>
                       </div>
                    </label>
                    <label className={`flex-1 flex items-center gap-2 p-3 border rounded-lg cursor-pointer ${simType === 'physical' ? 'bg-indigo-50 border-indigo-500 text-indigo-700' : 'hover:bg-gray-50'}`}>
                       <input type="radio" name="simType" value="physical" checked={simType === 'physical'} onChange={() => setSimType('physical')} className="text-indigo-600" />
                       <IdCard className="w-4 h-4" />
                        <div className="flex-1">
                          <div className="font-bold text-sm">实体卡</div>
                          <div className="text-xs opacity-70">Physical SIM</div>
                       </div>
                    </label>
                 </div>
                 {simType === 'physical' && (
                    <div className="mt-3 animate-fade-in">
                       <label className="block text-xs font-medium text-gray-500 mb-1">卡片类型/名称</label>
                       <div className="flex gap-2">
                          <select value={physicalCardName} onChange={(e) => setPhysicalCardName(e.target.value)} className="flex-1 px-3 py-2 border rounded-lg text-sm bg-gray-50">
                             {PHYSICAL_CARD_PRESETS.map(p => <option key={p} value={p}>{p}</option>)}
                             <option value="Other">其他 (自定义)</option>
                          </select>
                          {(!PHYSICAL_CARD_PRESETS.includes(physicalCardName) || physicalCardName === 'Other') && (
                             <input type="text" value={physicalCardName === 'Other' ? '' : physicalCardName} onChange={(e) => setPhysicalCardName(e.target.value)} className="flex-1 px-3 py-2 border rounded-lg text-sm" placeholder="自定义名称" />
                          )}
                       </div>
                       <label className="flex items-center gap-2 mt-3 p-2 border border-gray-200 rounded bg-gray-50 cursor-pointer hover:bg-gray-100 transition-colors">
                          <input type="checkbox" checked={isArchived} onChange={e => setIsArchived(e.target.checked)} className="rounded text-indigo-600" />
                          <div className="flex items-center gap-1.5 text-sm text-gray-700">
                            <Archive className="w-4 h-4 text-gray-500" />
                            <span>归档此卡 (不再作为活跃卡显示)</span>
                          </div>
                       </label>
                    </div>
                 )}
                 {simType === 'esim' && (
                    <div className="mt-3 animate-fade-in space-y-3">
                       <div>
                         <label className="block text-xs font-medium text-gray-500 mb-1">关联芯片</label>
                         <select value={selectedChipId} onChange={(e) => setSelectedChipId(e.target.value)} className="w-full px-3 py-2 border rounded-lg text-sm bg-gray-50 mb-2">
                            <option value="">-- 选择 eSIM 芯片 --</option>
                            {availableChips.map(chip => (
                               <option key={chip.id} value={chip.id}>{chip.nickname} ({chip.eid.slice(0, 10)}...)</option>
                            ))}
                         </select>
                         {!selectedChipId && (
                            <div>
                               <input type="text" value={manualEid} onChange={(e) => setManualEid(e.target.value)} className="w-full px-3 py-2 border rounded-lg text-sm font-mono" placeholder="手动输入 EID (如果未注册芯片)" />
                               {recommendedChip && (
                                  <div className="mt-1 text-xs text-indigo-600 cursor-pointer flex items-center gap-1" onClick={() => setSelectedChipId(recommendedChip.id)}>
                                     <Cpu className="w-3 h-3"/> 发现匹配芯片: {recommendedChip.nickname}
                                  </div>
                               )}
                            </div>
                         )}
                       </div>
                       
                       {/* eSIM Transfer Config */}
                       <div className="pt-2 border-t border-gray-100">
                          <label className="flex items-center gap-2 cursor-pointer mb-2">
                             <input type="checkbox" checked={isEsimTransferSupported} onChange={(e) => setIsEsimTransferSupported(e.target.checked)} className="rounded text-indigo-600" />
                             <span className="text-sm font-medium text-gray-700 flex items-center gap-1"><RotateCw className="w-3 h-3"/> 支持 eSIM 转移/换机</span>
                          </label>
                          {isEsimTransferSupported && (
                             <div className="pl-6 animate-fade-in grid grid-cols-1 gap-2">
                                <select 
                                   value={ESIM_TRANSFER_METHODS.some(m => m.value === esimTransferMethod) ? esimTransferMethod : 'Other'} 
                                   onChange={(e) => {
                                      const val = e.target.value;
                                      if (val === 'Other') {
                                         setEsimTransferMethod(''); // Use custom
                                      } else {
                                         setEsimTransferMethod(val);
                                         setCustomTransferMethod('');
                                      }
                                   }} 
                                   className="w-full px-2 py-1.5 text-xs border rounded bg-gray-50"
                                >
                                   {ESIM_TRANSFER_METHODS.map(m => <option key={m.value} value={m.value}>{m.label}</option>)}
                                   <option value="Other">其他/组合方式 (Other/Custom)</option>
                                </select>
                                {(!ESIM_TRANSFER_METHODS.some(m => m.value === esimTransferMethod) || esimTransferMethod === '') && (
                                    <input 
                                       type="text" 
                                       value={customTransferMethod} 
                                       onChange={(e) => { setCustomTransferMethod(e.target.value); setEsimTransferMethod(e.target.value); }}
                                       className="w-full px-2 py-1.5 text-xs border rounded"
                                       placeholder="请输入具体转移方法备注..."
                                    />
                                )}
                                
                                {esimTransferMethod === 'Delete & Rescan' && (
                                    <div className="mt-2 pl-2 border-l-2 border-indigo-100">
                                       <label className="block text-xs font-medium text-gray-600 mb-1">重扫次数限制 (Rescan Limit)</label>
                                       <div className="flex gap-2">
                                          <input 
                                             type="number" 
                                             min="1"
                                             value={transferRescanLimit === null ? '' : transferRescanLimit} 
                                             onChange={(e) => setTransferRescanLimit(e.target.value === '' ? null : Number(e.target.value))}
                                             placeholder="无限 (Unlimited)"
                                             className="w-24 px-2 py-1 text-xs border rounded outline-none focus:ring-1 focus:ring-indigo-300"
                                          />
                                          <button type="button" onClick={() => setTransferRescanLimit(10)} className="px-2 py-1 text-[10px] bg-gray-100 rounded hover:bg-gray-200 border border-gray-200">esim.gg (10)</button>
                                          <button type="button" onClick={() => setTransferRescanLimit(null)} className="px-2 py-1 text-[10px] bg-gray-100 rounded hover:bg-gray-200 border border-gray-200">无限 (Unlimited)</button>
                                       </div>
                                       <p className="text-[10px] text-gray-400 mt-1">默认为无限。部分供应商 (如 esim.gg) 限制二维码扫描次数。</p>
                                    </div>
                                )}
                             </div>
                          )}
                       </div>
                    </div>
                 )}
              </div>

              {/* Number and Region */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">号码信息 (E.164格式)</label>
                <div className="flex gap-2 items-center">
                  <div className="relative flex-1">
                    <input type="text" value={phoneNumber} onChange={(e) => setPhoneNumber(e.target.value)} className="w-full pl-10 pr-3 py-2 border border-gray-300 rounded-lg outline-none" placeholder="+86138..." />
                    <div className="absolute left-3 top-1/2 -translate-y-1/2 text-lg">{displayedFlag}</div>
                  </div>
                  <input type="text" value={countryCode} onChange={(e) => { setCountryCode(e.target.value); setRegionFlagOverride(''); }} className="w-20 px-3 py-2 border border-gray-300 rounded-lg outline-none" placeholder="+86" title="输入区号 (+1, +7, +39等)" />
                  <select value={numberType} onChange={(e) => setNumberType(e.target.value as NumberType)} className="w-28 px-2 py-2 border border-gray-300 rounded-lg outline-none bg-white text-sm">
                    {NUMBER_TYPES.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
                  </select>
                </div>
                {ambiguousOptions && (
                  <div className="mt-2 p-2 bg-yellow-50 border border-yellow-200 rounded-lg animate-fade-in">
                    <p className="text-xs text-yellow-800 mb-1 font-bold">请选择具体区域:</p>
                    <div className="flex flex-wrap gap-2 max-h-32 overflow-y-auto">
                       {ambiguousOptions.map((opt, i) => (
                         <label key={i} className={`flex items-center gap-1 cursor-pointer bg-white px-2 py-1 rounded border transition-colors ${regionFlagOverride === opt.flag ? 'border-indigo-500 ring-1 ring-indigo-500 bg-indigo-50' : 'hover:border-indigo-400'}`}>
                           <input type="radio" name="region_override" checked={regionFlagOverride === opt.flag} onChange={() => { setRegionFlagOverride(opt.flag); }} className="hidden" />
                           <span className="text-sm">{opt.flag} {opt.name}</span>
                         </label>
                       ))}
                    </div>
                  </div>
                )}
                <div className="mt-2">
                   <label className="text-xs text-gray-500 font-medium mb-1 block">一级行政区 (State/Province) - 可选</label>
                   <input type="text" value={adminDivision} onChange={(e) => setAdminDivision(e.target.value)} className="w-full px-3 py-1.5 border border-gray-300 rounded text-sm outline-none focus:border-indigo-500" placeholder="例如: New York, California, British Columbia..." />
                </div>
                <div className="mt-4">
                  <div className="flex justify-between items-center mb-2">
                    <label className="text-sm font-medium text-gray-700 flex items-center gap-1"><Hash className="w-3 h-3"/> 关联虚拟号 / 副号码</label>
                    <button type="button" onClick={handleAddVirtualNumber} className="text-xs text-indigo-600 hover:underline flex items-center gap-1"><Plus className="w-3 h-3"/> 添加号码</button>
                  </div>
                  <div className="space-y-2">
                    {virtualNumbers.map((vn, idx) => (
                      <div key={vn.id} className="flex gap-2 items-center bg-gray-50 p-2 rounded border border-gray-200">
                        <input type="text" value={vn.number} onChange={(e) => updateVirtualNumber(idx, 'number', e.target.value)} className="flex-1 px-2 py-1 text-sm border rounded" placeholder="+1234..." />
                        <select value={vn.type} onChange={(e) => updateVirtualNumber(idx, 'type', e.target.value)} className="w-24 px-1 py-1 text-sm border rounded bg-white">
                           {NUMBER_TYPES.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
                        </select>
                        <input type="text" value={vn.note || ''} onChange={(e) => updateVirtualNumber(idx, 'note', e.target.value)} className="flex-1 px-2 py-1 text-sm border rounded" placeholder="备注" />
                        <button type="button" onClick={() => removeVirtualNumber(idx)} className="text-gray-400 hover:text-red-500"><Trash2 className="w-4 h-4" /></button>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
              
              {/* Tags Input */}
              <div>
                 <label className="block text-sm font-medium text-gray-700 mb-1">标签 (Tags)</label>
                 <div className="flex gap-2 mb-2">
                    <input type="text" value={tagInput} onChange={(e) => setTagInput(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && (e.preventDefault(), handleAddTag())} className="flex-1 px-3 py-2 border rounded-lg text-sm" placeholder="输入标签按回车 (e.g. 旅游, 备用)" />
                    <button type="button" onClick={handleAddTag} className="bg-gray-100 text-gray-700 px-3 py-2 rounded-lg text-sm border hover:bg-gray-200">添加</button>
                 </div>
                 <div className="flex flex-wrap gap-2">
                    {tags.map(t => (
                       <span key={t} className="bg-indigo-100 text-indigo-700 px-2 py-1 rounded text-xs flex items-center gap-1">
                          {t} <button type="button" onClick={() => removeTag(t)} className="hover:text-indigo-900"><X className="w-3 h-3" /></button>
                       </span>
                    ))}
                 </div>
              </div>

              {/* Date, Cost, Priority */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
  <div>
    <label className="block text-sm font-medium text-gray-700 mb-1">开通日期 *</label>
    <input required type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} className="w-full px-3 py-2 border border-gray-300 rounded-lg outline-none focus:ring-2 focus:ring-indigo-500" />
  </div>
  
  {/* 新增：周期类型选择 */}
  <div>
    <label className="block text-sm font-medium text-gray-700 mb-1">计费模式</label>
    <select 
      value={cycleType} 
      onChange={(e) => setCycleType(e.target.value as CycleType)} 
      className="w-full px-3 py-2 border border-gray-300 rounded-lg outline-none bg-white"
    >
      <option value="daily">按天数 (Days)</option>
      <option value="monthly">按月 (Monthly)</option>
      <option value="annual">按年 (Annual)</option>
      <option value="permanent">永久 (Permanent)</option>
      <option value="activity_based">⚡ 活跃延期 (Activity Based)</option>
    </select>
  </div>

{/* 仅在选择“按天数”或“活跃延期”时显示天数输入 */}
 <div className={cycleType === 'daily' || cycleType === 'activity_based' ? 'block' : 'hidden'}>
    <label className="block text-sm font-medium text-gray-700 mb-1">
        {cycleType === 'activity_based' ? '有效期 (天)' : '间隔天数 *'}
    </label>
    <input 
      required={cycleType === 'daily'} 
      type="number" 
      min="1" 
      value={cycleDays} 
      onChange={(e) => setCycleDays(Number(e.target.value))} 
      className="w-full px-3 py-2 border border-gray-300 rounded-lg outline-none focus:ring-2 focus:ring-indigo-500" 
      placeholder={cycleType === 'activity_based' ? "例如 365" : ""}
    />
  </div>
  
  <div>
    <label className="block text-sm font-medium text-gray-700 mb-1">宽限期 (天)</label>
    <input type="number" min="0" value={gracePeriod} onChange={(e) => setGracePeriod(Number(e.target.value))} className="w-full px-3 py-2 border border-gray-300 rounded-lg outline-none" title="过期后多久自动归档" />
  </div>
  
<div className="mt-4 bg-gray-50 p-3 rounded-lg border border-gray-200">
  <label className="block text-sm font-medium text-gray-700 mb-1">
    最后活跃记录 (插卡/充值/消费/流量)
  </label>
  <input 
    type="date" 
    value={lastActiveDate || ""} 
    onChange={(e) => setLastActiveDate(e.target.value)} 
    className="w-full px-3 py-2 border border-gray-300 rounded-lg outline-none focus:ring-2 focus:ring-indigo-500" 
  />
  <div className="mt-2 space-y-1">
    <p className="text-[10px] text-gray-500">
      提示：记录您最后一次实际使用该卡的时间。
    </p>
    {cycleType === 'activity_based' ? (
      <p className="text-[10px] text-indigo-600 font-medium">
        ℹ️ 非永久套餐模式下，系统将从该日期起算有效期。
      </p>
    ) : cycleType === 'permanent' ? (
      <p className="text-[10px] text-gray-400">
        ℹ️ 在永久套餐模式下，此日期仅作记录备查，不影响到期计算。
      </p>
    ) : (
      <p className="text-[10px] text-indigo-600 font-medium">
        ℹ️ 设置后，系统将优先从该日期（而非开通日期）推算下次续费日。
      </p>
    )}
  </div>
</div>

</div>

              <div className="grid grid-cols-3 gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">套餐费用</label>
                  <input required type="number" min="0" step="0.01" value={cost} onChange={(e) => setCost(e.target.value)} className="w-full px-3 py-2 border border-gray-300 rounded-lg outline-none" />
                </div>
                <div>
                   <label className="block text-sm font-medium text-gray-700 mb-1">费用货币</label>
                   <select value={currency} onChange={(e) => setCurrency(e.target.value)} className="w-full px-3 py-2 border border-gray-300 rounded-lg outline-none">
                     {ALL_CURRENCIES.map(c => <option key={c.code} value={c.code}>{c.code} ({c.symbol})</option>)}
                   </select>
                </div>
                <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">优先级</label>
                    <select value={priority} onChange={(e) => setPriority(Number(e.target.value))} className="w-full px-3 py-2 border border-gray-300 rounded-lg outline-none">
                      {[1,2,3,4,5,6,7,8,9,10].map(p => (
                         <option key={p} value={p}>{p} {p === 1 ? '(最高)' : p === 10 ? '(最低)' : ''}</option>
                      ))}
                    </select>
                 </div>
              </div>

              {/* Balance Management Section */}
              <div className="bg-emerald-50/50 p-3 rounded-lg border border-emerald-100">
                 <label className="text-sm font-bold text-emerald-800 mb-2 flex items-center gap-1.5"><Wallet className="w-4 h-4"/> 账户余额管理 (可选)</label>
                 <div className="grid grid-cols-3 gap-4">
                     <div className="col-span-2">
                        <input type="number" step="0.01" value={balance} onChange={(e) => setBalance(e.target.value)} className="w-full px-3 py-2 border rounded-lg outline-none" placeholder="当前余额 (例如 50.00)" />
                     </div>
                     <div>
                        <select value={balanceCurrency} onChange={(e) => setBalanceCurrency(e.target.value)} className="w-full px-3 py-2 border rounded-lg outline-none bg-white">
                            {ALL_CURRENCIES.map(c => <option key={c.code} value={c.code}>{c.code}</option>)}
                        </select>
                     </div>
                 </div>
                 <p className="text-[10px] text-emerald-600 mt-1">用于记录 SIM 卡内的剩余话费。部分 PAYG 流量将直接扣除此余额。</p>
              </div>
              <div className="grid grid-cols-2 gap-4 bg-gray-100/50 p-3 rounded-lg border border-dashed border-gray-200 mt-4">
  <div>
    <label className="block text-[11px] font-bold text-gray-500 uppercase mb-1">SIM PIN</label>
    <input 
      type="text" 
      value={simPin} 
      onChange={(e) => setSimPin(e.target.value)} 
      className="w-full px-3 py-1.5 border rounded-lg text-sm font-mono focus:ring-2 focus:ring-indigo-500 outline-none" 
      placeholder="默认通常为 0000"
    />
  </div>
  <div>
    <label className="block text-[11px] font-bold text-gray-500 uppercase mb-1">SIM PUK</label>
    <input 
      type="text" 
      value={simPuk} 
      onChange={(e) => setSimPuk(e.target.value)} 
      className="w-full px-3 py-1.5 border rounded-lg text-sm font-mono focus:ring-2 focus:ring-indigo-500 outline-none" 
      placeholder="通常为 8 位数字"
    />
  </div>
</div>
            </div> // 这里是 activeTab === 'basic' 的闭合
          )}

          {/* Details Tab */}
          {activeTab === 'details' && (
            <div className="space-y-6">
               {/* KYC Info */}
               <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">KYC 认证信息</label>
                <div className="grid grid-cols-2 gap-2">
                  {KYC_OPTIONS.map(opt => (
                    <label key={opt.value} className={`flex items-center gap-2 p-3 border rounded-lg cursor-pointer transition-all ${kycType === opt.value ? 'bg-indigo-50 border-indigo-500 ring-1 ring-indigo-500' : 'hover:bg-gray-50 border-gray-200'}`}>
                      <input type="radio" name="kyc" value={opt.value} checked={kycType === opt.value} onChange={() => setKycType(opt.value as KycType)} className="text-indigo-600 focus:ring-indigo-500" />
                      <span className="text-sm text-gray-700">{opt.label}</span>
                    </label>
                  ))}
                </div>
              </div>
              
              {/* Payment Methods */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">支持的支付方式</label>
                <div className="flex flex-wrap gap-2 mb-3 max-h-40 overflow-y-auto">
                  {PAYMENT_METHODS.map(method => (
                    <button type="button" key={method} onClick={() => togglePaymentMethod(method as PaymentMethod)} className={`px-3 py-1.5 rounded-full text-xs font-medium border transition-all ${paymentMethods.includes(method as PaymentMethod) ? 'bg-indigo-600 text-white border-indigo-600 shadow-sm' : 'bg-white text-gray-600 border-gray-200 hover:border-gray-300 hover:bg-gray-50'}`}>
                      {method}
                    </button>
                  ))}
                </div>
                <div className="relative">
                   <StickyNote className="absolute top-2.5 left-3 w-4 h-4 text-gray-400" />
                   <textarea
                     value={paymentMethodNote}
                     onChange={(e) => setPaymentMethodNote(e.target.value)}
                     className="w-full pl-10 pr-3 py-2 border rounded-lg text-sm h-20 outline-none resize-none"
                     placeholder="支付备注: 例如卡密购买渠道、代充联系方式等..."
                   />
                </div>
              </div>

              {/* INDEPENDENT Payment Sources Selection (Unchanged) */}
              <div className="space-y-4">
                  {/* Card Section */}
                  <div className={`rounded-lg border transition-all ${hasCard ? 'border-indigo-200 bg-white' : 'border-gray-200 bg-gray-50'}`}>
                      <div className="p-3 flex items-center justify-between cursor-pointer" onClick={() => setHasCard(!hasCard)}>
                          <div className="flex items-center gap-2 font-medium text-sm text-gray-700">
                             <input type="checkbox" checked={hasCard} onChange={() => {}} className="rounded text-indigo-600 pointer-events-none" />
                             <CreditCard className="w-4 h-4" />
                             绑定银行卡/信用卡
                          </div>
                      </div>
                      {hasCard && (
                         <div className="p-3 border-t border-indigo-100 grid grid-cols-2 gap-3 animate-fade-in">
                            <select value={cardType} onChange={(e) => setCardType(e.target.value)} className="px-2 py-1.5 border rounded text-xs">
                               <option value="Visa">Visa</option><option value="Mastercard">Mastercard</option><option value="AmEx">AmEx</option><option value="JCB">JCB</option><option value="UnionPay">UnionPay</option><option value="Other">Other</option>
                            </select>
                            <div className="flex items-center gap-2">
                               <label className="flex items-center gap-1 text-xs cursor-pointer">
                                  <input type="checkbox" checked={cardIsVirtual} onChange={(e) => setCardIsVirtual(e.target.checked)} />
                                  虚拟卡
                               </label>
                            </div>
                            <input type="text" value={cardBankName} onChange={(e) => setCardBankName(e.target.value)} placeholder="发卡行 (e.g. Chase)" className="col-span-2 px-2 py-1.5 border rounded text-xs" />
                            <input type="text" value={cardNumber} onChange={(e) => setCardNumber(e.target.value)} placeholder="卡号 (后4位)" className="col-span-2 px-2 py-1.5 border rounded text-xs font-mono" />
                            <input type="text" value={cardRemarks} onChange={(e) => setCardRemarks(e.target.value)} placeholder="备注 (e.g. 3DS验证手机)" className="col-span-2 px-2 py-1.5 border rounded text-xs" />
                         </div>
                      )}
                  </div>

                  {/* Bank Account Section */}
                  <div className={`rounded-lg border transition-all ${hasAccount ? 'border-blue-200 bg-white' : 'border-gray-200 bg-gray-50'}`}>
                      <div className="p-3 flex items-center justify-between cursor-pointer" onClick={() => setHasAccount(!hasAccount)}>
                          <div className="flex items-center gap-2 font-medium text-sm text-gray-700">
                             <input type="checkbox" checked={hasAccount} onChange={() => {}} className="rounded text-blue-600 pointer-events-none" />
                             <Landmark className="w-4 h-4" />
                             绑定银行账户
                          </div>
                      </div>
                      {hasAccount && (
                         <div className="p-3 border-t border-blue-100 grid grid-cols-2 gap-3 animate-fade-in">
                            <input type="text" value={accBankName} onChange={(e) => setAccBankName(e.target.value)} placeholder="银行名称 (e.g. HSBC HK)" className="col-span-2 px-2 py-1.5 border rounded text-xs" />
                            <input type="text" value={accNumber} onChange={(e) => setAccNumber(e.target.value)} placeholder="账号 / 户口号" className="col-span-2 px-2 py-1.5 border rounded text-xs font-mono" />
                            <input type="text" value={accRegion} onChange={(e) => setAccRegion(e.target.value)} placeholder="区域代码 (e.g. HK)" className="px-2 py-1.5 border rounded text-xs uppercase" />
                            <div className="flex items-center gap-2">
                               <label className="flex items-center gap-1 text-xs cursor-pointer" title="非居民账户">
                                  <input type="checkbox" checked={accIdentity === 'non_citizen'} onChange={(e) => setAccIdentity(e.target.checked ? 'non_citizen' : 'citizen')} />
                                  <UserCheck className="w-3 h-3"/> Non-Citizen
                               </label>
                            </div>
                            <input type="text" value={accIban} onChange={(e) => setAccIban(e.target.value)} placeholder="IBAN (Optional)" className="col-span-2 px-2 py-1.5 border rounded text-xs font-mono" />
                            <input type="text" value={accRemarks} onChange={(e) => setAccRemarks(e.target.value)} placeholder="备注" className="col-span-2 px-2 py-1.5 border rounded text-xs" />
                         </div>
                      )}
                  </div>
              </div>
               
               <div className="space-y-3">
                 <div>
                   <label className="block text-sm font-medium text-gray-700 mb-1">官方网站</label>
                   <input type="url" value={website} onChange={(e) => setWebsite(e.target.value)} className="w-full px-3 py-2 border border-gray-300 rounded-lg outline-none" placeholder="https://..." />
                 </div>
                 <div>
                   <label className="block text-sm font-medium text-gray-700 mb-1">直达充值链接 (Deep Link)</label>
                   <div className="relative">
                     <LinkIcon className="absolute left-3 top-2.5 w-4 h-4 text-gray-400" />
                     <input type="url" value={topUpUrl} onChange={(e) => setTopUpUrl(e.target.value)} className="w-full pl-10 pr-3 py-2 border border-gray-300 rounded-lg outline-none" placeholder="https://m.client.com/topup?id=..." />
                   </div>
                   <p className="text-[10px] text-gray-400 mt-1">此链接将显示为卡片上的快捷充值按钮。</p>
                 </div>
               </div>
            </div>
          )}
          
          {/* Scenarios Tab (Unchanged Logic, just re-rendering) */}
          {activeTab === 'scenarios' && (
            <div className="space-y-4">
               {scenarios.map((scenario, idx) => (
                 <div key={scenario.id} className="bg-white border border-gray-200 rounded-lg p-4 relative shadow-sm">
                    <button onClick={() => handleRemoveScenario(idx)} className="absolute top-2 right-2 text-gray-400 hover:text-red-500 p-1"><Trash2 className="w-4 h-4" /></button>
                    <div className="grid grid-cols-1 gap-3 mb-3">
                       <div className="flex gap-2">
                          <input 
                             type="text" 
                             value={scenario.regionCode} 
                             onChange={(e) => updateScenarioField(idx, 'regionCode', e.target.value)} 
                             className="w-24 px-2 py-1 border rounded text-sm" 
                             placeholder="区号 +86"
                          />
                          <input 
                             type="text" 
                             value={scenario.note} 
                             onChange={(e) => updateScenarioField(idx, 'note', e.target.value)} 
                             className="flex-1 px-2 py-1 border rounded text-sm font-bold" 
                             placeholder="场景名称 (e.g. 漫游上网)"
                          />
                       </div>
                       
                       {/* 3 Modes */}
                       <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
                          {renderScenarioModeConfig(idx, 'local', '本地使用 (Local)', 'bg-emerald-50 border-emerald-200')}
                          {renderScenarioModeConfig(idx, 'roaming', '国际漫游 (Roaming)', 'bg-blue-50 border-blue-200')}
                          {renderScenarioModeConfig(idx, 'vowifi', 'VoWiFi (Wi-Fi Call)', 'bg-indigo-50 border-indigo-200')}
                       </div>
                    </div>
                 </div>
               ))}
               <button type="button" onClick={handleAddScenario} className="w-full py-2 border-2 border-dashed border-gray-300 rounded-lg text-gray-500 font-medium hover:border-indigo-400 hover:text-indigo-600 transition-colors flex items-center justify-center gap-2">
                 <Plus className="w-4 h-4" /> 添加使用场景
               </button>
            </div>
          )}
          
          {/* New Transactions Tab */}
          {activeTab === 'transactions' && (
             <div className="space-y-4">
                 <div className="flex items-center justify-between">
                    <h3 className="font-bold text-gray-700 text-sm">历史账单 & 充值记录</h3>
                    <button type="button" onClick={handleAddTransaction} className="text-xs flex items-center gap-1 bg-indigo-50 text-indigo-600 px-2 py-1 rounded border border-indigo-100 hover:bg-indigo-100"><Plus className="w-3 h-3"/> 记一笔</button>
                 </div>
                 <div className="space-y-2">
                    {transactions.length === 0 && <p className="text-xs text-gray-400 text-center py-4">暂无记录</p>}
                    {transactions.map(t => (
                       <div key={t.id} className="bg-white p-3 rounded border border-gray-200 text-sm">
                           <div className="flex gap-2 mb-2">
                              <input type="date" value={t.date} onChange={(e) => updateTransaction(t.id, {date: e.target.value})} className="border rounded px-2 py-1 text-xs" />
                              <select value={t.type} onChange={(e) => updateTransaction(t.id, {type: e.target.value as any})} className="border rounded px-2 py-1 text-xs bg-white">
                                 <option value="topup">充值 (Top-up)</option>
                                 <option value="consumption">消费 (Cost)</option>
                                 <option value="fee">月租/年费 (Fee)</option>
                              </select>
                              <div className="flex-1 flex gap-1">
                                 <input type="number" value={t.amount} onChange={(e) => updateTransaction(t.id, {amount: Number(e.target.value)})} className="w-full border rounded px-2 py-1 text-xs font-bold text-right" placeholder="0.00" />
                                 <select value={t.currency} onChange={(e) => updateTransaction(t.id, {currency: e.target.value})} className="border rounded px-1 py-1 text-xs bg-gray-50 w-16">
                                     {ALL_CURRENCIES.map(c => <option key={c.code} value={c.code}>{c.code}</option>)}
                                 </select>
                              </div>
                              <button type="button" onClick={() => removeTransaction(t.id)} className="text-gray-400 hover:text-red-500"><Trash2 className="w-4 h-4"/></button>
                           </div>
                           <div className="flex gap-2">
                              <input type="text" value={t.method || ''} onChange={(e) => updateTransaction(t.id, {method: e.target.value})} className="w-24 border rounded px-2 py-1 text-xs" placeholder="渠道 (e.g. 淘宝)" />
                              <input type="text" value={t.note || ''} onChange={(e) => updateTransaction(t.id, {note: e.target.value})} className="flex-1 border rounded px-2 py-1 text-xs" placeholder="备注 (e.g. 汇率 7.2)" />
                           </div>
                       </div>
                    ))}
                 </div>
             </div>
          )}

          {/* Notes & Data Tab */}
          {activeTab === 'notes' && (
             <div className="space-y-6">
                <div>
                   <label className="block text-sm font-medium text-gray-700 mb-2 flex items-center gap-1"><Signal className="w-4 h-4" /> 流量/用量监控</label>
                   <div className="space-y-3">
                      {dataPlans.map((plan, idx) => (
                        <div key={plan.id} className="bg-white p-3 rounded-lg border border-gray-200">
                           <div className="flex justify-between items-start mb-2">
                              <div className="flex-1 mr-2">
                                 <input 
                                   type="text" 
                                   value={plan.regionNote} 
                                   onChange={(e) => updateDataPlan(idx, 'regionNote', e.target.value)} 
                                   className="w-full px-2 py-1 border rounded text-sm font-bold mb-1" 
                                   placeholder="区域/用途 (e.g. 漫游流量)" 
                                 />
                              </div>
                              <button type="button" onClick={() => removeDataPlan(idx)} className="text-gray-400 hover:text-red-500"><X className="w-4 h-4" /></button>
                           </div>
                           <div className="grid grid-cols-2 gap-2 text-xs">
                              <div>
                                 <label className="block text-gray-500 mb-0.5">总量</label>
                                 <div className="flex">
                                    <input 
                                       type="number" 
                                       min="0"
                                       step="0.01" 
                                       value={plan.total} 
                                       onChange={(e) => updateDataPlan(idx, 'total', Number(e.target.value))} 
                                       className="w-full px-2 py-1 border rounded-l outline-none focus:border-indigo-500" 
                                    />
                                    <select 
                                       value={plan.unit} 
                                       onChange={(e) => updateDataPlan(idx, 'unit', e.target.value)} 
                                       className="bg-gray-50 border-y border-r rounded-r px-1 outline-none text-gray-600"
                                    >
                                       <option value="MB">MB</option>
                                       <option value="GB">GB</option>
                                    </select>
                                 </div>
                              </div>
                              <div>
                                 <label className="block text-gray-500 mb-0.5">已用</label>
                                 <input 
                                    type="number" 
                                    min="0"
                                    step="0.01" 
                                    value={plan.used} 
                                    onChange={(e) => updateDataPlan(idx, 'used', Number(e.target.value))} 
                                    className="w-full px-2 py-1 border rounded outline-none focus:border-indigo-500" 
                                 />
                              </div>
                              <div className="col-span-2 pt-1">
                                <label className="flex items-center gap-2 cursor-pointer">
                                   <input 
                                      type="checkbox" 
                                      checked={plan.isPayg} 
                                      onChange={(e) => updateDataPlan(idx, 'isPayg', e.target.checked)} 
                                      className="rounded text-indigo-600"
                                   />
                                   <span className="text-gray-600">按量付费 (Pay Per Use / PAYG)</span>
                                </label>
                                {plan.isPayg && (
                                   <div className="mt-1 flex items-center gap-2 animate-fade-in">
                                      <span className="text-gray-500">费率:</span>
                                      <input 
                                         type="number" 
                                         value={plan.paygCostPerUnit || ''} 
                                         onChange={(e) => updateDataPlan(idx, 'paygCostPerUnit', Number(e.target.value))} 
                                         className="w-20 px-1 py-0.5 border rounded text-right" 
                                      />
                                      <span className="text-gray-500">/ {plan.unit}</span>
                                   </div>
                                )}
                             </div>
                             
                             <div className="col-span-2 pt-2 border-t border-dashed border-gray-200 mt-1">
                                <div 
                                   className="flex justify-between items-center cursor-pointer hover:bg-gray-50 rounded px-1 -mx-1 py-0.5" 
                                   onClick={() => setExpandedDataPlanId(expandedDataPlanId === plan.id ? null : plan.id)}
                                >
                                   <span className="font-bold text-gray-600 flex items-center gap-1 text-[10px] uppercase tracking-wider">
                                      <Gauge className="w-3 h-3"/> 限速/高级策略
                                   </span>
                                   <span className="text-gray-400 text-[10px]">{expandedDataPlanId === plan.id ? '收起' : '展开'}</span>
                                </div>
                                {expandedDataPlanId === plan.id && (
                                   <div className="mt-2 space-y-2 bg-gray-50 p-2 rounded animate-fade-in border border-gray-100">
                                      {/* High Speed Quota */}
                                      <div>
                                         <label className="block text-gray-500 mb-0.5">高速流量额度</label>
                                         <div className="flex items-center gap-1">
                                            <input 
                                               type="number" 
                                               value={plan.highSpeedQuota || ''} 
                                               onChange={(e) => updateDataPlan(idx, 'highSpeedQuota', Number(e.target.value))} 
                                               className="flex-1 px-2 py-1 border rounded bg-white" 
                                               placeholder="0 = 不限" 
                                            />
                                            <span className="text-gray-500">{plan.unit}</span>
                                         </div>
                                      </div>
                                      {/* Throttled Speed */}
                                      <div>
                                         <label className="block text-gray-500 mb-0.5">达量后限速</label>
                                         <div className="flex gap-1 mb-1">
                                            <input 
                                               type="number" 
                                               value={plan.throttledSpeed || ''} 
                                               onChange={(e) => updateDataPlan(idx, 'throttledSpeed', Number(e.target.value))} 
                                               className="flex-1 px-2 py-1 border rounded bg-white" 
                                               placeholder="128"
                                            />
                                            <select 
                                               value={plan.throttledSpeedUnit || 'kbps'} 
                                               onChange={(e) => updateDataPlan(idx, 'throttledSpeedUnit', e.target.value)} 
                                               className="w-20 px-1 py-1 border rounded bg-white text-[10px]"
                                            >
                                               {SPEED_UNITS.map(u => <option key={u} value={u}>{u}</option>)}
                                            </select>
                                         </div>
                                         <label className="flex items-center gap-1 mt-1 cursor-pointer">
                                            <input 
                                               type="checkbox" 
                                               checked={plan.isThrottledUnlimited} 
                                               onChange={(e) => updateDataPlan(idx, 'isThrottledUnlimited', e.target.checked)} 
                                               className="rounded text-indigo-600"
                                            />
                                            <span className="text-gray-600">无限低速流量 (Unlimited Throttled)</span>
                                         </label>
                                      </div>
                                      {/* Overall Speed Limit */}
                                       <div className="pt-2 border-t border-gray-200">
                                         <label className="block text-gray-500 mb-0.5">整体限速 (Hard Cap)</label>
                                         <div className="flex gap-1">
                                            <input 
                                               type="number" 
                                               value={plan.overallSpeedLimit || ''} 
                                               onChange={(e) => updateDataPlan(idx, 'overallSpeedLimit', Number(e.target.value))} 
                                               className="flex-1 px-2 py-1 border rounded bg-white" 
                                               placeholder="0 = 不限"
                                            />
                                            <select 
                                               value={plan.overallSpeedLimitUnit || 'Mbps'} 
                                               onChange={(e) => updateDataPlan(idx, 'overallSpeedLimitUnit', e.target.value)} 
                                               className="w-20 px-1 py-1 border rounded bg-white text-[10px]"
                                            >
                                               {SPEED_UNITS.map(u => <option key={u} value={u}>{u}</option>)}
                                            </select>
                                         </div>
                                      </div>
                                   </div>
                                )}
                             </div>
                           </div>
                        </div>
                      ))}
                   </div>
                   <button type="button" onClick={handleAddDataPlan} className="w-full py-2 border-2 border-dashed border-gray-300 rounded-lg text-gray-500 font-medium hover:border-indigo-400 hover:text-indigo-600 transition-colors flex items-center justify-center gap-2">
                     <Plus className="w-4 h-4" /> 添加流量包
                   </button>
                </div>
                
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2 flex items-center gap-1"><Info className="w-4 h-4"/> 保号 / 充值 / 历史备注</label>
                  <textarea value={keepAliveNote} onChange={(e) => setKeepAliveNote(e.target.value)} className="w-full px-3 py-2 border border-gray-300 rounded-lg h-32 outline-none resize-none font-mono text-xs leading-relaxed" placeholder="记录保号规则、上次充值时间、卡片历史等..." />
                </div>
             </div>
          )}

        </form>

        <div className="p-4 bg-gray-50 border-t border-gray-100 flex justify-end gap-3">
          <button onClick={onClose} type="button" className="px-5 py-2.5 text-gray-600 font-medium hover:bg-gray-100 rounded-xl transition-colors">取消</button>
          <button onClick={handleSubmit} type="button" className="px-6 py-2.5 bg-indigo-600 text-white font-bold rounded-xl hover:bg-indigo-700 shadow-lg shadow-indigo-200 transition-all transform active:scale-95">保存套餐</button>
        </div>
      </div>
    </div>
  );
};

export default SubscriptionForm;


import React, { useState } from 'react';
import { Trash2, Share2, RefreshCw, Calendar, Phone, Edit2, ChevronDown, ChevronUp, Wifi, CreditCard, Cpu, Signal, Globe, Archive, ArchiveRestore, IdCard, Hash, MapPin, Landmark, UserCheck, ArrowRightLeft, Download, TrendingUp, StickyNote, Gauge, Wallet, RotateCw, AlertTriangle, Zap } from 'lucide-react';
import { Subscription, Scenario, ESimChip } from '../types';
import { getFlagFromPhoneNumber, calculateNextRenewal, formatDate, getDaysRemaining, formatPhoneNumberDisplay, generateICS, calculateProjectedCost, shareUtils } from '../utils/helpers';
import { KYC_OPTIONS, OPERATOR_TYPES, NUMBER_TYPES } from '../constants';
import QRCode from 'qrcode';

interface SubscriptionCardProps {
  subscription: Subscription;
  linkedChip?: ESimChip;
  isSelected: boolean;
  isDemoMode?: boolean; // New prop for Demo Mode
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
  onEdit: (sub: Subscription) => void;
  onArchive: (id: string, currentStatus: boolean) => void;
  onPorting: (sub: Subscription) => void;
  onQuickUpdate: (id: string, updates: Partial<Subscription>) => void;
}

const SubscriptionCard: React.FC<SubscriptionCardProps> = ({ subscription, linkedChip, isSelected, isDemoMode = false, onSelect, onDelete, onEdit, onArchive, onPorting, onQuickUpdate }) => {
  const [expanded, setExpanded] = useState(false);
  const [showQr, setShowQr] = useState(false);
  const [qrUrl, setQrUrl] = useState('');
  
  // 处理“一键打卡”
  const handleCheckIn = (e: React.MouseEvent) => {
    e.stopPropagation();
    const today = new Date().toISOString().slice(0, 10);
    const confirmMsg = `⚡ 确认打卡？\n\n确认今天 (${today}) 已经插卡、连网、消费或充值了吗？\n有效期将基于今天顺延 ${subscription.cycleDays || 365} 天。`;
    
    if (window.confirm(confirmMsg)) {
        onQuickUpdate(subscription.id, { lastActiveDate: today });
    }
  };
  
  const handleShare = async (e: React.MouseEvent) => {
  e.stopPropagation();
  
  // 确何一些字段【不被包含】
  const shareData = {
    nickname: subscription.nickname,
    operatorType: subscription.operatorType,
    cost: subscription.cost,
    currency: subscription.currency,
    cycleDays: subscription.cycleDays,
    cycleType: subscription.cycleType,
    keepAliveNote: subscription.keepAliveNote,
    // simPin, simPuk, phoneNumber, eSim 等隐私内容自动被排除
  };

  const base64Data = shareUtils.encodeData(shareData); // 使用刚才新建的 shareUtils
  const shareUrl = `${window.location.origin}${window.location.pathname}?import=${base64Data}`;

  // 生成二维码（内容为上面刚生成的URL）
  try {
    const url = await QRCode.toDataURL(shareUrl, {
      margin: 2,
      width: 256,
      color: {
        dark: '#4f46e5', // 使用 App 的默认主题色（靛蓝色）
        light: '#ffffff'
      }
});
    setQrUrl(url);
    setShowQr(true);
  } catch (err) {
    console.error('QR生成失败', err);
  }
};

  const nextRenewal = calculateNextRenewal(subscription.startDate, subscription.cycleDays, subscription.cycleType, subscription.lastActiveDate);
  const daysRemaining = getDaysRemaining(nextRenewal);
  const threshold = subscription.notificationThreshold ?? 7;
  const gracePeriod = subscription.gracePeriod ?? 0;
  
  const flag = getFlagFromPhoneNumber(subscription.phoneNumber, subscription.countryCode);
  const displayPhone = formatPhoneNumberDisplay(subscription.phoneNumber, isDemoMode);
  
  // Status Logic including Grace Period
  let statusColor = 'bg-emerald-50 text-emerald-700 border-emerald-200';
  let statusText = `剩 ${daysRemaining} 天`;

  if (daysRemaining <= 0) {
     const daysPast = Math.abs(daysRemaining);
     if (daysPast === 0) {
         statusColor = 'bg-amber-50 text-amber-700 border-amber-200';
         statusText = '今天到期';
     } else if (daysPast <= gracePeriod) {
         statusColor = 'bg-gray-800 text-white border-gray-700';
         statusText = `宽限期: 剩 ${gracePeriod - daysPast} 天`;
     } else {
         statusColor = 'bg-gray-200 text-gray-600 border-gray-300';
         statusText = `过期 ${daysPast} 天`;
     }
  } else if (daysRemaining <= threshold) {
     statusColor = 'bg-red-50 text-red-700 border-red-200';
  } else if (daysRemaining <= 30) {
      statusColor = 'bg-amber-50 text-amber-700 border-amber-200';
  }

  const getDataColor = (used: number, total: number, isPayg?: boolean) => {
    if (isPayg) return 'bg-amber-500'; // Special color for PAYG
    if (total === 0) return 'bg-gray-200';
    const percentage = (used / total) * 100;
    if (percentage >= 90) return 'bg-red-500';
    if (percentage >= 70) return 'bg-amber-400';
    return 'bg-emerald-500';
  };

  const kycLabel = KYC_OPTIONS.find(k => k.value === subscription.kycType)?.label;
  const operatorLabel = OPERATOR_TYPES.find(o => o.value === subscription.operatorType)?.label || subscription.operatorType;
  const numberTypeLabel = NUMBER_TYPES.find(n => n.value === subscription.numberType)?.label;

  // Data processing
  const dataPlans = subscription.dataPlans?.map(dp => ({
      ...dp,
      totalVal: dp.total ?? dp.totalGB ?? 0,
      usedVal: dp.used ?? dp.usedGB ?? 0,
      displayUnit: dp.unit || 'GB'
  })) || (subscription.dataUsage ? [{
      ...subscription.dataUsage,
      totalVal: subscription.dataUsage.total ?? subscription.dataUsage.totalGB ?? 0,
      usedVal: subscription.dataUsage.used ?? subscription.dataUsage.usedGB ?? 0,
      displayUnit: subscription.dataUsage.unit || 'GB'
  }] : []);

  const isPhysical = subscription.simType === 'physical';
  const hasEsim = !isPhysical && (subscription.eSim?.eid || subscription.eSim?.chipId);

  // Helper to format speed info
  const renderSpeedInfo = (plan: any) => {
      const parts = [];
      if (plan.overallSpeedLimit > 0) parts.push(`整体限速 ${plan.overallSpeedLimit}${plan.overallSpeedLimitUnit}`);
      if (plan.highSpeedQuota > 0) parts.push(`高速 ${plan.highSpeedQuota}${plan.unit}`);
      if (plan.isThrottledUnlimited) parts.push(`达量后无限@${plan.throttledSpeed}${plan.throttledSpeedUnit}`);
      else if (plan.throttledSpeed > 0) parts.push(`达量后限速@${plan.throttledSpeed}${plan.throttledSpeedUnit}`);
      
      if (parts.length === 0) return null;
      return <div className="text-[10px] text-indigo-600 flex items-center gap-1 mt-0.5"><Gauge className="w-3 h-3"/> {parts.join(' | ')}</div>;
  };

  return (
    <div className={`bg-white rounded-xl shadow-sm border transition-all relative group ${isSelected ? 'ring-2 ring-indigo-500 border-indigo-500' : 'border-gray-200 hover:shadow-md'} ${subscription.isArchived ? 'opacity-70 grayscale bg-gray-50' : ''}`}>
    {/* 二维码分享覆盖层 */}
{showQr && (
  <div 
    className="absolute inset-0 bg-white/95 z-30 flex flex-col items-center justify-center p-6 animate-fade-in"
    onClick={(e) => { e.stopPropagation(); setShowQr(false); }}
  >
    <div className="bg-white p-2 border-4 border-indigo-600 rounded-xl shadow-xl">
       <img src={qrUrl} alt="Share QR" className="w-32 h-32" />
    </div>
    <p className="mt-4 text-xs font-bold text-gray-800">扫描导入此套餐模板</p>
    <div className="mt-2 px-4 text-center">
       <p className="text-[10px] text-amber-600 flex items-center justify-center gap-1 font-medium">
          <AlertTriangle className="w-2.5 h-2.5" /> 请确保备注中不含个人敏感信息
       </p>
       <p className="text-[9px] text-gray-400 mt-1">隐私数据（号码、PIN/PUK、卡号）已自动剔除</p>
    </div>
    <p className="text-[10px] text-gray-400 mt-1">点击任意处关闭</p>
  </div>
)}
      <div 
        className="absolute top-4 left-4 z-10 cursor-pointer"
        onClick={() => onSelect(subscription.id)}
      >
        <div className={`w-5 h-5 rounded border flex items-center justify-center ${isSelected ? 'bg-indigo-600 border-indigo-600' : 'bg-white border-gray-300'}`}>
          {isSelected && <svg className="w-3 h-3 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" /></svg>}
        </div>
      </div>

      <div className="p-5 pl-12" onClick={() => !isSelected && setExpanded(!expanded)}>
        <div className="flex justify-between items-start mb-3 cursor-pointer">
          <div className="flex items-center gap-3">
            <span className="text-3xl select-none" role="img" aria-label="region flag">{flag}</span>
            <div>
              <h3 className="font-bold text-gray-800 text-lg leading-tight flex items-center gap-2">
                {subscription.nickname}
                {subscription.priority === 1 && <span className="text-xs bg-red-100 text-red-600 px-1.5 rounded">主力</span>}
                {isPhysical ? (
                   <IdCard className="w-4 h-4 text-emerald-600" title={`实体卡: ${subscription.physicalCardName}`} />
                ) : hasEsim ? (
                   <Cpu className={`w-4 h-4 ${linkedChip ? 'text-indigo-500' : 'text-gray-400'}`} title={linkedChip ? `On: ${linkedChip.nickname}` : "eSIM"} />
                ) : null}
              </h3>
              <div className="flex items-center gap-1.5 text-gray-500 text-sm mt-0.5 font-mono">
                {subscription.phoneNumber ? <Phone className="w-3 h-3" /> : <Wifi className="w-3 h-3" />}
                <span>{displayPhone}</span>
                {numberTypeLabel && <span className="text-[10px] bg-gray-100 px-1 rounded text-gray-400">{subscription.numberType}</span>}
              </div>
            </div>
          </div>
          
          <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
            {/* 新增：一键打卡按钮。只要不是永久模式，就显示闪电按钮 */}
            {subscription.cycleType !== 'permanent' && (
               <button 
                  onClick={handleCheckIn}
                  className="p-1.5 text-amber-500 hover:text-white hover:bg-amber-500 rounded transition-colors shadow-sm border border-amber-200" 
                  title={`最后活跃: ${subscription.lastActiveDate || '无记录'}\n点击更新为今天并重新计算到期日`}
               >
                  <Zap className="w-4 h-4" fill="currentColor" />
               </button>
            )}
              <button 
      onClick={handleShare} 
      className="p-1.5 text-gray-400 hover:text-indigo-600 hover:bg-indigo-50 rounded transition-colors" 
      title="分享套餐 (二维码)"
    >
        <Share2 className="w-4 h-4" />
    </button>
            <button onClick={(e) => { e.stopPropagation(); onPorting(subscription); }} className="p-1.5 text-gray-400 hover:text-indigo-600 hover:bg-indigo-50 rounded" title="携号转网 (MNP)">
                <ArrowRightLeft className="w-4 h-4" />
            </button>
            <button onClick={(e) => { e.stopPropagation(); generateICS(subscription.nickname, subscription.phoneNumber || 'Data', nextRenewal, subscription.cost, subscription.currency); }} className="p-1.5 text-gray-400 hover:text-indigo-600 hover:bg-indigo-50 rounded" title="导出日历 (.ics)">
                <Download className="w-4 h-4" />
            </button>
            <button onClick={(e) => { e.stopPropagation(); onArchive(subscription.id, !!subscription.isArchived); }} className="p-1.5 text-gray-400 hover:text-indigo-600 hover:bg-indigo-50 rounded" title={subscription.isArchived ? "Unarchive" : "Archive"}>
               {subscription.isArchived ? <ArchiveRestore className="w-4 h-4" /> : <Archive className="w-4 h-4" />}
            </button>
            <button onClick={(e) => { e.stopPropagation(); onEdit(subscription); }} className="p-1.5 text-gray-400 hover:text-indigo-600 hover:bg-indigo-50 rounded"><Edit2 className="w-4 h-4" /></button>
            <button onClick={(e) => { e.stopPropagation(); onDelete(subscription.id); }} className="p-1.5 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded"><Trash2 className="w-4 h-4" /></button>
          </div>
        </div>
        
        <div className="flex gap-2 flex-wrap mb-2">
          {operatorLabel && (
            <span className="text-[10px] px-2 py-0.5 bg-indigo-50 text-indigo-700 rounded border border-indigo-100 truncate">{operatorLabel}</span>
          )}
          {subscription.adminDivision && (
            <span className="text-[10px] px-2 py-0.5 bg-orange-50 text-orange-700 rounded border border-orange-100 flex items-center gap-1">
              <MapPin className="w-3 h-3" /> {subscription.adminDivision}
            </span>
          )}
          {/* Balance Display */}
          {subscription.balance !== undefined && (
            <span className="text-[10px] px-2 py-0.5 bg-emerald-100 text-emerald-800 rounded border border-emerald-200 flex items-center gap-1 font-mono font-bold">
               <Wallet className="w-3 h-3" /> {subscription.balance} {subscription.balanceCurrency}
            </span>
          )}
        </div>

        <div className="grid grid-cols-2 gap-y-2 gap-x-4 text-sm mt-4">
           <div className="flex items-center justify-between col-span-2 sm:col-span-1">
              <span className="text-gray-500 flex items-center gap-1.5"><RefreshCw className="w-3.5 h-3.5" /> 费用</span>
              <span className="font-medium">{subscription.cost} <span className="text-xs text-gray-500">{subscription.currency}</span></span>
              {/* 新增周期类型文字说明 */}
            <span className="text-[9px] text-gray-400">
                / {subscription.cycleType === 'monthly' ? '月' : subscription.cycleType === 'annual' ? '年' : subscription.cycleType === 'permanent' ? '永久' : `${subscription.cycleDays}天`}
            </span>
           </div>
           <div className="flex items-center justify-between col-span-2 sm:col-span-1">
              <span className="text-gray-500 flex items-center gap-1.5"><Calendar className="w-3.5 h-3.5" /> 到期</span>
              <span className={`font-medium ${daysRemaining <= threshold && daysRemaining > 0 ? 'text-red-600' : 'text-gray-800'}`}>{formatDate(nextRenewal)}</span>
           </div>
        </div>

        <div className="mt-3 flex flex-col gap-2">
            {/* Card Info */}
            {(subscription.debitCreditCard || (subscription.bankCard && subscription.bankCard.type !== 'Local_Bank')) && (
                <div className="flex flex-col gap-1 text-xs text-gray-600 bg-gray-50 p-2 rounded border border-gray-100 w-full">
                    <div className="flex items-center justify-between">
                        <div className="flex items-center gap-1.5">
                            <CreditCard className="w-3.5 h-3.5 text-gray-400" />
                            <span className="font-medium text-gray-800">{subscription.debitCreditCard?.type || subscription.bankCard?.type}</span>
                            <span>•</span>
                            <span className="font-mono text-gray-700">{subscription.debitCreditCard?.bankName || subscription.bankCard?.bankName}</span>
                        </div>
                        {subscription.debitCreditCard?.isVirtual && <span className="bg-purple-100 text-purple-600 px-1.5 rounded-[3px] text-[9px] border border-purple-200">Virtual</span>}
                    </div>
                    <div className="flex items-center gap-2 mt-1 pl-5 text-gray-500">
                        <span className="font-mono">{isDemoMode ? '**** **** **** ****' : (subscription.debitCreditCard?.cardNumber || subscription.bankCard?.cardNumber)}</span>
                    </div>
                    {(subscription.debitCreditCard?.remarks || (subscription.bankCard && subscription.bankCard.type !== 'Local_Bank' && subscription.bankCard.remarks)) && !isDemoMode && (
                        <div className="mt-1 pl-5 text-[10px] text-gray-400 italic truncate border-t border-gray-100 pt-1">
                            {subscription.debitCreditCard?.remarks || subscription.bankCard?.remarks}
                        </div>
                    )}
                </div>
            )}

            {/* Bank Account Info */}
            {(subscription.bankAccount || (subscription.bankCard && subscription.bankCard.type === 'Local_Bank')) && (
                <div className="flex flex-col gap-1 text-xs text-gray-600 bg-blue-50/30 p-2 rounded border border-blue-100 w-full">
                    <div className="flex items-center justify-between">
                        <div className="flex items-center gap-1.5">
                            <Landmark className="w-3.5 h-3.5 text-blue-500" />
                            <span className="font-medium text-gray-800">Account</span>
                            <span>•</span>
                            <span className="font-mono text-gray-700">{subscription.bankAccount?.bankName || subscription.bankCard?.bankName}</span>
                        </div>
                        {subscription.bankAccount?.regionCode && <span className="bg-blue-100 text-blue-600 px-1.5 rounded-[3px] text-[9px] border border-blue-200">{subscription.bankAccount.regionCode}</span>}
                    </div>
                    <div className="flex items-center gap-2 mt-1 pl-5 text-gray-500">
                        <span className="font-mono">{isDemoMode ? '********' : (subscription.bankAccount?.accountNumber || subscription.bankCard?.cardNumber)}</span>
                    </div>
                    {(subscription.bankAccount?.remarks || (subscription.bankCard && subscription.bankCard.type === 'Local_Bank' && subscription.bankCard.remarks)) && !isDemoMode && (
                        <div className="mt-1 pl-5 text-[10px] text-gray-400 italic truncate border-t border-blue-100 pt-1">
                            {subscription.bankAccount?.remarks || subscription.bankCard?.remarks}
                        </div>
                    )}
                </div>
            )}
        </div>

        {/* Data Plans Display */}
        {dataPlans.length > 0 && (
          <div className="mt-4 pt-3 border-t border-gray-50 space-y-3">
             {dataPlans.map((plan, idx) => (
                <div key={idx}>
                   <div className="flex justify-between text-xs mb-1">
                     <span className="text-gray-500 flex items-center gap-1">
                        {plan.regionNote || '数据流量'}
                        {plan.isPayg && (
                           <span className="text-[9px] px-1 bg-amber-100 text-amber-700 rounded border border-amber-200" title={`费率: ${plan.paygCostPerUnit || 0} / ${plan.unit}`}>PAYG</span>
                        )}
                     </span>
                     <div className="text-right">
                        <span className="font-medium text-gray-700">{plan.usedVal} / {plan.totalVal} {plan.displayUnit}</span>
                     </div>
                   </div>
                   <div className="w-full bg-gray-100 rounded-full h-1.5 overflow-hidden shadow-inner">
                     <div className={`h-full rounded-full transition-all duration-500 ${getDataColor(plan.usedVal, plan.totalVal, plan.isPayg)}`} style={{ width: `${Math.min((plan.usedVal / plan.totalVal) * 100, 100)}%` }} />
                   </div>
                   {renderSpeedInfo(plan)}
                </div>
             ))}
          </div>
        )}

        <div className="mt-4 flex items-center justify-between">
          <div className="flex gap-2">
             {isPhysical && <span className="text-[10px] px-2 py-0.5 bg-emerald-50 text-emerald-700 rounded border border-emerald-200 truncate max-w-[100px]">{subscription.physicalCardName}</span>}
             {kycLabel && <span className="text-[10px] px-2 py-0.5 bg-gray-100 text-gray-500 rounded border border-gray-200">{kycLabel}</span>}
             {subscription.isArchived && <span className="text-[10px] px-2 py-0.5 bg-gray-200 text-gray-600 rounded border border-gray-300">已归档</span>}
          </div>
          <div className={`px-3 py-1 rounded-full text-xs font-bold border ${statusColor} transition-colors`}>
            {statusText}
          </div>
        </div>
        
        {expanded && (
           <div className="mt-4 pt-4 border-t border-gray-100 text-xs text-gray-600 space-y-2 animate-fade-in">
              {/* Cost Prediction Module */}
              <div className="mb-3 bg-gradient-to-r from-indigo-50 to-blue-50 p-3 rounded-lg border border-indigo-100">
                <h4 className="font-bold text-indigo-800 mb-1 flex items-center gap-1">
                   <TrendingUp className="w-3 h-3" /> 费用预测 (估算)
                </h4>
                <div className="grid grid-cols-3 gap-2 text-center">
                   <div>
                     <span className="block text-gray-500 text-[10px]">30天</span>
                     <span className="font-mono font-medium text-gray-800">{calculateProjectedCost(subscription.cost, subscription.cycleDays, 30).toFixed(1)} <span className="text-[9px]">{subscription.currency}</span></span>
                   </div>
                   <div className="border-l border-indigo-200">
                     <span className="block text-gray-500 text-[10px]">90天</span>
                     <span className="font-mono font-medium text-gray-800">{calculateProjectedCost(subscription.cost, subscription.cycleDays, 90).toFixed(1)}</span>
                   </div>
                   <div className="border-l border-indigo-200">
                     <span className="block text-gray-500 text-[10px]">180天</span>
                     <span className="font-mono font-medium text-gray-800">{calculateProjectedCost(subscription.cost, subscription.cycleDays, 180).toFixed(1)}</span>
                   </div>
                </div>
              </div>

              {subscription.paymentMethodNote && (
                 <div className="mb-2 bg-yellow-50 p-2 rounded border border-yellow-100 text-yellow-800">
                    <strong className="block mb-1 flex items-center gap-1"><StickyNote className="w-3 h-3"/> 支付备注:</strong>
                    <p className="whitespace-pre-wrap">{isDemoMode ? '**********' : subscription.paymentMethodNote}</p>
                 </div>
              )}

              {(subscription.virtualNumbers?.length ?? 0) > 0 && (
                <div className="mb-2">
                   <strong className="block text-gray-800 mb-1 flex items-center gap-1"><Hash className="w-3 h-3"/> 虚拟/副号码:</strong>
                   <div className="space-y-1">
                     {subscription.virtualNumbers?.map(vn => (
                       <div key={vn.id} className="bg-gray-50 p-1.5 rounded flex justify-between items-center border border-gray-100">
                         <div className="flex items-center gap-2">
                            <span className="font-mono text-gray-800">{isDemoMode ? '****' : vn.number}</span>
                            <span className="text-[9px] bg-white border px-1 rounded text-gray-500">{vn.type}</span>
                         </div>
                         {vn.note && <span className="text-gray-400 italic">{vn.note}</span>}
                       </div>
                     ))}
                   </div>
                </div>
              )}
              
              {(subscription.simPin || subscription.simPuk) && (
  <div className="mt-2 flex gap-3">
    {subscription.simPin && (
      <div className="bg-gray-50 px-2 py-1 rounded border border-gray-100">
        <span className="text-[9px] text-gray-400 block uppercase font-bold">PIN</span>
        <span className="font-mono text-xs font-bold text-gray-700">
          {isDemoMode ? '****' : subscription.simPin}
        </span>
      </div>
    )}
    {subscription.simPuk && (
      <div className="bg-gray-50 px-2 py-1 rounded border border-gray-100">
        <span className="text-[9px] text-gray-400 block uppercase font-bold">PUK</span>
        <span className="font-mono text-xs font-bold text-gray-700">
          {isDemoMode ? '********' : subscription.simPuk}
        </span>
      </div>
    )}
  </div>
)}
           
              {(subscription.scenarios?.length ?? 0) > 0 && (
                <div>
                   <strong className="block text-gray-800 mb-1">场景:</strong>
                   <div className="flex flex-wrap gap-1">
                      {subscription.scenarios?.map(s => (
                        <span key={s.id} className="bg-blue-50 text-blue-700 px-1.5 py-0.5 rounded border border-blue-100 flex items-center gap-1">
                          {getFlagFromPhoneNumber(undefined, s.regionCode)} {s.note}
                        </span>
                      ))}
                   </div>
                </div>
              )}
              {isPhysical ? (
                 <div className="mt-2">
                    <strong className="block text-gray-800 mb-1 flex items-center gap-1"><IdCard className="w-3 h-3"/> 实体卡信息:</strong>
                    <div className="bg-gray-50 p-2 rounded text-gray-600 font-mono text-[10px]">
                       <p>{subscription.physicalCardName}</p>
                    </div>
                 </div>
              ) : hasEsim && (
                 <div className="mt-2">
                    <strong className="block text-gray-800 mb-1 flex items-center gap-1"><Cpu className="w-3 h-3"/> eSIM 信息:</strong>
                    <div className="bg-gray-50 p-2 rounded text-gray-600 grid grid-cols-1 gap-1 font-mono text-[10px] break-all">
                        {linkedChip ? (
                           <>
                             <p><span className="font-bold text-gray-500">Chip:</span> {linkedChip.nickname} ({linkedChip.type})</p>
                             <p><span className="font-bold text-gray-500">EID:</span> {isDemoMode ? '89*************' : linkedChip.eid}</p>
                           </>
                        ) : (
                           <p><span className="font-bold text-gray-500">EID:</span> {isDemoMode ? '89*************' : subscription.eSim?.eid}</p>
                        )}
                        {subscription.eSim?.profileSize && <p><span className="font-bold text-gray-500">Size:</span> {subscription.eSim.profileSize}</p>}
                        
                        {subscription.isEsimTransferSupported && (
                             <div className="mt-1 pt-1 border-t border-gray-200">
                                <span className="flex items-center gap-1 text-indigo-600 font-bold"><RotateCw className="w-3 h-3"/> 转移策略:</span>
                                <p className="ml-4 text-gray-500">{subscription.esimTransferMethod || '未知'}</p>
                             </div>
                        )}
                    </div>
                 </div>
              )}
              {subscription.keepAliveNote && (
                <div>
                  <strong className="block text-gray-800 mb-1">保号策略 / 备注:</strong>
                  <p className="bg-gray-50 p-2 rounded text-gray-500 whitespace-pre-wrap">{subscription.keepAliveNote}</p>
                </div>
              )}
           </div>
        )}
      </div>
      
      <button onClick={(e) => { e.stopPropagation(); setExpanded(!expanded); }} className="absolute bottom-0 left-0 right-0 h-4 flex items-center justify-center text-gray-300 hover:text-gray-500 hover:bg-gray-50 rounded-b-xl transition-colors">
        {expanded ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
      </button>
    </div>
  );
};

export default SubscriptionCard;

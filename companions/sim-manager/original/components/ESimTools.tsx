import React, { useState, useEffect } from 'react';
import { QrCode, HardDrive, AlertCircle, X } from 'lucide-react';
import QRCode from 'qrcode';
import { generateLPAString } from '../utils/helpers';

const ESimTools: React.FC = () => {
  const [activeTab, setActiveTab] = useState<'lpa' | 'storage'>('lpa');

  // LPA State
  const [smdp, setSmdp] = useState('');
  const [activationCode, setActivationCode] = useState('');
  const [lpaString, setLpaString] = useState('');
  const [qrDataUrl, setQrDataUrl] = useState('');

  // Storage State
  const [totalStorage, setTotalStorage] = useState(150); // e.g., 5ber standard approx
  const [profiles, setProfiles] = useState<{size: number}[]>([{size: 20}]);
  
  useEffect(() => {
     if (smdp && activationCode) {
        const lpa = generateLPAString(smdp.trim(), activationCode.trim());
        setLpaString(lpa);
        QRCode.toDataURL(lpa)
           .then(url => setQrDataUrl(url))
           .catch(err => console.error(err));
     } else {
        setLpaString('');
        setQrDataUrl('');
     }
  }, [smdp, activationCode]);

  const usedStorage = profiles.reduce((sum, p) => sum + p.size, 0);
  const freeStorage = totalStorage - usedStorage;

  return (
    <div className="h-full flex flex-col">
       <div className="flex border-b border-gray-200 mb-4">
          <button 
            onClick={() => setActiveTab('lpa')}
            className={`flex-1 py-2 text-sm font-medium ${activeTab === 'lpa' ? 'text-indigo-600 border-b-2 border-indigo-600' : 'text-gray-500 hover:text-gray-700'}`}
          >
            <div className="flex items-center justify-center gap-2"><QrCode className="w-4 h-4"/> LPA 生成器</div>
          </button>
          <button 
            onClick={() => setActiveTab('storage')}
            className={`flex-1 py-2 text-sm font-medium ${activeTab === 'storage' ? 'text-indigo-600 border-b-2 border-indigo-600' : 'text-gray-500 hover:text-gray-700'}`}
          >
            <div className="flex items-center justify-center gap-2"><HardDrive className="w-4 h-4"/> 容量计算器</div>
          </button>
       </div>

       <div className="flex-1 overflow-y-auto">
          {activeTab === 'lpa' && (
             <div className="space-y-4 px-1">
                <div className="bg-blue-50 p-3 rounded-lg border border-blue-100 text-xs text-blue-800 flex gap-2">
                   <AlertCircle className="w-4 h-4 flex-shrink-0" />
                   <p>输入运营商提供的 SM-DP+ 地址和激活码，生成二维码以便扫描激活。</p>
                </div>
                <div>
                   <label className="block text-xs font-bold text-gray-700 mb-1">SM-DP+ Address</label>
                   <input 
                      type="text" 
                      value={smdp} 
                      onChange={(e) => setSmdp(e.target.value)} 
                      className="w-full px-3 py-2 border rounded-lg text-sm font-mono"
                      placeholder="rsp.truphone.com"
                   />
                </div>
                <div>
                   <label className="block text-xs font-bold text-gray-700 mb-1">Activation Code</label>
                   <input 
                      type="text" 
                      value={activationCode} 
                      onChange={(e) => setActivationCode(e.target.value)} 
                      className="w-full px-3 py-2 border rounded-lg text-sm font-mono"
                      placeholder="AD-1234-5678..."
                   />
                </div>
                
                {lpaString && (
                   <div className="mt-4 p-4 bg-gray-50 rounded-lg flex flex-col items-center border border-gray-200 animate-fade-in">
                      <img src={qrDataUrl} alt="eSIM QR Code" className="w-48 h-48 bg-white p-2 border" />
                      <div className="mt-3 w-full">
                         <label className="text-xs text-gray-500 block text-center mb-1">LPA String</label>
                         <input type="text" readOnly value={lpaString} className="w-full text-[10px] text-center bg-transparent border-none focus:ring-0 text-gray-600 font-mono" />
                      </div>
                   </div>
                )}
             </div>
          )}

          {activeTab === 'storage' && (
             <div className="space-y-4 px-1">
                <div className="bg-amber-50 p-3 rounded-lg border border-amber-100 text-xs text-amber-800 flex gap-2">
                   <AlertCircle className="w-4 h-4 flex-shrink-0" />
                   <p>估算 5ber / Estk / RedteaGo 等可写卡还能存多少 Profile。</p>
                </div>
                
                <div className="flex items-center gap-2">
                   <label className="text-xs font-bold text-gray-700 w-24">总容量 (KB)</label>
                   <input 
                      type="number" 
                      value={totalStorage} 
                      onChange={(e) => setTotalStorage(Number(e.target.value))} 
                      className="flex-1 px-3 py-1 border rounded text-sm"
                   />
                </div>

                <div className="space-y-2">
                   <label className="block text-xs font-bold text-gray-700">已安装 Profiles (估算大小)</label>
                   {profiles.map((p, i) => (
                      <div key={i} className="flex gap-2 items-center">
                         <span className="text-xs w-6 text-gray-500">#{i+1}</span>
                         <input 
                           type="range" 
                           min="5" max="200" step="5" 
                           value={p.size} 
                           onChange={(e) => {
                              const newProfiles = [...profiles];
                              newProfiles[i].size = Number(e.target.value);
                              setProfiles(newProfiles);
                           }} 
                           className="flex-1"
                         />
                         <span className="text-xs w-12 text-right">{p.size} KB</span>
                         <button onClick={() => setProfiles(profiles.filter((_, idx) => idx !== i))} className="text-red-500 hover:bg-red-50 p-1 rounded"><X className="w-3 h-3"/></button>
                      </div>
                   ))}
                   <button 
                      onClick={() => setProfiles([...profiles, {size: 20}])}
                      className="w-full py-2 border border-dashed border-gray-300 rounded text-xs text-gray-500 hover:text-indigo-600 hover:border-indigo-300"
                   >
                      + 添加 Profile
                   </button>
                </div>

                <div className="mt-4 pt-4 border-t border-gray-100">
                   <div className="flex justify-between items-end mb-2">
                      <span className="text-sm font-bold text-gray-700">Storage Usage</span>
                      <span className={`text-sm font-mono ${freeStorage < 0 ? 'text-red-600 font-bold' : 'text-gray-600'}`}>
                         {usedStorage} / {totalStorage} KB
                      </span>
                   </div>
                   <div className="w-full bg-gray-200 rounded-full h-3 overflow-hidden">
                      <div 
                         className={`h-full transition-all ${freeStorage < 0 ? 'bg-red-500' : usedStorage/totalStorage > 0.9 ? 'bg-amber-500' : 'bg-emerald-500'}`} 
                         style={{ width: `${Math.min((usedStorage / totalStorage) * 100, 100)}%` }} 
                      />
                   </div>
                   <p className="text-right text-xs text-gray-500 mt-1">
                      剩余: {freeStorage} KB ({freeStorage < 0 ? '溢出!' : `约 ${Math.floor(freeStorage/20)} 个常规Profile`})
                   </p>
                </div>
             </div>
          )}
       </div>
    </div>
  );
};

export default ESimTools;
import React, { useState, useEffect } from 'react';
import { Lock, Unlock, Loader2, ShieldCheck, Fingerprint } from 'lucide-react';
import { securityHelper, webAuthnHelper } from '../utils/helpers';
import { SecuritySettings } from '../types';

interface LockScreenProps {
  correctPinHash?: string; // 存储在本地的 SHA-256 字符串
  securitySettings?: SecuritySettings; // 包含生物识别信息的配置对象
  onUnlock: () => void;
  onLog: (msg: string) => void;
}

const LockScreen: React.FC<LockScreenProps> = ({ correctPinHash, onUnlock, securitySettings }) => {
  const [pin, setPin] = useState('');
  const [error, setError] = useState(false); // PIN 错误状态
  const [verifying, setVerifying] = useState(false); // 正在计算 Hash
  const [bioError, setBioError] = useState(false); // 生物识别失败状态

  // 1. 页面挂载时自动聚焦并尝试触发一次生物识别
  useEffect(() => {
    const input = document.getElementById('lock-pin-input');
    if (input) input.focus();

    if (securitySettings?.biometricEnabled && securitySettings.webauthnId) {
        // 延迟 500ms 触发，给浏览器渲染弹窗的时间，防止某些浏览器冲突
        setTimeout(() => {
            handleBiometricUnlock();
        }, 500);
    }
  }, []);

  // 2. 处理生物识别解锁
  const handleBiometricUnlock = async () => {
    if (!securitySettings?.webauthnId) return;
    onLog("🔑 发起生物识别/FIDO2 挑战请求...");
    
    try {
        const success = await webAuthnHelper.authenticate(securitySettings.webauthnId);
        if (success) {
            onLog("✅ 生物识别验证通过")
            onUnlock();
        }
    } catch (e) {
        console.error("Biometric authentication failed", e);
        onLog(`⚠️ 生物识别尝试未成功或取消`);
        setBioError(true);
        // 2秒后重置图标颜色
        setTimeout(() => setBioError(false), 2000);
    }
  };

  // 3. 处理 PIN 码解锁（哈希比对）
  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!correctPinHash) {
        onUnlock(); 
        return;
    }

    setVerifying(true);
    try {
      // 计算输入 PIN 的哈希值
      const inputHash = await securityHelper.hashPin(pin);
      
      if (inputHash === correctPinHash) {
        onUnlock();
      } else {
        throw new Error("Wrong PIN");
      }
    } catch (err) {
      setError(true);
      setPin('');
      // 触发震动动画后 500ms 重置状态
      setTimeout(() => setError(false), 500);
    } finally {
      setVerifying(false);
    }
  };

  return (
    <div className="fixed inset-0 z-[100] bg-gray-900 flex flex-col items-center justify-center p-4 animate-fade-in">
      {/* 背景动态模糊装饰 */}
      <div className="absolute inset-0 overflow-hidden pointer-events-none">
         <div className="absolute top-1/4 left-1/4 w-64 h-64 bg-indigo-500/20 rounded-full blur-3xl"></div>
         <div className="absolute bottom-1/4 right-1/4 w-64 h-64 bg-purple-500/20 rounded-full blur-3xl"></div>
      </div>

      <div className="bg-white/10 backdrop-blur-lg p-8 rounded-2xl shadow-2xl w-full max-w-sm border border-white/20 text-center relative z-10">
        <div className={`mb-6 mx-auto w-16 h-16 rounded-full flex items-center justify-center text-white transition-all duration-300 ${error ? 'bg-red-500/20 animate-shake' : 'bg-white/20'}`}>
          {verifying ? (
             <Loader2 className="w-8 h-8 animate-spin" />
          ) : error ? (
             <Lock className="w-8 h-8" />
          ) : (
             <ShieldCheck className="w-8 h-8" />
          )}
        </div>
        
        <h2 className="text-xl font-bold text-white mb-2">应用已锁定</h2>
        <p className="text-indigo-200 text-sm mb-6">请输入安全 PIN 码或使用生物识别访问。</p>
        
        <form onSubmit={handleSubmit}>
           <input 
              id="lock-pin-input"
              type="password" 
              value={pin}
              onChange={(e) => setPin(e.target.value)}
              className={`w-full text-center text-2xl tracking-[1em] py-3 rounded-xl bg-gray-800/50 border transition-all duration-300 font-mono mb-4 text-white placeholder-gray-600 focus:outline-none focus:ring-2 ${
                  error 
                  ? 'border-red-500 ring-red-500/50' 
                  : 'border-gray-600 focus:border-indigo-500 focus:ring-indigo-500/50'
              }`}
              placeholder="••••"
              maxLength={20}
              autoComplete="off"
              disabled={verifying}
           />
           
           <button 
             type="submit" 
             disabled={verifying || pin.length === 0}
             className="w-full py-3 bg-indigo-600 hover:bg-indigo-700 disabled:bg-indigo-600/50 disabled:cursor-not-allowed text-white font-bold rounded-xl transition-all active:scale-95 shadow-lg shadow-indigo-900/20"
           >
             {verifying ? '正在校验...' : '解锁'}
           </button>
        </form>

        {/* 生物识别按钮区域 */}
        {securitySettings?.biometricEnabled && (
            <div className="mt-6 flex flex-col items-center animate-fade-in">
                <div className="w-full flex items-center gap-3 mb-6">
                    <div className="h-px bg-gray-700 flex-1"></div>
                    <span className="text-[10px] text-gray-500 uppercase font-bold tracking-widest">或使用生物识别</span>
                    <div className="h-px bg-gray-700 flex-1"></div>
                </div>
                
                <button 
                    onClick={handleBiometricUnlock}
                    className={`p-4 rounded-full border-2 transition-all duration-300 shadow-lg group ${
                        bioError 
                        ? 'border-red-500 bg-red-500/10 text-red-500 animate-shake' 
                        : 'border-indigo-500/50 bg-indigo-500/10 text-indigo-400 hover:bg-indigo-600 hover:text-white hover:border-indigo-600'
                    }`}
                    title="点击开始生物识别扫描"
                >
                    <Fingerprint className="w-10 h-10 group-active:scale-90 transition-transform" />
                </button>
                <p className="text-[10px] text-gray-500 mt-3 uppercase tracking-tighter">
                   支持指纹 / 面容 / Yubikey
                </p>
            </div>
        )}

        <div className="mt-8 pt-6 border-t border-white/10">
            <p className="text-[10px] text-gray-500 flex items-center justify-center gap-1">
                <Lock className="w-3 h-3" />
                加密等级: SHA-256 (Hashed) & WebAuthn (FIDO2)
            </p>
        </div>
      </div>
    </div>
  );
};

export default LockScreen;
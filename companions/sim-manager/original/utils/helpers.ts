

import { PHONE_PREFIX_TO_FLAG } from '../constants';
import { Subscription, Transaction } from '../types';

export const shareUtils = {
  // 编码：处理 Unicode -> Base64
  encodeData: (data: any) => {
    const jsonStr = JSON.stringify(data);
    // 使用 encodeURIComponent 处理中文，再通过 btoa 转换
    return btoa(encodeURIComponent(jsonStr));
  },
  // 解码：处理 Base64 -> Unicode
  decodeData: (base64: string) => {
    try {
      const jsonStr = decodeURIComponent(atob(base64));
      return JSON.parse(jsonStr);
    } catch (e) {
      console.error("解码失败", e);
      return null;
    }
  }
};

export const webAuthnHelper = {
  // 检查浏览器是否支持生物识别
  isSupported: async () => {
    return (
      window.PublicKeyCredential &&
      PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable &&
      (await PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable())
    );
  },

  // 注册生物识别
  register: async (username: string) => {
    const challenge = crypto.getRandomValues(new Uint8Array(32));
    const userId = crypto.getRandomValues(new Uint8Array(16));

    const publicKeyCredentialCreationOptions: PublicKeyCredentialCreationOptions = {
      challenge,
      rp: { name: "全球通套餐管家", id: window.location.hostname },
      user: {
        id: userId,
        name: username,
        displayName: username,
      },
      pubKeyCredParams: [{ alg: -7, type: "public-key" }, { alg: -257, type: "public-key" }],
      authenticatorSelection: {
        userVerification: "preferred",
        residentKey: "preferred",
      },
      timeout: 60000,
      attestation: "none",
    };

    const credential = (await navigator.credentials.create({
      publicKey: publicKeyCredentialCreationOptions,
    })) as PublicKeyCredential;

    // 返回 Base64 编码的 ID 供存储
    return btoa(String.fromCharCode(...new Uint8Array(credential.rawId)));
  },

  // 验证生物识别
  authenticate: async (credentialIdBase64: string) => {
    const challenge = crypto.getRandomValues(new Uint8Array(32));
    const rawId = Uint8Array.from(atob(credentialIdBase64), (c) => c.charCodeAt(0));

    const publicKeyCredentialRequestOptions: PublicKeyCredentialRequestOptions = {
      challenge,
      allowCredentials: [{
        id: rawId,
        type: "public-key",
      }],
      userVerification: "required",
      timeout: 60000,
    };

    await navigator.credentials.get({
      publicKey: publicKeyCredentialRequestOptions,
    });
    
    return true; // 如果没有抛出错误，则验证通过
  },
};

export const ITU_ZONES: Record<number, string> = {
  1: '北美 (NANP)',
  2: '非洲 (Africa)',
  3: '欧洲 (Europe-3)',
  4: '欧洲 (Europe-4)',
  5: '中南美洲 (Americas)',
  6: '东南亚/大洋洲',
  7: '俄罗斯/独联体',
  8: '东亚/特殊',
  9: '中东/西亚/南亚'
};

export const getITUZone = (countryCode?: string): number | null => {
  if (!countryCode) return null;
  // Handle case where user input might include spaces or dashes, or starts with +
  const clean = countryCode.replace(/^\+/, '').trim();
  if (!clean) return null;
  
  const firstDigit = parseInt(clean[0]);
  if (!isNaN(firstDigit) && firstDigit >= 1 && firstDigit <= 9) {
    return firstDigit;
  }
  return null;
};

export const getFlagFromPhoneNumber = (phoneNumber?: string, countryCode?: string): string => {
  if (phoneNumber) {
    // Sort keys by length descending to match longest prefix first
    const sortedPrefixes = Object.keys(PHONE_PREFIX_TO_FLAG).sort((a, b) => b.length - a.length);
    
    // Clean the number (remove spaces, dashes)
    const cleanNumber = phoneNumber.replace(/[\s-]/g, '');

    for (const prefix of sortedPrefixes) {
      if (cleanNumber.startsWith(prefix)) {
        return PHONE_PREFIX_TO_FLAG[prefix];
      }
    }
  }
  
  // Fallback to manual country code if phone matches nothing or is empty
  if (countryCode) {
    const cleanCode = countryCode.startsWith('+') ? countryCode : `+${countryCode}`;
    if (PHONE_PREFIX_TO_FLAG[cleanCode]) {
      return PHONE_PREFIX_TO_FLAG[cleanCode];
    }
  }

  return '🌐'; // Unknown
};

// Formats +86138... to "+86 138..."
// If isDemoMode is true, masks the number: "+86 ****"
export const formatPhoneNumberDisplay = (phoneNumber?: string, isDemoMode: boolean = false): string => {
  if (!phoneNumber) return '纯流量 / 无号码';
  
  const cleanNumber = phoneNumber.replace(/[\s-]/g, '');
  const sortedPrefixes = Object.keys(PHONE_PREFIX_TO_FLAG).sort((a, b) => b.length - a.length);

  for (const prefix of sortedPrefixes) {
    if (cleanNumber.startsWith(prefix)) {
      if (isDemoMode) {
          return `${prefix} ****`;
      }
      const rest = cleanNumber.slice(prefix.length);
      return `${prefix} ${rest}`;
    }
  }
  
  // If no prefix matched
  if (isDemoMode) return '****';
  return phoneNumber;
};

export const calculateNextRenewal = (
  startDateStr: string, 
  cycleDays: number, 
  cycleType: string = 'daily',
  lastActiveDateStr?: string 
): Date => {
  if (cycleType === 'permanent') return new Date('2099-12-31');

  const today = new Date();
  today.setHours(0, 0, 0, 0);

  // 这里的 baseDate 是计算的起点
  let nextDate = new Date(lastActiveDateStr || startDateStr);
  nextDate.setHours(0, 0, 0, 0);

  // 如果是活跃延期或手动打卡，先加一个周期
  if (lastActiveDateStr || cycleType === 'activity_based') {
     nextDate = getNextCycleDate(nextDate, cycleDays, cycleType);
  }

  // 重要：如果加完一个周期还是在今天之前（比如欠费很久了），
  // 则继续累加直到未来的某个续费日
  if (cycleType !== 'permanent') {
    // 防止死循环
    const safeDays = cycleDays <= 0 ? 30 : cycleDays; 
    let limit = 0;
    while (nextDate.getTime() <= today.getTime() && limit < 120) {
      nextDate = getNextCycleDate(nextDate, safeDays, cycleType);
      limit++;
    }
  }
  
  return nextDate;
};

const getNextCycleDate = (current: Date, days: number, type: string): Date => {
  const next = new Date(current);
  if (type === 'monthly') {
    next.setMonth(next.getMonth() + 1);
  } else if (type === 'annual') {
    next.setFullYear(next.getFullYear() + 1);
  } else {
    // Default or Daily
    next.setDate(next.getDate() + (days || 30));
  }
  return next;
};

export const formatDate = (date: Date): string => {
  return date.toLocaleDateString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' });
};

export const getDaysRemaining = (renewalDate: Date): number => {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  renewalDate.setHours(0, 0, 0, 0);
  
  const diffTime = renewalDate.getTime() - today.getTime();
  return Math.ceil(diffTime / (1000 * 60 * 60 * 24));
};

export const calculateProjectedCost = (cost: number, cycleDays: number, daysToProject: number): number => {
  if (cycleDays <= 0) return 0;
  // Cost per day * projection days
  return (cost / cycleDays) * daysToProject;
};

export const generateICS = (nickname: string, phoneNumber: string, renewalDate: Date, cost: number, currency: string) => {
  const dateStr = renewalDate.toISOString().replace(/-|:|\.\d\d\d/g, "").slice(0, 8); // YYYYMMDD
  
  const icsContent = [
    'BEGIN:VCALENDAR',
    'VERSION:2.0',
    'PRODID:-//SimManager//CN',
    'BEGIN:VEVENT',
    `UID:${crypto.randomUUID()}@simmanager`,
    `DTSTAMP:${new Date().toISOString().replace(/-|:|\.\d\d\d/g, "")}`,
    `DTSTART;VALUE=DATE:${dateStr}`,
    `SUMMARY:📅 续费: ${nickname}`,
    `DESCRIPTION:号码: ${phoneNumber}\\n费用: ${cost} ${currency}\\n请及时充值或检查自动扣款。`,
    'BEGIN:VALARM',
    'TRIGGER:-P1D',
    'ACTION:DISPLAY',
    'DESCRIPTION:Reminder',
    'END:VALARM',
    'END:VEVENT',
    'END:VCALENDAR'
  ].join('\r\n');

  const blob = new Blob([icsContent], { type: 'text/calendar;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `renewal_${nickname}_${dateStr}.ics`;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
};

export const generateBatchICS = (subscriptions: Subscription[]) => {
  if (subscriptions.length === 0) {
    alert('没有可导出的活跃套餐。');
    return;
  }

  const events = subscriptions.filter(s => !s.isArchived).map(sub => {
    const renewalDate = calculateNextRenewal(sub.startDate, sub.cycleDays);
    const dateStr = renewalDate.toISOString().replace(/-|:|\.\d\d\d/g, "").slice(0, 8);
    const phone = sub.phoneNumber || 'Data/Sim';
    
    return [
      'BEGIN:VEVENT',
      `UID:${sub.id}@simmanager`,
      `DTSTAMP:${new Date().toISOString().replace(/-|:|\.\d\d\d/g, "")}`,
      `DTSTART;VALUE=DATE:${dateStr}`,
      `SUMMARY:📅 续费: ${sub.nickname}`,
      `DESCRIPTION:号码: ${phone}\\n费用: ${sub.cost} ${sub.currency}\\n请检查状态。`,
      'BEGIN:VALARM',
      'TRIGGER:-P1D',
      'ACTION:DISPLAY',
      'DESCRIPTION:Reminder',
      'END:VALARM',
      'END:VEVENT'
    ].join('\r\n');
  }).join('\r\n');

  const icsContent = [
    'BEGIN:VCALENDAR',
    'VERSION:2.0',
    'PRODID:-//SimManager//CN',
    `X-WR-CALNAME:套餐续费日历`,
    events,
    'END:VCALENDAR'
  ].join('\r\n');

  const blob = new Blob([icsContent], { type: 'text/calendar;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `sim_renewals_batch_${new Date().toISOString().slice(0, 10)}.ics`;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
};

// --- v4 Helpers ---

// WebDAV Client (Basic Auth)
export const webdavClient = {
    async put(url: string, username: string, pass: string, data: string) {
        const headers = new Headers();
        headers.set('Authorization', 'Basic ' + btoa(username + ":" + pass));
        headers.set('Content-Type', 'application/json');
        
        const response = await fetch(url, {
            method: 'PUT',
            headers: headers,
            body: data
        });
        
        if (!response.ok) throw new Error(`WebDAV Upload Failed: ${response.statusText}`);
        return response;
    },
    
    async get(url: string, username: string, pass: string) {
        const headers = new Headers();
        headers.set('Authorization', 'Basic ' + btoa(username + ":" + pass));
        
        const response = await fetch(url, {
            method: 'GET',
            headers: headers
        });

        if (!response.ok) throw new Error(`WebDAV Download Failed: ${response.statusText}`);
        return await response.text();
    }
};

export const securityHelper = {
  // Hash PIN using SHA-256
  async hashPin(pin: string): Promise<string> {
    const encoder = new TextEncoder();
    const data = encoder.encode(pin);
    const hashBuffer = await crypto.subtle.digest('SHA-256', data);
    const hashArray = Array.from(new Uint8Array(hashBuffer));
    return hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
  }
};


// Simple Crypto for E2EE (Using Web Crypto API)
// For simplicity in this demo, we use a basic key derivation and AES-GCM
// In production, use a library like 'crypto-js' or robust WebCrypto implementation
export const cryptoHelper = {
    async encrypt(text: string, password: string): Promise<string> {
        const enc = new TextEncoder();
        const salt = crypto.getRandomValues(new Uint8Array(16));
        const iv = crypto.getRandomValues(new Uint8Array(12));
        
        const keyMaterial = await crypto.subtle.importKey(
            "raw", enc.encode(password), { name: "PBKDF2" }, false, ["deriveKey"]
        );
        
        const key = await crypto.subtle.deriveKey(
            { name: "PBKDF2", salt, iterations: 100000, hash: "SHA-256" },
            keyMaterial, { name: "AES-GCM", length: 256 }, false, ["encrypt"]
        );
        
        const encrypted = await crypto.subtle.encrypt(
            { name: "AES-GCM", iv }, key, enc.encode(text)
        );
        
        // Pack: salt + iv + ciphertext
        const buffer = new Uint8Array(salt.byteLength + iv.byteLength + encrypted.byteLength);
        buffer.set(salt, 0);
        buffer.set(iv, salt.byteLength);
        buffer.set(new Uint8Array(encrypted), salt.byteLength + iv.byteLength);
        
        return btoa(String.fromCharCode(...buffer));
    },

    async decrypt(ciphertext: string, password: string): Promise<string> {
        const enc = new TextEncoder();
        const binaryStr = atob(ciphertext);
        const bytes = new Uint8Array(binaryStr.length);
        for(let i=0; i<binaryStr.length; i++) bytes[i] = binaryStr.charCodeAt(i);
        
        const salt = bytes.slice(0, 16);
        const iv = bytes.slice(16, 28);
        const data = bytes.slice(28);
        
        const keyMaterial = await crypto.subtle.importKey(
            "raw", enc.encode(password), { name: "PBKDF2" }, false, ["deriveKey"]
        );
        
        const key = await crypto.subtle.deriveKey(
            { name: "PBKDF2", salt, iterations: 100000, hash: "SHA-256" },
            keyMaterial, { name: "AES-GCM", length: 256 }, false, ["decrypt"]
        );
        
        const decrypted = await crypto.subtle.decrypt(
            { name: "AES-GCM", iv }, key, data
        );
        
        return new TextDecoder().decode(decrypted);
    }
};

export const convertCurrency = (amount: number, from: string, to: string, rates: Record<string, number>): number => {
    if (from === to) return amount;
    // Base is 1.0. All rates are relative to base.
    // Amount in Base = Amount / Rate(From)
    // Amount in To = Amount in Base * Rate(To)
    const rateFrom = rates[from] || 1; // Default to 1 if missing (bad)
    const rateTo = rates[to] || 1;
    
    return (amount / rateFrom) * rateTo;
};

// LPA:1$SM-DP+$ActivationCode
export const generateLPAString = (smdp: string, activationCode: string): string => {
   return `LPA:1$${smdp}$${activationCode}`;
};

// --- CSV ---
export const generateCSV = (subscriptions: Subscription[]) => {
  const headers = ['昵称', '号码', '运营商', '类型', '费用', 'PIN', 'PUK', '货币', '到期日', '备注'];
  const rows = subscriptions.map(sub => {
    const renewal = calculateNextRenewal(sub.startDate, sub.cycleDays, sub.cycleType);
    return [
      `"${sub.nickname}"`,
      `"${sub.phoneNumber || ''}"`,
      `"${sub.operatorType}"`,
      `"${sub.simType}"`,
      `"${sub.simPin || ''}"`,
      `"${sub.simPuk || ''}"`,
      sub.cost,
      sub.currency,
      renewal.toISOString().slice(0, 10),
      `"${sub.keepAliveNote?.replace(/\n/g, ' ') || ''}"`
    ].join(',');
  });
  
  const csvContent = "\uFEFF" + [headers.join(','), ...rows].join('\n'); // Add BOM for Excel
  const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `sim_manager_export_${new Date().toISOString().slice(0, 10)}.csv`;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
};

// --- Live Exchange Rates ---

export const fetchExchangeRates = async (apiKey: string, base: string): Promise<Record<string, number> | null> => {
  try {
    const res = await fetch(`https://v6.exchangerate-api.com/v6/${apiKey}/latest/${base}`);
    const data = await res.json();
    if (data.result === 'success') {
      return data.conversion_rates;
    }
    return null;
  } catch (e) {
    console.error("Failed to fetch rates", e);
    return null;
  }
};
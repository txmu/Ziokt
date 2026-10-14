

export type KycType = 
  | 'none' 
  | 'id_card' 
  | 'permit' 
  | 'passport_no_visa' 
  | 'passport_visa' 
  | 'mainland_agency' 
  | 'overseas_agency';

export type PaymentMethod = 
  | 'WeChat' | 'Alipay' | 'Octopus' | 'Visa' | 'Mastercard' 
  | 'AmEx' | 'JCB' | 'UnionPay' | 'USDT' | 'TON' | 'Crypto_Other' 
  | 'PayPal' | 'ApplePay' | 'GooglePay' | 'Discover' | 'DinersClub' 
  | 'Wise' | 'Revolut' | 'Payoneer' | 'Skrill' | 'Neteller' | 'WebMoney' 
  | 'PerfectMoney' | 'WeChatPayHK' | 'AlipayHK'
  | 'GCash' | 'GrabPay' | 'TouchNGo' | 'LinePay' | 'KakaoPay' 
  | 'PayNow' | 'FPS' | 'IBAN_SEPA' | 'Local_Bank' | 'Other';

export type OperatorType = 'MNO' | 'MVNO_Branded' | 'MVNO_Aggregator' | 'Roaming_Provider' | 'TopConnect' | 'Other';

export type NumberType = 'Mobile' | 'VoIP' | 'Landline' | 'Satellite';

export type CycleType = 'daily' | 'monthly' | 'annual' | 'permanent' | 'activity_based';

// Experimental Notification Trigger API Type Definition
declare global {
  interface NotificationOptions {
    showTrigger?: any; // TimestampTrigger
  }
}

export interface VirtualNumber {
  id: string;
  number: string;
  type: NumberType;
  note?: string;
}

export interface ScenarioFeatureSet {
  smsIn: boolean;
  smsOut: boolean;
  callIn: boolean;
  callOut: boolean;
  voicemail: boolean;
  data?: boolean; 
}

export type RoamingPrerequisite = 'none' | 'package_required' | 'balance_threshold';

export interface ScenarioMode {
  isAvailable: boolean;
  isActive: boolean;
  features: ScenarioFeatureSet;
  remark?: string;
  networkTypes?: string[]; 
  operators?: string[];
  
  // New Advanced Fields
  isHotspotSupported?: boolean; // Dependent on data=true
  roamLikeHome?: boolean; // Roaming only
  roamingPrerequisite?: RoamingPrerequisite; // Roaming only
  vowifiE911Required?: boolean; // VoWiFi only
}

export interface Scenario {
  id: string;
  regionCode: string; // E.164 prefix for flag
  phoneNumber?: string; 
  note: string;
  
  local?: ScenarioMode; // New Local Use scenario
  roaming?: ScenarioMode;
  vowifi?: ScenarioMode;
  
  // Legacy
  features?: string[]; 
}

export type SpeedUnit = 'kbps' | 'Mbps' | 'Gbps' | 'kB/s' | 'MB/s' | 'GB/s';

export interface DataUsage {
  id: string;
  total: number;
  used: number;
  unit: 'MB' | 'GB'; 
  regionNote: string;
  expiryDate: string;
  
  // PAYG / Long-term Balance Deduction
  isPayg?: boolean; 
  paygCostPerUnit?: number; // e.g., 10 (Currency depends on sub)
  
  // Advanced Speed Limits
  highSpeedQuota?: number; // Amount of high speed data (in same unit as total/used)
  throttledSpeed?: number; // Speed limit after high speed quota
  throttledSpeedUnit?: SpeedUnit;
  isThrottledUnlimited?: boolean; // If true, volume is unlimited after quota, only speed limited
  overallSpeedLimit?: number; // General cap
  overallSpeedLimitUnit?: SpeedUnit;

  // Legacy support
  totalGB?: number;
  usedGB?: number;
}

export interface ESimChip {
  id: string;
  eid: string;
  nickname: string;
  type: 'Native_Phone' | 'Adapter';
  adapterProtocol?: 'OMAPI' | 'ARA-M' | 'Other'; 
  remarks?: string;
  deviceChangeMethod?: string;
  deviceHistory?: string;
  isArchived?: boolean;
}

export interface ESimInfo {
  chipId?: string; 
  eid: string; 
  eiccid?: string;
  profileSize: string; 
}

// New Separate Payment Types
export interface DebitCreditCard {
  id: string;
  type: 'Visa' | 'Mastercard' | 'AmEx' | 'JCB' | 'UnionPay' | 'Other';
  bankName: string;
  cardNumber: string; 
  isVirtual?: boolean;
  remarks?: string;
}

export interface BankAccountDetails {
  id: string;
  bankName: string;
  accountNumber: string;
  regionCode?: string;
  iban?: string;
  identityType?: 'citizen' | 'non_citizen';
  remarks?: string;
}

// Legacy Interface kept for compatibility migration
export interface BankCard {
  id: string; 
  type: 'Visa' | 'Mastercard' | 'AmEx' | 'JCB' | 'UnionPay' | 'Local_Bank' | 'Other';
  bankName: string;
  cardNumber: string; 
  currency?: string;
  isVirtual?: boolean;
  remarks?: string;
  regionCode?: string; 
  iban?: string;
  identityType?: 'citizen' | 'non_citizen';
}

// v4 Transaction Interface
export interface Transaction {
  id: string;
  date: string;
  amount: number;
  currency: string;
  type: 'topup' | 'consumption' | 'fee';
  method?: string; // e.g. Alipay
  exchangeRate?: number; // Rate to base currency
  note?: string;
}

export interface Subscription {
  id: string;
  nickname: string;
  phoneNumber?: string; 
  countryCode?: string; 
  adminDivision?: string; // New: First-level Administrative Division (State/Province)
  
  operatorType?: OperatorType;
  numberType?: NumberType; 
  virtualNumbers?: VirtualNumber[];
  tags?: string[]; // Arbitrary filtering tags

  simType?: 'esim' | 'physical';
  physicalCardName?: string; 
  simPin?: string; // SIM卡本身的PIN码
  simPuk?: string; // SIM卡本身的PUK码
  
  startDate: string;
  lastActiveDate?: string; // 新增：专门记录最后一次插卡/连网/充值的时间
  cycleType?: CycleType; // Replace or augment cycleDays
  cost: number;
  currency: string;
  
  // Balance System
  balance?: number;
  balanceCurrency?: string;
  
  gracePeriod?: number; 
  
  kycType?: KycType;
  paymentMethods?: PaymentMethod[]; 
  
  // Independent Payment Sources
  debitCreditCard?: DebitCreditCard;
  bankAccount?: BankAccountDetails;
  
  // Legacy field
  bankCard?: BankCard; 

  paymentMethodNote?: string;
  website?: string; 
  topUpUrl?: string; // New: Deep link for Top Up
  
  scenarios?: Scenario[];
  
  dataPlans?: DataUsage[];
  dataUsage?: DataUsage; 
  
  eSim?: ESimInfo;
  
  // eSIM Transfer Config
  isEsimTransferSupported?: boolean;
  esimTransferMethod?: string;
  transferRescanLimit?: number | null; // New: For "Delete & Rescan" method

  keepAliveNote?: string;
  
  // v4: Transaction Log
  transactions?: Transaction[];

  notificationThreshold: number; 
  priority: number; 
  
  isArchived?: boolean;
}

export interface SavedScript {
  id: string;
  name: string;
  code: string;
  lastRun?: string;
}

export type ThemeType = 'default' | 'sakura' | 'snow' | 'geek' | 'matcha';

export type ChartType = 'pie' | 'bar' | 'line';

export interface ChartData {
  labels: string[];
  values: number[];
  seriesName?: string;
}

export interface ChartWidget {
  id: string;
  title: string;
  type: ChartType;
  data: ChartData;
  createdAt: string;
  isPinned?: boolean; // New PIN feature
}

export interface GlobalIO {
  input: string;
  output: string;
}

export interface NotificationSettings {
  enabled: boolean;
  useTriggers: boolean; // Experimental Notification Triggers API
  webhookUrl?: string; // Webhook support
  webhookEnabled?: boolean;
  soundEnabled?: boolean; // Sound
}

// v4 Settings Interfaces
export interface SecuritySettings {
    enabled: boolean;
    pinHash?: string; // SHA-256 Hash
    biometricEnabled?: boolean; // 是否启用生物识别
    webauthnId?: string;       // 存储凭证 ID，用于验证身份
}

export interface SyncSettings {
    webdavUrl?: string;
    username?: string;
    password?: string;
    lastSync?: string;
    encryptionPassword?: string; // New: Master password for E2EE
    isEncrypted?: boolean; // New
}

export interface CurrencySettings {
    baseCurrency: string;
    rates: Record<string, number>;
    apiKey?: string; // New: ExchangeRate-API Key
    lastUpdated?: string; // New
    autoUpdate?: boolean; // New
}

export interface AppData {
  version: number;
  appTitle?: string;
  theme?: ThemeType;
  isDemoMode?: boolean; // New: Demo / Screenshot Mode
  hasReadGuide?: boolean; 
  notificationSettings?: NotificationSettings; // New field
  
  // v4 New Global Settings
  securitySettings?: SecuritySettings;
  syncSettings?: SyncSettings;
  currencySettings?: CurrencySettings;

  subscriptions: Subscription[];
  eSimChips: ESimChip[];
  scripts: SavedScript[];
  chartWidgets?: ChartWidget[];
  globalIO?: GlobalIO; // Persist IO state
}

export interface Stats {
  totalMonthlyCost: number;
  activeCount: number;
  expiringSoonCount: number;
}

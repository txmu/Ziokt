

import React, { useState } from 'react';
import { X, Plus, Cpu, Edit2, Trash2, Archive, ArchiveRestore, AlertCircle, Settings, Box } from 'lucide-react';
import { ESimChip } from '../types';
import { ESIM_DEVICE_PRESETS } from '../constants';
import ESimTools from './ESimTools';

interface ESimManagerProps {
  chips: ESimChip[];
  onUpdate: (chips: ESimChip[]) => void;
  onClose: () => void;
}

const ESimManager: React.FC<ESimManagerProps> = ({ chips, onUpdate, onClose }) => {
  const [activeTab, setActiveTab] = useState<'manage' | 'tools'>('manage');
  
  const [editingId, setEditingId] = useState<string | null>(null);
  const [showArchived, setShowArchived] = useState(false);
  
  // Form State
  const [eid, setEid] = useState('');
  const [nickname, setNickname] = useState('');
  const [type, setType] = useState<'Native_Phone' | 'Adapter'>('Native_Phone');
  const [protocol, setProtocol] = useState<'OMAPI' | 'ARA-M' | 'Other'>('OMAPI');
  const [remarks, setRemarks] = useState('');
  const [deviceChangeMethod, setDeviceChangeMethod] = useState('');
  const [deviceHistory, setDeviceHistory] = useState('');
  const [isArchived, setIsArchived] = useState(false);

  const startEdit = (chip?: ESimChip) => {
    setActiveTab('manage');
    if (chip) {
      setEditingId(chip.id);
      setEid(chip.eid);
      setNickname(chip.nickname);
      setType(chip.type);
      setProtocol(chip.adapterProtocol || 'OMAPI');
      setRemarks(chip.remarks || '');
      setDeviceChangeMethod(chip.deviceChangeMethod || '');
      setDeviceHistory(chip.deviceHistory || '');
      setIsArchived(chip.isArchived || false);
    } else {
      setEditingId('new');
      setEid('');
      setNickname('');
      setType('Native_Phone');
      setProtocol('OMAPI');
      setRemarks('');
      setDeviceChangeMethod('');
      setDeviceHistory('');
      setIsArchived(false);
    }
  };

  const applyPreset = (presetName: string) => {
     const p = ESIM_DEVICE_PRESETS.find(x => x.name === presetName);
     if (p) {
        setNickname(prev => prev || p.name);
        if (p.eidPrefix) setEid(p.eidPrefix);
        setDeviceChangeMethod(p.method);
        if (p.name.includes('5ber') || p.name.includes('Estk') || p.name.includes('Redtea')) {
           setType('Adapter');
        } else {
           setType('Native_Phone');
        }
     }
  };

  const handleSave = () => {
    const newChip: ESimChip = {
      id: editingId === 'new' ? crypto.randomUUID() : editingId!,
      eid,
      nickname,
      type,
      adapterProtocol: type === 'Adapter' ? protocol : undefined,
      remarks,
      deviceChangeMethod,
      deviceHistory,
      isArchived
    };

    if (editingId === 'new') {
      onUpdate([...chips, newChip]);
    } else {
      onUpdate(chips.map(c => c.id === editingId ? newChip : c));
    }
    setEditingId(null);
  };

  const handleDelete = (id: string) => {
    if (window.confirm('确定删除此 eSIM 芯片记录吗？这将解除其与现有套餐的关联。')) {
      onUpdate(chips.filter(c => c.id !== id));
      if (editingId === id) setEditingId(null);
    }
  };

  const handleToggleArchive = (chip: ESimChip) => {
      const updated = chips.map(c => c.id === chip.id ? { ...c, isArchived: !c.isArchived } : c);
      onUpdate(updated);
      // Sync local form state if currently editing this one
      if (editingId === chip.id) {
          setIsArchived(!chip.isArchived);
      }
  };

  const filteredChips = chips.filter(c => showArchived || !c.isArchived);

  return (
    <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-4xl overflow-hidden flex flex-col max-h-[85vh]">
        <div className="flex justify-between items-center p-4 border-b border-gray-100">
          <div className="flex items-center gap-4">
              <h2 className="text-lg font-bold text-gray-800 flex items-center gap-2">
                <Cpu className="w-5 h-5 text-indigo-600" /> eSIM 芯片仓库
              </h2>
              <div className="flex bg-gray-100 rounded-lg p-0.5">
                  <button onClick={() => setActiveTab('manage')} className={`px-3 py-1 rounded text-xs font-medium transition-all ${activeTab === 'manage' ? 'bg-white shadow text-indigo-600' : 'text-gray-500'}`}>
                     管理
                  </button>
                  <button onClick={() => setActiveTab('tools')} className={`px-3 py-1 rounded text-xs font-medium transition-all ${activeTab === 'tools' ? 'bg-white shadow text-indigo-600' : 'text-gray-500'}`}>
                     工具箱 (LPA)
                  </button>
              </div>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600"><X className="w-6 h-6" /></button>
        </div>
        
        {activeTab === 'tools' ? (
           <div className="flex-1 overflow-hidden p-4">
              <ESimTools />
           </div>
        ) : (
        <div className="flex flex-1 overflow-hidden">
          {/* List */}
          <div className="w-1/3 border-r border-gray-200 bg-gray-50 flex flex-col">
            <div className="p-3 border-b border-gray-200 flex flex-col gap-2">
              <button onClick={() => startEdit()} className="w-full bg-indigo-600 text-white py-2 rounded-lg text-sm font-medium hover:bg-indigo-700 flex items-center justify-center gap-2">
                <Plus className="w-4 h-4" /> 注册新芯片
              </button>
              <label className="flex items-center gap-2 text-xs text-gray-500 cursor-pointer self-end select-none hover:text-gray-700 transition-colors">
                <input type="checkbox" checked={showArchived} onChange={(e) => setShowArchived(e.target.checked)} className="rounded text-indigo-600 focus:ring-indigo-500" />
                显示已归档 ({chips.filter(c => c.isArchived).length})
              </label>
            </div>
            <div className="flex-1 overflow-y-auto p-2 space-y-2">
              {filteredChips.map(chip => (
                <div key={chip.id} className={`p-3 rounded-lg border cursor-pointer transition-colors group relative ${editingId === chip.id ? 'bg-indigo-50 border-indigo-300' : 'bg-white border-gray-200 hover:border-indigo-200'} ${chip.isArchived ? 'bg-gray-100 border-dashed' : ''}`} onClick={() => startEdit(chip)}>
                  <div className="flex justify-between items-start">
                    <span className={`font-medium text-sm truncate ${chip.isArchived ? 'text-gray-500 line-through' : 'text-gray-800'}`}>{chip.nickname}</span>
                    <button 
                       onClick={(e) => { e.stopPropagation(); handleToggleArchive(chip); }}
                       className={`p-1 rounded transition-colors ${chip.isArchived ? 'text-indigo-600 hover:bg-indigo-100' : 'text-gray-400 hover:text-gray-600 hover:bg-gray-100 opacity-0 group-hover:opacity-100'}`}
                       title={chip.isArchived ? "恢复 (Restore)" : "归档 (Archive)"}
                    >
                        {chip.isArchived ? <ArchiveRestore className="w-3.5 h-3.5" /> : <Archive className="w-3.5 h-3.5" />}
                    </button>
                  </div>
                  <div className="text-[10px] text-gray-500 font-mono truncate mt-1">{chip.eid}</div>
                  <div className="mt-1 flex gap-1 items-center">
                     <span className={`text-[9px] px-1.5 py-0.5 rounded border ${chip.type === 'Adapter' ? 'bg-amber-50 text-amber-700 border-amber-200' : 'bg-blue-50 text-blue-700 border-blue-200'}`}>
                       {chip.type === 'Adapter' ? '转接卡' : '原生'}
                     </span>
                     {chip.type === 'Adapter' && <span className="text-[9px] px-1.5 py-0.5 rounded border bg-gray-100 text-gray-600">{chip.adapterProtocol}</span>}
                     {chip.isArchived && <span className="text-[9px] px-1.5 py-0.5 rounded bg-gray-200 text-gray-600 font-bold">已归档</span>}
                  </div>
                </div>
              ))}
              {filteredChips.length === 0 && (
                <div className="text-center py-8 px-4 text-gray-400">
                   <p className="text-xs">无符合条件的芯片。</p>
                   {!showArchived && chips.some(c => c.isArchived) && (
                      <p className="text-[10px] mt-2 text-indigo-500 cursor-pointer" onClick={() => setShowArchived(true)}>查看已归档项目</p>
                   )}
                </div>
              )}
            </div>
          </div>

          {/* Edit Panel */}
          <div className="flex-1 p-6 overflow-y-auto bg-white">
            {editingId ? (
              <div className="space-y-5 animate-fade-in">
                <div className="flex justify-between items-center pb-4 border-b border-gray-100">
                   <h3 className="font-bold text-gray-800 text-lg flex items-center gap-2">
                     {editingId === 'new' ? '注册新芯片' : '编辑芯片详情'}
                     {isArchived && <span className="text-xs bg-gray-200 text-gray-600 px-2 py-1 rounded-full font-normal">已归档</span>}
                   </h3>
                   {editingId !== 'new' && (
                     <div className="flex gap-2">
                        <button 
                          onClick={() => setIsArchived(!isArchived)} 
                          className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors ${isArchived ? 'bg-white border-gray-300 text-gray-700 hover:bg-gray-50' : 'bg-gray-100 border-gray-200 text-gray-600 hover:bg-gray-200'}`}
                        >
                           {isArchived ? <ArchiveRestore className="w-3.5 h-3.5" /> : <Archive className="w-3.5 h-3.5" />}
                           {isArchived ? '恢复' : '归档'}
                        </button>
                        <button onClick={() => handleDelete(editingId)} className="text-red-500 hover:bg-red-50 p-2 rounded-lg transition-colors" title="Delete">
                           <Trash2 className="w-4 h-4" />
                        </button>
                     </div>
                   )}
                </div>
                
                {/* Preset Selector */}
                <div className="flex items-center gap-2 text-xs">
                    <Box className="w-3.5 h-3.5 text-indigo-500" />
                    <span className="text-gray-500">快速填入预设:</span>
                    <select onChange={(e) => applyPreset(e.target.value)} className="border rounded px-2 py-1 bg-gray-50 outline-none text-gray-700">
                       <option value="">-- 选择设备模板 --</option>
                       {ESIM_DEVICE_PRESETS.map(p => <option key={p.name} value={p.name}>{p.name}</option>)}
                    </select>
                </div>

                <div className="grid grid-cols-2 gap-4">
                  <div className="col-span-2">
                    <label className="block text-sm font-medium text-gray-700 mb-1">EID (完整)</label>
                    <input type="text" value={eid} onChange={(e) => setEid(e.target.value)} className="w-full px-3 py-2 border rounded-lg font-mono text-sm focus:ring-2 focus:ring-indigo-500 outline-none" placeholder="89..." />
                    <p className="text-xs text-gray-400 mt-1 flex items-center gap-1"><AlertCircle className="w-3 h-3"/> EID 是 eSIM 芯片的唯一标识，通常为 32 位数字。</p>
                  </div>
                  <div className="col-span-2">
                    <label className="block text-sm font-medium text-gray-700 mb-1">芯片备注名 *</label>
                    <input type="text" value={nickname} onChange={(e) => setNickname(e.target.value)} className="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-indigo-500 outline-none" placeholder="e.g. Pixel 7 Pro, 5ber White" />
                  </div>
                  
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">硬件类型</label>
                    <select value={type} onChange={(e) => setType(e.target.value as any)} className="w-full px-3 py-2 border rounded-lg bg-white outline-none">
                      <option value="Native_Phone">原生 eSIM 手机</option>
                      <option value="Adapter">eSIM 转接卡</option>
                    </select>
                  </div>
                  
                  {type === 'Adapter' && (
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-1">访问协议</label>
                      <select value={protocol} onChange={(e) => setProtocol(e.target.value as any)} className="w-full px-3 py-2 border rounded-lg bg-white outline-none">
                        <option value="OMAPI">OMAPI (免Root)</option>
                        <option value="ARA-M">ARA-M (Android原生)</option>
                        <option value="Other">其他 / 读卡器</option>
                      </select>
                    </div>
                  )}

                  <div className="col-span-2">
                     <label className="block text-sm font-medium text-gray-700 mb-1">写入/切换方式</label>
                     <textarea value={deviceChangeMethod} onChange={(e) => setDeviceChangeMethod(e.target.value)} className="w-full px-3 py-2 border rounded-lg h-16 text-sm resize-none outline-none" placeholder="e.g. 仅支持删除后重新扫描二维码，或需要联系客服..." />
                  </div>

                  <div className="col-span-2">
                     <label className="block text-sm font-medium text-gray-700 mb-1">设备历史 / 备注</label>
                     <textarea value={deviceHistory} onChange={(e) => setDeviceHistory(e.target.value)} className="w-full px-3 py-2 border rounded-lg h-16 text-sm resize-none outline-none" placeholder="e.g. 2023年在 iPhone 13 使用，2024年转入 Pixel 8..." />
                  </div>

                  <div className="col-span-2">
                    <label className="block text-sm font-medium text-gray-700 mb-1">通用备注</label>
                    <textarea value={remarks} onChange={(e) => setRemarks(e.target.value)} className="w-full px-3 py-2 border rounded-lg h-16 text-sm resize-none outline-none" placeholder="其他兼容性记录..." />
                  </div>
                </div>
                
                <div className="flex justify-end gap-3 pt-4 border-t">
                  <button onClick={() => setEditingId(null)} className="px-4 py-2 text-gray-600 hover:bg-gray-100 rounded-lg transition-colors">取消</button>
                  <button onClick={handleSave} className="px-6 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 shadow-md transition-all">
                    {editingId === 'new' ? '创建芯片' : '保存修改'}
                  </button>
                </div>
              </div>
            ) : (
              <div className="h-full flex flex-col items-center justify-center text-gray-400">
                <div className="bg-gray-50 p-6 rounded-full mb-4">
                   <Cpu className="w-12 h-12 text-gray-300" />
                </div>
                <p>请选择左侧芯片进行编辑，或点击“注册新芯片”。</p>
              </div>
            )}
          </div>
        </div>
        )}
      </div>
    </div>
  );
};

export default ESimManager;


import React, { useState, useEffect } from 'react';
import { X, Play, Save, Trash2, PieChart, Plus, LayoutDashboard, ArrowDownUp } from 'lucide-react';
import { AppData, SavedScript, ChartWidget, ChartType, ChartData, GlobalIO } from '../types';
import ChartRenderer from './ChartRenderer';

interface ScriptPlaygroundProps {
  appData: AppData;
  scripts: SavedScript[];
  globalIO: GlobalIO;
  onSaveScripts: (scripts: SavedScript[]) => void;
  onAddWidget: (widget: ChartWidget) => void;
  onUpdateIO: (io: GlobalIO) => void;
  onClose: () => void;
}

const ScriptPlayground: React.FC<ScriptPlaygroundProps> = ({ appData, scripts, globalIO, onSaveScripts, onAddWidget, onUpdateIO, onClose }) => {
  const [activeScriptId, setActiveScriptId] = useState<string | null>(null);
  const [code, setCode] = useState('// API Available:\n// api.log(msg)\n// api.readInput() -> string\n// api.writeOutput(str)\n// api.renderPieChart(title, data)\n\napi.log("Ready.");');
  const [name, setName] = useState('New Script');
  const [output, setOutput] = useState<any[]>([]);
  
  // Local state for IO while editing, synced with parent on change or run
  const [inputText, setInputText] = useState(globalIO.input);
  const [outputText, setOutputText] = useState(globalIO.output);
  
  const [previewChart, setPreviewChart] = useState<Partial<ChartWidget> | null>(null);

  useEffect(() => {
    // Sync local state when global changes (initially)
    setInputText(globalIO.input);
    setOutputText(globalIO.output);
  }, []);

  const handleIOChange = (type: 'input' | 'output', val: string) => {
      if (type === 'input') setInputText(val);
      else setOutputText(val);
      
      // Sync up
      onUpdateIO({
          input: type === 'input' ? val : inputText,
          output: type === 'output' ? val : outputText
      });
  };

  const loadScript = (s: SavedScript) => {
    setActiveScriptId(s.id);
    setCode(s.code);
    setName(s.name);
    setOutput([]);
    setPreviewChart(null);
  };

  const createNew = () => {
    setActiveScriptId(crypto.randomUUID());
    setCode('// Example: Process Input\nconst input = api.readInput();\napi.log("Input length: " + input.length);\napi.writeOutput("Processed: " + input.toUpperCase());');
    setName('Untitled Script');
    setOutput([]);
    setPreviewChart(null);
  };

  const runScript = () => {
    setOutput([]);
    setPreviewChart(null);
    try {
      const api = {
        log: (...args: any[]) => setOutput(prev => [...prev, args.map(a => JSON.stringify(a, null, 2)).join(' ')]),
        readInput: () => inputText,
        writeOutput: (str: string) => {
            setOutputText(str);
            handleIOChange('output', str);
        },
        renderPieChart: (title: string, data: ChartData) => setPreviewChart({ title, type: 'pie', data }),
        renderBarChart: (title: string, data: ChartData) => setPreviewChart({ title, type: 'bar', data }),
        renderLineChart: (title: string, data: ChartData) => setPreviewChart({ title, type: 'line', data }),
      };
      
      const func = new Function('data', 'api', code);
      func(appData, api);
    } catch (e: any) {
      setOutput(prev => [...prev, `Error: ${e.message}`]);
    }
  };

  const saveScript = () => {
    if (!activeScriptId) return;
    const newScript: SavedScript = {
      id: activeScriptId,
      name,
      code,
      lastRun: new Date().toISOString()
    };
    
    const existingIndex = scripts.findIndex(s => s.id === activeScriptId);
    if (existingIndex >= 0) {
      const updated = [...scripts];
      updated[existingIndex] = newScript;
      onSaveScripts(updated);
    } else {
      onSaveScripts([...scripts, newScript]);
    }
    alert('脚本已保存');
  };

  const addToDashboard = () => {
    if (previewChart && previewChart.title && previewChart.type && previewChart.data) {
      const widget: ChartWidget = {
        id: crypto.randomUUID(),
        title: previewChart.title,
        type: previewChart.type,
        data: previewChart.data,
        createdAt: new Date().toISOString()
      };
      onAddWidget(widget);
      alert('图表已保存到主页仪表盘');
    }
  };

  const deleteScript = (id: string) => {
    if (window.confirm('Delete script?')) {
       onSaveScripts(scripts.filter(s => s.id !== id));
       if (activeScriptId === id) {
         setActiveScriptId(null);
         setCode('');
       }
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-6xl h-[90vh] flex overflow-hidden">
        {/* Sidebar */}
        <div className="w-64 bg-gray-50 border-r border-gray-200 flex flex-col">
          <div className="p-4 border-b border-gray-200 flex justify-between items-center">
             <span className="font-bold text-gray-700">脚本库</span>
             <button onClick={createNew} className="text-indigo-600 hover:bg-indigo-50 p-1 rounded"><Plus className="w-5 h-5" /></button>
          </div>
          <div className="flex-1 overflow-y-auto">
             {scripts.map(s => (
               <div key={s.id} className={`p-3 border-b flex justify-between group cursor-pointer ${activeScriptId === s.id ? 'bg-indigo-50' : 'hover:bg-gray-100'}`} onClick={() => loadScript(s)}>
                  <div className="truncate text-sm font-medium">{s.name}</div>
                  <button onClick={(e) => {e.stopPropagation(); deleteScript(s.id)}} className="hidden group-hover:block text-red-500"><Trash2 className="w-4 h-4" /></button>
               </div>
             ))}
          </div>
        </div>

        {/* Main */}
        <div className="flex-1 flex flex-col min-w-0">
           <div className="h-14 border-b border-gray-200 flex items-center justify-between px-4 pr-14 bg-white">
              {activeScriptId ? (
                <input type="text" value={name} onChange={(e) => setName(e.target.value)} className="font-bold text-lg text-gray-800 border-none focus:ring-0 outline-none w-1/2" />
              ) : <div className="text-gray-400">选择或新建脚本</div>}
              
              <div className="flex items-center gap-2">
                 <button onClick={runScript} disabled={!activeScriptId} className="flex items-center gap-1 px-3 py-1.5 bg-green-600 text-white rounded hover:bg-green-700 disabled:opacity-50"><Play className="w-4 h-4" /> 运行</button>
                 <button onClick={saveScript} disabled={!activeScriptId} className="flex items-center gap-1 px-3 py-1.5 bg-indigo-600 text-white rounded hover:bg-indigo-700 disabled:opacity-50"><Save className="w-4 h-4" /> 保存</button>
                 <button 
          onClick={onClose}
          className="absolute top-3 right-3 z-[60] p-2 bg-white/80 hover:bg-red-50 hover:text-red-600 rounded-full shadow-md border border-gray-200 transition-all active:scale-95"
          title="关闭脚本库"
        >
          <X className="w-8 h-8 sm:w-6 sm:h-6" />
        </button>
              </div>
           </div>

           <div className="flex-1 flex flex-col md:flex-row overflow-hidden">
              <div className="flex-1 flex flex-col relative">
                <textarea 
                  value={code} 
                  onChange={(e) => setCode(e.target.value)} 
                  className="flex-1 w-full p-4 font-mono text-sm resize-none outline-none bg-gray-50 text-gray-800 border-r border-gray-200"
                  spellCheck={false}
                  placeholder="// Select 'New Script' to start..."
                  disabled={!activeScriptId}
                />
                
                {/* I/O Section */}
                <div className="h-48 border-t border-gray-200 bg-white grid grid-cols-2">
                   <div className="flex flex-col border-r border-gray-200">
                      <div className="px-2 py-1 bg-gray-100 text-xs font-bold text-gray-500">Global Input (api.readInput)</div>
                      <textarea value={inputText} onChange={(e) => handleIOChange('input', e.target.value)} className="flex-1 p-2 text-xs font-mono resize-none outline-none" placeholder="Paste data here..." />
                   </div>
                   <div className="flex flex-col">
                      <div className="px-2 py-1 bg-gray-100 text-xs font-bold text-gray-500">Global Output (api.writeOutput)</div>
                      <textarea value={outputText} readOnly className="flex-1 p-2 text-xs font-mono resize-none outline-none bg-gray-50" placeholder="Script output..." />
                   </div>
                </div>
              </div>
              
              <div className="w-full md:w-5/12 bg-white flex flex-col overflow-hidden border-l border-gray-200">
                 <div className="p-2 bg-gray-100 text-xs font-bold text-gray-500 uppercase border-b">Console</div>
                 <div className="h-1/3 overflow-y-auto p-4 font-mono text-xs space-y-2 border-b bg-gray-50">
                    {output.length === 0 && <span className="text-gray-300 italic">...</span>}
                    {output.map((line, i) => <div key={i} className="whitespace-pre-wrap break-all">{line}</div>)}
                 </div>
                 
                 <div className="p-2 bg-gray-100 text-xs font-bold text-gray-500 uppercase border-b flex justify-between items-center">
                    <span>Chart Preview</span>
                    {previewChart && (
                       <button onClick={addToDashboard} className="flex items-center gap-1 text-indigo-600 hover:underline">
                          <LayoutDashboard className="w-3 h-3" /> 添加到仪表盘
                       </button>
                    )}
                 </div>
                 <div className="flex-1 p-4 overflow-y-auto bg-gray-50 flex flex-col items-center justify-center">
                    {previewChart && previewChart.type && previewChart.data ? (
                       <div className="w-full h-full">
                          <ChartRenderer 
                             type={previewChart.type} 
                             title={previewChart.title || 'Preview'} 
                             data={previewChart.data}
                             height={250}
                          />
                       </div>
                    ) : (
                       <div className="text-gray-300 text-xs text-center">
                         Run script to generate chart...
                       </div>
                    )}
                 </div>
              </div>
           </div>
        </div>
      </div>
    </div>
  );
};

export default ScriptPlayground;

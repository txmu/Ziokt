import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { Play, RotateCcw, Zap, Brain, Code, BookOpen, Cpu, Save, FolderOpen, Download, Upload, AlertCircle, Layers, SkipForward, Eye, Link, HardDrive, Triangle } from './icons';
import { Flags, Modes, Pipeline, Interrupts, ExternalDevices, CacheLine, CompilationResult, Watchpoint, TraceEntry, TraceInitialState, TraceDelta, FloatRegisters, VectorRegisters, DMAController, MMU, VECTOR_SIZE, Heap, TraceRegisterState, PipelineStageInfo, ExtendedMemory, HardDisk, DiskOperation, Partition, ExtendedMemoryConfig, HardDiskConfig, TDMAController, ManualControlConfig, MachineSnapshot } from '../types';
import { INSTRUCTIONS, EXAMPLES } from '../constants';
import AssemblyEditor from './AssemblyEditor';
import InstructionSetPage from './InstructionSetPage';

const CACHE_SIZE = 16;
const MEMORY_SIZE = 128; 
const TERNARY_MEMORY_SIZE = 729; 
const PIXEL_SCREEN_WIDTH = 32;
const PIXEL_SCREEN_HEIGHT = 32;
const KERNEL_SPACE_START = 64; 
const INTERRUPT_VECTOR_TABLE_BASE = 112; 
const STACK_START = KERNEL_SPACE_START - 1;
const HEAP_START = 20;
const HEAP_END = 40; 
const HEAP_HEADER_SIZE = 2; 
const MAX_EXT_MEM_SIZE = 1.44 * 1024 * 1024; 
const NUM_HARD_DISKS = 2;
const DEFAULT_PIXEL_COLOR = '#1a202c';
const MAX_HISTORY_SIZE = 50;

// --- Helper Components ---

const Modal: React.FC<{ title: string; children: React.ReactNode; onCancel: () => void; }> = ({ title, children, onCancel }) => (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 animate-fade-in">
        <div className="bg-gray-800 border border-cyan-500/50 rounded-lg shadow-xl p-6 w-full max-w-md m-4">
            <div className="flex justify-between items-center mb-4">
                <h2 className="text-xl font-bold text-cyan-300">{title}</h2>
                <button onClick={onCancel} className="text-gray-400 hover:text-white">&times;</button>
            </div>
            {children}
        </div>
    </div>
);

const CreateExtMemModal: React.FC<{ onConfirm: (config: ExtendedMemoryConfig) => void; onCancel: () => void; }> = ({ onConfirm, onCancel }) => {
    const [size, setSize] = useState(1024);
    const [kernelStart, setKernelStart] = useState(-1);
    const [policy, setPolicy] = useState<'disable' | 'mapToUser'>('disable');
    
    const handleSubmit = () => {
        if (size <= 0 || size > MAX_EXT_MEM_SIZE) { alert("Invalid size."); return; }
        const kStart = kernelStart < 0 ? null : kernelStart;
        if (kStart !== null && kStart >= size) { alert("Kernel start address must be less than total size."); return; }
        onConfirm({ size, kernelSpaceStart: kStart, onDisabledKernel: policy });
    };

    return (
        <Modal title="Create Extended RAM" onCancel={onCancel}>
            <div className="space-y-4 text-sm">
                <div>
                    <label className="block mb-1 text-gray-300">Size in words (max {MAX_EXT_MEM_SIZE})</label>
                    <input type="number" value={size} onChange={e => setSize(parseInt(e.target.value))} className="w-full bg-black/50 p-2 rounded border border-white/20" />
                </div>
                <div>
                    <label className="block mb-1 text-gray-300">Kernel Space Start Address (-1 for none)</label>
                    <input type="number" value={kernelStart} onChange={e => setKernelStart(parseInt(e.target.value))} className="w-full bg-black/50 p-2 rounded border border-white/20" />
                </div>
                {kernelStart >= 0 && (
                    <div>
                        <label className="block mb-1 text-gray-300">If Privileged Mode is off:</label>
                        <div className="flex gap-4">
                            <label><input type="radio" value="disable" checked={policy === 'disable'} onChange={() => setPolicy('disable')} /> Disable kernel space</label>
                            <label><input type="radio" value="mapToUser" checked={policy === 'mapToUser'} onChange={() => setPolicy('mapToUser')} /> Map to user space</label>
                        </div>
                    </div>
                )}
                <div className="flex justify-end gap-2 pt-2">
                    <button onClick={onCancel} className="px-4 py-2 bg-gray-600 rounded">Cancel</button>
                    <button onClick={handleSubmit} className="px-4 py-2 bg-blue-500 rounded">Create</button>
                </div>
            </div>
        </Modal>
    );
};

const CreateDiskModal: React.FC<{ diskId: number; onConfirm: (diskId: number, config: HardDiskConfig) => void; onCancel: () => void; }> = ({ diskId, onConfirm, onCancel }) => {
    const [size, setSize] = useState(2048);
    const [partitions, setPartitions] = useState<Partition[]>([{start: 0, size: 2048, type: 'FS'}]);

    useEffect(() => {
        setPartitions([{start: 0, size, type: 'FS'}]);
    }, [size]);

    const totalPartitioned = partitions.reduce((sum, p) => sum + p.size, 0);
    const remainingSize = size - totalPartitioned;

    const handlePartitionChange = (index: number, field: keyof Partition, value: string | number) => {
        const newPartitions = [...partitions];
        if(field === 'size' || field === 'start') value = parseInt(value as string) || 0;
        (newPartitions[index] as any)[field] = value;
        setPartitions(newPartitions);
    };

    const addPartition = () => {
        if (remainingSize <= 0) return;
        const start = totalPartitioned;
        setPartitions([...partitions, {start, size: remainingSize, type: 'GEN'}]);
    };

    const removePartition = (index: number) => {
        setPartitions(partitions.filter((_, i) => i !== index));
    };

    const handleSubmit = () => {
        if (size <= 0) { alert("Invalid disk size."); return; }
        if (totalPartitioned > size) { alert("Total partition size exceeds disk size."); return; }
        onConfirm(diskId, { size, partitions });
    };

    return (
        <Modal title={`Create Hard Disk ${diskId}`} onCancel={onCancel}>
            <div className="space-y-4 text-sm">
                <div>
                    <label className="block mb-1 text-gray-300">Total Disk Size in words</label>
                    <input type="number" value={size} onChange={e => setSize(parseInt(e.target.value) || 0)} className="w-full bg-black/50 p-2 rounded border border-white/20" />
                </div>
                <div>
                    <h3 className="text-gray-300 mb-2">Partitions</h3>
                    <div className="space-y-2 max-h-48 overflow-y-auto pr-2">
                        {partitions.map((p, i) => (
                            <div key={i} className="flex gap-2 items-center">
                                <input type="text" placeholder="Type" value={p.type} onChange={e => handlePartitionChange(i, 'type', e.target.value)} className="w-1/4 bg-black/50 p-1 rounded border border-white/20 text-xs"/>
                                <input type="number" placeholder="Size" value={p.size} onChange={e => handlePartitionChange(i, 'size', e.target.value)} className="w-1/2 bg-black/50 p-1 rounded border border-white/20 text-xs"/>
                                <button onClick={() => removePartition(i)} className="text-red-500 hover:text-red-400 font-bold text-lg">&times;</button>
                            </div>
                        ))}
                    </div>
                     <div className="text-xs text-gray-400 mt-2">
                        Remaining space: {remainingSize} words
                    </div>
                    <button onClick={addPartition} disabled={remainingSize <= 0} className="mt-2 text-xs p-1 bg-blue-500 rounded disabled:bg-gray-600">Add Partition</button>
                </div>
                <div className="flex justify-end gap-2 pt-2">
                    <button onClick={onCancel} className="px-4 py-2 bg-gray-600 rounded">Cancel</button>
                    <button onClick={handleSubmit} className="px-4 py-2 bg-blue-500 rounded">Create & Connect</button>
                </div>
            </div>
        </Modal>
    );
}

// --- Main Component ---

const TernaryComputer: React.FC = () => {
  const [memory, setMemory] = useState<number[]>(Array(MEMORY_SIZE).fill(0));
  const [accumulator, setAccumulator] = useState<number>(0);
  const [registerB, setRegisterB] = useState<number>(0);
  const [registerC, setRegisterC] = useState<number>(0);
  const [programCounter, setProgramCounter] = useState<number>(0);
  const [stackPointer, setStackPointer] = useState<number>(STACK_START);
  const [flags, setFlags] = useState<Flags>({ zero: true, negative: false, carry: false });
  const [running, setRunning] = useState<boolean>(false);
  const [log, setLog] = useState<string[]>([]);
  const [speed, setSpeed] = useState<number>(10); 
  const [code, setCode] = useState<string>(EXAMPLES['factorial'].code);
  const [compilationResult, setCompilationResult] = useState<CompilationResult | null>(null);

  const [activeTab, setActiveTab] = useState<string>('code');
  const [selectedExample, setSelectedExample] = useState<string>('factorial');
  
  const [modes, setModes] = useState<Modes>({
    pipelineEnabled: false,
    interruptEnabled: true,
    privilegedMode: false,
    debugMode: true,
    floatMode: false,
    vectorMode: false,
    cacheEnabled: true,
    dmaEnabled: false,
    temEnabled: false,
  });

  const [floatRegisters, setFloatRegisters] = useState<FloatRegisters>({ f0: 0.0, f1: 0.0, f2: 0.0, f3: 0.0 });
  const [vectorRegisters, setVectorRegisters] = useState<VectorRegisters>({ v0: Array(VECTOR_SIZE).fill(0), v1: Array(VECTOR_SIZE).fill(0), v2: Array(VECTOR_SIZE).fill(0), v3: Array(VECTOR_SIZE).fill(0) });
  const [dma, setDma] = useState<DMAController>({ source: 0, destination: 0, count: 0, status: 'idle' });
  const [mmu, setMmu] = useState<MMU>({ boundaryRegister: KERNEL_SPACE_START, temBoundaryRegister: TERNARY_MEMORY_SIZE });
  const [privilegeLevel, setPrivilegeLevel] = useState<number>(0);
  const [heap, setHeap] = useState<Heap>({start: HEAP_START, end: HEAP_END, freeListHead: -1});

  const [ternaryExpansionMemory, setTernaryExpansionMemory] = useState<number[]>(Array(TERNARY_MEMORY_SIZE).fill(0));
  const [temDma, setTemDma] = useState<TDMAController>({ source: 0, destination: 0, count: 0, direction: 'mem_to_tem', status: 'idle' });

  const [pipeline, setPipeline] = useState<Pipeline>({ fetch: null, decode: null, execute: null, memory: null, writeBack: null });
  const [interrupts, setInterrupts] = useState<Interrupts>({ pending: [], vector: 0, handlerAddress: INTERRUPT_VECTOR_TABLE_BASE, activeVector: null });
  const [cache, setCache] = useState<CacheLine[]>([]);
  const [breakpoints, setBreakpoints] = useState<number[]>([]);
  const [watchpoints, setWatchpoints] = useState<number[]>([]);
  
  const [externalDevices, setExternalDevices] = useState<ExternalDevices>({ keyboardInput: '', keyboardBuffer: [], display: '', cursorPosition: 0, pixelScreenBuffer: Array(PIXEL_SCREEN_WIDTH * PIXEL_SCREEN_HEIGHT).fill(DEFAULT_PIXEL_COLOR), fileSystem: [] });
  const [ioPortState, setIoPortState] = useState({ pixelX: 0, pixelY: 0 });
  
  const [executionTrace, setExecutionTrace] = useState<TraceEntry[]>([]);
  const [isRecordingTrace, setIsRecordingTrace] = useState<boolean>(false);

  const [stepOverTarget, setStepOverTarget] = useState<number | null>(null);
  
  // --- Storage & Modals ---
  const [extendedMemory, setExtendedMemory] = useState<ExtendedMemory | null>(null);
  const [hardDisks, setHardDisks] = useState<(HardDisk | null)[]>(Array(NUM_HARD_DISKS).fill(null));
  const [diskOperation, setDiskOperation] = useState<DiskOperation | null>(null);
  const [showCreateExtMemModal, setShowCreateExtMemModal] = useState<boolean>(false);
  const [showCreateDiskModal, setShowCreateDiskModal] = useState<number | null>(null);

  // --- Direct Control ---
  const [manualCommand, setManualCommand] = useState<string>('');
  const [manualConfig, setManualConfig] = useState<ManualControlConfig>({ keepOnReset: true });
  const [machineHistory, setMachineHistory] = useState<MachineSnapshot[]>([]);
  const [machineFuture, setMachineFuture] = useState<MachineSnapshot[]>([]);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const extMemFileInputRef = useRef<HTMLInputElement>(null);
  const diskFileInputRefs = useRef<(HTMLInputElement | null)[]>([]);
  const cycleCount = useRef(0);
  const preCycleState = useRef<{memory: number[], registers: TraceRegisterState, extendedMemory: ExtendedMemory | null, ternaryExpansionMemory: number[], hardDisks: (HardDisk|null)[]}>({ memory: [], registers: { acc: 0, b: 0, c: 0, pc: 0, sp: 0, flags: { zero: false, negative: false, carry: false } }, extendedMemory: null, ternaryExpansionMemory: [], hardDisks: [] });
  const pipelinePCUpdate = useRef<number | null>(null);
  const displayRef = useRef<HTMLPreElement>(null);
  const logContainerRef = useRef<HTMLDivElement>(null);
  
  const addLog = useCallback((msg: string, source: string = "CPU") => {
    const pc = source === "CPU" ? `[PC:${programCounter}]` : `[${source}]`;
    const pl = modes.privilegedMode ? ` PL${privilegeLevel}` : '';
    setLog(prev => [`${cycleCount.current.toString().padStart(4, '0')}:${pl}${pc} ${msg}`, ...prev.slice(0, 199)]);
  }, [programCounter, privilegeLevel, modes.privilegedMode]);

  const flagsToNumber = (f: Flags, pl: number): number => (f.zero ? 1 : 0) | (f.negative ? 2 : 0) | (f.carry ? 4 : 0) | (pl << 8);
  const numberToFlags = (n: number): {flags: Flags, pl: number} => ({ flags: { zero: (n & 1) > 0, negative: (n & 2) > 0, carry: (n & 4) > 0 }, pl: (n >> 8) & 0xFF });

  const updateFlags = useCallback((value: number) => ({
      zero: value === 0,
      negative: value < 0,
      carry: Math.abs(value) > 2**16,
  }), []);

  const handleInterrupt = useCallback((vector: number) => {
    if (!modes.interruptEnabled) return;
    setInterrupts(prev => {
        if (prev.pending.includes(vector)) return prev;
        return {...prev, pending: [...prev.pending, vector].sort((a,b) => a - b)};
    });
    addLog(`Interrupt requested: vector ${vector}`, "INT");
  }, [modes.interruptEnabled, addLog]);
  
  const checkMemoryAccess = useCallback((addr: number, isWrite: boolean = false): boolean => {
    const isExtMem = addr >= MEMORY_SIZE;
    
    if (modes.privilegedMode && privilegeLevel <= 0) return true;

    if (!isExtMem && (addr < 0 || addr >= MEMORY_SIZE)) {
        return false;
    }
    
    if (isExtMem) {
        if (!extendedMemory) return false;
        const relativeAddr = addr - MEMORY_SIZE;
        if (relativeAddr >= extendedMemory.config.size) return false;
        
        if (modes.privilegedMode && privilegeLevel >= 3) {
            addLog(`Access Fault: Public Plugin (PL3) cannot access Extended Memory`, "MMU");
            handleInterrupt(2);
            return false;
        }
    }

    if (modes.privilegedMode) {
        if (privilegeLevel > 0) {
             if (!isExtMem && addr >= mmu.boundaryRegister) {
                 addLog(`Protection Fault: PL${privilegeLevel} cannot access system address ${addr}`, "MMU");
                 handleInterrupt(2);
                 return false;
             }
             if (isExtMem) {
                 const { kernelSpaceStart } = extendedMemory!.config;
                 if (kernelSpaceStart !== null && (addr - MEMORY_SIZE) >= kernelSpaceStart) {
                     addLog(`Protection Fault: PL${privilegeLevel} cannot access extended system address ${addr}`, "MMU");
                     handleInterrupt(2);
                     return false;
                 }
             }
        }
    } else if (isExtMem) {
        const { kernelSpaceStart, onDisabledKernel } = extendedMemory!.config;
        if (kernelSpaceStart !== null && (addr - MEMORY_SIZE) >= kernelSpaceStart && onDisabledKernel === 'disable') {
             addLog(`Access Fault: Kernel extended memory address ${addr} is disabled`, "MMU");
             handleInterrupt(6);
             return false;
        }
    }
    return true;
  }, [modes.privilegedMode, privilegeLevel, mmu.boundaryRegister, addLog, handleInterrupt, extendedMemory]);

  const checkTemAccess = useCallback((addr: number, isWrite: boolean = false): boolean => {
    if (addr < 0 || addr >= TERNARY_MEMORY_SIZE) {
        addLog(`TEM Segmentation Fault: Address ${addr} is out of bounds (0-${TERNARY_MEMORY_SIZE-1})`, "MMU");
        handleInterrupt(2);
        return false;
    }
    if (modes.privilegedMode && privilegeLevel > 0 && addr >= mmu.temBoundaryRegister) {
      addLog(`TEM Protection Fault: PL${privilegeLevel} cannot access kernel address ${addr}`, "MMU");
      handleInterrupt(2);
      return false;
    }
    return true;
  }, [modes.privilegedMode, privilegeLevel, mmu.temBoundaryRegister, addLog, handleInterrupt]);

  const checkExtMemRelAccess = useCallback((relAddr: number, isWrite: boolean = false): boolean => {
      if (!extendedMemory) { addLog(`Extended Memory Fault: No extended memory loaded`, "MMU"); handleInterrupt(6); return false; }
      const absAddr = relAddr + MEMORY_SIZE;
      if (!checkMemoryAccess(absAddr, isWrite)) {
           addLog(`Segmentation Fault: Address ${absAddr} is out of bounds`, "MMU");
           handleInterrupt(2);
           return false;
      }
      return true;
  }, [checkMemoryAccess, extendedMemory, addLog, handleInterrupt]);

  const getValue = useCallback((addr: number): number => {
      if (!checkMemoryAccess(addr)) {
          if (addr < 0 || (addr >= MEMORY_SIZE && !extendedMemory) || (extendedMemory && addr >= MEMORY_SIZE + extendedMemory.config.size)) {
             addLog(`Segmentation Fault: Address ${addr} is out of bounds`, "MMU");
             handleInterrupt(2);
          }
          return 0;
      }
      if (addr < MEMORY_SIZE && modes.cacheEnabled) {
        const cacheHit = cache.find(line => line.tag === addr);
        if (cacheHit) {
          cacheHit.lastUsed = cycleCount.current;
          return cacheHit.data;
        }
        const value = memory[addr] || 0;
        const newCache = [...cache];
        if (newCache.length >= CACHE_SIZE) { newCache.sort((a, b) => a.lastUsed - b.lastUsed); newCache.shift(); }
        newCache.push({ tag: addr, data: value, lastUsed: cycleCount.current });
        setCache(newCache);
        return value;
      }
      if (addr < MEMORY_SIZE) return memory[addr] || 0;
      if (extendedMemory) {
          return extendedMemory.data[addr - MEMORY_SIZE] || 0;
      }
      return 0;
    }, [memory, modes.cacheEnabled, cache, addLog, checkMemoryAccess, extendedMemory, handleInterrupt]);

  const writeMemory = useCallback((addr: number, value: number, currentMemory: number[]): {mem: number[], ext: ExtendedMemory|null} => {
    if (!checkMemoryAccess(addr, true)) {
        if (addr < 0 || (addr >= MEMORY_SIZE && !extendedMemory) || (extendedMemory && addr >= MEMORY_SIZE + extendedMemory.config.size)) {
             addLog(`Segmentation Fault: Address ${addr} is out of bounds`, "MMU");
             handleInterrupt(2);
        }
        return {mem: currentMemory, ext: extendedMemory};
    }
    if (modes.debugMode && watchpoints.includes(addr)) {
      const oldVal = addr < MEMORY_SIZE ? currentMemory[addr] : (extendedMemory ? extendedMemory.data[addr - MEMORY_SIZE] : 0);
      addLog(`Watchpoint hit at address ${addr}. Value changed from ${oldVal} to ${value}`, "DBG");
      setRunning(false);
    }
    if (addr < MEMORY_SIZE) {
        const newMem = [...currentMemory];
        newMem[addr] = value;
        if (modes.cacheEnabled) {
            const cacheIndex = cache.findIndex(line => line.tag === addr);
            if (cacheIndex > -1) {
                const newCache = [...cache];
                newCache[cacheIndex] = { tag: addr, data: value, lastUsed: cycleCount.current };
                setCache(newCache);
            }
        }
        return { mem: newMem, ext: extendedMemory };
    } else if (extendedMemory) {
        const relAddr = addr - MEMORY_SIZE;
        const newData = [...extendedMemory.data];
        newData[relAddr] = value;
        return { mem: currentMemory, ext: { ...extendedMemory, data: newData } };
    }
    return { mem: currentMemory, ext: extendedMemory };
  }, [modes, watchpoints, addLog, cache, checkMemoryAccess, extendedMemory, handleInterrupt]);
  
    const captureStateBeforeCycle = () => {
        if (!isRecordingTrace) return;
        preCycleState.current = {
            memory: [...memory],
            registers: {
                acc: accumulator, b: registerB, c: registerC, pc: programCounter, sp: stackPointer, flags: { ...flags },
                privilegeLevel: privilegeLevel, mmuBoundary: mmu.boundaryRegister
            },
            extendedMemory: extendedMemory ? JSON.parse(JSON.stringify(extendedMemory)) : null,
            ternaryExpansionMemory: [...ternaryExpansionMemory],
            hardDisks: hardDisks ? JSON.parse(JSON.stringify(hardDisks)) : [],
        };
    };

    const recordTraceDelta = () => {
        if (!isRecordingTrace) return;
        const fromReg = preCycleState.current.registers;
        const toReg: TraceRegisterState = { acc: accumulator, b: registerB, c: registerC, pc: programCounter, sp: stackPointer, flags, privilegeLevel, mmuBoundary: mmu.boundaryRegister };
        const registerChanges: TraceDelta['registerChanges'] = {};
        if (fromReg.acc !== toReg.acc) registerChanges.acc = { from: fromReg.acc, to: toReg.acc };
        if (fromReg.b !== toReg.b) registerChanges.b = { from: fromReg.b, to: toReg.b };
        if (fromReg.c !== toReg.c) registerChanges.c = { from: fromReg.c, to: toReg.c };
        if (fromReg.pc !== toReg.pc) registerChanges.pc = { from: fromReg.pc, to: toReg.pc };
        if (fromReg.sp !== toReg.sp) registerChanges.sp = { from: fromReg.sp, to: toReg.sp };
        if (JSON.stringify(fromReg.flags) !== JSON.stringify(toReg.flags)) registerChanges.flags = { from: fromReg.flags, to: toReg.flags };
        if (fromReg.privilegeLevel !== toReg.privilegeLevel) registerChanges.privilegeLevel = { from: fromReg.privilegeLevel!, to: toReg.privilegeLevel! };
        if (fromReg.mmuBoundary !== toReg.mmuBoundary) registerChanges.mmuBoundary = { from: fromReg.mmuBoundary!, to: toReg.mmuBoundary! };

        const memoryChanges: TraceDelta['memoryChanges'] = {};
        for (let i = 0; i < MEMORY_SIZE; i++) {
            if (preCycleState.current.memory[i] !== memory[i]) {
                memoryChanges[i] = { from: preCycleState.current.memory[i], to: memory[i] };
            }
        }
        const extendedMemoryChanges: TraceDelta['extendedMemoryChanges'] = {};
        if (preCycleState.current.extendedMemory && extendedMemory) {
             const len = Math.min(preCycleState.current.extendedMemory.data.length, extendedMemory.data.length);
             for (let i = 0; i < len; i++) {
                if (preCycleState.current.extendedMemory.data[i] !== extendedMemory.data[i]) {
                    extendedMemoryChanges[i] = { from: preCycleState.current.extendedMemory.data[i], to: extendedMemory.data[i] };
                }
             }
        }
        const temChanges: TraceDelta['temChanges'] = {};
        for (let i = 0; i < TERNARY_MEMORY_SIZE; i++) {
            if (preCycleState.current.ternaryExpansionMemory[i] !== ternaryExpansionMemory[i]) {
                temChanges[i] = { from: preCycleState.current.ternaryExpansionMemory[i], to: ternaryExpansionMemory[i] };
            }
        }
        const hardDiskChanges: TraceDelta['hardDiskChanges'] = {};
        for (let i = 0; i < NUM_HARD_DISKS; i++) {
            const beforeDisk = preCycleState.current.hardDisks[i];
            const afterDisk = hardDisks[i];
            if (beforeDisk && afterDisk) {
                const diskDelta: { [address: number]: { from: number; to: number } } = {};
                for (let j = 0; j < afterDisk.config.size; j++) {
                    if (beforeDisk.data[j] !== afterDisk.data[j]) {
                        diskDelta[j] = { from: beforeDisk.data[j], to: afterDisk.data[j] };
                    }
                }
                if (Object.keys(diskDelta).length > 0) {
                    hardDiskChanges[i] = diskDelta;
                }
            }
        }

        let opcode = 0;
        let operand = 0;
        if (fromReg.pc < MEMORY_SIZE) {
            opcode = preCycleState.current.memory[fromReg.pc];
            operand = preCycleState.current.memory[fromReg.pc + 1];
        } else if (preCycleState.current.extendedMemory) {
            const rel = fromReg.pc - MEMORY_SIZE;
            opcode = preCycleState.current.extendedMemory.data[rel];
            operand = preCycleState.current.extendedMemory.data[rel + 1];
        }
        const instInfo = Object.entries(INSTRUCTIONS).find(([op]) => parseInt(op) === opcode);
        const delta: TraceDelta = {
            type: 'delta', cycle: cycleCount.current, pc: fromReg.pc,
            instruction: { opcode, name: instInfo ? instInfo[1].name : '???', operand },
            memoryChanges, extendedMemoryChanges, temChanges, hardDiskChanges, registerChanges,
        };
        setExecutionTrace(prev => [...prev, delta]);
    };
  
  const executeSingleInstruction = useCallback((manualInstruction?: {opcode: number, operand: number}) => {
    let currentPC = programCounter, currentACC = accumulator, currentB = registerB, currentC = registerC, currentSP = stackPointer, currentFlags = flags;
    let currentDisplay = externalDevices.display, currentKbdBuffer = [...externalDevices.keyboardBuffer], currentMemory = memory;
    let currentPixelBuffer = [...externalDevices.pixelScreenBuffer];
    let currentIoPorts = { ...ioPortState };
    let currentExtMem = extendedMemory;
    
    if (!manualInstruction && !checkMemoryAccess(currentPC)) { 
        addLog(`Segmentation Fault: PC ${currentPC} is out of bounds`, "MMU");
        handleInterrupt(2);
        setRunning(false); 
        return; 
    }
    
    let opcode = 0;
    let operand = 0;

    if (manualInstruction) {
        opcode = manualInstruction.opcode;
        operand = manualInstruction.operand;
    } else {
        opcode = getValue(currentPC);
    }
    
    const instInfo = Object.entries(INSTRUCTIONS).find(([op]) => parseInt(op) === opcode);
    const opName = instInfo ? instInfo[1].name : '???';
    const requiresOperand = [1,-1,2,-2,3,-3,4,-4,5,-5,-6,7,-7,8,-8,9,-9,10,-12,-13,14,-14,15,17,18,-18,19,-19,20,23,24,-24,26,-26,30,31,36,37,40,41,70,80,-80,81,-81,82,84].includes(opcode);

    if (requiresOperand && !manualInstruction) {
        if (!checkMemoryAccess(currentPC + 1)) { 
            addLog(`Segmentation Fault: Operand at ${currentPC + 1} is out of bounds`, "MMU");
            handleInterrupt(2);
            setRunning(false); 
            return; 
        }
        operand = getValue(currentPC + 1);
    }

    if ([-1, 14, 15, -11, -12, -27, -28].includes(opcode)) {
         let targetAddr = operand;
         if (opcode === -27) targetAddr = currentB;
         else if (opcode === -28) targetAddr = currentC;
         else if (opcode === -11 || opcode === -12) targetAddr = currentSP - 1;
         
         if (!checkMemoryAccess(targetAddr, true)) {
             addLog(`Critical Safety: Execution aborted before invalid store to ${targetAddr}`, 'ERR');
             addLog(`Segmentation Fault: Address ${targetAddr} is out of bounds`, "MMU");
             handleInterrupt(2);
             setRunning(false);
             return;
         }
    }

    addLog(`Executing ${opName} (${opcode}) ${requiresOperand ? operand : ''} ${manualInstruction ? '(Manual)' : ''}`);
    let nextPc = manualInstruction ? currentPC : currentPC + (requiresOperand ? 2 : 1);
    
    const writeMem = (addr: number, value: number) => { 
        const res = writeMemory(addr, value, currentMemory);
        currentMemory = res.mem;
        currentExtMem = res.ext;
    };

    const push = (val: number) => {
        const newSP = currentSP - 1;
        if (newSP < mmu.boundaryRegister && modes.privilegedMode && privilegeLevel > 0) { addLog('Stack Overflow into Kernel!', 'ERR'); handleInterrupt(3); setRunning(false); return; }
        if (!checkMemoryAccess(newSP, true)) { 
             addLog(`Stack Fault: ${newSP} invalid`, "MMU");
             handleInterrupt(2);
             setRunning(false); 
             return; 
        }
        writeMem(newSP, val); currentSP = newSP;
    };
    const pop = () => {
        if (currentSP >= MEMORY_SIZE) { addLog('Stack Underflow!', 'ERR'); handleInterrupt(3); setRunning(false); return 0; }
        const val = getValue(currentSP); currentSP = currentSP + 1; return val;
    };
    
    const checkPrivilege = () => {
        if (modes.privilegedMode && privilegeLevel > 0) { 
            addLog(`Privilege Violation: ${opName} is a kernel-only instruction`, 'MMU'); 
            handleInterrupt(2); 
            return false; 
        }
        return true;
    }
    
    const checkIO = () => {
        if (modes.privilegedMode && privilegeLevel >= 2) {
            addLog(`I/O Protection Fault: PL${privilegeLevel} cannot use I/O`, 'MMU');
            handleInterrupt(2);
            return false;
        }
        return true;
    };

    switch(opcode) {
        case 0: if(checkPrivilege()) { setRunning(false); addLog("Execution halted."); } break;
        case 1: currentACC = getValue(operand); break;
        case -1: writeMem(operand, currentACC); break;
        case 2: currentACC += getValue(operand); break;
        case -2: currentACC -= getValue(operand); break;
        case 3: currentACC *= getValue(operand); break;
        case -3: { const val = getValue(operand); if (val === 0) { handleInterrupt(4); } else {currentACC = Math.trunc(currentACC / val);} break; }
        case 4: { const val = getValue(operand); if (val === 0) { handleInterrupt(4); } else {currentACC = currentACC % val;} break; }
        case -4: currentACC &= getValue(operand); break;
        case 5: currentACC |= getValue(operand); break;
        case -5: currentACC ^= getValue(operand); break;
        case 6: currentACC = ~currentACC; break;
        case -6: currentACC <<= getValue(operand); break;
        case 7: currentACC >>= getValue(operand); break;
        case -7: nextPc = operand; break;
        case 8: if (currentFlags.zero) nextPc = operand; break;
        case -8: if (!currentFlags.zero) nextPc = operand; break;
        case 9: if (currentFlags.negative) nextPc = operand; break;
        case -9: if (!currentFlags.negative) nextPc = operand; break;
        case 10: currentFlags = updateFlags(currentACC - getValue(operand)); break;
        case -10: currentACC++; break;
        case 11: currentACC--; break;
        case -11: push(currentACC); break;
        case 12: currentACC = pop(); break;
        case -12: push(nextPc); nextPc = operand; break;
        case 13: nextPc = pop(); break;
        case -13: currentB = getValue(operand); break;
        case 14: writeMem(operand, currentB); break;
        case -14: currentC = getValue(operand); break;
        case 15: writeMem(operand, currentC); break;
        case -15: currentB = currentACC; break;
        case 16: currentACC = currentB; break;
        case -16: currentC = currentACC; break;
        case 17: handleInterrupt(operand); break;
        case -17: { 
            if(!checkPrivilege()) break; 
            const vec = pop();
            const state = pop(); 
            const pc_ret = pop(); 
            
            const {flags: f, pl} = numberToFlags(state); 
            currentFlags = f; 
            setPrivilegeLevel(pl); 
            setInterrupts(prev => ({...prev, activeVector: vec === -1 ? null : vec}));
            
            nextPc = pc_ret; 
            addLog(`IRET to ${pc_ret}`, "INT");
            break; 
        }
        case 18: { 
            if (!checkIO()) break;
            const port = operand;
            switch (port) {
                case 0: if (currentKbdBuffer.length > 0) { currentACC = currentKbdBuffer.shift()!; } else { currentACC = 0; } break;
                default: addLog(`IN from unknown port ${port}`, "I/O"); currentACC = 0; break;
            }
            break;
        }
        case -18: { 
            if (!checkIO()) break;
            const port = operand;
            const value = currentACC;
            switch (port) {
                case 0: if (value === 8) { currentDisplay = currentDisplay.slice(0, -1); } else { currentDisplay += String.fromCharCode(value); } break;
                case 10: currentIoPorts = { ...currentIoPorts, pixelX: value }; break;
                case 11: currentIoPorts = { ...currentIoPorts, pixelY: value }; break;
                case 12: {
                    const x = currentIoPorts.pixelX;
                    const y = currentIoPorts.pixelY;
                    if (x >= 0 && x < PIXEL_SCREEN_WIDTH && y >= 0 && y < PIXEL_SCREEN_HEIGHT) {
                        currentPixelBuffer[y * PIXEL_SCREEN_WIDTH + x] = value;
                    }
                    break;
                }
                default: addLog(`OUT to unknown port ${port}`, "I/O"); break;
            }
            break;
        }
        case 19: if (currentFlags.zero) nextPc = operand; break;
        case -19: if (!currentFlags.zero) nextPc = operand; break;
        case 20: currentACC = operand; break;
        case -20: currentACC = currentC; break;
        case 21: if (checkPrivilege()) setMmu(m => ({ ...m, boundaryRegister: currentACC })); break;
        case 22: handleInterrupt(0); break;
        case 23: {
            if (modes.privilegedMode && operand < privilegeLevel) {
                 addLog(`Privilege Fault: Cannot escalate privilege from PL${privilegeLevel} to PL${operand} via instruction. Use INT/SYSCALL.`, 'MMU');
                 handleInterrupt(2);
            } else {
                setPrivilegeLevel(operand);
            }
            break;
        }
        case 24: currentB = operand; break;
        case -24: currentC = operand; break;
        case 25: currentC = currentB; break;
        case 26: if (currentFlags.carry) nextPc = operand; break;
        case -26: if (!currentFlags.carry) nextPc = operand; break;
        case 27: currentACC = getValue(currentB); break;
        case -27: writeMem(currentB, currentACC); break;
        case 28: currentACC = getValue(currentC); break;
        case -28: writeMem(currentC, currentACC); break;
        case 29: currentSP = currentACC; break;
        case 30: if (modes.floatMode) setFloatRegisters(f => ({ ...f, [`f${currentB}`]: getValue(operand) })); else handleInterrupt(1); break;
        case 31: if (modes.floatMode) writeMem(operand, floatRegisters[`f${currentB}`]); else handleInterrupt(1); break;
        case 32: if (modes.floatMode) setFloatRegisters(f => ({ ...f, [`f${currentB}`]: f[`f${currentB}`] + f[`f${currentC}`] })); else handleInterrupt(1); break;
        case 33: if (modes.floatMode) setFloatRegisters(f => ({ ...f, [`f${currentB}`]: f[`f${currentB}`] - f[`f${currentC}`] })); else handleInterrupt(1); break;
        case 34: if (modes.floatMode) setFloatRegisters(f => ({ ...f, [`f${currentB}`]: f[`f${currentB}`] * f[`f${currentC}`] })); else handleInterrupt(1); break;
        case 35: if (modes.floatMode) setFloatRegisters(f => ({ ...f, [`f${currentB}`]: f[`f${currentC}`] !== 0 ? f[`f${currentB}`] / f[`f${currentC}`] : 0 })); else handleInterrupt(1); break;
        case 36: if (modes.floatMode) setFloatRegisters(f => ({...f, [`f${operand}`]: currentACC })); else handleInterrupt(1); break;
        case 37: if (modes.floatMode) currentACC = Math.round(floatRegisters[`f${operand}`]); else handleInterrupt(1); break;
        case 40: if (modes.vectorMode) { const vec = []; for(let i=0; i<VECTOR_SIZE; i++) vec.push(getValue(operand+i)); setVectorRegisters(v => ({...v, [`v${currentB}`]: vec})); } else handleInterrupt(1); break;
        case 41: if (modes.vectorMode) { vectorRegisters[`v${currentB}`].forEach((val: number, i: number) => writeMem(operand+i, val)); } else handleInterrupt(1); break;
        case 42: if (modes.vectorMode) { const vA=vectorRegisters[`v${currentB}`], vB=vectorRegisters[`v${currentC}`]; setVectorRegisters(v => ({...v, [`v${currentACC}`]: vA.map((val, i) => val + vB[i])})); } else handleInterrupt(1); break;
        case 43: if (modes.vectorMode) { const vA=vectorRegisters[`v${currentB}`], vB=vectorRegisters[`v${currentC}`]; setVectorRegisters(v => ({...v, [`v${currentACC}`]: vA.map((val, i) => val - vB[i])})); } else handleInterrupt(1); break;
        case 44: if (modes.vectorMode) { const vA=vectorRegisters[`v${currentB}`], vB=vectorRegisters[`v${currentC}`]; setVectorRegisters(v => ({...v, [`v${currentACC}`]: vA.map((val, i) => val * vB[i])})); } else handleInterrupt(1); break;
        case 50: if (modes.dmaEnabled) { if(checkPrivilege()) setDma({source: currentB, destination: currentC, count: currentACC, status: 'busy'}); } else handleInterrupt(1); break;
        case 51: { if (!checkPrivilege()) break; const requestedSize = currentACC; let currentBlock = heap.freeListHead; let prevBlock = -1; let foundBlock = -1; while (currentBlock !== -1) { if (!checkMemoryAccess(currentBlock) || !checkMemoryAccess(currentBlock+1)) { setRunning(false); break; } const blockSize = Math.abs(currentMemory[currentBlock]); if (blockSize >= requestedSize + HEAP_HEADER_SIZE) { foundBlock = currentBlock; break; } prevBlock = currentBlock; currentBlock = currentMemory[currentBlock + 1]; } if (foundBlock === -1) { currentACC = 0; addLog(`Heap ALLOC failed for size ${requestedSize}`, "HEAP"); } else { const originalSize = currentMemory[foundBlock]; const nextFree = currentMemory[foundBlock + 1]; const canSplit = originalSize > requestedSize + HEAP_HEADER_SIZE * 2; if (canSplit) { const newBlockAddr = foundBlock + HEAP_HEADER_SIZE + requestedSize; const newBlockSize = originalSize - requestedSize - HEAP_HEADER_SIZE; writeMem(newBlockAddr, newBlockSize); writeMem(newBlockAddr + 1, nextFree); writeMem(foundBlock, -(requestedSize + HEAP_HEADER_SIZE)); if (prevBlock === -1) { setHeap(h => ({...h, freeListHead: newBlockAddr})); } else { writeMem(prevBlock + 1, newBlockAddr); } } else { writeMem(foundBlock, -originalSize); if (prevBlock === -1) { setHeap(h => ({...h, freeListHead: nextFree})); } else { writeMem(prevBlock + 1, nextFree); } } currentACC = foundBlock + HEAP_HEADER_SIZE; addLog(`Heap ALLOC size ${requestedSize} at ${currentACC}`, "HEAP"); } break; }
        case -51: { if (!checkPrivilege()) break; const ptr = currentACC; const blockAddr = ptr - HEAP_HEADER_SIZE; if (blockAddr < heap.start || blockAddr > heap.end || !checkMemoryAccess(blockAddr) || currentMemory[blockAddr] > 0) { addLog(`Heap FREE failed: invalid pointer ${ptr}`, "HEAP"); handleInterrupt(2); break; } const blockSize = Math.abs(currentMemory[blockAddr]); writeMem(blockAddr, blockSize); writeMem(blockAddr + 1, heap.freeListHead); setHeap(h => ({...h, freeListHead: blockAddr})); addLog(`Heap FREE at ${ptr}`, "HEAP"); break; }
        case 60: if (checkExtMemRelAccess(currentB)) currentACC = extendedMemory!.data[currentB]; break;
        case 61: if (checkExtMemRelAccess(currentB, true)) { const newData = [...extendedMemory!.data]; newData[currentB] = currentACC; setExtendedMemory(em => em ? {...em, data: newData} : null); currentExtMem = {...extendedMemory!, data: newData}; } break;
        case 70: { 
            if (!checkIO()) break;
            const cmd = currentACC; const diskId = currentB; const param1 = currentC; const param2 = getValue(operand);
            const disk = hardDisks[diskId];
            if (!disk || disk.status === 'disconnected') { addLog(`Disk ${diskId} not connected`, "DISK"); handleInterrupt(7); break; }
            if (disk.busy || diskOperation) { addLog(`Disk ${diskId} is busy`, "DISK"); handleInterrupt(7); break; }
            switch (cmd) {
                case 0: setDiskOperation({ type: 'read', diskId, memAddr: param1, diskAddr: param2, count: 1, progress: 0 }); addLog(`Disk ${diskId}: READ from disk:${param2} to mem:${param1} (1 word)`, "DISK"); break;
                case 1: setDiskOperation({ type: 'write', diskId, memAddr: param1, diskAddr: param2, count: 1, progress: 0 }); addLog(`Disk ${diskId}: WRITE from mem:${param1} to disk:${param2} (1 word)`, "DISK"); break;
                case 2: setDiskOperation({ type: 'trim', diskId, memAddr: 0, diskAddr: param1, count: param2, progress: 0 }); addLog(`Disk ${diskId}: TRIM from disk:${param1} for ${param2} words`, "DISK"); break;
                case 3: currentACC = 0; break; 
                default: addLog(`Invalid disk command ${cmd}`, "DISK"); handleInterrupt(7);
            }
            if (cmd <= 2) setHardDisks(disks => disks.map((d, i) => i === diskId ? {...d!, busy: true} : d));
            break;
        }
        case 80: if (modes.temEnabled && checkPrivilege() && checkTemAccess(operand)) currentACC = ternaryExpansionMemory[operand]; else if(!modes.temEnabled) handleInterrupt(1); break;
        case -80: if (modes.temEnabled && checkPrivilege() && checkTemAccess(operand, true)) setTernaryExpansionMemory(tem => tem.map((t, i) => i === operand ? Math.sign(currentACC) : t)); else if(!modes.temEnabled) handleInterrupt(1); break;
        case 81: if (modes.temEnabled && checkPrivilege() && checkTemAccess(operand)) currentACC += ternaryExpansionMemory[operand]; else if(!modes.temEnabled) handleInterrupt(1); break;
        case -81: if (modes.temEnabled && checkPrivilege() && checkTemAccess(operand, true)) setTernaryExpansionMemory(tem => tem.map((t, i) => i === operand ? -t : t)); else if(!modes.temEnabled) handleInterrupt(1); break;
        case 82: if (modes.temEnabled && checkPrivilege() && checkTemAccess(operand)) currentFlags = updateFlags(currentACC - ternaryExpansionMemory[operand]); else if(!modes.temEnabled) handleInterrupt(1); break;
        case 83: if(modes.temEnabled && checkPrivilege()) setTemDma({source: currentB, destination: currentC, count: currentACC, status: 'busy', direction: 'mem_to_tem'}); else if(!modes.temEnabled) handleInterrupt(1); break;
        case -83: if(modes.temEnabled && checkPrivilege()) setTemDma({source: currentB, destination: currentC, count: currentACC, status: 'busy', direction: 'tem_to_mem'}); else if(!modes.temEnabled) handleInterrupt(1); break;
        case 84: if (modes.temEnabled && checkPrivilege()) setMmu(m => ({...m, temBoundaryRegister: currentACC})); else if(!modes.temEnabled) handleInterrupt(1); break;
        default: addLog(`Illegal Opcode: ${opcode}`, "ERR"); handleInterrupt(1); break;
    }
    setExternalDevices(p=>({...p, display: currentDisplay, cursorPosition: currentDisplay.length, keyboardBuffer: currentKbdBuffer, pixelScreenBuffer: currentPixelBuffer}));
    setIoPortState(currentIoPorts);
    setMemory(currentMemory); setAccumulator(currentACC); setRegisterB(currentB); setRegisterC(currentC); setProgramCounter(nextPc); setStackPointer(currentSP);
    setExtendedMemory(currentExtMem);
    if (![10, 17, -17, 82].includes(opcode)) { setFlags(updateFlags(currentACC)); } else { setFlags(currentFlags); }
  }, [programCounter, memory, addLog, getValue, accumulator, flags, handleInterrupt, writeMemory, registerB, registerC, updateFlags, stackPointer, externalDevices, modes, privilegeLevel, mmu, floatRegisters, vectorRegisters, heap, checkMemoryAccess, extendedMemory, hardDisks, diskOperation, checkExtMemRelAccess, ternaryExpansionMemory, checkTemAccess, ioPortState]);

  const executePipelinedCycle = useCallback(() => {
    let nextPipeline: Pipeline = { fetch: null, decode: null, execute: null, memory: null, writeBack: null };
    let wbACC = accumulator, wbB = registerB, wbC = registerC;
    let mem = [...memory];
    let currentExtMem = extendedMemory;
    let sp = stackPointer;
    let nextFlags = flags;
    let pc = programCounter;
    let display = externalDevices.display;
    let kbdBuffer = [...externalDevices.keyboardBuffer];
    let pixelBuffer = [...externalDevices.pixelScreenBuffer];
    let ioPorts = { ...ioPortState };
    let nextFloatRegs = { ...floatRegisters };
    let nextVectorRegs = { ...vectorRegisters };
    let nextHeap = { ...heap };
    let nextTem = [...ternaryExpansionMemory];
    let nextPrivilegeLevel = privilegeLevel;
    
    const pipelineGetValue = (addr: number) => {
        if (addr < MEMORY_SIZE) return mem[addr] || 0;
        if (currentExtMem && addr >= MEMORY_SIZE && addr < MEMORY_SIZE + currentExtMem.config.size) {
            return currentExtMem.data[addr - MEMORY_SIZE] || 0;
        }
        return 0;
    };

    const pipelineWriteMem = (addr: number, val: number) => {
        if (addr < MEMORY_SIZE) { mem[addr] = val; }
        else if (currentExtMem && addr >= MEMORY_SIZE && addr < MEMORY_SIZE + currentExtMem.config.size) {
            if (currentExtMem === extendedMemory) {
                currentExtMem = { ...extendedMemory, data: [...extendedMemory.data] };
            }
            currentExtMem!.data[addr - MEMORY_SIZE] = val;
        }
    };

    if (pipeline.writeBack) {
        const { opcode, result } = pipeline.writeBack;
        addLog(`WB: ${INSTRUCTIONS[String(opcode)]?.name || '???'} -> Reg`, 'PIPE');
        if (result !== undefined) {
             const op = pipeline.writeBack.opcode;
             if ([1,2,-2,3,-3,4,-4,5,-5,6,-6,7,-10,11,12,16,-20,37,27,28,18,20,42,43,44,51,60,80,81].includes(op)) wbACC = result;
             if ([-13, -15, 24].includes(op)) wbB = result;
             if ([-14, -16, 25, -24].includes(op)) wbC = result;
             if ([29].includes(op)) sp = result;
        }
        if (![10, 17, -17, 82].includes(opcode)) {
            nextFlags = updateFlags(wbACC);
        }
    }
    nextPipeline.writeBack = pipeline.memory;

    if (pipeline.memory) {
        const { opcode, operand, result, address } = pipeline.memory;
        addLog(`MEM: ${INSTRUCTIONS[String(opcode)]?.name || '???'} Addr:${operand}`, 'PIPE');
        let memValue = result;
        if (operand !== undefined && ![ -1, 14, 15, -11, -12, 1, 2, -2, 3, -3, 4, -4, 5, -5, -6, 7, 10, -13, -14, 18, -18, 27, -27, 28, -28, 30, 31, 40, 41, 70, 80, -80, 81, -81, 82 ].every(op => op !== opcode) && !checkMemoryAccess(operand, [ -1, 14, 15, -11, -12, -27, -28 ].includes(opcode))) {
            setRunning(false);
        } else {
            switch(opcode) {
                case 1: case 2: case -2: case 3: case -3: case 4: case -4: case 5: case -5: case -6: case 7: case 10: case -13: case -14: memValue = pipelineGetValue(operand!); break;
                case 27: { memValue = pipelineGetValue(result!); break; } 
                case 28: { memValue = pipelineGetValue(result!); break; } 
                case -1: pipelineWriteMem(operand!, result!); break;
                case 14: pipelineWriteMem(operand!, result!); break;
                case 15: pipelineWriteMem(operand!, result!); break;
                case -27: pipelineWriteMem(operand!, result!); break; 
                case -28: pipelineWriteMem(operand!, result!); break; 
                case -11: sp--; pipelineWriteMem(sp, result!); break; 
                case 12: memValue = pipelineGetValue(sp); sp++; break; 
                case -12: sp--; pipelineWriteMem(sp, address + 2); break; 
                case 13: {
                    memValue = pipelineGetValue(sp); sp++;
                    pipelinePCUpdate.current = memValue;
                    break;
                }
                case -17: { // IRET in Pipeline Memory Stage
                    const vec = pipelineGetValue(sp); sp++;
                    const state = pipelineGetValue(sp); sp++;
                    const pc_ret = pipelineGetValue(sp); sp++;
                    
                    const {flags: f, pl} = numberToFlags(state);
                    nextFlags = f;
                    nextPrivilegeLevel = pl;
                    pipelinePCUpdate.current = pc_ret;
                    
                    setInterrupts(prev => ({...prev, activeVector: vec === -1 ? null : vec}));
                    
                    addLog(`IRET (PIPE) to ${pc_ret}`, "INT");
                    break;
                }
                case 18: { const port = operand!; if (port === 0 && kbdBuffer.length > 0) { memValue = kbdBuffer.shift()!; } else { memValue = 0; } break; }
                case -18: { const port = operand!; const value = result!; switch (port) { case 0: if (value === 8) { display = display.slice(0, -1); } else { display += String.fromCharCode(value); } break; case 10: ioPorts.pixelX = value; break; case 11: ioPorts.pixelY = value; break; case 12: { const x = ioPorts.pixelX; const y = ioPorts.pixelY; if (x >= 0 && x < PIXEL_SCREEN_WIDTH && y >= 0 && y < PIXEL_SCREEN_HEIGHT) { pixelBuffer[y * PIXEL_SCREEN_WIDTH + x] = value; } break; } } break; }
                case 30: if(modes.floatMode) nextFloatRegs[`f${wbB}`] = pipelineGetValue(operand!); else handleInterrupt(1); break; 
                case 31: if(modes.floatMode) pipelineWriteMem(operand!, nextFloatRegs[`f${wbB}`]); else handleInterrupt(1); break; 
                case 40: if (modes.vectorMode) { const vec = []; for(let i=0; i<VECTOR_SIZE; i++) vec.push(getValue(operand+i)); nextVectorRegs[`v${wbB}`] = vec; } else handleInterrupt(1); break; 
                case 41: if (modes.vectorMode) { nextVectorRegs[`v${wbB}`].forEach((val, i) => pipelineWriteMem(operand!+i, val)); } else handleInterrupt(1); break; 
                case 60: if (checkExtMemRelAccess(wbB)) memValue = currentExtMem!.data[wbB]; break; 
                case 61: if (checkExtMemRelAccess(wbB, true)) { if (currentExtMem === extendedMemory) currentExtMem = { ...extendedMemory!, data: [...extendedMemory!.data] }; currentExtMem!.data[wbB] = result!; } break; 
                case 80: if (modes.temEnabled && checkTemAccess(operand!)) memValue = nextTem[operand!]; break; 
                case -80: if (modes.temEnabled && checkTemAccess(operand!, true)) nextTem[operand!] = Math.sign(result!); break; 
                case 81: if (modes.temEnabled && checkTemAccess(operand!)) memValue = result! + nextTem[operand!]; break; 
                case -81: if (modes.temEnabled && checkTemAccess(operand!, true)) nextTem[operand!] = -nextTem[operand!]; break; 
            }
        }
        nextPipeline.memory = { ...pipeline.memory, result: memValue };
    }
    nextPipeline.memory = pipeline.execute;

    if (pipeline.execute) {
        const { opcode, operand, address, memValue } = pipeline.execute;
        addLog(`EX: ${INSTRUCTIONS[String(opcode)]?.name || '???'} Op:${operand}`, 'PIPE');
        let result = accumulator; 
        let isBranchTaken = false;
        let passedOperand = operand;
        
        let forwardACC = accumulator, forwardB = registerB, forwardC = registerC;
        const accWriters = [1,2,-2,3,-3,4,-4,5,-5,6,-6,7,-10,11,12,16,-20,37,27,28,18,20,42,43,44,51,60,80,81];
        const bWriters = [-13, -15, 24];
        const cWriters = [-14, -16, 25, -24];

        if (pipeline.writeBack?.result !== undefined) { 
            const op = pipeline.writeBack.opcode; const res = pipeline.writeBack.result;
            if(accWriters.includes(op)) forwardACC = res; if(bWriters.includes(op)) forwardB = res; if(cWriters.includes(op)) forwardC = res;
        }
        if (pipeline.memory?.result !== undefined) { 
            const op = pipeline.memory.opcode; const res = pipeline.memory.result;
            if(accWriters.includes(op)) forwardACC = res; if(bWriters.includes(op)) forwardB = res; if(cWriters.includes(op)) forwardC = res;
        }

        switch(opcode) {
            case 1: case 12: case 13: case -13: case -14: case 18: result = memValue!; break;
            case 27: result = forwardB; break;
            case 28: result = forwardC; break;
            case -27: passedOperand = forwardB; result = forwardACC; break;
            case -28: passedOperand = forwardC; result = forwardACC; break;
            case 2: result = forwardACC + memValue!; break;
            case -2: result = forwardACC - memValue!; break;
            case 3: result = forwardACC * memValue!; break;
            case -3: result = memValue! === 0 ? 0 : Math.trunc(forwardACC / memValue!); if (memValue! === 0) handleInterrupt(4); break;
            case 4: result = memValue! === 0 ? 0 : forwardACC % memValue!; if (memValue! === 0) handleInterrupt(4); break;
            case -4: result = forwardACC & memValue!; break;
            case 5: result = forwardACC | memValue!; break;
            case -5: result = forwardACC ^ memValue!; break;
            case 6: result = ~forwardACC; break;
            case -6: result = forwardACC << memValue!; break;
            case 7: result = forwardACC >> memValue!; break;
            case -7: case -12: isBranchTaken = true; pipelinePCUpdate.current = operand!; break; 
            case 8: if(flags.zero) { isBranchTaken = true; pipelinePCUpdate.current = operand!; } break; 
            case -8: if(!flags.zero) { isBranchTaken = true; pipelinePCUpdate.current = operand!; } break; 
            case 9: if (flags.negative) { isBranchTaken = true; pipelinePCUpdate.current = operand!; } break; 
            case -9: if (!flags.negative) { isBranchTaken = true; pipelinePCUpdate.current = operand!; } break; 
            case 26: if (flags.carry) { isBranchTaken = true; pipelinePCUpdate.current = operand!; } break; 
            case -26: if (!flags.carry) { isBranchTaken = true; pipelinePCUpdate.current = operand!; } break; 
            case 10: nextFlags = updateFlags(forwardACC - memValue!); break;
            case -10: result = forwardACC + 1; break;
            case 11: result = forwardACC - 1; break;
            case -11: case -18: result = forwardACC; break; 
            case 16: result = forwardB; break; 
            case -15: result = forwardACC; break; 
            case -16: result = forwardACC; break; 
            case -20: result = forwardC; break; 
            case 25: result = forwardB; break; 
            case 20: case 24: case -24: result = operand!; break; 
            case 29: result = forwardACC; break; 
            case 60: result = forwardB; break; 
            case 61: result = forwardACC; passedOperand = forwardB; break; 
            case 80: result = forwardACC; break; 
            case -80: result = forwardACC; break; 
            case 81: result = forwardACC; break; 
            case 0: setRunning(false); break;
            default: result = forwardACC; break;
        }
        nextPipeline.execute = { ...pipeline.execute, result, isBranchTaken, operand: passedOperand };
    }
    nextPipeline.execute = pipeline.decode;

    if (pipeline.decode) {
        addLog(`ID: ${INSTRUCTIONS[String(pipeline.decode.opcode)]?.name || '???'} Op:${pipeline.decode.operand}`, 'PIPE');
        let memValue;
        if ([1, -1, 2, -2, 3, -3, 4, -4, 5, -5, -6, 7, 10, -13, 14, -14, 15, 30, 31, 40, 41].includes(pipeline.decode.opcode)) {
           memValue = pipelineGetValue(pipeline.decode.operand!);
        }
        nextPipeline.decode = {...pipeline.decode, memValue};
    }
    nextPipeline.decode = pipeline.fetch;

    if (pipelinePCUpdate.current !== null) {
        pc = pipelinePCUpdate.current;
        pipelinePCUpdate.current = null;
        nextPipeline.fetch = null;
        nextPipeline.decode = null; 
        nextPipeline.execute = null; 
        addLog(`IF: Branch taken (or return). Flushing pipeline.`, 'PIPE');
    } else {
        if (running && checkMemoryAccess(pc)) {
            const opcode = pipelineGetValue(pc);
            const requiresOperand = [1,-1,2,-2,3,-3,4,-4,5,-5,-6,7,-7,8,-8,9,-9,10,-12,-13,14,-14,15,17,18,-18,19,-19,20,23,24,-24,26,-26,30,31,36,37,40,41,70,80,-80,81,-81,82,84].includes(opcode);
            
            if (requiresOperand && !checkMemoryAccess(pc + 1)) {
                setRunning(false);
                nextPipeline.fetch = null;
            } else {
                addLog(`IF: Fetching from PC:${pc}`, 'PIPE');
                nextPipeline.fetch = { instruction: opcode, address: pc };
                pc += (requiresOperand ? 2 : 1);
            }
        } else {
             if (running) setRunning(false);
             nextPipeline.fetch = null; 
        }
    }
    
    setPipeline(nextPipeline);
    setProgramCounter(pc);
    setAccumulator(wbACC); setRegisterB(wbB); setRegisterC(wbC);
    setStackPointer(sp); setMemory(mem);
    setFlags(nextFlags);
    setPrivilegeLevel(nextPrivilegeLevel);
    setExternalDevices(p => ({...p, display, keyboardBuffer: kbdBuffer, pixelScreenBuffer: pixelBuffer, cursorPosition: display.length}));
    setIoPortState(ioPorts);
    setFloatRegisters(nextFloatRegs);
    setVectorRegisters(nextVectorRegs);
    setHeap(nextHeap);
    setTernaryExpansionMemory(nextTem);
    setExtendedMemory(currentExtMem);
    
  }, [pipeline, memory, programCounter, stackPointer, accumulator, registerB, registerC, writeMemory, addLog, updateFlags, checkMemoryAccess, flags, running, handleInterrupt, externalDevices, ioPortState, floatRegisters, vectorRegisters, heap, ternaryExpansionMemory, extendedMemory, checkExtMemRelAccess, checkTemAccess, modes, privilegeLevel]);

  const cycle = useCallback(() => {
    cycleCount.current++;
    captureStateBeforeCycle();

    if (stepOverTarget !== null && programCounter >= stepOverTarget) { setRunning(false); setStepOverTarget(null); addLog(`Step-over complete.`, "DBG"); return; }
    
    if (interrupts.pending.length > 0 && modes.interruptEnabled) {
        const highestPriorityVector = interrupts.pending[0];
        const canTrigger = interrupts.activeVector === null || highestPriorityVector < interrupts.activeVector;

        if (canTrigger) {
            if (interrupts.activeVector !== null) {
                addLog(`Interrupt Priority: Preempting vector ${interrupts.activeVector} with ${highestPriorityVector}`, "INT");
            }

            setRunning(false);
            const vector = highestPriorityVector;
            addLog(`Servicing interrupt vector ${vector}`, "INT");
            const handlerAddr = getValue(INTERRUPT_VECTOR_TABLE_BASE + vector);
            
            const currentState = flagsToNumber(flags, privilegeLevel);
            const currentMemory = [...memory];
            let currentSP = stackPointer;
            const push = (val: number) => {
                currentSP--;
                if (currentSP >= 0 && currentSP < MEMORY_SIZE) currentMemory[currentSP] = val;
            };
            
            push(programCounter);
            push(currentState);
            push(interrupts.activeVector === null ? -1 : interrupts.activeVector);
            
            setStackPointer(currentSP);
            setMemory(currentMemory);
            setProgramCounter(handlerAddr);
            setPrivilegeLevel(0); 
            
            setInterrupts(prev => ({ 
                ...prev, 
                pending: prev.pending.slice(1),
                activeVector: vector 
            }));
            
            setPipeline({ fetch: null, decode: null, execute: null, memory: null, writeBack: null }); 
            setRunning(true); 
            return;
        }
    }
    
    if(modes.dmaEnabled && dma.status === 'busy' && dma.count > 0) {
        const newMem = [...memory];
        if (checkMemoryAccess(dma.source) && checkMemoryAccess(dma.destination, true)) {
            newMem[dma.destination] = newMem[dma.source];
            const newDma = {...dma, source: dma.source + 1, destination: dma.destination + 1, count: dma.count - 1};
            if(newDma.count === 0) {
                newDma.status = 'done';
                addLog('DMA transfer complete.', 'DMA');
                handleInterrupt(4);
            }
            setDma(newDma);
            setMemory(newMem);
        } else {
            addLog('DMA error: memory access out of bounds.', 'DMA');
            setDma({...dma, status: 'idle'});
            handleInterrupt(2);
        }
    }
    
    if(modes.temEnabled && temDma.status === 'busy' && temDma.count > 0) {
         if(temDma.direction === 'mem_to_tem') {
            if(checkMemoryAccess(temDma.source) && checkTemAccess(temDma.destination, true)) {
                const newTemMem = [...ternaryExpansionMemory];
                newTemMem[temDma.destination] = Math.sign(memory[temDma.source]);
                setTernaryExpansionMemory(newTemMem);
            } else { setTemDma(d=>({...d, status: 'idle'})); }
        } else { 
            if(checkTemAccess(temDma.source) && checkMemoryAccess(temDma.destination, true)) {
                const newMem = [...memory];
                newMem[temDma.destination] = ternaryExpansionMemory[temDma.source];
                setMemory(newMem);
            } else { setTemDma(d=>({...d, status: 'idle'})); }
        }
        const newDma = {...temDma, source: temDma.source + 1, destination: temDma.destination + 1, count: temDma.count - 1};
        if(newDma.count === 0) {
            newDma.status = 'done';
            addLog('TEM DMA transfer complete.', 'DMA');
            handleInterrupt(8); 
        }
        setTemDma(newDma);
    }

    if (diskOperation) {
        const op = {...diskOperation};
        const disk = hardDisks[op.diskId]!;
        let newDiskData = [...disk.data];
        let newMem = [...memory];

        if (op.type === 'read') newMem[op.memAddr + op.progress] = newDiskData[op.diskAddr + op.progress];
        else if (op.type === 'write') newDiskData[op.diskAddr + op.progress] = newMem[op.memAddr + op.progress];
        else if (op.type === 'trim') newDiskData[op.diskAddr + op.progress] = 0;
        
        op.progress++;

        if (op.progress >= op.count) {
            setDiskOperation(null);
            handleInterrupt(5); 
            addLog(`Disk ${op.diskId} ${op.type.toUpperCase()} complete.`, 'DISK');
            setHardDisks(disks => disks.map((d, i) => i === op.diskId ? {...d!, busy: false, data: newDiskData, checksum: newDiskData.reduce((a, b) => a + b, 0)} : d));
            setMemory(newMem);
        } else {
            setDiskOperation(op);
            setHardDisks(disks => disks.map((d, i) => i === op.diskId ? {...d!, data: newDiskData} : d));
            setMemory(newMem);
        }
    }

    if (modes.debugMode && breakpoints.includes(programCounter)) { addLog(`Breakpoint hit at address ${programCounter}`, "DBG"); setRunning(false); return; }
    
    if (modes.pipelineEnabled) { executePipelinedCycle(); } 
    else { executeSingleInstruction(); }

    recordTraceDelta();

  }, [interrupts, modes, dma, breakpoints, programCounter, flags, memory, executeSingleInstruction, addLog, stepOverTarget, getValue, stackPointer, privilegeLevel, executePipelinedCycle, flagsToNumber, handleInterrupt, checkMemoryAccess, isRecordingTrace, diskOperation, hardDisks, temDma, ternaryExpansionMemory, checkTemAccess, extendedMemory, ternaryExpansionMemory, ioPortState, externalDevices]);
  
  const stepOver = () => {
    const opcode = getValue(programCounter);
    if (opcode === -12) { 
        const nextInstructionAddress = programCounter + 2;
        setStepOverTarget(nextInstructionAddress);
        setRunning(true);
        addLog(`Stepping over CALL. Will pause at PC=${nextInstructionAddress}`, "DBG");
    } else {
        cycle(); 
    }
  };

  const reset = useCallback((initialMemory?: number[]) => {
    let mem = initialMemory ? [...initialMemory] : Array(MEMORY_SIZE).fill(0);
    const heapSize = HEAP_END - HEAP_START + 1;
    if (heapSize > HEAP_HEADER_SIZE) {
        mem[HEAP_START] = heapSize;
        mem[HEAP_START + 1] = -1;
        setHeap({ start: HEAP_START, end: HEAP_END, freeListHead: HEAP_START });
    } else {
        setHeap({ start: HEAP_START, end: HEAP_END, freeListHead: -1 });
    }

    setMemory(mem); setAccumulator(0); setRegisterB(0); setRegisterC(0);
    setProgramCounter(0); setStackPointer(STACK_START); setFlags({ zero: true, negative: false, carry: false });
    setRunning(false); setLog([]); setCache([]); 
    setBreakpoints([]); setWatchpoints([]);
    setInterrupts({ pending: [], vector: 0, handlerAddress: INTERRUPT_VECTOR_TABLE_BASE, activeVector: null });
    setExternalDevices({ keyboardInput: '', keyboardBuffer: [], display: '', cursorPosition: 0, pixelScreenBuffer: Array(PIXEL_SCREEN_WIDTH * PIXEL_SCREEN_HEIGHT).fill(DEFAULT_PIXEL_COLOR), fileSystem: [] });
    setPipeline({ fetch: null, decode: null, execute: null, memory: null, writeBack: null });
    setFloatRegisters({ f0: 0.0, f1: 0.0, f2: 0.0, f3: 0.0 });
    setVectorRegisters({ v0: Array(VECTOR_SIZE).fill(0), v1: Array(VECTOR_SIZE).fill(0), v2: Array(VECTOR_SIZE).fill(0), v3: Array(VECTOR_SIZE).fill(0) });
    setDma({ source: 0, destination: 0, count: 0, status: 'idle' });
    setMmu({ boundaryRegister: KERNEL_SPACE_START, temBoundaryRegister: TERNARY_MEMORY_SIZE }); setPrivilegeLevel(0);
    setTernaryExpansionMemory(Array(TERNARY_MEMORY_SIZE).fill(0));
    setTemDma({ source: 0, destination: 0, count: 0, direction: 'mem_to_tem', status: 'idle' });
    setExecutionTrace([]); setIsRecordingTrace(false);
    if (initialMemory && !extendedMemory) setExtendedMemory(null);
    
    setHardDisks(Array(NUM_HARD_DISKS).fill(null));
    setDiskOperation(null);
    cycleCount.current = 0;
    
    if (!manualConfig.keepOnReset) {
        setMachineHistory([]);
        setMachineFuture([]);
    }
  }, [manualConfig.keepOnReset, extendedMemory]);

  const takeSnapshot = useCallback((): MachineSnapshot => ({
    memory: [...memory],
    extendedMemoryData: extendedMemory ? [...extendedMemory.data] : null,
    accumulator, registerB, registerC, programCounter, stackPointer, flags: {...flags},
    ternaryExpansionMemory: [...ternaryExpansionMemory]
  }), [memory, extendedMemory, accumulator, registerB, registerC, programCounter, stackPointer, flags, ternaryExpansionMemory]);

  const restoreSnapshot = useCallback((snap: MachineSnapshot) => {
    setMemory(snap.memory);
    if (extendedMemory && snap.extendedMemoryData) {
        setExtendedMemory({...extendedMemory, data: snap.extendedMemoryData});
    }
    setAccumulator(snap.accumulator);
    setRegisterB(snap.registerB);
    setRegisterC(snap.registerC);
    setProgramCounter(snap.programCounter);
    setStackPointer(snap.stackPointer);
    setFlags(snap.flags);
    setTernaryExpansionMemory(snap.ternaryExpansionMemory);
  }, [extendedMemory]);

  const handleManualExecute = useCallback(() => {
      if (!manualCommand.trim()) return;
      const parts = manualCommand.trim().split(/\s+/);
      const opName = parts[0].toUpperCase();
      const opEntry = Object.entries(INSTRUCTIONS).find(([, info]) => info.name === opName);
      
      if (!opEntry) { addLog(`Unknown manual instruction: ${opName}`, "MAN"); return; }
      const opcode = parseInt(opEntry[0]);
      
      const requiresOperand = [1,-1,2,-2,3,-3,4,-4,5,-5,-6,7,-7,8,-8,9,-9,10,-12,-13,14,-14,15,17,18,-18,19,-19,20,23,24,-24,26,-26,30,31,36,37,40,41,70,80,-80,81,-81,82,84].includes(opcode);
      let operand = 0;
      if (requiresOperand) {
          if (!parts[1]) { addLog(`Manual instruction ${opName} requires operand`, "MAN"); return; }
          operand = parseInt(parts[1]);
          if (isNaN(operand)) { addLog(`Invalid operand: ${parts[1]}`, "MAN"); return; }
      }
      
      const snap = takeSnapshot();
      setMachineHistory(prev => [...prev.slice(-MAX_HISTORY_SIZE + 1), snap]);
      setMachineFuture([]); 

      executeSingleInstruction({opcode, operand});
      addLog(`Executed manual: ${opName} ${requiresOperand ? operand : ''}`, "MAN");
      setManualCommand('');
  }, [manualCommand, takeSnapshot, executeSingleInstruction, addLog]);

  const handleUndo = useCallback(() => {
      if (machineHistory.length === 0) return;
      const currentSnap = takeSnapshot();
      const previousSnap = machineHistory[machineHistory.length - 1];
      
      setMachineFuture(prev => [currentSnap, ...prev]);
      setMachineHistory(prev => prev.slice(0, -1));
      
      restoreSnapshot(previousSnap);
      addLog("Undid last manual operation.", "MAN");
  }, [machineHistory, takeSnapshot, restoreSnapshot, addLog]);

  const handleRedo = useCallback(() => {
      if (machineFuture.length === 0) return;
      const nextSnap = machineFuture[0];
      const currentSnap = takeSnapshot();

      setMachineHistory(prev => [...prev, currentSnap]);
      setMachineFuture(prev => prev.slice(1));

      restoreSnapshot(nextSnap);
      addLog("Redid manual operation.", "MAN");
  }, [machineFuture, takeSnapshot, restoreSnapshot, addLog]);

  interface ExtendedCompilationResult extends CompilationResult {
      extendedMemoryData?: { [addr: number]: number };
  }

  const compileCode = (source: string): ExtendedCompilationResult | null => { 
      try {
        const lines = source.split('\n');
        const newMem = Array(MEMORY_SIZE).fill(0);
        const extendedMemData: { [addr: number]: number } = {};
        
        const labels: { [key: string]: number } = {};
        const lineAddressMap: { [line: number]: number } = {};
        const addressLineMap: { [address: number]: number } = {};
        let tempAddr = 0;
        lines.forEach((line, i) => {
            const cleanLine = line.split('//')[0].trim();
            if (!cleanLine) return;
            lineAddressMap[i + 1] = tempAddr;
            addressLineMap[tempAddr] = i + 1;
            const instructionPart = cleanLine.includes(':') ? cleanLine.substring(cleanLine.indexOf(':') + 1).trim() : cleanLine;
            if (cleanLine.includes(':')) {
                const [label] = cleanLine.split(':');
                const trimmedLabel = label.trim();
                if (labels[trimmedLabel] !== undefined) { throw { message: `Duplicate label definition '${trimmedLabel}'`, line: i + 1 }; }
                labels[trimmedLabel] = tempAddr;
            }
            if(instructionPart) {
              const opName = instructionPart.split(/\s+/)[0].toUpperCase();
              const op = Object.entries(INSTRUCTIONS).find(([, info]) => info.name === opName);
              if (!op) return; 
              const opCode = parseInt(op[0]);
              if ([1,-1,2,-2,3,-3,4,-4,5,-5,-6,7,-7,8,-8,9,-9,10,-12,-13,14,-14,15,17,18,-18,19,-19,20,23,24,-24,26,-26,30,31,36,37,40,41,70,80,-80,81,-81,82,84].includes(opCode)) {
                tempAddr += 2;
              } else {
                tempAddr += 1;
              }
            }
        });
        let addr = 0;
        for (let i = 0; i < lines.length; i++) {
            const line = lines[i];
            const cleanLine = line.split('//')[0].trim();
            const instructionPart = cleanLine.includes(':') ? cleanLine.substring(cleanLine.indexOf(':') + 1).trim() : cleanLine;
            if (!instructionPart) continue;
            const parts = instructionPart.split(/\s+/);
            const opName = parts[0].toUpperCase();
            const op = Object.entries(INSTRUCTIONS).find(([, info]) => info.name === opName);
            if (!op) throw { message: `Unknown instruction '${parts[0]}'`, line: i + 1 };
            const opCode = parseInt(op[0]);
            if (isNaN(opCode)) throw { message: `Invalid instruction parsing for '${parts[0]}'`, line: i + 1 };
            
            if (addr < MEMORY_SIZE) newMem[addr] = opCode;
            else extendedMemData[addr - MEMORY_SIZE] = opCode;
            addr++;

            if ([1,-1,2,-2,3,-3,4,-4,5,-5,-6,7,-7,8,-8,9,-9,10,-12,-13,14,-14,15,17,18,-18,19,-19,20,23,24,-24,26,-26,30,31,36,37,40,41,70,80,-80,81,-81,82,84].includes(opCode)) {
              if (!parts[1]) throw { message: `Instruction '${opName}' requires an operand.`, line: i + 1 };
              let val = labels[parts[1]] !== undefined ? labels[parts[1]] : parseInt(parts[1]);
              if (isNaN(val)) {
                  throw { message: `Invalid operand '${parts[1]}'`, line: i + 1 };
              }
              
              if (addr < MEMORY_SIZE) newMem[addr] = val;
              else extendedMemData[addr - MEMORY_SIZE] = val;
              addr++;
            }
        }
        const result: ExtendedCompilationResult = { memory: newMem, extendedMemoryData: extendedMemData, lineAddressMap, addressLineMap, error: null, errorLine: null };
        setCompilationResult(result); addLog('Compile successful', "ASM"); return result;
    } catch (e: any) {
        const errorMsg = e.message || 'An unknown compilation error occurred.';
        addLog(errorMsg, "ASM");
        const result = { memory: [], lineAddressMap: {}, addressLineMap: {}, error: errorMsg, errorLine: e.line };
        setCompilationResult(result); return result;
    }
  };

  const handleCompileAndLoad = (source = code) => { 
      const result = compileCode(source); 
      if(result && !result.error) {
          reset(result.memory);
          
          if (result.extendedMemoryData && Object.keys(result.extendedMemoryData).length > 0) {
              const requiredSize = Math.max(...Object.keys(result.extendedMemoryData).map(k=>parseInt(k))) + 1;
              const size = Math.max(1024, requiredSize); // Default min 1024 words
              
              let newExtMemData = Array(size).fill(0);
              if (extendedMemory && extendedMemory.config.size >= size) {
                   newExtMemData = [...extendedMemory.data];
              }
              
              Object.entries(result.extendedMemoryData).forEach(([relAddr, val]) => {
                  newExtMemData[parseInt(relAddr)] = val;
              });
              
              setExtendedMemory({
                  version: 1,
                  config: extendedMemory ? extendedMemory.config : { size, kernelSpaceStart: -1, onDisabledKernel: 'disable' },
                  data: newExtMemData,
                  checksum: 0
              });
              addLog(`Loaded program into Extended Memory (${Object.keys(result.extendedMemoryData).length} words)`, "SYS");
          }

          setCode(source);
          setCompilationResult(result);
          const initialState: TraceInitialState = { type: 'initial', memory: result.memory, registers: { acc: 0, b: 0, c: 0, pc: 0, sp: STACK_START, flags: { zero: true, negative: false, carry: false }, privilegeLevel: 0, mmuBoundary: KERNEL_SPACE_START } };
          setExecutionTrace([initialState]);
      } 
  }

  const loadExample = (exampleKey: string) => {
    if (!exampleKey) return;
    const example = EXAMPLES[exampleKey];
    setCode(example.code);
    setSelectedExample(exampleKey);
    addLog(`Loaded example: ${example.name}`, "SYS");
    handleCompileAndLoad(example.code);
  };
  const saveCodeToLocal = () => { localStorage.setItem('ternary_computer_code', code); addLog('Code saved.', 'SYS'); };
  const loadCodeFromLocal = () => { const savedCode = localStorage.getItem('ternary_computer_code'); if (savedCode) { setCode(savedCode); handleCompileAndLoad(savedCode); addLog('Code loaded.', 'SYS'); } else { addLog('No code found.', 'SYS'); } };
  const exportStateToFile = () => {
      const state = { memory, accumulator, registerB, registerC, programCounter, stackPointer, flags, modes, privilegeLevel, mmu, floatRegisters, vectorRegisters, dma, heap, ternaryExpansionMemory, temDma, extendedMemory, hardDisks };
      const blob = new Blob([JSON.stringify(state, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob); const a = document.createElement('a'); a.href = url; a.download = 'state.json'; a.click(); URL.revokeObjectURL(url);
  };
  const exportTrace = () => {
    if (executionTrace.length <= 1) { addLog('No trace.', 'SYS'); return; }
    const blob = new Blob([JSON.stringify(executionTrace, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob); const a = document.createElement('a'); a.href = url; a.download = 'trace.json'; a.click(); URL.revokeObjectURL(url);
  };
  const importFromFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
      if (e.target.files && e.target.files[0]) {
          const file = e.target.files[0]; const text = await file.text();
          if (file.name.endsWith('.json')) {
              try { const state = JSON.parse(text); setMemory(state.memory); setAccumulator(state.accumulator); setRegisterB(state.registerB); setRegisterC(state.registerC); setProgramCounter(state.programCounter); setStackPointer(state.stackPointer); setFlags(state.flags); setModes(state.modes); setPrivilegeLevel(state.privilegeLevel); setMmu(state.mmu); setFloatRegisters(state.floatRegisters); setVectorRegisters(state.vectorRegisters); setDma(state.dma); setHeap(state.heap); if (state.ternaryExpansionMemory) setTernaryExpansionMemory(state.ternaryExpansionMemory); if (state.temDma) setTemDma(state.temDma); if (state.extendedMemory) setExtendedMemory(state.extendedMemory); if (state.hardDisks) setHardDisks(state.hardDisks); addLog('Imported.', 'SYS'); } catch (err) { addLog('Parse error.', 'ERR'); }
          } else { setCode(text); handleCompileAndLoad(text); }
      } e.target.value = '';
  };
  const importFromUrl = async (target: 'code' | 'ext_mem' | 'disk', diskId?: number) => {
      const url = prompt(`Enter URL:`); if (!url) return;
      try { const response = await fetch(url); if (!response.ok) throw new Error(`${response.status}`);
          if (target === 'code') { const text = await response.text(); setCode(text); handleCompileAndLoad(text); } 
          else { const fileData = await response.json(); if (target === 'ext_mem') handleLoadExtMem(fileData); else if (target === 'disk' && diskId !== undefined) handleLoadDisk(fileData, diskId, 'url.disk.json'); }
      } catch (err: any) { addLog(`Fetch error: ${err.message}`, 'ERR'); }
  };
  
  const confirmCreateExtMem = (config: ExtendedMemoryConfig) => { const data = Array(config.size).fill(0); const newExtMem: ExtendedMemory = { version: 1, config, data, checksum: 0 }; setExtendedMemory(newExtMem); addLog(`Created Ext RAM.`, 'SYS'); setShowCreateExtMemModal(false); };
  const handleLoadExtMem = (fileData: any) => { setExtendedMemory(fileData); addLog(`Loaded Ext Memory`, 'SYS'); };
  const handleImportExtMem = async (e: React.ChangeEvent<HTMLInputElement>) => { if (!e.target.files || !e.target.files[0]) return; const file = e.target.files[0]; try { const fileData = JSON.parse(await file.text()); handleLoadExtMem(fileData); } catch (err) { addLog(`Error reading Ext Mem`, 'ERR'); } e.target.value = ''; };
  const handleDownloadExtMem = () => { if (!extendedMemory) return; const blob = new Blob([JSON.stringify(extendedMemory, null, 2)], { type: 'application/json' }); const url = URL.createObjectURL(blob); const a = document.createElement('a'); a.href = url; a.download = 'ext.ram.json'; a.click(); URL.revokeObjectURL(url); };
  const confirmCreateDisk = (diskId: number, config: HardDiskConfig) => { const data = Array(config.size).fill(0); const newDisk: HardDisk = { version: 1, id: diskId, status: 'connected', busy: false, filename: `disk-${diskId}.json`, config, data, checksum: 0 }; setHardDisks(disks => disks.map((d, i) => i === diskId ? newDisk : d)); setShowCreateDiskModal(null); };
  const handleLoadDisk = (fileData: any, diskId: number, filename: string) => { const newDisk: HardDisk = {...fileData, id: diskId, status: 'connected', busy: false, filename }; setHardDisks(disks => disks.map((d, i) => i === diskId ? newDisk : d)); addLog(`Connected Disk ${diskId}`, 'SYS'); };
  const handleImportDisk = async (e: React.ChangeEvent<HTMLInputElement>, diskId: number) => { if (!e.target.files || !e.target.files[0]) return; const file = e.target.files[0]; try { const fileData = JSON.parse(await file.text()); handleLoadDisk(fileData, diskId, file.name); } catch (err) { addLog(`Error reading Disk`, 'ERR'); } e.target.value = ''; };
  const handleDownloadDisk = (diskId: number) => { const disk = hardDisks[diskId]; if (!disk) return; const blob = new Blob([JSON.stringify(disk, null, 2)], { type: 'application/json' }); const url = URL.createObjectURL(blob); const a = document.createElement('a'); a.href = url; a.download = disk.filename; a.click(); URL.revokeObjectURL(url); };
  const handleDisconnectDisk = (diskId: number) => { if(diskOperation?.diskId === diskId) setDiskOperation(null); setHardDisks(disks => disks.map((d, i) => i === diskId ? null : d)); addLog(`Disconnected Disk ${diskId}`, 'SYS'); };

  useEffect(() => { let timer: number | undefined; if (running) { timer = window.setInterval(cycle, speed); } return () => { if (timer) clearInterval(timer); }; }, [running, cycle, speed]);
  useEffect(() => { loadExample('factorial'); }, []);
  useEffect(() => { if (displayRef.current) { displayRef.current.scrollTop = displayRef.current.scrollHeight; } }, [externalDevices.display]);
  
  useEffect(() => {
      const handleKeyDown = (e: KeyboardEvent) => {
          if (!running) {
              if ((e.ctrlKey || e.metaKey) && e.key === 'z') { e.preventDefault(); handleUndo(); }
              if ((e.ctrlKey || e.metaKey) && e.key === 'y') { e.preventDefault(); handleRedo(); }
          }
      };
      window.addEventListener('keydown', handleKeyDown);
      return () => window.removeEventListener('keydown', handleKeyDown);
  }, [running, handleUndo, handleRedo]);

  const toggleBreakpoint = (addr: number) => setBreakpoints(prev => prev.includes(addr) ? prev.filter(b => b !== addr) : [...prev, addr]);
  const toggleWatchpoint = (addr: number) => setWatchpoints(prev => prev.includes(addr) ? prev.filter(w => w !== addr) : [...prev, addr]);
  const handleKeyboardInput = (e: React.KeyboardEvent<HTMLInputElement>) => { if (e.key === 'Enter') { const input = (e.target as HTMLInputElement).value; const charCodes = input.split('').map(char => char.charCodeAt(0)); setExternalDevices(prev => ({...prev, keyboardBuffer: [...prev.keyboardBuffer, ...charCodes, 10], keyboardInput: ''})); addLog(`Pushed input`, 'I/O'); (e.target as HTMLInputElement).value = ''; handleInterrupt(6); } };
  const handlePixelClick = (x: number, y: number) => { if (running) return; setRegisterB(x); setRegisterC(y); handleInterrupt(9); };
  const handleTemClick = (addr: number) => { if (running) return; setTernaryExpansionMemory(prev => { const newMem = [...prev]; const val = newMem[addr]; newMem[addr] = val === 0 ? 1 : val === 1 ? -1 : 0; return newMem; }); };
  
  const speedDisplay = useMemo(() => { if (speed < 1000) return `${(1000 / speed).toFixed(1)} Hz`; else return `${(speed / 1000).toFixed(2)} s/op`; }, [speed]);
  const getModeLabel = (key: keyof Modes) => { if (key === 'dmaEnabled') return 'DMA'; if (key === 'temEnabled') return 'TEM'; const label = key.replace('Mode', '').replace('Enabled', ''); return label.charAt(0).toUpperCase() + label.slice(1); };
  
  const getPrivilegeName = (level: number) => {
    switch(level) {
        case -3: return 'Hardware/Logic';
        case -2: return 'Security Monitor';
        case -1: return 'Hypervisor';
        case 0: return 'Kernel';
        case 1: return 'User';
        case 2: return 'Sandbox';
        case 3: return 'Public Plugin';
        default: return `Unknown (${level})`;
    }
  };

  const getPrivilegeColor = (level: number) => {
      if (level <= -2) return 'text-purple-400';
      if (level === -1) return 'text-orange-400';
      if (level === 0) return 'text-red-400';
      if (level === 1) return 'text-blue-400';
      if (level === 2) return 'text-yellow-400';
      return 'text-gray-400';
  };

  const renderMemoryGrid = (start: number, end: number, title: string, className: string = '') => (
    <div className={`bg-black/30 rounded-lg p-4 ${className}`}>
      <h2 className="text-lg font-bold text-cyan-300 mb-3">{title}</h2>
      <div className={`grid grid-cols-4 sm:grid-cols-8 gap-2`}>
        {memory.slice(start, end).map((value, index) => {
          const addr = start + index;
          const isPC = programCounter === addr, isBreakpoint = modes.debugMode && breakpoints.includes(addr);
          const isWatchpoint = modes.debugMode && watchpoints.includes(addr), isSP = stackPointer === addr;
          let bgColor = 'bg-white/5'; let borderColor = 'border-white/20';
          if (isPC) { bgColor = 'bg-yellow-400/20'; borderColor='border-yellow-400'; } else if (isSP) { bgColor = 'bg-green-400/20'; borderColor='border-green-400'; }
          return (
            <div key={addr} className={`p-2 rounded border-2 relative transition-colors duration-300 ${borderColor} ${bgColor}`}>
              <div className="text-xs text-gray-300 mb-1 cursor-pointer hover:text-white flex items-center justify-between">
                <div>{isBreakpoint && <span className="text-red-500 absolute top-0 left-1 text-lg" onClick={() => toggleBreakpoint(addr)}>●</span>}<span className="ml-4" onClick={() => toggleBreakpoint(addr)}>{addr}</span></div>
                {isWatchpoint ? <Eye className="w-4 h-4 text-purple-400 cursor-pointer" onClick={() => toggleWatchpoint(addr)}/> : <Eye className="w-4 h-4 text-gray-500 cursor-pointer hover:text-purple-400" onClick={() => toggleWatchpoint(addr)}/>}
              </div>
              <input type="number" value={value} onChange={(e) => { const newMem = [...memory]; newMem[addr] = parseInt(e.target.value) || 0; setMemory(newMem); }} disabled={running} className="w-full bg-black/50 text-white p-1 rounded text-xs text-center"/>
            </div>
          );
        })}
      </div>
    </div>
  );
  const renderFlag = (name: string, value: boolean) => (<div className={`px-2 py-1 rounded text-xs ${value ? 'bg-green-500' : 'bg-red-500'}`}>{name}</div>);
  const renderPipelineStage = (stageName: string, stageData: PipelineStageInfo | any) => {
    let content = <span className="text-gray-500">--- Empty ---</span>;
    if (!stageData && (pipeline.execute?.isBranchTaken || pipeline.memory?.isBranchTaken) && (stageName === 'Decode (ID)' || stageName === 'Fetch (IF)')) return (<div className="bg-black/40 p-3 rounded-lg flex-1 text-center"><h3 className="text-sm font-bold text-cyan-400 mb-1">{stageName}</h3><div className="font-mono text-xs h-6 flex items-center justify-center"><span className="text-yellow-500">--- Flush ---</span></div></div>);
    if (stageData) {
        const opcode = stageData.opcode ?? stageData.instruction;
        const name = INSTRUCTIONS[String(opcode)]?.name || '???';
        content = <span>{name} {stageData.operand !== undefined ? stageData.operand : ''}</span>;
    }
    return (<div className="bg-black/40 p-3 rounded-lg flex-1 text-center"><h3 className="text-sm font-bold text-cyan-400 mb-1">{stageName}</h3><div className="font-mono text-xs h-6 flex items-center justify-center">{content}</div></div>);
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-900 via-blue-900 to-indigo-900 text-white p-2 sm:p-4 font-sans">
      <div className="max-w-7xl mx-auto">
        <div className="bg-white/10 backdrop-blur-lg rounded-2xl p-4 sm:p-6 shadow-2xl border border-white/20">
          {/* Header and Tab Buttons */}
          <div className="flex flex-col sm:flex-row items-center justify-between mb-6">
             <div className="flex items-center gap-3 mb-4 sm:mb-0"><Brain className="w-8 h-8 text-cyan-300" /><h1 className="text-2xl sm:text-3xl font-bold text-white">Ternary Computer Simulator</h1></div>
             <div className="flex gap-2">
                <button onClick={() => setActiveTab('code')} className={`p-2 rounded-lg ${activeTab === 'code' ? 'bg-cyan-500' : 'bg-white/20'}`} title="Code Editor"><Code className="w-5 h-5" /></button>
                <button onClick={() => setActiveTab('memory')} className={`p-2 rounded-lg ${activeTab === 'memory' ? 'bg-cyan-500' : 'bg-white/20'}`} title="CPU & Memory"><Cpu className="w-5 h-5" /></button>
                <button onClick={() => setActiveTab('tem')} className={`p-2 rounded-lg ${activeTab === 'tem' ? 'bg-cyan-500' : 'bg-white/20'}`} title="TEM"><Triangle className="w-5 h-5" /></button>
                <button onClick={() => setActiveTab('storage')} className={`p-2 rounded-lg ${activeTab === 'storage' ? 'bg-cyan-500' : 'bg-white/20'}`} title="Storage"><HardDrive className="w-5 h-5" /></button>
                <button onClick={() => setActiveTab('io')} className={`p-2 rounded-lg ${activeTab === 'io' ? 'bg-cyan-500' : 'bg-white/20'}`} title="I/O"><Layers className="w-5 h-5" /></button>
                <button onClick={() => setActiveTab('isa')} className={`p-2 rounded-lg ${activeTab === 'isa' ? 'bg-cyan-500' : 'bg-white/20'}`} title="ISA"><BookOpen className="w-5 h-5" /></button>
             </div>
          </div>
          
          {activeTab === 'isa' ? ( <InstructionSetPage onBack={() => setActiveTab('code')} /> ) : (
            <>
              {/* Controls */}
              <div className="grid grid-cols-2 lg:grid-cols-6 gap-2 mb-4">
                  <button onClick={() => setRunning(!running)} className={`p-2 rounded-lg text-white flex items-center justify-center gap-2 ${running ? 'bg-red-500' : 'bg-green-500'}`}><Play className="w-5 h-5"/> {running ? 'Pause' : 'Run'}</button>
                  <button onClick={cycle} disabled={running} className="p-2 rounded-lg bg-blue-500 text-white flex items-center justify-center gap-2 disabled:bg-gray-600"><Zap className="w-5 h-5"/> Step</button>
                  <button onClick={stepOver} disabled={running} className="p-2 rounded-lg bg-blue-500 text-white flex items-center justify-center gap-2 disabled:bg-gray-600"><SkipForward className="w-5 h-5"/> Step Over</button>
                  <button onClick={()=>handleCompileAndLoad(code)} className="p-2 rounded-lg bg-gray-500 text-white flex items-center justify-center gap-2"><RotateCcw className="w-5 h-5"/> Reset</button>
                  <div className="col-span-2 flex items-center bg-black/30 p-2 rounded-lg">
                      <label htmlFor="speed" className="text-xs mr-2">Speed</label>
                      <input type="range" min="1" max="1000" step="1" value={speed} onChange={e => setSpeed(parseInt(e.target.value))} className="w-full h-2 bg-gray-700 rounded-lg appearance-none cursor-pointer"/>
                      <div className="text-xs w-20 text-center font-mono">{speedDisplay}</div>
                  </div>
              </div>
              
              {/* Direct Control Panel */}
              <div className="mb-4 p-3 bg-black/30 rounded-lg animate-fade-in flex flex-col sm:flex-row gap-3 items-center">
                 <h3 className="text-sm font-bold text-cyan-300 whitespace-nowrap">Direct Control:</h3>
                 <div className="flex-grow flex gap-2 w-full">
                     <input type="text" value={manualCommand} onChange={e => setManualCommand(e.target.value)} onKeyDown={e => { if(e.key === 'Enter') handleManualExecute(); }} placeholder="Type instruction (e.g., LOAD 5)..." className="flex-grow bg-black/50 text-white p-2 text-sm rounded border border-white/20 font-mono" disabled={running} />
                     <button onClick={handleManualExecute} disabled={running || !manualCommand} className="px-3 py-1 bg-cyan-600 rounded text-sm disabled:bg-gray-600 hover:bg-cyan-500">Exec</button>
                 </div>
                 <div className="flex gap-2 items-center">
                     <button onClick={handleUndo} disabled={machineHistory.length === 0 || running} title="Undo (Ctrl+Z)" className="p-2 bg-white/10 rounded hover:bg-white/20 disabled:opacity-30"><RotateCcw className="w-4 h-4 transform -scale-x-100"/></button>
                     <button onClick={handleRedo} disabled={machineFuture.length === 0 || running} title="Redo (Ctrl+Y)" className="p-2 bg-white/10 rounded hover:bg-white/20 disabled:opacity-30"><RotateCcw className="w-4 h-4"/></button>
                     <label className="flex items-center gap-2 text-xs cursor-pointer select-none">
                         <input type="checkbox" checked={manualConfig.keepOnReset} onChange={e => setManualConfig({...manualConfig, keepOnReset: e.target.checked})} className="rounded bg-gray-700 border-gray-500"/>
                         <span>Keep History</span>
                     </label>
                 </div>
              </div>

              {modes.pipelineEnabled && ( <div className="mb-4 p-4 bg-black/30 rounded-lg animate-fade-in"><h2 className="text-lg font-bold text-cyan-300 mb-3 text-center">5-Stage Pipeline</h2><div className="flex flex-col sm:flex-row gap-2">{renderPipelineStage('Fetch (IF)', pipeline.fetch ? { ...pipeline.fetch, opcode: pipeline.fetch.instruction, operand: memory[pipeline.fetch.address + 1] } : null)}{renderPipelineStage('Decode (ID)', pipeline.decode)}{renderPipelineStage('Execute (EX)', pipeline.execute)}{renderPipelineStage('Memory (MEM)', pipeline.memory)}{renderPipelineStage('Write-back (WB)', pipeline.writeBack)}</div></div> )}

              {activeTab === 'code' && (<div className="animate-fade-in space-y-4"><div className="grid grid-cols-1 md:grid-cols-2 gap-4"><div><label htmlFor="example-select" className="block text-sm font-medium text-gray-300 mb-1">Load Example</label><select id="example-select" value={selectedExample} onChange={(e) => loadExample(e.target.value)} className="bg-white/10 border border-white/20 text-white text-sm rounded-lg focus:ring-cyan-500 focus:border-cyan-500 block w-full p-2.5"><option value="">Select an example...</option>{Object.entries(EXAMPLES).map(([key, ex]) => <option key={key} value={key}>{ex.name}</option>)}</select></div><div className="flex items-end gap-2"><button onClick={saveCodeToLocal} className="p-2.5 bg-white/20 rounded-lg text-sm w-full flex items-center justify-center gap-2"><Save className="w-4 h-4"/>Save</button><button onClick={loadCodeFromLocal} className="p-2.5 bg-white/20 rounded-lg text-sm w-full flex items-center justify-center gap-2"><FolderOpen className="w-4 h-4"/>Load</button></div></div><AssemblyEditor code={code} setCode={setCode} onCompile={()=>handleCompileAndLoad()} running={running} breakpoints={breakpoints} setBreakpoints={setBreakpoints} compilationResult={compilationResult} programCounter={programCounter}/><div className="grid grid-cols-1 md:grid-cols-3 gap-2 text-sm"><button onClick={() => fileInputRef.current?.click()} className="p-2 bg-indigo-500 rounded-lg flex items-center justify-center gap-2"><Upload className="w-4 h-4"/>Import from File</button><input type="file" ref={fileInputRef} onChange={importFromFile} className="hidden" accept=".asm,.txt,.json"/><button onClick={() => importFromUrl('code')} className="p-2 bg-indigo-500 rounded-lg flex items-center justify-center gap-2"><Link className="w-4 h-4"/>Import from URL</button><button onClick={exportStateToFile} className="p-2 bg-indigo-500 rounded-lg flex items-center justify-center gap-2"><Download className="w-4 h-4"/>Export State</button></div></div>)}

              {activeTab === 'memory' && (<div className="grid grid-cols-1 lg:grid-cols-3 gap-4 animate-fade-in">
                <div className="lg:col-span-2 space-y-4">
                  {!modes.privilegedMode ? ( renderMemoryGrid(0, 128, 'Main Memory (0-127)') ) : ( <>{renderMemoryGrid(0, mmu.boundaryRegister, 'User Space', 'border-2 border-blue-500/50')}{renderMemoryGrid(mmu.boundaryRegister, MEMORY_SIZE, 'Kernel & IVT Space', 'border-2 border-red-500/50')}</> )}
                  {extendedMemory && (
                      <div className="bg-black/30 rounded-lg p-4 border-2 border-purple-500/30">
                          <h2 className="text-lg font-bold text-cyan-300 mb-3">Extended Memory Preview (First 64 words)</h2>
                          <div className={`grid grid-cols-4 sm:grid-cols-8 gap-2`}>
                              {extendedMemory.data.slice(0, 64).map((val, idx) => {
                                  const realAddr = MEMORY_SIZE + idx;
                                  const isPC = programCounter === realAddr;
                                  return <div key={realAddr} className={`p-2 rounded border border-white/10 bg-white/5 text-center text-xs relative ${isPC ? 'border-yellow-400 bg-yellow-400/20' : ''}`}><div className="text-gray-500 mb-1">{realAddr}</div>{val}</div>;
                              })}
                          </div>
                      </div>
                  )}
                </div>
                <div className="space-y-4">
                    <div className="bg-black/30 rounded-lg p-4">
                      <h2 className="text-lg font-bold text-cyan-300 mb-3">CPU Registers</h2>
                      <div className="grid grid-cols-2 gap-2 text-sm">
                        {['PC', 'ACC', 'REG B', 'REG C', 'SP'].map(reg => <div key={reg} className="bg-white/5 p-2 rounded flex justify-between items-center font-mono"><span className="text-gray-300">{reg}</span><span className="font-bold">{reg === 'PC' ? programCounter : reg === 'ACC' ? accumulator : reg === 'REG B' ? registerB : reg === 'REG C' ? registerC : stackPointer}</span></div>)}
                      </div>
                      <div className="flex gap-2 mt-2">{renderFlag('Z', flags.zero)}{renderFlag('N', flags.negative)}{renderFlag('C', flags.carry)}</div>
                    </div>
                    <div className="bg-black/30 rounded-lg p-4">
                        <h2 className="text-lg font-bold text-cyan-300 mb-3">Core Modes</h2>
                        <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 text-sm">
                            <label className="flex items-center gap-2 bg-white/5 p-2 rounded cursor-pointer hover:bg-white/10"><input type="checkbox" checked={modes.pipelineEnabled} onChange={() => setModes(m => ({...m, pipelineEnabled: !m.pipelineEnabled}))} className="form-checkbox h-4 w-4 text-cyan-400 bg-gray-800 border-gray-600 rounded focus:ring-cyan-500" /><span>Pipeline</span></label>
                            {(['privilegedMode', 'floatMode', 'vectorMode', 'dmaEnabled', 'temEnabled'] as Array<keyof Modes>).map(key => ( <label key={key} className="flex items-center gap-2 bg-white/5 p-2 rounded cursor-pointer hover:bg-white/10"><input type="checkbox" checked={modes[key]} onChange={() => { if(key === 'privilegedMode' && !modes.privilegedMode) setPrivilegeLevel(0); setModes(m => ({...m, [key]: !m[key]})) }} className="form-checkbox h-4 w-4 text-cyan-400 bg-gray-800 border-gray-600 rounded focus:ring-cyan-500" /><span>{getModeLabel(key)}</span></label> ))}
                        </div>
                    </div>
                    
                    {modes.privilegedMode && (
                        <div className="bg-black/30 rounded-lg p-4 animate-fade-in border-2 border-red-500/30">
                            <h2 className="text-lg font-bold text-cyan-300 mb-3 flex items-center gap-2"><AlertCircle className="w-4 h-4 text-red-400"/> Privileged Control</h2>
                            <div className="grid grid-cols-2 gap-2 text-sm">
                                <div className="bg-white/5 p-2 rounded flex justify-between items-center font-mono col-span-2">
                                    <span className="text-gray-300">Level</span>
                                    <span className={`font-bold ${getPrivilegeColor(privilegeLevel)}`}>{getPrivilegeName(privilegeLevel)} ({privilegeLevel})</span>
                                </div>
                                <div className="bg-white/5 p-2 rounded flex justify-between items-center font-mono"><span className="text-gray-300">MMU</span><span className="font-bold text-orange-400">{mmu.boundaryRegister}</span></div>
                                <div className="bg-white/5 p-2 rounded flex justify-between items-center font-mono"><span className="text-gray-300">Stack</span><span className="font-bold text-green-400">{stackPointer}</span></div>
                                <div className="bg-white/5 p-2 rounded flex justify-between items-center font-mono"><span className="text-gray-300">IVT Base</span><span className="font-bold">{INTERRUPT_VECTOR_TABLE_BASE}</span></div>
                                <div className="bg-white/5 p-2 rounded flex justify-between items-center font-mono"><span className="text-gray-300">Active INT</span><span className="font-bold text-yellow-400">{interrupts.activeVector !== null ? interrupts.activeVector : '-'}</span></div>
                                <div className="bg-white/5 p-2 rounded flex justify-between items-center font-mono"><span className="text-gray-300">Pending</span><span className="font-bold">{interrupts.pending.length}</span></div>
                                <div className="bg-white/5 p-2 rounded flex justify-between items-center font-mono col-span-2"><label className="flex items-center gap-2 cursor-pointer"><input type="checkbox" checked={modes.interruptEnabled} onChange={() => setModes(m => ({...m, interruptEnabled: !m.interruptEnabled}))} className="form-checkbox h-3 w-3"/><span>Interrupts Enabled</span></label></div>
                            </div>
                        </div>
                    )}
                </div>
              </div>)}

              {activeTab === 'tem' && (
                  <div className="animate-fade-in">
                    <div className="bg-black/30 rounded-lg p-4 mb-4">
                         <div className="flex justify-between items-center mb-3">
                            <h2 className="text-lg font-bold text-cyan-300">Ternary Expansion Memory (729 Trits)</h2>
                            {modes.privilegedMode && <div className="text-xs text-gray-400">Kernel Boundary: {mmu.temBoundaryRegister}</div>}
                         </div>
                         {!modes.temEnabled ? ( <div className="text-center p-8 text-gray-400">TEM is currently disabled. Enable it in the CPU & Memory tab.</div> ) : (
                             <div className="grid grid-cols-[repeat(auto-fill,minmax(30px,1fr))] gap-1">
                                 {ternaryExpansionMemory.map((val, i) => {
                                     const isBoundary = modes.privilegedMode && i === mmu.temBoundaryRegister;
                                     const isKernel = modes.privilegedMode && i >= mmu.temBoundaryRegister;
                                     let bg = val === 0 ? 'bg-gray-700' : val === 1 ? 'bg-cyan-600' : 'bg-red-600';
                                     if(isKernel) bg += ' opacity-60';
                                     return (
                                         <div key={i} onClick={()=>handleTemClick(i)} className={`${bg} h-8 flex items-center justify-center text-xs cursor-pointer hover:opacity-80 rounded relative border border-black/20 select-none text-white font-bold`} title={`TEM[${i}] = ${val}`}>
                                             {val === -1 ? '-' : val === 1 ? '+' : '0'}
                                             {isBoundary && <div className="absolute top-0 left-0 w-full h-0.5 bg-yellow-500 z-10"></div>}
                                         </div>
                                     );
                                 })}
                             </div>
                         )}
                    </div>
                  </div>
              )}

              {activeTab === 'storage' && (
                  <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 animate-fade-in">
                      <div className="bg-black/30 rounded-lg p-4">
                          <h2 className="text-lg font-bold text-cyan-300 mb-3">Extended RAM Module</h2>
                          {!extendedMemory ? (
                             <div className="text-center p-8 border-2 border-dashed border-gray-600 rounded-lg">
                                 <p className="text-gray-400 mb-4">No Extended Memory Module Installed</p>
                                 <div className="flex justify-center gap-2">
                                     <button onClick={()=>setShowCreateExtMemModal(true)} className="px-4 py-2 bg-blue-600 rounded hover:bg-blue-500">Create New</button>
                                     <button onClick={() => extMemFileInputRef.current?.click()} className="px-4 py-2 bg-gray-600 rounded hover:bg-gray-500">Load File</button>
                                     <input type="file" ref={extMemFileInputRef} onChange={handleImportExtMem} className="hidden" accept=".json"/>
                                 </div>
                             </div>
                          ) : (
                             <div className="space-y-3">
                                 <div className="bg-white/5 p-3 rounded flex justify-between"><span>Size</span><span className="font-mono">{extendedMemory.config.size} words</span></div>
                                 <div className="bg-white/5 p-3 rounded flex justify-between"><span>Kernel Start</span><span className="font-mono">{extendedMemory.config.kernelSpaceStart ?? 'None'}</span></div>
                                 <div className="grid grid-cols-2 gap-2 mt-4">
                                     <button onClick={handleDownloadExtMem} className="p-2 bg-indigo-600 rounded text-sm">Export .json</button>
                                     <button onClick={()=>setExtendedMemory(null)} className="p-2 bg-red-600 rounded text-sm">Eject</button>
                                 </div>
                             </div>
                          )}
                          {showCreateExtMemModal && <CreateExtMemModal onConfirm={confirmCreateExtMem} onCancel={()=>setShowCreateExtMemModal(false)} />}
                      </div>
                      
                      <div className="space-y-4">
                          {hardDisks.map((disk, i) => (
                              <div key={i} className="bg-black/30 rounded-lg p-4">
                                  <h2 className="text-lg font-bold text-cyan-300 mb-3 flex justify-between">
                                      <span>Hard Disk {i}</span>
                                      {disk && <span className={`text-xs px-2 py-1 rounded ${disk.busy ? 'bg-yellow-500 text-black' : 'bg-green-500'}`}>{disk.busy ? 'BUSY' : 'READY'}</span>}
                                  </h2>
                                  {!disk ? (
                                      <div className="text-center p-4 border-2 border-dashed border-gray-600 rounded-lg">
                                         <button onClick={()=>setShowCreateDiskModal(i)} className="text-sm text-blue-400 hover:underline">Create/Connect Disk</button>
                                         <div className="mt-2 text-xs text-gray-500">or <span className="cursor-pointer hover:text-white" onClick={()=>diskFileInputRefs.current[i]?.click()}>Load File</span></div>
                                         <input type="file" ref={el => diskFileInputRefs.current[i] = el} onChange={(e)=>handleImportDisk(e, i)} className="hidden" accept=".json"/>
                                      </div>
                                  ) : (
                                      <div className="space-y-2 text-sm">
                                          <div className="flex justify-between"><span>Size:</span> <span>{disk.config.size}</span></div>
                                          <div className="flex justify-between"><span>Partitions:</span> <span>{disk.config.partitions.length}</span></div>
                                          <div className="flex justify-between"><span>Filename:</span> <span className="text-gray-400">{disk.filename}</span></div>
                                          <div className="flex gap-2 mt-2">
                                              <button onClick={()=>handleDownloadDisk(i)} className="flex-1 p-1 bg-indigo-600 rounded text-xs">Save</button>
                                              <button onClick={()=>handleDisconnectDisk(i)} className="flex-1 p-1 bg-red-600 rounded text-xs">Disconnect</button>
                                          </div>
                                      </div>
                                  )}
                                  {showCreateDiskModal === i && <CreateDiskModal diskId={i} onConfirm={confirmCreateDisk} onCancel={()=>setShowCreateDiskModal(null)} />}
                              </div>
                          ))}
                      </div>
                  </div>
              )}

              {activeTab === 'io' && (
                  <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 animate-fade-in">
                      <div className="bg-black/30 rounded-lg p-4 flex flex-col">
                          <h2 className="text-lg font-bold text-cyan-300 mb-3">TTY Display (Port 0)</h2>
                          <div className="relative flex-grow bg-black border border-gray-700 rounded p-2 font-mono text-green-400 text-sm min-h-[200px] overflow-hidden">
                               <pre ref={displayRef} className="absolute inset-0 overflow-y-auto p-2 whitespace-pre-wrap break-all">
                                   {externalDevices.display}
                                   <span className="animate-pulse inline-block w-2 h-4 bg-green-400 align-middle ml-1"></span>
                               </pre>
                          </div>
                          <div className="mt-3 flex gap-2">
                              <input type="text" placeholder="Keyboard Input (Enter to send)" onKeyDown={handleKeyboardInput} className="flex-grow bg-gray-800 border border-gray-600 rounded p-2 text-white text-sm"/>
                              <div className="bg-gray-700 p-2 rounded text-xs text-gray-300 flex items-center">Buf: {externalDevices.keyboardBuffer.length}</div>
                          </div>
                      </div>
                      
                      <div className="bg-black/30 rounded-lg p-4 flex flex-col items-center">
                          <h2 className="text-lg font-bold text-cyan-300 mb-3">Pixel Display (32x32)</h2>
                          <div className="bg-black border border-gray-700 p-1 inline-block shadow-lg">
                              <div className="grid grid-cols-[repeat(32,10px)] grid-rows-[repeat(32,10px)] gap-[1px] bg-gray-900">
                                  {externalDevices.pixelScreenBuffer.map((colorVal, idx) => {
                                      const x = idx % PIXEL_SCREEN_WIDTH;
                                      const y = Math.floor(idx / PIXEL_SCREEN_WIDTH);
                                      let color = DEFAULT_PIXEL_COLOR;
                                      if (typeof colorVal === 'number') {
                                          const r = (colorVal >> 16) & 0xFF;
                                          const g = (colorVal >> 8) & 0xFF;
                                          const b = colorVal & 0xFF;
                                          color = `rgb(${r},${g},${b})`;
                                      } else {
                                          color = colorVal;
                                      }
                                      return (
                                          <div key={idx} 
                                               style={{backgroundColor: color}} 
                                               className="w-full h-full cursor-pointer hover:opacity-80" 
                                               title={`(${x},${y})`}
                                               onClick={() => handlePixelClick(x, y)}
                                          />
                                      );
                                  })}
                              </div>
                          </div>
                          <div className="mt-2 text-xs text-gray-400">
                              Ports: 10(X), 11(Y), 12(Color/Draw). Interrupt Vector: 9
                          </div>
                      </div>
                  </div>
              )}

              <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mt-4 h-64">
                <div className="lg:col-span-2 bg-black/30 rounded-lg p-4 flex flex-col">
                   <h2 className="text-lg font-bold text-cyan-300 mb-2 flex justify-between items-center">
                       <span>System Log</span>
                       <button onClick={() => setLog([])} className="text-xs text-gray-400 hover:text-white">Clear</button>
                   </h2>
                   <div ref={logContainerRef} className="flex-grow overflow-y-auto font-mono text-xs space-y-1 bg-black/20 p-2 rounded border border-white/5">
                       {log.length === 0 && <div className="text-gray-600 italic">System ready.</div>}
                       {log.map((entry, i) => {
                           const isErr = entry.includes('[ERR]') || entry.includes('Fault');
                           return <div key={i} className={`${isErr ? 'text-red-400' : 'text-gray-300'}`}>{entry}</div>
                       })}
                   </div>
                </div>
                <div className="bg-black/30 rounded-lg p-4 flex flex-col">
                   <h2 className="text-lg font-bold text-cyan-300 mb-2 flex justify-between items-center">
                       <span>Execution Trace</span>
                       <div className="flex gap-2">
                           <label className="flex items-center gap-1 text-xs cursor-pointer"><input type="checkbox" checked={isRecordingTrace} onChange={(e)=>setIsRecordingTrace(e.target.checked)} className="form-checkbox h-3 w-3"/> Rec</label>
                           <button onClick={exportTrace} disabled={executionTrace.length===0} className="text-xs text-blue-400 hover:text-blue-300 disabled:text-gray-600">Export</button>
                       </div>
                   </h2>
                   <div className="flex-grow overflow-y-auto font-mono text-xs bg-black/20 p-2 rounded border border-white/5">
                       {executionTrace.length === 0 ? (
                           <div className="text-gray-600 italic">Trace buffer empty.</div>
                       ) : (
                           <div className="space-y-1">
                               <div className="text-gray-500">Buffer: {executionTrace.length} cycles</div>
                               {executionTrace.slice(-10).reverse().map((entry, i) => {
                                   if (entry.type === 'initial') return <div key={i} className="text-blue-400">-- Initial State --</div>;
                                   return (
                                       <div key={i} className="border-l-2 border-gray-700 pl-2 mb-1">
                                           <div className="text-yellow-500">Cyc {entry.cycle} | PC:{entry.pc} | {entry.instruction.name}</div>
                                           {Object.entries(entry.registerChanges).map(([reg, delta]) => (
                                               <div key={reg} className="text-gray-400 pl-2">{reg.toUpperCase()}: {(delta as any).from} &rarr; <span className="text-white">{(delta as any).to}</span></div>
                                           ))}
                                       </div>
                                   );
                               })}
                           </div>
                       )}
                   </div>
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
};

export default TernaryComputer;
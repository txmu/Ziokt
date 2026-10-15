export interface Flags {
  zero: boolean;
  negative: boolean;
  carry: boolean;
}

export interface Modes {
  pipelineEnabled: boolean;
  interruptEnabled: boolean;
  privilegedMode: boolean;
  debugMode: boolean;
  floatMode: boolean;
  vectorMode: boolean;
  cacheEnabled: boolean;
  dmaEnabled: boolean;
  temEnabled: boolean;
}

export interface PipelineFetchStage {
  instruction: number;
  address: number;
}

export interface PipelineStageInfo {
  opcode: number;
  operand?: number;
  address: number;
  // For execution results
  result?: number;
  memValue?: number;
  isBranchTaken?: boolean;
}


export interface Pipeline {
  fetch: PipelineFetchStage | null;
  decode: PipelineStageInfo | null;
  execute: PipelineStageInfo | null;
  memory: PipelineStageInfo | null;
  writeBack: PipelineStageInfo | null;
}

export interface Interrupts {
  pending: number[];
  vector: number;
  handlerAddress: number;
  activeVector: number | null; // Tracks the current ISR vector for priority
}

export interface ExternalDevices {
  keyboardInput: string;
  keyboardBuffer: number[];
  display: string;
  cursorPosition: number;
  pixelScreenBuffer: (string|number)[];
  fileSystem: any[];
}

export interface InstructionInfo {
  name: string;
  desc: {
    en: string;
    zh: string;
  };
}

export interface InstructionsMap {
  [key: string]: InstructionInfo;
}

export interface CacheLine {
  tag: number; // memory address
  data: number;
  lastUsed: number; // for LRU
}

export interface Watchpoint {
  address: number;
}

export interface CompilationResult {
  memory: number[];
  lineAddressMap: { [line: number]: number };
  addressLineMap: { [address: number]: number };
  error?: string | null;
  errorLine?: number | null;
}

// Types for Execution Trace Export
export interface TraceRegisterState {
    acc: number;
    b: number;
    c: number;
    pc: number;
    sp: number;
    flags: Flags;
    // Added for advanced modes
    privilegeLevel?: number;
    mmuBoundary?: number;
}

export interface TraceRegisterDelta {
    acc?: { from: number; to: number };
    b?: { from: number; to: number };
    c?: { from: number; to: number };
    pc?: { from: number; to: number };
    sp?: { from: number; to: number };
    flags?: { from: Flags; to: Flags };
    privilegeLevel?: { from: number; to: number };
    mmuBoundary?: { from: number; to: number };
}


export interface TraceInitialState {
    type: 'initial';
    memory: number[];
    registers: TraceRegisterState;
}

export interface TraceDelta {
    type: 'delta';
    cycle: number;
    pc: number;
    instruction: {
        opcode: number;
        name: string;
        operand?: number;
    };
    memoryChanges: { [address: number]: { from: number; to: number } };
    extendedMemoryChanges: { [address: number]: { from: number; to: number } };
    temChanges: { [address: number]: { from: number; to: number } };
    hardDiskChanges: { [diskId: number]: { [address: number]: { from: number; to: number } } };
    registerChanges: TraceRegisterDelta;
}

export type TraceEntry = TraceInitialState | TraceDelta;

// Advanced Mode Types
export interface FloatRegisters {
  [key: string]: number; // f0, f1, f2, f3
}

export const VECTOR_SIZE = 4;
export interface VectorRegisters {
  [key: string]: number[]; // v0, v1, v2, v3
}

export interface DMAController {
    source: number;
    destination: number;
    count: number;
    status: 'idle' | 'busy' | 'done';
}

export interface TDMAController {
    source: number;
    destination: number;
    count: number;
    direction: 'mem_to_tem' | 'tem_to_mem';
    status: 'idle' | 'busy' | 'done';
}

export interface MMU {
    boundaryRegister: number;
    temBoundaryRegister: number;
}

export interface Heap {
    start: number;
    end: number;
    freeListHead: number;
}

// Extended Storage Types
export interface ExtendedMemoryConfig {
    size: number;
    kernelSpaceStart: number | null;
    onDisabledKernel: 'disable' | 'mapToUser';
}
export interface ExtendedMemory {
    version: number;
    config: ExtendedMemoryConfig;
    data: number[];
    checksum: number;
}

export interface Partition {
    start: number;
    size: number;
    type: string;
}

export interface HardDiskConfig {
    size: number;
    partitions: Partition[];
}

export interface HardDisk {
    version: number;
    id: number;
    config: HardDiskConfig;
    data: number[];
    status: 'connected' | 'disconnected';
    filename: string;
    busy: boolean;
    checksum: number;
}

export interface DiskOperation {
    type: 'read' | 'write' | 'trim';
    diskId: number;
    memAddr: number;
    diskAddr: number;
    count: number;
    progress: number;
}

export interface ManualControlConfig {
    keepOnReset: boolean;
}

// Snapshot for Undo/Redo
export interface MachineSnapshot {
    memory: number[];
    extendedMemoryData: number[] | null;
    accumulator: number;
    registerB: number;
    registerC: number;
    programCounter: number;
    stackPointer: number;
    flags: Flags;
    ternaryExpansionMemory: number[];
}
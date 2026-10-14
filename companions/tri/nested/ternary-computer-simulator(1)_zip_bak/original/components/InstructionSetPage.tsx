import React from 'react';
import { INSTRUCTIONS } from '../constants';
import { RotateCcw } from './icons';

const InstructionSetPage: React.FC<{ onBack: () => void }> = ({ onBack }) => {
  return (
    <div className="animate-fade-in">
      <div className="flex justify-between items-center mb-4">
        <h2 className="text-2xl font-bold text-cyan-300">Instruction Set (EN/ZH)</h2>
        <button onClick={onBack} className="flex items-center gap-2 px-4 py-2 bg-cyan-500 hover:bg-cyan-600 text-white rounded-lg">
          <RotateCcw className="w-5 h-5" /> Back to Simulator
        </button>
      </div>
      <div className="max-h-[75vh] overflow-y-auto">
        <table className="w-full text-sm text-left text-gray-300">
            <thead className="bg-white/10 text-xs uppercase sticky top-0">
                <tr>
                    <th className="p-2">Opcode</th>
                    <th className="p-2">Name</th>
                    <th className="p-2">Description</th>
                    <th className="p-2">中文描述</th>
                </tr>
            </thead>
            <tbody>
                {Object.entries(INSTRUCTIONS).sort((a,b) => parseInt(a[0]) - parseInt(b[0])).map(([opcode, {name, desc}]) => (
                    <tr key={opcode} className="border-b border-white/10 hover:bg-white/5">
                        <td className="p-2 font-mono">{opcode}</td>
                        <td className="p-2 font-mono">{name}</td>
                        <td className="p-2">{desc.en}</td>
                        <td className="p-2">{desc.zh}</td>
                    </tr>
                ))}
            </tbody>
        </table>
      </div>
    </div>
  );
};

export default InstructionSetPage;
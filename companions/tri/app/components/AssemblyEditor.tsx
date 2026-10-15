import React, { useRef, useEffect, useState, useMemo } from 'react';
import { CompilationResult } from '../types';
import { INSTRUCTIONS, EXAMPLES } from '../constants';

interface AssemblyEditorProps {
    code: string;
    setCode: (code: string) => void;
    onCompile: () => void;
    running: boolean;
    breakpoints: number[];
    setBreakpoints: (addrs: number[]) => void;
    compilationResult: CompilationResult | null;
    programCounter: number;
}

const AssemblyEditor: React.FC<AssemblyEditorProps> = ({ code, setCode, onCompile, running, breakpoints, setBreakpoints, compilationResult, programCounter }) => {
    const textareaRef = useRef<HTMLTextAreaElement>(null);
    const highlightRef = useRef<HTMLDivElement>(null);
    const lineNumbersRef = useRef<HTMLDivElement>(null);
    const [isFocused, setIsFocused] = useState(false);

    const instructionSet = useMemo(() => new Set(Object.values(INSTRUCTIONS).map(i => i.name)), []);

    const highlightSyntax = (text: string) => {
        const currentLine = compilationResult?.addressLineMap[programCounter];
        return text.split('\n').map((line, i) => {
            const isCurrentPC = (i + 1) === currentLine;
            let highlightedLine = line
                .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
                .replace(/\b(\d+)\b/g, '<span class="text-yellow-300">$1</span>') // Numbers
                .replace(/^(\s*)(\w+:)/gm, '$1<span class="text-purple-400">$2</span>') // Labels
                .replace(/\/\/.*/g, '<span class="text-gray-500">$&</span>'); // Comments
            
            const parts = line.trim().split(/\s+/);
            if (parts.length > 0) {
                const op = parts[0].toUpperCase();
                if (instructionSet.has(op)) {
                    highlightedLine = highlightedLine.replace(new RegExp(`\\b(${op})\\b`, 'i'), '<span class="text-cyan-400 font-semibold">$1</span>');
                }
            }
            
            return `<div class="${isCurrentPC ? 'bg-yellow-500/20' : ''}">${highlightedLine || '&nbsp;'}</div>`;
        }).join('');
    };

    const handleScroll = () => {
        if (textareaRef.current && highlightRef.current && lineNumbersRef.current) {
            const scrollTop = textareaRef.current.scrollTop;
            highlightRef.current.scrollTop = scrollTop;
            highlightRef.current.scrollLeft = textareaRef.current.scrollLeft;
            lineNumbersRef.current.style.transform = `translateY(-${scrollTop}px)`;
        }
    };
    
    const toggleBreakpointByLine = (lineNumber: number) => {
      const address = compilationResult?.lineAddressMap[lineNumber];
      if (address !== undefined) {
          setBreakpoints(
              breakpoints.includes(address)
                  ? breakpoints.filter(b => b !== address)
                  : [...breakpoints, address]
          );
      }
    };

    const lineCount = code.split('\n').length;
    
    return (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <div className="bg-black/30 rounded-lg p-4">
                <div className="flex justify-between items-center mb-3">
                    <h2 className="text-lg font-bold text-cyan-300">Assembly Editor</h2>
                    <div className="flex gap-2">
                        <button onClick={onCompile} disabled={running} className="px-4 py-2 bg-purple-500 hover:bg-purple-600 disabled:bg-gray-500 text-white rounded-lg text-sm">Compile & Load</button>
                    </div>
                </div>

                <div className="relative font-mono text-sm h-96">
                    <div className="absolute top-0 left-0 flex h-full overflow-hidden">
                       <div ref={lineNumbersRef} className="line-numbers bg-black/20 text-right pr-2 pt-1 text-gray-400 select-none flex flex-col items-end z-10">
                           {Array.from({ length: lineCount }, (_, i) => {
                               const lineNumber = i + 1;
                               const address = compilationResult?.lineAddressMap[lineNumber];
                               const hasBreakpoint = address !== undefined && breakpoints.includes(address);
                               const hasError = compilationResult?.errorLine === lineNumber;

                               return (
                                   <div key={i} className="relative h-[21px] flex items-center" onClick={() => toggleBreakpointByLine(lineNumber)}>
                                       {hasBreakpoint && <span className="text-red-500 text-lg leading-none absolute -left-3 top-1/2 -translate-y-1/2 cursor-pointer">●</span>}
                                       {hasError && <span className="text-red-500 text-lg leading-none absolute -left-3 top-1/2 -translate-y-1/2" title={compilationResult?.error ?? ''}>!</span>}
                                       <span className="cursor-pointer">{lineNumber}</span>
                                   </div>
                               );
                           })}
                       </div>
                    </div>

                    <textarea
                        ref={textareaRef}
                        value={code}
                        onChange={(e) => setCode(e.target.value)}
                        onScroll={handleScroll}
                        onFocus={() => setIsFocused(true)}
                        onBlur={() => setIsFocused(false)}
                        placeholder={`// Your assembly code goes here...\n// Example:\nLOADI 5\nSTORE 40`}
                        className="absolute top-0 left-0 w-full h-full bg-transparent text-transparent caret-green-300 p-1 pl-12 resize-none border-none outline-none font-mono leading-[21px]"
                        disabled={running}
                        spellCheck="false"
                    />

                    <div
                        ref={highlightRef}
                        className={`absolute top-0 left-0 w-full h-full text-green-300 p-1 pl-12 pointer-events-none overflow-auto font-mono leading-[21px] whitespace-pre-wrap border rounded ${isFocused ? 'border-cyan-500' : 'border-white/20'}`}
                        dangerouslySetInnerHTML={{ __html: highlightSyntax(code) }}
                    />
                </div>
                {compilationResult?.error && (
                    <div className="mt-2 bg-red-500/20 text-red-300 p-2 rounded text-xs">
                        Error on line {compilationResult.errorLine}: {compilationResult.error}
                    </div>
                )}
            </div>
            <div className="bg-black/30 rounded-lg p-4">
                <h2 className="text-lg font-bold text-cyan-300 mb-3">Code Snippets & Examples</h2>
                <div className="space-y-2 text-sm max-h-[440px] overflow-y-auto">
                    {Object.values(EXAMPLES).map((ex, i) => (
                         <div key={i} className="bg-white/5 p-3 rounded">
                            <div className="text-yellow-300 font-bold mb-1">{ex.name}</div>
                            <p className="text-xs text-gray-400 mb-2">{ex.desc}</p>
                            <pre className="text-green-300 font-mono text-xs whitespace-pre-wrap bg-black/20 p-2 rounded">{ex.code}</pre>
                         </div>
                    ))}
                </div>
            </div>
        </div>
    );
};

export default AssemblyEditor;

import React from 'react';
import { AlertTriangle, X } from 'lucide-react';

interface ConfirmationModalProps {
  title: string;
  message: string;
  confirmText?: string;
  cancelText?: string;
  isDanger?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

const ConfirmationModal: React.FC<ConfirmationModalProps> = ({ 
  title, 
  message, 
  confirmText = '确认', 
  cancelText = '取消', 
  isDanger = false,
  onConfirm, 
  onCancel 
}) => {
  return (
    <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-[60] p-4 animate-fade-in">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-sm overflow-hidden transform transition-all scale-100">
        <div className="p-5">
           <div className="flex items-start gap-4">
              <div className={`p-3 rounded-full flex-shrink-0 ${isDanger ? 'bg-red-100 text-red-600' : 'bg-amber-100 text-amber-600'}`}>
                 <AlertTriangle className="w-6 h-6" />
              </div>
              <div className="flex-1">
                 <h3 className="text-lg font-bold text-gray-900 mb-2">{title}</h3>
                 <p className="text-sm text-gray-500 leading-relaxed">{message}</p>
              </div>
           </div>
        </div>
        <div className="bg-gray-50 p-4 flex gap-3 justify-end border-t border-gray-100">
           <button 
             onClick={onCancel}
             className="px-4 py-2 text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 font-medium transition-colors text-sm"
           >
             {cancelText}
           </button>
           <button 
             onClick={onConfirm}
             className={`px-4 py-2 text-white rounded-lg font-bold shadow-md transition-colors text-sm ${isDanger ? 'bg-red-600 hover:bg-red-700' : 'bg-indigo-600 hover:bg-indigo-700'}`}
           >
             {confirmText}
           </button>
        </div>
      </div>
    </div>
  );
};

export default ConfirmationModal;

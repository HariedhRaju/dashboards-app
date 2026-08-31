import React, { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { uploadBugsFile, type ImportResult } from './api';

const MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024; // 10 MB

export function ImportBugsModal() {
  const [isOpen, setIsOpen] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [defaultProject, setDefaultProject] = useState<string>('');
  const [isUploading, setIsUploading] = useState(false);
  const [clientError, setClientError] = useState<string | null>(null);
  const [result, setResult] = useState<ImportResult | null>(null);

  const queryClient = useQueryClient();

  const handleOpen = () => {
    setIsOpen(true);
    setClientError(null);
    setResult(null);
    setSelectedFile(null);
    setDefaultProject('');
  };

  const handleClose = () => {
    if (!isUploading) {
      setIsOpen(false);
    }
  };

  const validateAndSetFile = (file: File | null) => {
    setClientError(null);
    setResult(null);
    if (!file) {
      setSelectedFile(null);
      return;
    }

    const filename = file.name || '';
    const ext = filename.substring(filename.lastIndexOf('.')).toLowerCase();
    if (!['.xlsx', '.xls', '.csv'].includes(ext)) {
      setClientError('Unsupported file type. Please upload an .xlsx, .xls, or .csv file.');
      setSelectedFile(null);
      return;
    }

    if (file.size === 0) {
      setClientError('The selected file is empty.');
      setSelectedFile(null);
      return;
    }

    if (file.size > MAX_FILE_SIZE_BYTES) {
      setClientError('File too large. Maximum allowed size is 10 MB.');
      setSelectedFile(null);
      return;
    }

    setSelectedFile(file);
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0] || null;
    validateAndSetFile(file);
  };

  const handleUpload = async () => {
    if (!selectedFile) return;

    setIsUploading(true);
    setClientError(null);
    setResult(null);

    try {
      const res = await uploadBugsFile(selectedFile, defaultProject.trim() || undefined);
      setResult(res);
      // Refresh all dashboard metrics immediately
      queryClient.invalidateQueries({ queryKey: ['metric'] });
    } catch (err: any) {
      setClientError(err?.message || 'Something went wrong while importing the file. Please try again.');
    } finally {
      setIsUploading(false);
    }
  };

  return (
    <>
      <button
        onClick={handleOpen}
        className="
          bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-medium px-3 py-1.5
          rounded-md flex items-center gap-1.5 transition-colors cursor-pointer shadow-sm
        "
        title="Import Excel or CSV Bug Tracker"
      >
        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
        </svg>
        <span>Import Bugs</span>
      </button>

      {isOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-xs">
          <div className="bg-neutral-900 border border-neutral-800 rounded-xl max-w-lg w-full p-5 shadow-2xl relative text-neutral-200">
            {/* Modal Header */}
            <div className="flex items-center justify-between pb-3 border-b border-neutral-800 mb-4">
              <h2 className="text-base font-semibold text-neutral-100 flex items-center gap-2">
                <svg className="w-4 h-4 text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                </svg>
                Import Bug Tracker File
              </h2>
              <button
                onClick={handleClose}
                disabled={isUploading}
                className="text-neutral-400 hover:text-neutral-200 text-sm p-1 rounded-md transition-colors"
              >
                ✕
              </button>
            </div>

            {/* File Selection Box */}
            <div className="mb-4">
              <label className="block text-xs font-medium text-neutral-400 mb-1">
                Select Excel or CSV File
              </label>
              <input
                type="file"
                accept=".xlsx,.xls,.csv"
                onChange={handleFileChange}
                disabled={isUploading}
                className="
                  block w-full text-xs text-neutral-300
                  file:mr-3 file:py-1.5 file:px-3 file:rounded-md file:border-0
                  file:text-xs file:font-medium file:bg-neutral-800 file:text-neutral-200
                  hover:file:bg-neutral-700 cursor-pointer bg-neutral-950 border border-neutral-800 rounded-lg p-2
                "
              />
              <p className="text-[11px] text-neutral-500 mt-1">
                Supported formats: <code className="text-neutral-400">.xlsx</code>, <code className="text-neutral-400">.xls</code>, <code className="text-neutral-400">.csv</code> (Max 10 MB)
              </p>
            </div>

            {/* Selected File Details & Optional Default Project */}
            {selectedFile && (
              <div className="bg-neutral-950/80 border border-neutral-800 rounded-lg p-3 mb-4 text-xs space-y-2">
                <div className="flex justify-between items-center text-neutral-300">
                  <span className="truncate max-w-[280px] font-mono text-emerald-400">{selectedFile.name}</span>
                  <span className="text-neutral-500">{(selectedFile.size / 1024).toFixed(1)} KB</span>
                </div>

                <div>
                  <label className="block text-[11px] text-neutral-400 mb-1">
                    Default Project Name (Optional)
                  </label>
                  <input
                    type="text"
                    placeholder="e.g. The Fertile Crescent"
                    value={defaultProject}
                    onChange={(e) => setDefaultProject(e.target.value)}
                    disabled={isUploading}
                    className="w-full bg-neutral-900 border border-neutral-800 rounded px-2 py-1 text-xs text-neutral-200 placeholder-neutral-600 focus:outline-none focus:border-neutral-700"
                  />
                </div>
              </div>
            )}

            {/* Error Message Display */}
            {clientError && (
              <div className="bg-red-950/50 border border-red-800/80 rounded-lg p-3 mb-4 text-xs text-red-300">
                <div className="font-semibold mb-0.5">Import Error</div>
                <div>{clientError}</div>
              </div>
            )}

            {/* Import Summary Result Display */}
            {result && (
              <div className="bg-neutral-950 border border-neutral-800 rounded-lg p-3 mb-4 text-xs space-y-3">
                <div className="flex items-center justify-between font-medium">
                  <span className={result.skipped > 0 ? "text-amber-400" : "text-emerald-400"}>
                    {result.skipped > 0 ? "Import completed with warnings" : "Import completed successfully"}
                  </span>
                  <span className="text-neutral-500 text-[11px]">Total rows: {result.total_rows ?? (result.inserted + result.updated + result.skipped)}</span>
                </div>

                {/* Metrics Summary Grid */}
                <div className="grid grid-cols-3 gap-2 text-center">
                  <div className="bg-emerald-950/40 border border-emerald-900/60 rounded p-2">
                    <div className="text-emerald-400 font-bold text-sm">{result.inserted}</div>
                    <div className="text-[10px] text-neutral-400 uppercase tracking-wider">Inserted</div>
                  </div>
                  <div className="bg-blue-950/40 border border-blue-900/60 rounded p-2">
                    <div className="text-blue-400 font-bold text-sm">{result.updated}</div>
                    <div className="text-[10px] text-neutral-400 uppercase tracking-wider">Updated</div>
                  </div>
                  <div className="bg-amber-950/40 border border-amber-900/60 rounded p-2">
                    <div className="text-amber-400 font-bold text-sm">{result.skipped}</div>
                    <div className="text-[10px] text-neutral-400 uppercase tracking-wider">Skipped</div>
                  </div>
                </div>

                {/* Error Rows Detailed Breakdown */}
                {result.errors && result.errors.length > 0 && (
                  <div className="mt-2 pt-2 border-t border-neutral-800">
                    <div className="font-semibold text-amber-300 mb-1.5">Skipped Row Errors</div>
                    <div className="max-h-36 overflow-y-auto space-y-1.5 pr-1">
                      {result.errors.map((err, idx) => (
                        <div key={idx} className="bg-neutral-900 border border-neutral-800 rounded p-2 text-[11px]">
                          <div className="flex justify-between font-mono text-neutral-400">
                            <span>Row {err.row}</span>
                            <span className="text-amber-400">Field: {err.field}</span>
                          </div>
                          <div className="text-neutral-300 mt-0.5">{err.reason}</div>
                          {err.value !== null && err.value !== undefined && (
                            <div className="text-neutral-500 text-[10px] truncate mt-0.5">Provided value: {String(err.value)}</div>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* Modal Actions */}
            <div className="flex justify-end gap-2 pt-2 border-t border-neutral-800">
              <button
                type="button"
                onClick={handleClose}
                disabled={isUploading}
                className="px-3 py-1.5 text-xs text-neutral-400 hover:text-neutral-200 transition-colors"
              >
                {result ? 'Close' : 'Cancel'}
              </button>
              {selectedFile && !result && (
                <button
                  type="button"
                  onClick={handleUpload}
                  disabled={isUploading}
                  className="
                    bg-emerald-600 hover:bg-emerald-500 disabled:bg-neutral-800
                    disabled:text-neutral-500 text-white text-xs font-medium px-4 py-1.5
                    rounded-md transition-colors cursor-pointer flex items-center gap-1.5
                  "
                >
                  {isUploading ? (
                    <>
                      <span className="inline-block w-3 h-3 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                      <span>Uploading...</span>
                    </>
                  ) : (
                    <span>Upload & Import</span>
                  )}
                </button>
              )}
            </div>
          </div>
        </div>
      )}
    </>
  );
}

import React, { useState } from 'react';
import { FileDown, Loader2 } from 'lucide-react';
import { useFilters } from './filters';

const API_BASE =
  (typeof import.meta !== 'undefined' && import.meta.env?.VITE_DASHBOARDS_API) || '';

export function DownloadReportButton() {
  const filters = useFilters();
  const [isDownloading, setIsDownloading] = useState(false);

  const handleDownload = async () => {
    setIsDownloading(true);
    try {
      // Find active project_id from filter or query default
      let projectId = filters?.project_id;
      if (!projectId) {
        const dimRes = await fetch(`${API_BASE}/api/dimensions/bug_projects`);
        if (dimRes.ok) {
          const data = await dimRes.json();
          if (data && data.length > 0) {
            projectId = data[0].value;
          }
        }
      }

      if (!projectId) {
        alert('Please select a game first to export its QA report.');
        return;
      }

      const res = await fetch(`${API_BASE}/api/bugs/export-docx?project_id=${encodeURIComponent(projectId)}`);
      if (!res.ok) {
        throw new Error(`Export failed with status ${res.status}`);
      }

      const blob = await res.blob();
      const contentDisposition = res.headers.get('content-disposition');
      let filename = 'QA_Executive_Report.docx';
      if (contentDisposition) {
        const match = contentDisposition.match(/filename="?([^"]+)"?/);
        if (match && match[1]) {
          filename = match[1];
        }
      }

      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);
    } catch (err: any) {
      console.error('Download report error:', err);
      alert(`Failed to download report: ${err.message || 'Unknown error'}`);
    } finally {
      setIsDownloading(false);
    }
  };

  return (
    <button
      onClick={handleDownload}
      disabled={isDownloading}
      className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold text-indigo-200 bg-indigo-950/70 hover:bg-indigo-900/80 border border-indigo-700/60 rounded-lg shadow-sm hover:shadow-indigo-500/20 hover:border-indigo-500 transition-all disabled:opacity-50"
      title="Download QA Executive Report as Word (.docx)"
    >
      {isDownloading ? (
        <Loader2 className="w-3.5 h-3.5 animate-spin text-indigo-400" />
      ) : (
        <FileDown className="w-3.5 h-3.5 text-indigo-400" />
      )}
      <span>{isDownloading ? 'Exporting...' : 'Download Report (.docx)'}</span>
    </button>
  );
}

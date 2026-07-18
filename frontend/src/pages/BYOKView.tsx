import React, { useState } from 'react';
import { UploadCloud, Link, FileText, Database, ShieldCheck, Zap } from 'lucide-react';
import { useTheme } from '../context/ThemeContext';
import { api } from '../api/client';

export default function BYOKView({ domain = 'All Domains' }: { domain?: string }) {
  const { colors } = useTheme();
  const [tab, setTab] = useState<'file' | 'url' | 'raw'>('file');
  const [content, setContent] = useState('');
  const [title, setTitle] = useState('');
  const [fileName, setFileName] = useState('');
  const [ingesting, setIngesting] = useState(false);
  const [success, setSuccess] = useState(false);
  const fileInputRef = React.useRef<HTMLInputElement>(null);

  const handleFileSelected = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setFileName(file.name);
    if (!title) setTitle(file.name);
    // Read the real file content (text-based files) so we ingest actual bytes,
    // not a placeholder. Binary formats are best-effort decoded as text.
    const text = await file.text();
    setContent(text);
  };

  const handleIngest = async () => {
    if (!content) return;  // require real content for every mode, including file
    setIngesting(true);
    setSuccess(false);
    try {
      await api.ingestSignal({
        signal_type: 'BYOK_INGESTION',
        source: tab === 'file' ? `Local Upload: ${fileName}` : tab === 'url' ? 'Web Scrape' : 'Manual Entry',
        title: title || 'Custom Knowledge Upload',
        content,  // real content for all tabs
        severity: 'INFO'
      });
      setSuccess(true);
      setContent('');
      setTitle('');
      setFileName('');
      setTimeout(() => setSuccess(false), 3000);
    } catch (e) {
      console.error(e);
    }
    setIngesting(false);
  };

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-8">
      <header className="pb-6 border-b" style={{ borderColor: colors.hairline }}>
        <h1 className="text-3xl font-bold tracking-tight" style={{ color: colors.ink }}>
          Bring Your Own Knowledge (BYOK)
        </h1>
        <p className="mt-2" style={{ color: colors.inkSubtle }}>
          Directly inject custom domain knowledge into the {domain} ontology. Upload documents, provide URLs, or paste raw text to be vectorized and integrated into the knowledge base immediately.
        </p>
      </header>

      <div className="flex gap-2">
        {[
          { id: 'file', label: 'Upload Documents', icon: UploadCloud },
          { id: 'url', label: 'Scrape URL', icon: Link },
          { id: 'raw', label: 'Raw Text', icon: FileText }
        ].map(t => (
          <button
            key={t.id}
            onClick={() => setTab(t.id as any)}
            className="flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-medium transition-all"
            style={{
              background: tab === t.id ? `${colors.primary}15` : colors.surface1,
              color: tab === t.id ? colors.primary : colors.inkSubtle,
              border: `1px solid ${tab === t.id ? colors.primary : colors.hairline}`
            }}
          >
            <t.icon className="w-4 h-4" />
            {t.label}
          </button>
        ))}
      </div>

      <div className="bg-white rounded-2xl p-6 premium-shadow" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
        <div className="space-y-5">
          <div>
            <label className="block text-sm font-medium mb-1.5" style={{ color: colors.ink }}>Title / Reference Name</label>
            <input
              type="text"
              value={title}
              onChange={e => setTitle(e.target.value)}
              placeholder="e.g., Q3 Financial Compliance Update"
              className="w-full px-4 py-2.5 rounded-xl border focus:outline-none focus:ring-2"
              style={{ background: colors.inputBg, borderColor: colors.hairline, color: colors.ink }}
            />
          </div>

          {tab === 'file' && (
            <div className="border-2 border-dashed rounded-xl p-12 text-center" style={{ borderColor: colors.hairline, background: colors.surface2 }}>
              <input
                ref={fileInputRef}
                type="file"
                accept=".txt,.md,.csv,.json,.log,.xml,.yaml,.yml"
                className="hidden"
                onChange={handleFileSelected}
              />
              <UploadCloud className="w-12 h-12 mx-auto mb-4" style={{ color: colors.inkTertiary }} />
              <h3 className="text-lg font-medium" style={{ color: colors.ink }}>
                {fileName ? fileName : 'Select a File'}
              </h3>
              <p className="text-sm mt-1 mb-4" style={{ color: colors.inkSubtle }}>
                {fileName
                  ? `${content.length.toLocaleString()} characters loaded - ready to ingest`
                  : 'Supports text formats: TXT, MD, CSV, JSON, XML, YAML, LOG'}
              </p>
              <button onClick={() => fileInputRef.current?.click()} className="px-5 py-2 rounded-xl text-sm font-medium text-white" style={{ background: colors.primary }}>
                {fileName ? 'Choose Different File' : 'Browse Files'}
              </button>
            </div>
          )}

          {tab === 'url' && (
            <div>
              <label className="block text-sm font-medium mb-1.5" style={{ color: colors.ink }}>Target URL</label>
              <input
                type="url"
                value={content}
                onChange={e => setContent(e.target.value)}
                placeholder="https://example.com/documentation"
                className="w-full px-4 py-2.5 rounded-xl border focus:outline-none focus:ring-2"
                style={{ background: colors.inputBg, borderColor: colors.hairline, color: colors.ink }}
              />
            </div>
          )}

          {tab === 'raw' && (
            <div>
              <label className="block text-sm font-medium mb-1.5" style={{ color: colors.ink }}>Raw Text Content</label>
              <textarea
                value={content}
                onChange={e => setContent(e.target.value)}
                rows={8}
                placeholder="Paste your raw unstructured text here..."
                className="w-full px-4 py-3 rounded-xl border focus:outline-none focus:ring-2 resize-none"
                style={{ background: colors.inputBg, borderColor: colors.hairline, color: colors.ink }}
              />
            </div>
          )}
        </div>

        <div className="mt-8 pt-6 border-t flex items-center justify-between" style={{ borderColor: colors.hairline }}>
          <div className="flex items-center gap-4 text-sm" style={{ color: colors.inkSubtle }}>
            <span className="flex items-center gap-1.5"><ShieldCheck className="w-4 h-4 text-emerald-500" /> PII Scrubbing Enabled</span>
            <span className="flex items-center gap-1.5"><Database className="w-4 h-4 text-indigo-500" /> Auto-Vectorization</span>
          </div>

          <button
            onClick={handleIngest}
            disabled={ingesting || !content}
            className="flex items-center gap-2 px-6 py-2.5 rounded-xl font-semibold text-white transition-opacity disabled:opacity-50"
            style={{ background: colors.primary }}
          >
            {ingesting ? (
              <span className="animate-pulse">Ingesting...</span>
            ) : (
              <>
                <Zap className="w-4 h-4" />
                Ingest to Knowledge Base
              </>
            )}
          </button>
        </div>

        {success && (
          <div className="mt-4 p-4 rounded-xl flex items-center gap-3 bg-emerald-50 border border-emerald-100 text-emerald-700">
            <ShieldCheck className="w-5 h-5 text-emerald-500" />
            <span className="font-medium">Knowledge successfully ingested, scrubbed, and vectorized!</span>
          </div>
        )}
      </div>
    </div>
  );
}

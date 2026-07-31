import React, { useEffect, useState } from 'react';
import type { ElicitationDashboard } from '../api/client';
import { api } from '../api/client';
import { useTheme } from '../context/ThemeContext';
import { BrainLoading, BrainError, BrainEmpty } from '../components/BrainStates';
import { MessagesSquare, Send, Award, CheckCircle, Clock, User, TrendingUp, Sparkles, Loader2, XCircle, AlertTriangle } from 'lucide-react';

export default function ElicitationHub() {
  const { colors } = useTheme();
  const [data, setData] = useState<ElicitationDashboard | null>(null);
  const [loading, setLoading] = useState(true);
  const [answering, setAnswering] = useState<string | null>(null);
  const [answerText, setAnswerText] = useState('');
  // Ask-an-expert generator (POST /elicitation/generate)
  const [showGen, setShowGen] = useState(false);
  const [genEmployee, setGenEmployee] = useState('');
  const [genDomain, setGenDomain] = useState('');
  const [genBusy, setGenBusy] = useState(false);
  const [banner, setBanner] = useState<{ tone: 'ok' | 'warn' | 'bad'; text: string } | null>(null);

  const loadData = () => {
    setLoading(true);
    api.getElicitation().then((d) => {
      setData(d);
      setLoading(false);
    }).catch(() => setLoading(false));
  };

  useEffect(() => {
    loadData();
  }, []);

  const handleSubmit = async (qId: string) => {
    if (!answerText.trim()) return;
    try {
      await api.submitAnswer(qId, answerText);
      setAnswering(null);
      setAnswerText('');
      loadData();
    } catch (e) {
      console.error(e);
    }
  };

  const generateQuestion = async () => {
    setGenBusy(true);
    setBanner(null);
    try {
      const r = await api.generateElicitationQuestion({
        employee_id: genEmployee.trim(),
        domain: genDomain.trim() || null,
      });
      if (r.status === 'GENERATED') {
        setBanner({ tone: 'ok', text: `Question sent: "${r.question}"` });
        setShowGen(false);
        setGenEmployee(''); setGenDomain('');
        loadData();
      } else if (r.status === 'SKIPPED_RATE_LIMIT') {
        setBanner({ tone: 'warn', text: 'That person has already had three questions this week. Pick someone else or wait until next week.' });
      } else {
        setBanner({ tone: 'warn', text: r.message || 'No question could be generated for that person right now.' });
      }
    } catch (e: any) {
      setBanner({ tone: 'bad', text: e?.message || 'Could not generate a question.' });
    } finally {
      setGenBusy(false);
    }
  };

  // Accent color per question type, keyed to the theme palette.
  const typeColor = (t: string): string => {
    if (t === 'GAP_FILL') return colors.info;
    if (t === 'CONTRADICTION') return colors.error;
    if (t === 'DECAY_REVALIDATION') return colors.warning;
    return colors.primary;
  };

  if (loading && !data) return <BrainLoading message="Loading Knowledge Capture…" />;
  if (!data) return <BrainError message="Failed to load elicitation data." onRetry={loadData} />;
  const d = data;

  const card: React.CSSProperties = {
    background: colors.surface1,
    border: `1px solid ${colors.hairline}`,
    borderRadius: '14px',
  };

  const METRICS = [
    { label: 'Questions Sent (7d)', icon: MessagesSquare, color: colors.info, value: d.stats.total_questions.toString() },
    { label: 'Response Rate', icon: TrendingUp, color: colors.success, value: `${(d.stats.response_rate * 100).toFixed(1)}%` },
    { label: 'Avg Quality Score', icon: Award, color: colors.warning, value: (d.stats.avg_quality_score * 100).toFixed(0) },
  ];

  return (
    <div className="h-full overflow-y-auto" style={{ background: colors.canvas, color: colors.ink }}>
      <div className="max-w-7xl mx-auto p-6 space-y-5">
        {/* Header */}
        <div className="flex items-start gap-3">
          <div className="w-11 h-11 rounded-xl flex items-center justify-center shrink-0"
            style={{ background: `linear-gradient(135deg, ${colors.primary}, ${colors.primary}99)` }}>
            <MessagesSquare className="w-6 h-6 text-white" />
          </div>
          <div className="flex-1">
            <h1 className="text-[24px] font-bold tracking-tight">Knowledge Capture Hub</h1>
            <p className="text-[13px] mt-1" style={{ color: colors.inkSubtle }}>
              Active Elicitation - Targeted micro-surveys for domain expert knowledge harvesting
            </p>
          </div>
          <button onClick={() => { setShowGen(v => !v); setBanner(null); }}
            className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-[13px] font-semibold text-white self-center transition-all hover:brightness-110"
            style={{ background: colors.primary }}>
            <Sparkles className="w-4 h-4" /> {showGen ? 'Close' : 'Ask an Expert'}
          </button>
        </div>

        {banner && (
          <div className="flex items-start gap-2 px-4 py-2.5 rounded-lg text-[12px] font-medium"
            style={{
              background: (banner.tone === 'ok' ? colors.success : banner.tone === 'warn' ? colors.warning : colors.error) + '15',
              color: banner.tone === 'ok' ? colors.success : banner.tone === 'warn' ? colors.warning : colors.error,
            }}>
            {banner.tone === 'ok'
              ? <CheckCircle className="w-4 h-4 shrink-0 mt-px" />
              : banner.tone === 'warn'
                ? <AlertTriangle className="w-4 h-4 shrink-0 mt-px" />
                : <XCircle className="w-4 h-4 shrink-0 mt-px" />}
            <span className="flex-1">{banner.text}</span>
            <button onClick={() => setBanner(null)} className="text-[11px] opacity-70">dismiss</button>
          </div>
        )}

        {showGen && (
          <div className="p-5 space-y-3" style={card}>
            <h3 className="text-[14px] font-semibold" style={{ color: colors.ink }}>Ask an Expert</h3>
            <p className="text-[11px]" style={{ color: colors.inkTertiary }}>
              KAEOS writes one targeted question aimed at a gap it has found in what it knows. Each person gets at most three questions a week.
            </p>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
              <div>
                <label className="text-[11px] font-semibold uppercase tracking-wider block mb-1" style={{ color: colors.inkSubtle }}>Who to ask</label>
                {d.contributors.length > 0 ? (
                  <select value={genEmployee} onChange={e => setGenEmployee(e.target.value)}
                    className="w-full px-3 py-2 rounded-lg text-[13px] outline-none"
                    style={{ background: colors.inputBg, border: `1px solid ${colors.hairline}`, color: colors.ink }}>
                    <option value="">Choose a person…</option>
                    {d.contributors.map(c => (
                      <option key={c.employee_id} value={c.employee_id}>{c.display_name} · {c.department}</option>
                    ))}
                  </select>
                ) : (
                  <input value={genEmployee} onChange={e => setGenEmployee(e.target.value)}
                    placeholder="Employee id"
                    className="w-full px-3 py-2 rounded-lg text-[13px] outline-none"
                    style={{ background: colors.inputBg, border: `1px solid ${colors.hairline}`, color: colors.ink }} />
                )}
              </div>
              <div>
                <label className="text-[11px] font-semibold uppercase tracking-wider block mb-1" style={{ color: colors.inkSubtle }}>Subject area (optional)</label>
                <input value={genDomain} onChange={e => setGenDomain(e.target.value)}
                  placeholder="finance, support, engineering…"
                  className="w-full px-3 py-2 rounded-lg text-[13px] outline-none"
                  style={{ background: colors.inputBg, border: `1px solid ${colors.hairline}`, color: colors.ink }} />
              </div>
            </div>
            <div className="flex justify-end gap-2">
              <button onClick={() => setShowGen(false)}
                className="px-4 py-2 rounded-lg text-[13px]"
                style={{ background: colors.surface2, color: colors.inkMuted, border: `1px solid ${colors.hairline}` }}>Cancel</button>
              <button onClick={generateQuestion} disabled={genBusy || !genEmployee.trim()}
                className="flex items-center gap-2 px-4 py-2 rounded-lg text-[13px] font-semibold text-white disabled:opacity-50"
                style={{ background: colors.primary }}>
                {genBusy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />} Generate Question
              </button>
            </div>
          </div>
        )}

        {/* Metric Cards */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          {METRICS.map((m) => (
            <div key={m.label} style={{ ...card, padding: '18px' }}>
              <div className="flex items-center gap-3 mb-3">
                <div className="w-9 h-9 rounded-lg flex items-center justify-center shrink-0" style={{ background: m.color + '18' }}>
                  <m.icon className="w-5 h-5" style={{ color: m.color }} />
                </div>
                <span className="text-[11px] font-semibold uppercase tracking-wider" style={{ color: colors.inkSubtle }}>{m.label}</span>
              </div>
              <div className="text-[28px] font-bold tracking-tight tabular-nums" style={{ color: colors.ink }}>{m.value}</div>
            </div>
          ))}
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          {/* Pending Questions - 2 cols */}
          <div className="lg:col-span-2 space-y-4">
            <h2 className="text-[15px] font-semibold" style={{ color: colors.ink }}>Pending Questions ({d.pending_questions.length})</h2>

            {d.pending_questions.length === 0 ? (
              <div style={card}>
                <BrainEmpty
                  title="All caught up"
                  action="No pending knowledge gaps to resolve."
                  icon={CheckCircle}
                />
              </div>
            ) : (
              d.pending_questions.map((q) => {
                const tc = typeColor(q.question_type);
                const highPriority = q.priority === 'HIGH';
                return (
                  <div key={q.id} style={{ ...card, padding: '18px' }}>
                    <div className="flex items-center gap-2 mb-3 flex-wrap">
                      <span className="px-2 py-0.5 rounded text-[11px] font-semibold"
                        style={{ background: tc + '1f', color: tc, border: `1px solid ${tc}3d` }}>
                        {q.question_type.replace(/_/g, ' ')}
                      </span>
                      <span className="px-2 py-0.5 rounded text-[11px] font-semibold"
                        style={highPriority
                          ? { background: colors.error + '1f', color: colors.error, border: `1px solid ${colors.error}3d` }
                          : { background: colors.surface2, color: colors.inkMuted, border: `1px solid ${colors.hairline}` }}>
                        {q.priority}
                      </span>
                      <span className="text-[12px] ml-auto flex items-center gap-1" style={{ color: colors.inkSubtle }}>
                        <User className="w-3 h-3" /> {q.employee_name} · {q.department}
                      </span>
                    </div>

                    <p className="text-[13px] leading-relaxed mb-3" style={{ color: colors.ink }}>{q.question_text}</p>

                    <div className="flex gap-4 mb-3 text-[12px]" style={{ color: colors.inkSubtle }}>
                      <span>Specificity: <strong style={{ color: colors.inkMuted }}>{q.specificity.toFixed(2)}</strong></span>
                      <span>Groundedness: <strong style={{ color: colors.inkMuted }}>{q.groundedness.toFixed(2)}</strong></span>
                      <span>Answerability: <strong style={{ color: colors.inkMuted }}>{q.answerability.toFixed(2)}</strong></span>
                    </div>

                    <div className="text-[12px] mb-4" style={{ color: colors.inkSubtle }}>
                      Context: <span className="font-medium" style={{ color: colors.primary }}>{q.context_ref}</span> · via {q.delivery_channel}
                    </div>

                    {answering === q.id ? (
                      <div className="space-y-3 pt-3" style={{ borderTop: `1px solid ${colors.hairline}` }}>
                        <textarea
                          value={answerText}
                          onChange={(e) => setAnswerText(e.target.value)}
                          placeholder="Type your answer to resolve this knowledge gap..."
                          className="w-full h-20 px-4 py-3 rounded-lg text-[13px] outline-none resize-vertical focus:ring-2"
                          style={{ background: colors.inputBg, border: `1px solid ${colors.hairline}`, color: colors.ink }}
                        />
                        <div className="flex gap-2 justify-end">
                          <button
                            onClick={() => { setAnswering(null); setAnswerText(''); }}
                            className="px-4 py-2 text-[13px] rounded-lg transition-all hover:opacity-80"
                            style={{ background: colors.surface2, color: colors.inkMuted, border: `1px solid ${colors.hairline}` }}
                          >Cancel</button>
                          <button
                            onClick={() => handleSubmit(q.id)}
                            className="px-4 py-2 rounded-lg text-[13px] font-semibold transition-all hover:opacity-90 flex items-center gap-2"
                            style={{ background: colors.primary, color: '#fff' }}
                          ><Send className="w-4 h-4" /> Submit Answer</button>
                        </div>
                      </div>
                    ) : (
                      <button
                        onClick={() => setAnswering(q.id)}
                        className="px-4 py-2 rounded-lg text-[13px] font-semibold transition-all hover:opacity-90"
                        style={{ background: colors.primary + '15', color: colors.primary, border: `1px solid ${colors.primary}30` }}
                      >Answer This Question</button>
                    )}
                  </div>
                );
              })
            )}

            {/* Recent Answers */}
            {d.recent_answers.length > 0 && (
              <>
                <h2 className="text-[15px] font-semibold mt-8 flex items-center gap-2" style={{ color: colors.ink }}>
                  <Clock className="w-5 h-5" style={{ color: colors.success }} /> Recently Harvested
                </h2>
                {d.recent_answers.map(q => (
                  <div key={q.id} className="opacity-70" style={{ ...card, padding: '16px', borderColor: colors.success + '40' }}>
                    <div className="flex items-center gap-2 mb-2">
                      <CheckCircle className="w-4 h-4" style={{ color: colors.success }} />
                      <span className="text-[12px] font-semibold" style={{ color: colors.success }}>ANSWERED</span>
                      <span className="text-[12px] ml-auto" style={{ color: colors.inkSubtle }}>{q.employee_name}</span>
                    </div>
                    <p className="text-[13px]" style={{ color: colors.inkSubtle }}>{q.question_text}</p>
                  </div>
                ))}
              </>
            )}
          </div>

          {/* Top Contributors - 1 col */}
          <div>
            <h2 className="text-[15px] font-semibold mb-4 flex items-center gap-2" style={{ color: colors.ink }}>
              <Award className="w-5 h-5" style={{ color: colors.warning }} /> Top Contributors
            </h2>
            <div className="space-y-3">
              {d.contributors.map((c, i) => {
                const rankBg = i === 0 ? colors.warning : i === 1 ? colors.inkSubtle : colors.primary;
                return (
                  <div key={c.employee_id} style={{ ...card, padding: '16px' }}>
                    <div className="flex items-center gap-3 mb-3">
                      <div className="w-8 h-8 rounded-full flex items-center justify-center text-[13px] font-bold"
                        style={{ background: rankBg + '22', color: rankBg }}>{i + 1}</div>
                      <div>
                        <div className="text-[13px] font-semibold" style={{ color: colors.ink }}>{c.display_name}</div>
                        <div className="text-[12px]" style={{ color: colors.inkSubtle }}>{c.role} · {c.department}</div>
                      </div>
                    </div>
                    <div className="grid grid-cols-3 gap-2 text-[12px]">
                      <div><span className="block" style={{ color: colors.inkSubtle }}>Score</span><span className="font-bold" style={{ color: colors.success }}>{c.reputation_score.toFixed(2)}</span></div>
                      <div><span className="block" style={{ color: colors.inkSubtle }}>Contribs</span><span className="font-bold" style={{ color: colors.ink }}>{c.total_contributions}</span></div>
                      <div><span className="block" style={{ color: colors.inkSubtle }}>Rate</span><span className="font-bold" style={{ color: colors.ink }}>{Math.round(c.response_rate * 100)}%</span></div>
                    </div>
                    {c.badge && (
                      <span className="mt-2 inline-block px-2 py-0.5 text-[11px] font-bold rounded"
                        style={{ background: colors.warning + '18', color: colors.warning, border: `1px solid ${colors.warning}30` }}>{c.badge}</span>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

import React, { useState, useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Settings, Play, Square, Eye, EyeOff, Folder, File, Plus, Trash2, CheckCircle2, Circle, Loader2, Sparkles, AlertTriangle, ArrowRight, X } from 'lucide-react';

// Splash Screen Component
const SplashScreen = ({ onFinish }) => {
  useEffect(() => {
    const t = setTimeout(onFinish, 2000);
    return () => clearTimeout(t);
  }, [onFinish]);

  return (
    <motion.div 
      initial={{ opacity: 1 }}
      exit={{ opacity: 0, transition: { duration: 0.8, ease: "easeInOut" } }}
      style={{ position: 'fixed', inset: 0, background: '#030303', zIndex: 9999, display: 'flex', justifyContent: 'center', alignItems: 'center' }}
    >
      <motion.div
        initial={{ scale: 0.8, opacity: 0, filter: 'blur(10px)' }}
        animate={{ scale: 1, opacity: 1, filter: 'blur(0px)' }}
        transition={{ duration: 1, ease: "easeOut" }}
        style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '20px' }}
      >
        <div style={{ position: 'relative' }}>
          <motion.div 
            animate={{ rotate: 360 }}
            transition={{ duration: 4, repeat: Infinity, ease: "linear" }}
            style={{ position: 'absolute', inset: -20, background: 'radial-gradient(circle, rgba(255, 75, 0, 0.4) 0%, transparent 60%)', filter: 'blur(20px)' }}
          />
          <div style={{ background: 'linear-gradient(135deg, #FF4B00, #E63E00)', borderRadius: '50%', padding: '16px', position: 'relative', zIndex: 1 }}>
            <Sparkles size={32} color="white" />
          </div>
        </div>
        <motion.h1 
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.5, duration: 0.8 }}
          style={{ fontSize: '24px', fontWeight: 600, letterSpacing: '-0.03em' }}
        >
          CodeAgent
        </motion.h1>
      </motion.div>
    </motion.div>
  );
};

export default function App() {
  const [loading, setLoading] = useState(true);
  const [settings, setSettings] = useState({ provider: 'deepseek', api_key: '', gemini_api_key: '', base_url: 'https://api.deepseek.com', model: 'deepseek-v4-pro', thinking: true, max_turns: 120, remember_key: true, input_files: [], output_dir: '' });
  const [models, setModels] = useState(['deepseek-v4-pro', 'deepseek-chat', 'deepseek-reasoner', 'deepseek-flash']);
  const [showKey, setShowKey] = useState(false);
  const [running, setRunning] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [log, setLog] = useState([]);
  const [todos, setTodos] = useState([]);
  const [status, setStatus] = useState('Ready.');
  const [usage, setUsage] = useState(null);
  const [showSettings, setShowSettings] = useState(false);
  const [testResult, setTestResult] = useState('');
  const [isDemoMode, setIsDemoMode] = useState(false);
  
  const logEndRef = useRef(null);

  useEffect(() => {
    window.api.isDemo().then(d => setIsDemoMode(!!d));
    window.api.invoke('get_settings', {}).then(res => {
      if (res && !res.error) {
        setSettings(s => ({ ...s, ...res.result }));
        if (res.result.provider === 'gemini') {
          setModels(['gemini-3.8-flash', 'gemini-3.1-flash-lite', 'gemini-3.5-flash', 'gemini-flash-latest']);
        }
      }
    });

    window.api.onEvent((msg) => {
      if (msg.error) { appendLog({ type: 'error', text: msg.error }); setRunning(false); return; }
      if (!msg.event && msg.result === 'started') return;
      if (!msg.event && msg.result === 'stopping') { setStatus('Stopping after current request...'); return; }
      handleIncomingEvent(msg);
    });
  }, []);

  // Scroll only the transcript panel. scrollIntoView would also scroll every ancestor
  // (including the page, which the oversized glow orbs make taller than the window).
  useEffect(() => {
    const panel = logEndRef.current?.closest('[data-transcript]');
    if (panel) panel.scrollTo({ top: panel.scrollHeight, behavior: 'smooth' });
  }, [log]);

  const handleChange = (k, v) => {
    setSettings(s => {
      const ns = { ...s, [k]: v };
      if (k === 'provider' && v !== s.provider) {
        // Each provider has its own endpoint and models; never send one provider's key to the other.
        const providerModels = v === 'gemini' 
          ? ['gemini-3.8-flash', 'gemini-3.1-flash-lite', 'gemini-3.5-flash', 'gemini-flash-latest']
          : ['deepseek-v4-pro', 'deepseek-flash', 'deepseek-chat', 'deepseek-reasoner'];
        setModels(providerModels);
        ns.model = v === 'gemini' ? 'gemini-3.8-flash' : 'deepseek-v4-pro';
        ns.base_url = v === 'gemini' ? 'https://generativelanguage.googleapis.com/v1beta/openai' : 'https://api.deepseek.com';
      }
      return ns;
    });
  };

  const appendLog = (entry) => setLog(prev => [...prev, { ...entry, id: Date.now() + Math.random() }]);

  const handleTest = async () => {
    setTestResult('Testing...');
    const res = await window.api.invoke('test_connection', { settings });
    setTestResult(res.error ? `✗ ${res.error}` : res.result.message);
  };

  const handleAddFiles = async () => {
    const files = await window.api.pickFiles();
    if (files) handleChange('input_files', [...new Set([...settings.input_files, ...files])]);
  };

  const handleBrowseOut = async () => {
    const dir = await window.api.pickFolder();
    if (dir) handleChange("output_dir", dir);
  };

  const handleGenerate = async () => {
    if (running) return;
    await window.api.invoke('save_settings', settings);

    if (await window.api.isDemo()) {
      setLog([]); setTodos([]); setUsage(null); setRunning(true); setStatus('Starting...');
      window.demoRunning = true; runDemoSequence(); return;
    }

    if (!(settings.provider === 'gemini' ? settings.gemini_api_key : settings.api_key)) { alert("Missing API Key"); return; }
    if (!settings.output_dir) { alert("Missing output directory"); return; }
    if (settings.input_files.length === 0) { alert("Select at least one input file"); return; }

    const check = await window.api.invoke('check_output_dir', { path: settings.output_dir });
    if (check.result && !check.result.empty && !check.result.is_file) {
      if (!confirm("Output directory is not empty. Overwrite?")) return;
    }

    setLog([]); setTodos([]); setUsage(null); setRunning(true); setStatus('Starting...');
    const started = await window.api.invoke('start_run', { settings });
    if (started && started.error) { appendLog({ type: 'error', text: started.error }); setRunning(false); setStatus('Ready.'); }
  };

  const runDemoSequence = async () => {
    const demoEvents = [
      { event: 'status', message: 'Turn 1/120: Preprocessing spec...' },
      { event: 'thinking', message: "Analyzing architecture spec: 4 domain classes, 11 diagrams, and 4 inconsistencies to resolve." },
      { event: 'assistant', message: "I'll start by planning the project structure and tracking deliverables." },
      { event: 'tool_call', data: { name: 'todo_write', args: { target: 'todos' } } },
      { event: 'todos', data: { todos: [
        { id: 1, content: 'Parse spec and resolve issues', status: 'pending' },
        { id: 2, content: 'Domain models (Game, Question, User, Admin)', status: 'pending' },
        { id: 3, content: 'REST API & Endpoints', status: 'pending' },
        { id: 4, content: 'Test Suite & Spec Coverage Validation', status: 'pending' }
      ] } },
      { event: 'tool_result', message: 'Updated todos.', data: { ok: true } },
      { event: 'usage', data: { requests: 1, prompt_tokens: 1200, completion_tokens: 150, cache_hit_tokens: 800 } },
      { event: 'status', message: 'Turn 2/120: Writing domain models...' },
      { event: 'assistant', message: "Spec parsed. Implementing the domain models now." },
      { event: 'tool_call', data: { name: 'todo_write', args: { target: 'todos' } } },
      { event: 'todos', data: { todos: [
        { id: 1, content: 'Parse spec and resolve issues', status: 'completed' },
        { id: 2, content: 'Domain models (Game, Question, User, Admin)', status: 'in_progress' },
        { id: 3, content: 'REST API & Endpoints', status: 'pending' },
        { id: 4, content: 'Test Suite & Spec Coverage Validation', status: 'pending' }
      ] } },
      { event: 'tool_call', data: { name: 'write_file', args: { path: 'src/domain/game.js' } } },
      { event: 'tool_result', message: 'Created src/domain/game.js (84 lines)', data: { ok: true } },
      { event: 'usage', data: { requests: 2, prompt_tokens: 1400, completion_tokens: 200, cache_hit_tokens: 1400 } },
      { event: 'status', message: 'Turn 3/120: Implementing REST API & routes...' },
      { event: 'tool_call', data: { name: 'todo_write', args: { target: 'todos' } } },
      { event: 'todos', data: { todos: [
        { id: 1, content: 'Parse spec and resolve issues', status: 'completed' },
        { id: 2, content: 'Domain models (Game, Question, User, Admin)', status: 'completed' },
        { id: 3, content: 'REST API & Endpoints', status: 'in_progress' },
        { id: 4, content: 'Test Suite & Spec Coverage Validation', status: 'pending' }
      ] } },
      { event: 'tool_call', data: { name: 'write_file', args: { path: 'src/server.js' } } },
      { event: 'tool_result', message: 'Created src/server.js (112 lines)', data: { ok: true } },
      { event: 'status', message: 'Turn 4/120: Running validation & test coverage...' },
      { event: 'tool_call', data: { name: 'todo_write', args: { target: 'todos' } } },
      { event: 'todos', data: { todos: [
        { id: 1, content: 'Parse spec and resolve issues', status: 'completed' },
        { id: 2, content: 'Domain models (Game, Question, User, Admin)', status: 'completed' },
        { id: 3, content: 'REST API & Endpoints', status: 'completed' },
        { id: 4, content: 'Test Suite & Spec Coverage Validation', status: 'completed' }
      ] } },
      { event: 'tool_call', data: { name: 'check_project', args: {} } },
      { event: 'tool_result', message: 'check_project: 0 blocking issues. All spec classes, states & tests pass.', data: { ok: true } },
      { event: 'tool_call', data: { name: 'finish', args: {} } },
      { event: 'tool_result', message: 'Project complete.', data: { ok: true } },
      { event: 'done', data: { success: true, summary: "Completed Space Fractions scaffold, passing 100% of static checks and coverage requirements.", turns: 4, stop_reason: "finished", usage: { requests: 4, prompt_tokens: 2500, completion_tokens: 800, cache_hit_tokens: 2000 }, files: ["src/domain/game.js", "src/server.js"], elapsed_s: 3.2 } }
    ];
    for (const msg of demoEvents) {
      if (!window.demoRunning) break;
      await new Promise(r => setTimeout(r, 220));
      handleIncomingEvent(msg);
    }
  };

  const handleIncomingEvent = (msg) => {
      const { event, message, data } = msg;
      if (event === 'status') {
        if (message && !message.startsWith('Turn ')) appendLog({ type: 'status', text: message });
        else if (message) setStatus(message);
      } else if (event === 'assistant') { appendLog({ type: 'assistant', text: message });
      } else if (event === 'thinking' && settings.thinking) { appendLog({ type: 'thinking', text: message });
      } else if (event === 'tool_call') {
        const verbMap = { write_file: 'Write', edit_file: 'Update', read_file: 'Read', list_files: 'List', search_files: 'Search', read_spec: 'Read spec', check_project: 'Check project', todo_write: 'Update Todos', finish: 'Finish' };
        appendLog({ type: 'tool_call', verb: verbMap[data?.name] || data?.name || 'Tool', target: data?.args?.path || data?.args?.pattern || data?.args?.section || '' });
      } else if (event === 'tool_result') { appendLog({ type: 'tool_result', ok: data?.ok !== false, text: (message || '').split('\n')[0] });
      } else if (event === 'todos') { setTodos(data?.todos || []);
      } else if (event === 'usage') { setUsage(data);
      } else if (event === 'warning') { appendLog({ type: 'warning', text: message });
      } else if (event === 'error') { appendLog({ type: 'error', text: message });
      } else if (event === 'done') { 
        appendLog({ type: 'done', data }); 
        setRunning(false); 
        setStopping(false); 
        window.demoRunning = false; 
        setStatus(data.success ? 'Generation Complete' : `Stopped: ${data.stop_reason}`);
        if (data.success) {
          setTodos(prev => prev.map(t => ({ ...t, status: 'completed' })));
        }
      }
  };

  const formatCost = () => {
    if (!usage || settings.provider !== 'deepseek') return '';
    const { prompt_tokens, cache_hit_tokens, completion_tokens } = usage;
    const miss = Math.max(0, prompt_tokens - (cache_hit_tokens || 0));
    let cost = (settings.model || '').includes('pro') 
             ? ((cache_hit_tokens || 0) * 0.044 + miss * 1.32 + completion_tokens * 3.96) / 1000000 
             : ((cache_hit_tokens || 0) * 0.006 + miss * 0.30 + completion_tokens * 1.20) / 1000000;
    return cost > 0 ? `$${cost.toFixed(4)}` : '';
  };

  return (
    <>
      <AnimatePresence>{loading && <SplashScreen onFinish={() => setLoading(false)} />}</AnimatePresence>
      
      {!loading && (
        <div style={{ position: 'absolute', inset: 0, display: 'flex', padding: '24px', gap: '24px' }}>
          <div className="noise-overlay"></div>
          <div className="glow-orb" style={{ top: '10%', left: '15%', width: '900px', height: '900px' }}></div>
          <div className="glow-orb" style={{ bottom: '-15%', right: '5%', width: '700px', height: '700px', background: 'radial-gradient(circle, rgba(255, 75, 0, 0.15) 0%, transparent 60%)', animationDelay: '-8s' }}></div>
          
          {/* Sidebar */}
          <motion.div 
            initial={{ x: -30, opacity: 0 }}
            animate={{ x: 0, opacity: 1 }}
            transition={{ duration: 0.6, ease: [0.16, 1, 0.3, 1] }}
            className="glass-panel" style={{ height: '100%', width: '360px', display: 'flex', flexDirection: 'column', zIndex: 10, overflow: 'hidden' }}>
            
            <div style={{ padding: '28px 28px 20px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                <div style={{ background: 'linear-gradient(135deg, #FF4B00, #ff8a00)', borderRadius: '50%', padding: '8px', boxShadow: '0 4px 12px rgba(255, 75, 0, 0.3)' }}>
                  <Sparkles size={16} color="white" />
                </div>
                <h2 style={{ fontSize: '18px', fontWeight: 600, letterSpacing: '-0.02em' }}>CodeAgent</h2>
              </div>
              <button className="button-icon" onClick={() => setShowSettings(true)} disabled={running}><Settings size={18} /></button>
            </div>

            <div style={{ flex: 1, overflowY: 'auto', padding: '0 28px 24px', display: 'flex', flexDirection: 'column', gap: '24px' }}>
              
              <div className="input-group">
                <label className="label-text">Provider</label>
                <select className="input-field" value={settings.provider} onChange={e => handleChange('provider', e.target.value)} disabled={running}>
                  <option value="deepseek">DeepSeek (official)</option>
                  <option value="gemini">Gemini (testing only)</option>
                </select>
              </div>

              <div className="input-group">
                <label className="label-text">Authentication</label>
                <div style={{ display: 'flex', gap: '8px' }}>
                  <div style={{ position: 'relative', flex: 1 }}>
                    <input type={showKey ? 'text' : 'password'} className="input-field" style={{ paddingRight: '40px' }} placeholder="API Key" value={settings.provider === 'gemini' ? settings.gemini_api_key : settings.api_key} onChange={e => handleChange(settings.provider === 'gemini' ? 'gemini_api_key' : 'api_key', e.target.value)} disabled={running} />
                    <button onClick={() => setShowKey(!showKey)} style={{ position: 'absolute', right: '12px', top: '12px', background: 'none', border: 'none', color: 'var(--text-dim)', cursor: 'pointer' }}>
                      {showKey ? <EyeOff size={16} /> : <Eye size={16} />}
                    </button>
                  </div>
                  <button className="button-secondary" style={{ padding: '0 18px' }} onClick={handleTest} disabled={running}>Test</button>
                </div>
                <AnimatePresence>
                  {testResult && <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }} style={{ fontSize: '12px', marginTop: '10px', color: testResult.includes('✗') ? 'var(--error)' : 'var(--success)' }}>{testResult}</motion.div>}
                </AnimatePresence>
              </div>

              <div className="input-group">
                <label className="label-text">Model</label>
                <div style={{ position: 'relative' }}>
                  <input
                    type="text"
                    list="model-options"
                    className="input-field"
                    placeholder="Enter or select model..."
                    value={settings.model}
                    onChange={e => handleChange('model', e.target.value)}
                    disabled={running}
                  />
                  <datalist id="model-options">
                    {models.map(m => <option key={m} value={m} />)}
                  </datalist>
                </div>
              </div>

              <div className="glass-card" style={{ padding: '16px 20px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
                  <label className="label-text" style={{ marginBottom: 0 }}>Input Specs</label>
                  <button onClick={handleAddFiles} disabled={running} style={{ background: 'none', border: 'none', color: 'var(--accent)', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '4px', fontSize: '12px', fontWeight: 600 }}><Plus size={14}/> Add</button>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  <AnimatePresence>
                    {settings.input_files.length === 0 && <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} style={{ padding: '16px', background: 'rgba(0,0,0,0.2)', borderRadius: '12px', color: 'var(--text-dim)', fontSize: '12px', textAlign: 'center' }}>No files selected</motion.div>}
                    {settings.input_files.map((f, i) => (
                      <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, scale: 0.95 }} key={f} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 14px', background: 'rgba(0,0,0,0.3)', border: '1px solid var(--border)', borderRadius: '10px', fontSize: '12px' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', overflow: 'hidden' }}>
                          <File size={14} color="var(--text-dim)" />
                          <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{f.split(/[/\\]/).pop()}</span>
                        </div>
                        <button className="button-icon" disabled={running} onClick={() => handleChange('input_files', settings.input_files.filter(x => x !== f))} style={{ padding: '4px' }}><Trash2 size={14}/></button>
                      </motion.div>
                    ))}
                  </AnimatePresence>
                </div>
              </div>

              <div className="input-group">
                <label className="label-text">Output Directory</label>
                <div style={{ display: 'flex', gap: '8px' }}>
                  <input type="text" className="input-field" placeholder="Select destination..." value={settings.output_dir} onChange={e => handleChange('output_dir', e.target.value)} disabled={running}/>
                  <button className="button-secondary" style={{ padding: '0 16px' }} onClick={handleBrowseOut} disabled={running}><Folder size={16}/></button>
                </div>
              </div>

            </div>

            <div style={{ padding: '28px', borderTop: '1px solid var(--border)', background: 'rgba(0,0,0,0.1)' }}>
              {running ? (
                <button className="button-secondary" style={{ width: '100%', padding: '16px', background: 'rgba(255,255,255,0.03)' }} disabled={stopping} onClick={() => { window.demoRunning = false; setStopping(true); setStatus('Stopping...'); window.api.invoke('stop_run', {}); }}>
                  <Square size={16} /> Stop Generation
                </button>
              ) : (
                <button className="button-primary" style={{ width: '100%', padding: '16px' }} onClick={handleGenerate}>
                  Start Generation <ArrowRight size={16} />
                </button>
              )}
            </div>
          </motion.div>

          {/* Main Area */}
          <motion.div 
            initial={{ y: 30, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            transition={{ delay: 0.1, duration: 0.6, ease: [0.16, 1, 0.3, 1] }}
            className="glass-panel" style={{ height: '100%', flex: 1, display: 'flex', flexDirection: 'column', zIndex: 10, overflow: 'hidden' }}>
            
            <div style={{ height: '72px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', padding: '0 32px', background: 'rgba(0,0,0,0.1)' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
                {running ? <Loader2 size={20} color="var(--accent)" className="spin" /> : (status.includes('Complete') ? <CheckCircle2 size={20} color="var(--success)" /> : <Circle size={20} color="var(--text-muted)" />)}
                <span style={{ fontSize: '15px', fontWeight: 500 }}>{status}</span>
                {isDemoMode && <span style={{ fontSize: '10px', fontWeight: 700, padding: '2px 8px', borderRadius: '4px', background: 'rgba(255, 75, 0, 0.15)', color: 'var(--accent)', border: '1px solid rgba(255, 75, 0, 0.3)', textTransform: 'uppercase' }}>Demo Mode</span>}
              </div>
              <AnimatePresence>
                {usage && (
                  <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: '20px', fontSize: '13px', color: 'var(--text-dim)', fontWeight: 500 }}>
                    <span>Tokens: {Math.floor(usage.prompt_tokens/1000)}k / {Math.floor(usage.completion_tokens/1000)}k</span>
                    {formatCost() && <span style={{ background: 'rgba(255,255,255,0.06)', padding: '6px 14px', borderRadius: '99px', border: '1px solid rgba(255,255,255,0.05)', color: 'white' }}>{formatCost()}</span>}
                  </motion.div>
                )}
              </AnimatePresence>
            </div>

            <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
              <AnimatePresence>
                {todos.length > 0 && (
                  <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} style={{ padding: '24px 32px', borderBottom: '1px solid var(--border)', background: 'rgba(0,0,0,0.2)', flexShrink: 0, maxHeight: '200px', overflowY: 'auto' }}>
                    <h3 className="label-text" style={{ marginBottom: '16px' }}>Live Process</h3>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: '16px' }}>
                      {todos.map((t, idx) => (
                        <motion.div key={t.id} initial={{ opacity: 0, scale: 0.95 }} animate={{ opacity: 1, scale: 1 }} transition={{ delay: idx * 0.05 }} className="glass-card" style={{ padding: '16px 20px', display: 'flex', alignItems: 'flex-start', gap: '14px', border: t.status === 'in_progress' ? '1px solid rgba(255,75,0,0.3)' : '', background: t.status === 'in_progress' ? 'rgba(255,75,0,0.05)' : '' }}>
                          <div style={{ marginTop: '2px' }}>
                            {t.status === 'completed' ? <CheckCircle2 size={20} color="var(--success)" /> : (t.status === 'in_progress' ? <Loader2 size={20} color="var(--accent)" className="spin" /> : <Circle size={20} color="var(--border)" />)}
                          </div>
                          <span style={{ fontSize: '14px', lineHeight: 1.5, color: t.status === 'completed' ? 'var(--text-dim)' : 'var(--text)' }}>{t.content}</span>
                        </motion.div>
                      ))}
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>

              <div data-transcript style={{ flex: 1, padding: '32px', overflowY: 'auto', fontFamily: 'JetBrains Mono, monospace', fontSize: '13px', lineHeight: 1.7 }}>
                {log.length === 0 && !running && (
                   <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.3 }} style={{ height: '100%', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', opacity: 0.7 }}>
                     <div style={{ boxSizing: 'border-box', padding: '24px', borderRadius: '50%', background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.05)', marginBottom: '32px' }}>
                        <Sparkles size={48} color="var(--text-dim)" />
                     </div>
                     <h2 style={{ fontSize: '22px', fontWeight: 500, marginBottom: '12px', fontFamily: 'Plus Jakarta Sans, sans-serif' }}>Ready to generate</h2>
                     <p style={{ color: 'var(--text-dim)', fontSize: '15px', fontFamily: 'Plus Jakarta Sans, sans-serif' }}>Configure your project architecture on the left.</p>
                   </motion.div>
                )}

                <div style={{ maxWidth: '850px', margin: '0 auto', display: 'flex', flexDirection: 'column', gap: '16px' }}>
                  <AnimatePresence>
                    {log.map((l) => (
                      <motion.div key={l.id} initial={{ opacity: 0, y: 15 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4 }}>
                        {l.type === 'assistant' && <div className="glass-card" style={{ padding: '20px', display: 'flex', gap: '16px' }}><div style={{ color: 'var(--accent)', fontWeight: 600 }}>AI</div><div>{l.text}</div></div>}
                        {l.type === 'tool_call' && <div style={{ display: 'flex', alignItems: 'center', gap: '12px', color: 'var(--text)', padding: '0 20px' }}><div style={{ width: '6px', height: '6px', borderRadius: '50%', background: 'var(--accent)', boxShadow: '0 0 8px var(--accent)' }}></div><strong>{l.verb}</strong> <span style={{ color: 'var(--text-dim)' }}>{l.target}</span></div>}
                        {l.type === 'tool_result' && <div style={{ color: l.ok ? 'var(--text-dim)' : 'var(--error)', marginLeft: '23px', paddingLeft: '16px', borderLeft: '1px solid var(--border)' }}>{l.ok ? '✓ ' : '✗ '}{l.text}</div>}
                        {l.type === 'status' && <div style={{ color: 'var(--text-muted)', fontSize: '12px', marginTop: '8px', textTransform: 'uppercase', letterSpacing: '0.1em', padding: '0 20px' }}>— {l.text}</div>}
                        {l.type === 'error' && <div style={{ color: 'var(--error)', padding: '12px 20px', background: 'rgba(239,68,68,0.08)', borderRadius: '12px', border: '1px solid rgba(239,68,68,0.25)', whiteSpace: 'pre-wrap' }}>✗ {l.text}</div>}
                        {l.type === 'warning' && <div style={{ color: 'var(--warning)', padding: '0 20px' }}>⚠ {l.text}</div>}
                        {l.type === 'thinking' && <div style={{ color: 'var(--text-dim)', fontStyle: 'italic', padding: '16px 20px', background: 'rgba(0,0,0,0.2)', borderRadius: '12px', border: '1px solid rgba(255,255,255,0.03)' }}>{l.text}</div>}
                        {l.type === 'done' && (
                          <div className="glass-card" style={{ marginTop: '24px', padding: '32px', border: `1px solid ${l.data.success ? 'rgba(16, 185, 129, 0.2)' : 'rgba(245, 158, 11, 0.2)'}`, background: l.data.success ? 'rgba(16, 185, 129, 0.05)' : 'rgba(245, 158, 11, 0.05)' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '16px', marginBottom: '20px' }}>
                              <div style={{ padding: '10px', borderRadius: '50%', background: l.data.success ? 'rgba(16,185,129,0.1)' : 'rgba(245,158,11,0.1)' }}>
                                {l.data.success ? <CheckCircle2 size={24} color="var(--success)" /> : <AlertTriangle size={24} color="var(--warning)" />}
                              </div>
                              <h3 style={{ fontSize: '20px', fontWeight: 600, color: 'white', fontFamily: 'Plus Jakarta Sans, sans-serif' }}>{l.data.success ? 'Generation Complete' : `Stopped: ${l.data.stop_reason}`}</h3>
                            </div>
                            <p style={{ fontSize: '14px', lineHeight: 1.7, marginBottom: '24px', color: 'rgba(255,255,255,0.8)' }}>{l.data.summary}</p>
                            <div style={{ display: 'flex', gap: '32px', color: 'var(--text-dim)', fontSize: '12px', textTransform: 'uppercase', letterSpacing: '0.1em', fontFamily: 'Plus Jakarta Sans, sans-serif' }}>
                              <div><strong style={{ color: 'white', display: 'block', fontSize: '18px', fontWeight: 600, letterSpacing: 0 }}>{l.data.turns}</strong> Turns</div>
                              <div><strong style={{ color: 'white', display: 'block', fontSize: '18px', fontWeight: 600, letterSpacing: 0 }}>{l.data.elapsed_s?.toFixed(0)}s</strong> Elapsed</div>
                              <div><strong style={{ color: 'white', display: 'block', fontSize: '18px', fontWeight: 600, letterSpacing: 0 }}>{l.data.files?.length || 0}</strong> Files</div>
                            </div>
                          </div>
                        )}
                      </motion.div>
                    ))}
                  </AnimatePresence>
                  <div ref={logEndRef} style={{ height: '40px' }} />
                </div>
              </div>
            </div>
          </motion.div>

          <AnimatePresence>
            {showSettings && (
              <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(8px)', zIndex: 100, display: 'flex', justifyContent: 'center', alignItems: 'center' }}>
                <motion.div initial={{ scale: 0.95, opacity: 0, y: 20 }} animate={{ scale: 1, opacity: 1, y: 0 }} exit={{ scale: 0.95, opacity: 0, y: 20 }} className="glass-panel" style={{ width: '440px', background: 'var(--panel)' }}>
                  <div style={{ padding: '24px 32px', borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <h2 style={{ fontSize: '18px', fontWeight: 600 }}>Preferences</h2>
                    <button className="button-icon" onClick={() => setShowSettings(false)}><X size={20}/></button>
                  </div>
                  <div style={{ padding: '32px', display: 'flex', flexDirection: 'column', gap: '24px' }}>
                    <div className="input-group">
                      <label className="label-text">Base URL</label>
                      <input type="text" className="input-field" value={settings.base_url} onChange={e => handleChange('base_url', e.target.value)} />
                    </div>
                    <div className="input-group">
                      <label className="label-text">Max Turns</label>
                      <input type="number" className="input-field" value={settings.max_turns} onChange={e => handleChange('max_turns', parseInt(e.target.value))} />
                    </div>
                    <div className="glass-card" style={{ display: 'flex', alignItems: 'center', gap: '16px', padding: '16px 20px', cursor: 'pointer' }} onClick={() => handleChange('thinking', !settings.thinking)}>
                      <input type="checkbox" className="custom-checkbox" checked={settings.thinking} readOnly />
                      <label style={{ fontSize: '14px', fontWeight: 500, pointerEvents: 'none' }}>Show model reasoning</label>
                    </div>
                    <div className="glass-card" style={{ display: 'flex', alignItems: 'center', gap: '16px', padding: '16px 20px', cursor: 'pointer' }} onClick={() => handleChange('remember_key', !settings.remember_key)}>
                      <input type="checkbox" className="custom-checkbox" checked={settings.remember_key} readOnly />
                      <label style={{ fontSize: '14px', fontWeight: 500, pointerEvents: 'none' }}>Remember API keys</label>
                    </div>
                  </div>
                  <div style={{ padding: '24px 32px', borderTop: '1px solid var(--border)', display: 'flex', justifyContent: 'flex-end', background: 'rgba(0,0,0,0.1)' }}>
                    <button className="button-primary" onClick={() => { window.api.invoke('save_settings', settings); setShowSettings(false); }}>Save Preferences</button>
                  </div>
                </motion.div>
              </motion.div>
            )}
          </AnimatePresence>

          <style>{`
            .spin { animation: spin 1s linear infinite; }
            @keyframes spin { 100% { transform: rotate(360deg); } }
          `}</style>
        </div>
      )}
    </>
  );
}

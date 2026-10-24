import { useEffect, useMemo, useRef, useState } from 'react';
import Window from './components/Window.jsx';
import { addFile, deleteFile, getNote, listFiles, saveNote } from './db.js';

const APPS = [
  { id:'explorer', name:'File Explorer', icon:'📁', description:'Browse local workspace' },
  { id:'notepad', name:'Notepad', icon:'📝', description:'Write and save a note' },
  { id:'settings', name:'Settings', icon:'⚙️', description:'Desktop preferences' },
  { id:'about', name:'About Cloud PC', icon:'☁️', description:'What this simulation does' }
];

function Clock() {
  const [now, setNow] = useState(new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);
  return <div className="clock"><span>{now.toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'})}</span><small>{now.toLocaleDateString([], {day:'2-digit', month:'short'})}</small></div>;
}

function Notepad({ noteId='main' }) {
  const [value, setValue] = useState('');
  const [status, setStatus] = useState('Loading local note…');
  const timer = useRef(null);
  const latestValue = useRef('');
  const pendingSave = useRef(false);
  useEffect(() => {
    let alive = true;
    getNote(noteId).then(text => {
      if (alive) {
        latestValue.current = text;
        setValue(text);
        setStatus('Saved locally');
      }
    }).catch(() => { if (alive) setStatus('Local database unavailable'); });
    return () => {
      alive = false;
      clearTimeout(timer.current);
      // Flush a pending debounced edit when the user closes Notepad quickly.
      if (pendingSave.current) {
        pendingSave.current = false;
        saveNote(noteId, latestValue.current).catch(() => {});
      }
    };
  }, [noteId]);
  const change = (next) => {
    latestValue.current = next;
    pendingSave.current = true;
    setValue(next);
    setStatus('Unsaved changes');
    clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      pendingSave.current = false;
      saveNote(noteId, next).then(() => setStatus('Saved locally · ' + new Date().toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'})))
        .catch(() => setStatus('Could not save locally'));
    }, 300);
  };
  return <div className="notepad">
    <div className="editor-toolbar"><span>Untitled note</span><span className="save-status">{status}</span></div>
    <textarea aria-label="Note content" value={value} onChange={e=>change(e.target.value)} placeholder="Start typing… Your note is stored in this browser on this device." />
    <div className="editor-footer"><span>{value.length} characters</span><span>Local-only storage</span></div>
  </div>;
}

function Explorer() {
  const [files, setFiles] = useState([]);
  const [busy, setBusy] = useState(true);
  const [message, setMessage] = useState('Loading files…');
  const inputRef = useRef(null);
  const refresh = async () => {
    try { setFiles(await listFiles()); setMessage(''); } catch { setMessage('Could not read local database.'); }
    finally { setBusy(false); }
  };
  useEffect(() => { refresh(); }, []);
  const upload = async (e) => {
    const chosen = Array.from(e.target.files || []);
    try {
      for (const file of chosen) await addFile(file);
      setMessage(chosen.length ? 'File metadata added to workspace.' : '');
      await refresh();
    } catch { setMessage('Unable to add file metadata.'); }
    e.target.value = '';
  };
  const remove = async (id) => { await deleteFile(id); await refresh(); };
  return <div className="explorer">
    <div className="explorer-toolbar"><div className="crumb">⌂ <span>/</span> This device <span>/</span> Workspace</div><button className="primary-button" onClick={()=>inputRef.current?.click()}>＋ Add files</button><input ref={inputRef} hidden type="file" multiple onChange={upload} /></div>
    <div className="file-heading"><span>Name</span><span>Type</span><span>Size</span><span></span></div>
    {busy && <div className="empty-state">{message}</div>}
    {!busy && files.length === 0 && <div className="empty-state"><div className="empty-icon">📂</div><strong>This workspace is empty</strong><p>Add files to record their names and details in local storage.</p><small>File contents are not uploaded or copied into this demo workspace.</small></div>}
    {files.map(file => <div className="file-row" key={file.id}><span className="file-name">📄 {file.name}</span><span>{file.type || 'File'}</span><span>{file.size ? (file.size/1024).toFixed(1)+' KB' : '—'}</span><button className="icon-button" title="Remove entry" aria-label={'Remove '+file.name} onClick={()=>remove(file.id)}>×</button></div>)}
    {message && !busy && <p className="inline-message">{message}</p>}
    <div className="explorer-note">Demo workspace · Entries are saved in IndexedDB on this device.</div>
  </div>;
}

function Settings({ wallpaper, setWallpaper }) {
  const options = [
    ['aurora','Aurora'],['midnight','Midnight'],['dusk','Dusk']
  ];
  return <div className="settings-view">
    <h2>Personalization</h2><p>Choose a desktop background.</p>
    <div className="wallpaper-options">{options.map(([id,label])=><button key={id} className={'wallpaper-option '+(wallpaper===id?'selected':'')} onClick={()=>setWallpaper(id)}><span className={'wallpaper-preview '+id}/><span>{label}</span></button>)}</div>
    <div className="notice">Storage note: notes and workspace entries remain in this browser profile. They are not synchronized to a cloud server.</div>
  </div>;
}

function About() {
  return <div className="about-view"><div className="about-logo">☁</div><h2>My Cloud PC</h2><p>A touch-friendly desktop simulation that runs in your browser.</p><div className="about-grid"><div><strong>Included</strong><span>Window controls, taskbar, Start menu</span></div><div><strong>Local storage</strong><span>IndexedDB via Dexie.js</span></div><div><strong>Not included</strong><span>Remote CPU, remote desktop sessions, cloud file sync</span></div></div><p className="muted">This is a local web app demo, not a hosted virtual machine.</p></div>;
}

export default function App() {
  const [startOpen, setStartOpen] = useState(false);
  const [search, setSearch] = useState('');
  const [windows, setWindows] = useState([]);
  const [minimized, setMinimized] = useState([]);
  const [topZ, setTopZ] = useState(20);
  const [wallpaper, setWallpaper] = useState(() => { try { return localStorage.getItem('cloudpc-wallpaper') || 'aurora'; } catch { return 'aurora'; } });
  const [mobile, setMobile] = useState(window.matchMedia('(max-width: 680px)').matches);

  useEffect(() => {
    const m = window.matchMedia('(max-width: 680px)');
    const update = () => setMobile(m.matches);
    m.addEventListener?.('change', update);
    return () => m.removeEventListener?.('change', update);
  }, []);

  const visibleApps = useMemo(() => APPS.filter(a => a.name.toLowerCase().includes(search.toLowerCase())), [search]);
  const launch = (appId) => {
    setWindows(current => {
      const existing = current.find(w=>w.id===appId);
      if (existing) return current.map(w=>w.id===appId?{...w,z:topZ+1}:w);
      return [...current, {id:appId,title:APPS.find(a=>a.id===appId)?.name || appId,z:topZ+1,maximized:false,pos:{x:70+current.length*28,y:50+current.length*24}}];
    });
    setMinimized(list=>list.filter(id=>id!==appId));
    setTopZ(z=>z+1);
    setStartOpen(false);
    setSearch('');
  };
  const close = (id) => { setWindows(list=>list.filter(w=>w.id!==id)); setMinimized(list=>list.filter(x=>x!==id)); };
  const focus = (id) => { setTopZ(z=>z+1); setWindows(list=>list.map(w=>w.id===id?{...w,z:topZ+1}:w)); };
  const minimize = (id) => setMinimized(list=>list.includes(id)?list:[...list,id]);
  const toggleMax = (id) => setWindows(list=>list.map(w=>w.id===id?{...w,maximized:!w.maximized}:w));
  const changeWallpaper = (value) => { setWallpaper(value); try { localStorage.setItem('cloudpc-wallpaper', value); } catch { /* Keep the current-session choice if storage is blocked. */ } };
  const renderApp = (id) => {
    if (id==='notepad') return <Notepad />;
    if (id==='explorer') return <Explorer />;
    if (id==='settings') return <Settings wallpaper={wallpaper} setWallpaper={changeWallpaper} />;
    return <About />;
  };

  return <main className={'desktop wallpaper-'+wallpaper} onPointerDown={e=>{if(e.target===e.currentTarget) setStartOpen(false);}}>
    <div className="desktop-topline"><div className="brand-pill"><span className="brand-mark">◈</span><span>Cloud<span className="brand-light">PC</span></span></div><div className="desktop-caption">PERSONAL WEB DESKTOP <span>•</span> LOCAL SESSION</div><button className="top-action" onClick={()=>launch('about')}>ⓘ About</button></div>
    <div className="desktop-icons">
      {APPS.map((app,index)=><button key={app.id} className="desktop-icon" style={{'--i':index}} onDoubleClick={()=>launch(app.id)} onClick={()=>{if(mobile) launch(app.id);}} aria-label={'Open '+app.name}><span className={'desktop-icon-art icon-'+app.id}>{app.icon}</span><span>{app.name}</span></button>)}
      <button className="desktop-icon recycle" onDoubleClick={()=>launch('explorer')} onClick={()=>{if(mobile) launch('explorer');}}><span className="desktop-icon-art">🗑️</span><span>Recycle Bin</span></button>
    </div>

    {windows.filter(w=>!minimized.includes(w.id)).map(w=><Window key={w.id} id={w.id} title={w.title} initialPos={w.pos} zIndex={w.z} isMaximized={w.maximized} mobileFullscreen={mobile} onClose={close} onMinimize={minimize} onFocus={focus} onToggleMaximize={toggleMax}>{renderApp(w.id)}</Window>)}

    {startOpen && <div className="start-menu" onPointerDown={e=>e.stopPropagation()}>
      <div className="start-profile"><div className="avatar">C</div><div><strong>Cloud PC</strong><small>Local desktop</small></div><span className="profile-status">● Ready</span></div>
      <div className="start-search"><span>⌕</span><input aria-label="Search apps" value={search} onChange={e=>setSearch(e.target.value)} placeholder="Search apps and tools" autoFocus /></div>
      <div className="start-section-title">Pinned apps <span>{visibleApps.length} apps</span></div>
      <div className="start-app-grid">{visibleApps.map(app=><button key={app.id} onClick={()=>launch(app.id)}><span className="start-app-icon">{app.icon}</span><span><strong>{app.name}</strong><small>{app.description}</small></span></button>)}</div>
      <div className="start-bottom"><span>◈ CloudPC Demo</span><button onClick={()=>launch('settings')}>⚙ Settings</button></div>
    </div>}

    <footer className="taskbar">
      <button className={'start-button '+(startOpen?'active':'')} onClick={()=>setStartOpen(open=>!open)} aria-label="Open Start menu"><span className="start-logo">⊞</span><span className="start-label">Start</span></button>
      <div className="taskbar-divider"/>
      <div className="task-pins">{windows.map(w=><button key={w.id} className={'task-pin '+(!minimized.includes(w.id)?'running':'')} onClick={()=>minimized.includes(w.id)?(setMinimized(list=>list.filter(id=>id!==w.id)),focus(w.id)):minimize(w.id)} title={w.title}><span>{APPS.find(a=>a.id===w.id)?.icon}</span><span className="task-pin-label">{w.title}</span></button>)}</div>
      <div className="taskbar-spacer"/>
      <div className="system-tray"><span className="tray-icon" title="Network">◉</span><span className="tray-icon" title="Volume">◖</span><span className="tray-icon" title="Battery">▰</span><Clock/></div>
    </footer>
  </main>;
}

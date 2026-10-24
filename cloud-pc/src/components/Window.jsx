import { useEffect, useRef, useState } from 'react';

const clamp = (n, min, max) => Math.min(Math.max(n, min), Math.max(min, max));

export default function Window({
  id, title, children, onClose, onMinimize, onFocus,
  initialPos = { x: 70, y: 60 }, zIndex = 10, isMaximized = false,
  onToggleMaximize, mobileFullscreen = false
}) {
  const [pos, setPos] = useState(initialPos);
  const [size, setSize] = useState({ width: 560, height: 390 });
  const drag = useRef(null);
  const resize = useRef(null);
  const [interacting, setInteracting] = useState(false);
  const windowRef = useRef(null);

  useEffect(() => {
    const handleMove = (e) => {
      if (drag.current) {
        const d = drag.current;
        setPos({
          x: clamp(e.clientX - d.dx, 0, window.innerWidth - 120),
          y: clamp(e.clientY - d.dy, 0, window.innerHeight - 100)
        });
      } else if (resize.current) {
        const r = resize.current;
        setSize({
          width: clamp(r.width + e.clientX - r.x, 280, window.innerWidth - pos.x),
          height: clamp(r.height + e.clientY - r.y, 180, window.innerHeight - pos.y - 56)
        });
      }
    };
    const handleUp = () => {
      drag.current = null;
      resize.current = null;
      setInteracting(false);
    };
    window.addEventListener('pointermove', handleMove);
    window.addEventListener('pointerup', handleUp);
    window.addEventListener('pointercancel', handleUp);
    return () => {
      window.removeEventListener('pointermove', handleMove);
      window.removeEventListener('pointerup', handleUp);
      window.removeEventListener('pointercancel', handleUp);
    };
  }, [pos.x, pos.y]);

  const startDrag = (e) => {
    if (isMaximized || e.target.closest('button')) return;
    e.preventDefault();
    onFocus?.(id);
    drag.current = { dx: e.clientX - pos.x, dy: e.clientY - pos.y };
    setInteracting(true);
    e.currentTarget.setPointerCapture?.(e.pointerId);
  };

  const startResize = (e) => {
    e.preventDefault();
    e.stopPropagation();
    onFocus?.(id);
    resize.current = { x:e.clientX, y:e.clientY, width:size.width, height:size.height };
    setInteracting(true);
  };

  return (
    <section
      ref={windowRef}
      className={'app-window ' + (isMaximized ? 'maximized ' : '') + (mobileFullscreen ? 'mobile-fullscreen ' : '') + (interacting ? 'interacting' : '')}
      style={{ left:isMaximized || mobileFullscreen ? 0 : pos.x, top:isMaximized || mobileFullscreen ? 0 : pos.y, width:isMaximized || mobileFullscreen ? '100%' : size.width, height:isMaximized || mobileFullscreen ? 'calc(100% - 56px)' : size.height, zIndex }}
      onPointerDown={() => onFocus?.(id)}
      aria-label={title}
    >
      <header className="window-titlebar" onPointerDown={startDrag} onDoubleClick={() => onToggleMaximize?.(id)}>
        <div className="window-heading"><span className="window-app-dot" /> <strong>{title}</strong></div>
        <div className="window-controls">
          <button aria-label="Minimize window" title="Minimize" onPointerDown={e=>e.stopPropagation()} onClick={() => onMinimize?.(id)}>−</button>
          <button aria-label={isMaximized ? 'Restore window' : 'Maximize window'} title={isMaximized ? 'Restore' : 'Maximize'} onPointerDown={e=>e.stopPropagation()} onClick={() => onToggleMaximize?.(id)}>{isMaximized ? '❐' : '□'}</button>
          <button className="close-control" aria-label="Close window" title="Close" onPointerDown={e=>e.stopPropagation()} onClick={() => onClose?.(id)}>×</button>
        </div>
      </header>
      <div className="window-content">{children}</div>
      {!isMaximized && !mobileFullscreen && <div className="resize-handle" aria-label="Resize window" onPointerDown={startResize} />}
    </section>
  );
}

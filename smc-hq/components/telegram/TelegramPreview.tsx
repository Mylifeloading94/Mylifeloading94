'use client';

export function TelegramPreview({ text, signalId, demo, onClose }: { text: string; signalId: string; demo: boolean; onClose: () => void }) {
  return (
    <div className="modal-bg" role="dialog" aria-modal="true" aria-label="Telegram message preview" onClick={onClose}>
      <div className="tgphone" onClick={(e) => e.stopPropagation()}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
          <b style={{ fontFamily: 'Bangers, Impact', letterSpacing: '.06em', fontSize: 20 }}>✈ TELEGRAM {demo ? 'PREVIEW' : 'MESSAGE'}</b>
          <button className="btn sm red" onClick={onClose} aria-label="Close preview">✕</button>
        </div>
        {demo && <div className="chip demo" style={{ marginBottom: 8, color: '#0b0b14' }}>DEMO DATA — NOT SENT TO TELEGRAM</div>}
        <div className="tgbubble">{text}</div>
        <div style={{ marginTop: 8, fontSize: 11, opacity: 0.7 }}>{signalId}</div>
      </div>
    </div>
  );
}

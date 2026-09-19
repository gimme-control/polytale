// Small inline icons (stroke = currentColor).

type P = { className?: string };
const base = "shrink-0";

export const IconPlay = ({ className = "h-4 w-4" }: P) => (
  <svg viewBox="0 0 24 24" className={`${base} ${className}`} fill="currentColor"><path d="M8 5.5v13a1 1 0 0 0 1.5.86l10.2-6.5a1 1 0 0 0 0-1.72L9.5 4.64A1 1 0 0 0 8 5.5Z" /></svg>
);
export const IconSlow = ({ className = "h-4 w-4" }: P) => (
  <svg viewBox="0 0 24 24" className={`${base} ${className}`} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <path d="M4 15.5c0-3.6 2.9-6.5 6.5-6.5s6.5 2.9 6.5 6.5" />
    <path d="M17 15.5h2.2c.9 0 1.3-1 .7-1.6L18.6 12.6" />
    <path d="M3 15.5h15" />
    <path d="M7 15.5v2.5M14 15.5v2.5" />
    <path d="M8 11.5l2.5 2 2.5-2" />
  </svg>
);
export const IconEye = ({ className = "h-4 w-4" }: P) => (
  <svg viewBox="0 0 24 24" className={`${base} ${className}`} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
    <path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12Z" />
    <circle cx="12" cy="12" r="3" />
  </svg>
);
export const IconMic = ({ className = "h-6 w-6" }: P) => (
  <svg viewBox="0 0 24 24" className={`${base} ${className}`} fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round">
    <rect x="8.5" y="3" width="7" height="12" rx="3.5" fill="currentColor" fillOpacity="0.18" />
    <path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21M8.5 21h7" />
  </svg>
);
export const IconKeyboard = ({ className = "h-5 w-5" }: P) => (
  <svg viewBox="0 0 24 24" className={`${base} ${className}`} fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round">
    <rect x="2.5" y="6" width="19" height="12" rx="2.5" />
    <path d="M6 10h.01M9.3 10h.01M12.6 10h.01M15.9 10h.01M18 10h.01M6 13.5h.01M18 13.5h.01M9 14.5h6" />
  </svg>
);
export const IconBulb = ({ className = "h-4 w-4" }: P) => (
  <svg viewBox="0 0 24 24" className={`${base} ${className}`} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <path d="M9 18h6M10 21h4M12 3a6 6 0 0 0-3.5 10.9c.6.5 1 1.2 1 2V16h5v-.1c0-.8.4-1.5 1-2A6 6 0 0 0 12 3Z" />
  </svg>
);
export const IconCheck = ({ className = "h-3.5 w-3.5" }: P) => (
  <svg viewBox="0 0 24 24" className={`${base} ${className}`} fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round"><path d="M5 12.5l4.5 4.5L19 7.5" /></svg>
);
export const IconX = ({ className = "h-4 w-4" }: P) => (
  <svg viewBox="0 0 24 24" className={`${base} ${className}`} fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M6 6l12 12M18 6L6 18" /></svg>
);
export const IconRetry = ({ className = "h-4 w-4" }: P) => (
  <svg viewBox="0 0 24 24" className={`${base} ${className}`} fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M4 12a8 8 0 1 0 2.4-5.7M4 4v4.5h4.5" /></svg>
);
export const IconSend = ({ className = "h-4 w-4" }: P) => (
  <svg viewBox="0 0 24 24" className={`${base} ${className}`} fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M5 12h13M13 6l6 6-6 6" /></svg>
);
export const IconMenu = ({ className = "h-5 w-5" }: P) => (
  <svg viewBox="0 0 24 24" className={`${base} ${className}`} fill="currentColor"><circle cx="5.5" cy="12" r="1.7" /><circle cx="12" cy="12" r="1.7" /><circle cx="18.5" cy="12" r="1.7" /></svg>
);
export const IconHeadphones = ({ className = "h-5 w-5" }: P) => (
  <svg viewBox="0 0 24 24" className={`${base} ${className}`} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
    <path d="M4 15v-3a8 8 0 0 1 16 0v3" />
    <rect x="3" y="14" width="4.5" height="7" rx="2" />
    <rect x="16.5" y="14" width="4.5" height="7" rx="2" />
  </svg>
);
export const IconVolume = ({ className = "h-4 w-4" }: P) => (
  <svg viewBox="0 0 24 24" className={`${base} ${className}`} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <path d="M4 9.5h3.5L12 5.5v13l-4.5-4H4z" fill="currentColor" fillOpacity="0.15" />
    <path d="M15.5 9a4 4 0 0 1 0 6M18 6.5a7.5 7.5 0 0 1 0 11" />
  </svg>
);
export const IconHand = ({ className = "h-4 w-4" }: P) => (
  <svg viewBox="0 0 24 24" className={`${base} ${className}`} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <path d="M9 11V5.5a1.5 1.5 0 0 1 3 0V11M12 10V4.5a1.5 1.5 0 0 1 3 0V11M15 10.5V6.5a1.5 1.5 0 0 1 3 0V14a7 7 0 0 1-7 7h-.5a6 6 0 0 1-5-2.7L3.2 15a1.6 1.6 0 0 1 2.6-1.8L9 16V11" />
  </svg>
);

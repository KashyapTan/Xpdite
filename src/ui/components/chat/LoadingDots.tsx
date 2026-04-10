import { useState, useEffect } from 'react';
import '../../CSS/chat/LoadingDots.css';

// DEV: set to true to always show the animation for styling
const DEV_PREVIEW = false;

interface LoadingDotsProps {
  isVisible?: boolean;
}

export function LoadingDots({ isVisible = true }: LoadingDotsProps) {
  const [render, setRender] = useState(DEV_PREVIEW || isVisible);

  useEffect(() => {
    if (DEV_PREVIEW || isVisible) setRender(true);
  }, [isVisible]);

  const onAnimationEnd = () => {
    if (!DEV_PREVIEW && !isVisible) setRender(false);
  };

  if (!render) return null;

  return (
    <div
      className={`thinking-animation-container ${!DEV_PREVIEW && !isVisible ? 'fade-out' : ''}`}
      onAnimationEnd={onAnimationEnd}
    >
      <div className="black-hole-wrapper">
        <div className="gravitational-lens"></div>
        <div className="accretion-disk"></div>
        <div className="event-horizon"></div>
        <div className="black-hole-core"></div>
      </div>
    </div>
  );
}

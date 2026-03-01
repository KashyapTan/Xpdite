import { useState, useEffect } from 'react';
import '../../CSS/LoadingDots.css';

interface LoadingDotsProps {
  isVisible?: boolean;
}

export function LoadingDots({ isVisible = true }: LoadingDotsProps) {
  const [render, setRender] = useState(isVisible);

  useEffect(() => {
    if (isVisible) setRender(true);
  }, [isVisible]);

  const onAnimationEnd = () => {
    if (!isVisible) setRender(false);
  };

  if (!render) return null;

  return (
    <div
      className={`thinking-animation-container ${!isVisible ? 'fade-out' : ''}`}
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

import '../../CSS/LoadingDots.css';

export function LoadingDots() {
  return (
    <div className="thinking-animation-container">
      <div className="black-hole-wrapper">
        <div className="gravitational-lens"></div>
        <div className="accretion-disk"></div>
        <div className="event-horizon"></div>
        <div className="black-hole-core"></div>
      </div>
    </div>
  );
}

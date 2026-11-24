import { RiskLegend } from './components/RiskLegend';
import { MapView } from './map/MapView';

export function App() {
  return (
    <div className="layout">
      <aside className="panel" aria-label="Trip planner">
        <header>
          <h1>Weather-Aware Truck Routing</h1>
          <p className="muted">Plan a trip to compare routes by forecast weather risk.</p>
        </header>
        {/* Phase 4: trip form and route cards. */}
        <RiskLegend />
      </aside>
      <main className="map-area">
        <MapView />
        {/* Phase 5: heatmap slider docked here. */}
      </main>
    </div>
  );
}

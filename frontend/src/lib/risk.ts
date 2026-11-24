/**
 * Risk level presentation: colours and labels only.
 *
 * The backend alone computes risk. Nothing here (or anywhere in the frontend) may derive a level
 * from weather values; components only map a level the API returned to its colour and label.
 * One palette is used for route lines, checkpoint dots, mileage bars, the legend and the heatmap.
 */
import type { CheckpointLevel, RiskLevelKey } from '../api/types';

export interface RiskStyle {
  label: string;
  colour: string;
  /** Text colour that stays readable on top of `colour`. */
  onColour: string;
}

/** Ordered Low to No Travel; the index equals the backend's numeric level (0-4). */
export const RISK_LEVELS: readonly RiskLevelKey[] = ['low', 'moderate', 'high', 'severe', 'no_travel'];

export const RISK_STYLES: Readonly<Record<CheckpointLevel, RiskStyle>> = {
  low: { label: 'Low', colour: '#1a9850', onColour: '#ffffff' },
  moderate: { label: 'Moderate', colour: '#f2c12e', onColour: '#1f1f1f' },
  high: { label: 'High', colour: '#f46d43', onColour: '#1f1f1f' },
  severe: { label: 'Severe', colour: '#d73027', onColour: '#ffffff' },
  no_travel: { label: 'No Travel', colour: '#5e1a7a', onColour: '#ffffff' },
  unknown: { label: 'No forecast', colour: '#9aa0a6', onColour: '#1f1f1f' },
};

/** Map a heatmap cell value (0-4 or null) to its level key; null means no forecast. */
export function levelFromIndex(index: number | null): CheckpointLevel {
  if (index === null) return 'unknown';
  return RISK_LEVELS[index] ?? 'unknown';
}

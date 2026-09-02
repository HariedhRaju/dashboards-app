import os
import textwrap

API_FILE = "a:\\vs _codes\\coe\\dash_board\\dashboards-app\\dashboards-frontend\\src\\api.ts"

with open(API_FILE, 'r', encoding='utf-8') as f:
    content = f.read()

new_types_and_functions = """
export interface FeatureHealth {
  name: string;
  total_bugs: number;
  open_bugs: number;
  in_progress_bugs: number;
  closed_bugs: number;
  critical_bugs: number;
  high_bugs: number;
  medium_bugs: number;
  low_bugs: number;
  risk_score: number;
  confidence_score: number;
  health_status: 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'SAFE';
}

export interface GameHealth {
  project_id: string;
  name: string;
  total_bugs: number;
  open_bugs: number;
  in_progress_bugs: number;
  closed_bugs: number;
  critical_bugs: number;
  high_bugs: number;
  medium_bugs: number;
  low_bugs: number;
  feature_count: number;
  risk_score: number;
  confidence_score: number;
  health_status: 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'SAFE';
}

export interface GameHealthResponse {
  game: GameHealth;
  features: FeatureHealth[];
}

export async function fetchGameHealth(projectId: string): Promise<GameHealthResponse> {
  const res = await fetch(`${API_BASE}/api/bugs/game-health?project_id=${projectId}`, {
    credentials: 'include',
  });
  if (!res.ok) {
    throw new Error('Failed to fetch game health');
  }
  return res.json();
}

export async function fetchGameSummary(gameHealth: any): Promise<{ summary: string }> {
  const res = await fetch(`${API_BASE}/api/bugs/game-summary`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(gameHealth),
    credentials: 'include',
  });
  if (!res.ok) {
    throw new Error('Failed to fetch game summary');
  }
  return res.json();
}
"""

if "export interface GameHealth" not in content:
    content += "\n" + new_types_and_functions
    with open(API_FILE, 'w', encoding='utf-8') as f:
        f.write(content)
    print("Updated api.ts")
else:
    print("api.ts already updated")

"""Generate a sortable HTML report of saved starter states."""

from __future__ import annotations

import argparse
import html
import re
from dataclasses import dataclass
from pathlib import Path


STATE_NAME_RE = re.compile(
    r"^(?P<pokemon>.+?)\s+-\s+(?P<dvs>PERFECT|\d+(?:-\d+){3})\.state$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class StarterState:
    pokemon: str
    attack: int
    defense: int
    speed: int
    special: int
    state_path: Path
    env_name: str

    @property
    def total(self) -> int:
        return self.attack + self.defense + self.speed + self.special

    @property
    def perfect(self) -> bool:
        return self.total == 60


def parse_state_path(state_path: Path, envs_dir: Path) -> StarterState | None:
    match = STATE_NAME_RE.match(state_path.name)
    if match is None:
        return None

    dv_text = match.group("dvs").upper()
    values = (15, 15, 15, 15) if dv_text == "PERFECT" else tuple(
        int(value) for value in dv_text.split("-")
    )
    if any(value < 0 or value > 15 for value in values):
        return None

    relative_path = state_path.relative_to(envs_dir)
    env_name = relative_path.parts[0] if len(relative_path.parts) > 1 else "Unknown"
    return StarterState(
        pokemon=match.group("pokemon").strip(),
        attack=values[0],
        defense=values[1],
        speed=values[2],
        special=values[3],
        state_path=state_path,
        env_name=env_name,
    )


def find_states(envs_dir: Path) -> list[StarterState]:
    states = []
    for state_path in sorted(envs_dir.glob("*/states/*.state")):
        parsed = parse_state_path(state_path, envs_dir)
        if parsed is not None:
            states.append(parsed)
    return sorted(states, key=lambda state: (-state.total, state.pokemon.lower()))


def render_rows(states: list[StarterState], project_root: Path) -> str:
    rows = []
    for state in states:
        relative_state = state.state_path.relative_to(project_root).as_posix()
        cells = [
            state.pokemon,
            state.env_name,
            state.attack,
            state.defense,
            state.speed,
            state.special,
            state.total,
            "YES" if state.perfect else "",
            relative_state,
        ]
        row_class = " class=\"perfect\"" if state.perfect else ""
        rendered_cells = []
        for index, cell in enumerate(cells):
            rendered = html.escape(str(cell))
            if index == len(cells) - 1:
                rendered = f"<code>{rendered}</code>"
            rendered_cells.append(f"<td>{rendered}</td>")
        rows.append(f"<tr{row_class}>{''.join(rendered_cells)}</tr>")
    return "\n".join(rows) or '<tr><td colspan="9" class="empty">No saved states found.</td></tr>'


def render_html(states: list[StarterState], project_root: Path) -> str:
    rows = render_rows(states, project_root)
    generated_label = f"{len(states)} saved state{'s' if len(states) != 1 else ''}"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Pokemon Starter DVs</title>
  <style>
    :root {{ color-scheme: light; font-family: system-ui, sans-serif; }}
    body {{ margin: 0; padding: 24px; background: #f1f4f7; color: #17202a; }}
    main {{ max-width: 1200px; margin: 0 auto; }}
    h1 {{ margin: 0 0 4px; }}
    .summary {{ margin: 0 0 18px; color: #52606d; }}
    .table-wrap {{ max-height: 75vh; overflow: auto; background: white; border: 1px solid #cbd5df; border-radius: 8px; }}
    table {{ width: 100%; border-collapse: collapse; min-width: 850px; }}
    th, td {{ padding: 10px 12px; border-bottom: 1px solid #e4e9ee; text-align: left; white-space: nowrap; }}
    th {{ position: sticky; top: 0; z-index: 1; background: #263746; color: white; cursor: pointer; user-select: none; }}
    th:hover {{ background: #3d566a; }}
    td:nth-child(n+3):nth-child(-n+7) {{ text-align: right; font-variant-numeric: tabular-nums; }}
    tr.perfect {{ background: #fff4c2; font-weight: 600; }}
    tr:hover {{ background: #eaf3fb; }}
    tr.perfect:hover {{ background: #ffeaa0; }}
    code {{ font-size: 0.85em; }}
    .empty {{ text-align: center; padding: 28px; color: #687783; }}
  </style>
</head>
<body>
  <main>
    <h1>Pokemon Starter DVs</h1>
    <p class="summary">{html.escape(generated_label)}. Click any column header to sort.</p>
    <div class="table-wrap">
      <table id="starters">
        <thead><tr>
          <th data-type="text">Pokemon</th>
          <th data-type="text">Environment</th>
          <th data-type="number">Attack DV</th>
          <th data-type="number">Defense DV</th>
          <th data-type="number">Speed DV</th>
          <th data-type="number">Special DV</th>
          <th data-type="number">Total</th>
          <th data-type="text">Perfect</th>
          <th data-type="text">State file</th>
        </tr></thead>
        <tbody>{rows}</tbody>
      </table>
    </div>
  </main>
  <script>
    document.querySelectorAll("#starters th").forEach((header, index) => {{
      header.addEventListener("click", () => {{
        const table = header.closest("table");
        const body = table.querySelector("tbody");
        const ascending = header.dataset.order !== "asc";
        table.querySelectorAll("th").forEach(item => delete item.dataset.order);
        header.dataset.order = ascending ? "asc" : "desc";
        [...body.rows].sort((left, right) => {{
          const a = left.cells[index].textContent.trim();
          const b = right.cells[index].textContent.trim();
          const numeric = header.dataset.type === "number";
          const comparison = numeric ? Number(a) - Number(b) : a.localeCompare(b);
          return (ascending ? 1 : -1) * comparison;
        }}).forEach(row => body.appendChild(row));
      }});
    }});
  </script>
</body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--envs-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "envs",
        help="Folder containing one states/ folder per environment",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parent / "starter_report.html",
        help="HTML report path",
    )
    args = parser.parse_args()

    envs_dir = args.envs_dir.resolve()
    project_root = Path(__file__).resolve().parents[1]
    states = find_states(envs_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_html(states, project_root), encoding="utf-8")
    print(f"Found {len(states)} saved state(s).")
    print(f"Report written to: {args.output.resolve()}")


if __name__ == "__main__":
    main()
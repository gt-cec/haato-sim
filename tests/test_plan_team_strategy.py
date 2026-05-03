#!/usr/bin/env python3
"""
Test script for FireWatchWingman.plan_team_strategy method.

This script allows you to test the wingman's team planning heuristics by:
1. Setting up different mission states (positions, fire statuses)
2. Calling plan_team_strategy() directly
3. Rendering vector graphics visualizations saved to tests/wingman_plan_test_results/

Usage:
    python tests/test_plan_team_strategy.py          # Run all scenarios
    python tests/test_plan_team_strategy.py -s 2     # Run scenario 2 only
    python tests/test_plan_team_strategy.py -i       # Interactive mode
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np

# Configure matplotlib for non-interactive backend before importing pyplot
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from matplotlib.lines import Line2D

from utility.base_classes import Target, GeoUtils

__test__ = False


# =============================================================================
# CONFIGURATION
# =============================================================================

OUTPUT_DIR = Path(__file__).parent / "wingman_plan_test_results"

# Map bounds for visualization (derived from target positions)
MAP_BOUNDS = {
    'lat_min': 47.70,
    'lat_max': 48.00,
    'lon_min': -121.40,
    'lon_max': -120.85
}

# Fire status colors
STATUS_COLORS = {
    0.0: '#808080',  # Gray - Unclassified
    1.0: '#FFD700',  # Gold - Spotted
    2.0: '#FF8C00',  # Orange - Position Marked
    3.0: '#32CD32',  # Green - Initial Route Done
    4.0: '#4169E1',  # Blue - Fully Handled
}

STATUS_NAMES = {
    0.0: "Unclassified",
    1.0: "Spotted",
    2.0: "Position Marked",
    3.0: "Initial Route Done",
    4.0: "Fully Handled"
}

CLASSIFICATION_NAMES = {
    0: "Unknown",
    1: "Moderate",
    2: "Severe"
}


# =============================================================================
# MOCK CLASSES
# =============================================================================

class MockXPC:
    """Mock XPC connection for testing without X-Plane."""

    def __init__(self):
        self.drefs = {}

    def getDREF(self, dref_name, fallback=None):
        """Get a dataref value, returning fallback if not set."""
        return self.drefs.get(dref_name, fallback if fallback is not None else 0.0)

    def sendDREF(self, dref_name, value):
        """Set a dataref value."""
        self.drefs[dref_name] = value


class MockMissionManager:
    """Minimal mock of FireWatchMM providing just what plan_team_strategy needs."""

    def __init__(self, targets):
        self.targets = targets
        self.target_id_to_index = {t.id: i for i, t in enumerate(targets)}


# =============================================================================
# TEST DATA SETUP
# =============================================================================

# Synthetic fire targets shaped like HAATO config.yaml mission entries.
FIRE_TARGETS_DATA = [
    {"latitude": 47.9748, "longitude": -121.258566, "altitude": 1500.2, "type": "moderate"},
    {"latitude": 47.76563325, "longitude": -121.318566, "altitude": 400.2, "type": "severe"},
    {"latitude": 47.8364665, "longitude": -121.318566, "altitude": 800.7, "type": "moderate"},
    {"latitude": 47.8364665, "longitude": -120.897615, "altitude": 620.0, "type": "severe"},
    {"latitude": 47.75563325, "longitude": -121.21332825, "altitude": 1300.9, "type": "moderate"},
    {"latitude": 47.76223325, "longitude": -121.1080905, "altitude": 1500.2, "type": "severe"},
    {"latitude": 47.90729975, "longitude": -121.00285275, "altitude": 1300.8, "type": "moderate"},
    {"latitude": 47.942133, "longitude": -121.00285275, "altitude": 1300.8, "type": "moderate"},
]


def create_targets():
    """Create Target objects from the fire data."""
    targets = []
    for i, data in enumerate(FIRE_TARGETS_DATA):
        target = Target(
            type=data["type"],
            lat=data["latitude"],
            long=data["longitude"],
            alt=data["altitude"],
            id=i
        )
        targets.append(target)
    return targets


def create_observation(mission_timer, human_pos, targets):
    """
    Build observation array matching the format expected by plan_team_strategy.

    Args:
        mission_timer: Mission elapsed time in seconds
        human_pos: Tuple of (lat, long, alt, hdg, spd)
        targets: List of Target objects

    Returns:
        numpy array with observation data
    """
    obs = np.zeros(6 + len(targets) * 8, dtype=np.float64)

    # Base observation data
    obs[0] = mission_timer
    obs[1] = human_pos[0]  # lat
    obs[2] = human_pos[1]  # long
    obs[3] = human_pos[2]  # alt
    obs[4] = human_pos[3] if len(human_pos) > 3 else 90.0   # hdg
    obs[5] = human_pos[4] if len(human_pos) > 4 else 150.0  # spd

    # Target data (8 values per target)
    for i, t in enumerate(targets):
        idx = 6 + i * 8
        obs[idx + 0] = t.lat
        obs[idx + 1] = t.long
        obs[idx + 2] = t.alt
        obs[idx + 3] = float(t.spotted)
        obs[idx + 4] = float(t.handled)
        obs[idx + 5] = float(t.is_being_handled)
        obs[idx + 6] = t.human_in_range_time
        obs[idx + 7] = t.wingman_in_range_time

    return obs


def setup_fire_drefs(xpc, statuses, classifications=None, whoflew_initial=None):
    """
    Set up fire status datarefs in the mock XPC.

    Args:
        xpc: MockXPC instance
        statuses: List of 8 status values (0.0-4.0)
        classifications: List of 8 classification values (0, 1, or 2)
        whoflew_initial: List of 8 values (0.0=none, 1.0=human, 2.0=wingman)
    """
    if classifications is None:
        classifications = [0] * 8
    if whoflew_initial is None:
        whoflew_initial = [0.0] * 8

    for i in range(8):
        xpc.sendDREF(f"custom/haato/target{i}status", statuses[i])
        xpc.sendDREF(f"custom/haato/target{i}classification", classifications[i])
        xpc.sendDREF(f"custom/haato/target{i}_whoflew_initial", whoflew_initial[i])


# =============================================================================
# VISUALIZATION - MATPLOTLIB VECTOR GRAPHICS
# =============================================================================

def render_scenario_image(scenario_name, scenario_num, human_pos, wingman_pos, targets,
                          statuses, classifications, human_current_plan, wingman_current_goal,
                          result, output_path):
    """
    Render a complete scenario visualization as a vector graphics image.

    Args:
        scenario_name: Description of the scenario
        scenario_num: Scenario number for filename
        human_pos: (lat, long, alt) tuple
        wingman_pos: (lat, long, alt) tuple
        targets: List of Target objects
        statuses: List of fire statuses (0.0-4.0)
        classifications: List of classifications (0, 1, 2)
        human_current_plan: Human's current plan (-1 for none)
        wingman_current_goal: Wingman's current goal (-1 for none)
        result: Dict with 'human_plan' and 'wingman_plan'
        output_path: Path to save the image
    """
    # Create figure with two subplots: map (left) and info panel (right)
    fig = plt.figure(figsize=(16, 10))

    # Left panel: Map (60% width)
    ax_map = fig.add_axes([0.05, 0.1, 0.55, 0.8])

    # Right panel: Info (35% width)
    ax_info = fig.add_axes([0.65, 0.1, 0.32, 0.8])
    ax_info.axis('off')

    # === DRAW MAP ===
    _draw_map(ax_map, human_pos, wingman_pos, targets, statuses, classifications,
              human_current_plan, wingman_current_goal, result)

    # === DRAW INFO PANEL ===
    _draw_info_panel(ax_info, scenario_name, human_pos, wingman_pos, targets,
                     statuses, classifications, human_current_plan, wingman_current_goal, result)

    # Title
    fig.suptitle(f"Scenario {scenario_num}: {scenario_name}", fontsize=14, fontweight='bold', y=0.97)

    # Save
    plt.savefig(output_path, dpi=150, bbox_inches='tight', facecolor='white')
    plt.close(fig)


def _draw_map(ax, human_pos, wingman_pos, targets, statuses, classifications,
              human_current_plan, wingman_current_goal, result):
    """Draw the map portion of the visualization."""

    # Set map bounds
    ax.set_xlim(MAP_BOUNDS['lon_min'], MAP_BOUNDS['lon_max'])
    ax.set_ylim(MAP_BOUNDS['lat_min'], MAP_BOUNDS['lat_max'])
    ax.set_aspect('equal', adjustable='box')

    # Grid
    ax.grid(True, linestyle='--', alpha=0.3)
    ax.set_xlabel('Longitude', fontsize=10)
    ax.set_ylabel('Latitude', fontsize=10)
    ax.set_title('Mission Area', fontsize=12, fontweight='bold')

    # Calculate distances for display
    human_distances = []
    wingman_distances = []
    for target in targets:
        human_distances.append(GeoUtils.haversine_distance(
            human_pos[0], human_pos[1], target.lat, target.long
        ))
        wingman_distances.append(GeoUtils.haversine_distance(
            wingman_pos[0], wingman_pos[1], target.lat, target.long
        ))

    # Draw fires as circles with status colors
    for i, target in enumerate(targets):
        status = statuses[i]
        color = STATUS_COLORS.get(status, '#808080')

        # Outer circle (fire marker)
        circle = patches.Circle(
            (target.long, target.lat),
            radius=0.015,
            facecolor=color,
            edgecolor='black',
            linewidth=2,
            zorder=10
        )
        ax.add_patch(circle)

        # Fire type indicator (inner marker for severe)
        # if target.type == "severe":
        #     inner = patches.Circle(
        #         (target.long, target.lat),
        #         radius=0.006,
        #         facecolor='red',
        #         edgecolor='darkred',
        #         linewidth=1,
        #         zorder=11
        #     )
        #     ax.add_patch(inner)

        # Fire ID label
        ax.annotate(
            str(i),
            (target.long, target.lat),
            fontsize=9,
            fontweight='bold',
            ha='center',
            va='center',
            color='white' if status in [0.0, 4.0] else 'black',
            zorder=12
        )

        # Distance labels (small text below fire)
        ax.annotate(
            f"H:{human_distances[i]:.1f}nm\nW:{wingman_distances[i]:.1f}nm",
            (target.long, target.lat - 0.025),
            fontsize=6,
            ha='center',
            va='top',
            color='#444444',
            zorder=5
        )

    # Draw suggested plan arrows
    human_plan = result['human_plan']
    wingman_plan = result['wingman_plan']

    if human_plan != 99.0 and 0 <= human_plan <= 7:
        target = targets[int(human_plan)]
        ax.annotate(
            '',
            xy=(target.long, target.lat),
            xytext=(human_pos[1], human_pos[0]),
            arrowprops=dict(
                arrowstyle='-|>',
                color='blue',
                lw=2,
                ls='--',
                mutation_scale=15
            ),
            zorder=8
        )

    if wingman_plan != 99.0 and 0 <= wingman_plan <= 7:
        target = targets[int(wingman_plan)]
        ax.annotate(
            '',
            xy=(target.long, target.lat),
            xytext=(wingman_pos[1], wingman_pos[0]),
            arrowprops=dict(
                arrowstyle='-|>',
                color='red',
                lw=2,
                ls='--',
                mutation_scale=15
            ),
            zorder=8
        )

    # Draw human position (blue triangle)
    ax.plot(
        human_pos[1], human_pos[0],
        marker='^',
        markersize=15,
        color='blue',
        markeredgecolor='darkblue',
        markeredgewidth=2,
        zorder=15,
        label='Human'
    )
    ax.annotate(
        'H',
        (human_pos[1], human_pos[0]),
        fontsize=8,
        fontweight='bold',
        ha='center',
        va='center',
        color='white',
        zorder=16
    )

    # Draw wingman position (red diamond)
    ax.plot(
        wingman_pos[1], wingman_pos[0],
        marker='D',
        markersize=13,
        color='red',
        markeredgecolor='darkred',
        markeredgewidth=2,
        zorder=15,
        label='Wingman'
    )
    ax.annotate(
        'W',
        (wingman_pos[1], wingman_pos[0]),
        fontsize=7,
        fontweight='bold',
        ha='center',
        va='center',
        color='white',
        zorder=16
    )

    # Legend for fire statuses
    legend_elements = [
        Line2D([0], [0], marker='^', color='w', markerfacecolor='blue',
               markeredgecolor='darkblue', markersize=10, label='Human'),
        Line2D([0], [0], marker='D', color='w', markerfacecolor='red',
               markeredgecolor='darkred', markersize=10, label='Wingman'),
        Line2D([0], [0], marker='o', color='w', markerfacecolor='#808080',
               markeredgecolor='black', markersize=10, label='Unclassified'),
        Line2D([0], [0], marker='o', color='w', markerfacecolor='#FFD700',
               markeredgecolor='black', markersize=10, label='Spotted'),
        Line2D([0], [0], marker='o', color='w', markerfacecolor='#FF8C00',
               markeredgecolor='black', markersize=10, label='Pos. Marked'),
        Line2D([0], [0], marker='o', color='w', markerfacecolor='#32CD32',
               markeredgecolor='black', markersize=10, label='Initial Done'),
        Line2D([0], [0], marker='o', color='w', markerfacecolor='#4169E1',
               markeredgecolor='black', markersize=10, label='Complete'),
        Line2D([0], [0], linestyle='--', color='blue', lw=2, label='Human Plan'),
        Line2D([0], [0], linestyle='--', color='red', lw=2, label='Wingman Plan'),
    ]
    ax.legend(handles=legend_elements, loc='lower left', fontsize=7, ncol=2)


def _draw_info_panel(ax, scenario_name, human_pos, wingman_pos, targets,
                     statuses, classifications, human_current_plan, wingman_current_goal, result):
    """Draw the information panel."""

    # Build info text
    lines = []

    # Header
    lines.append("=" * 40)
    lines.append("MISSION STATE")
    lines.append("=" * 40)
    lines.append("")

    # Positions
    lines.append("HUMAN:")
    lines.append(f"  Position: ({human_pos[0]:.4f}, {human_pos[1]:.4f})")
    lines.append(f"  Altitude: {human_pos[2]:.0f} m")
    if 0 <= human_current_plan <= 7:
        lines.append(f"  Current Plan: Fire {int(human_current_plan)}")
    else:
        lines.append("  Current Plan: None")
    lines.append("")

    lines.append("WINGMAN:")
    lines.append(f"  Position: ({wingman_pos[0]:.4f}, {wingman_pos[1]:.4f})")
    lines.append(f"  Altitude: {wingman_pos[2]:.0f} m")
    if wingman_current_goal >= 0:
        lines.append(f"  Current Goal: Fire {wingman_current_goal}")
    else:
        lines.append("  Current Goal: None")
    lines.append("")

    # Fire status table
    lines.append("-" * 40)
    lines.append("FIRE STATUS:")
    lines.append("-" * 40)
    lines.append(f"{'ID':<4}{'Type':<9}{'Status':<16}{'Class':<10}")
    lines.append("-" * 40)

    for i, target in enumerate(targets):
        status = statuses[i]
        status_name = STATUS_NAMES.get(status, f"?({status})")
        class_name = CLASSIFICATION_NAMES.get(int(classifications[i]), "?")
        fire_type = target.type[:8]  # Truncate type
        lines.append(f"{i:<4}{fire_type:<9}{status_name:<16}{class_name:<10}")

    lines.append("")

    # Suggested plan
    lines.append("=" * 40)
    lines.append("SUGGESTED TEAM PLAN")
    lines.append("=" * 40)
    lines.append("")

    human_plan = result['human_plan']
    wingman_plan = result['wingman_plan']

    if human_plan == 99.0:
        lines.append("Human: Keep current plan")
    else:
        lines.append(f"Human: Go to Fire {int(human_plan)}")

    if wingman_plan == 99.0:
        lines.append("Wingman: Keep current plan")
    else:
        lines.append(f"Wingman: Go to Fire {int(wingman_plan)}")

    # Render text
    text = "\n".join(lines)
    ax.text(
        0, 1, text,
        transform=ax.transAxes,
        fontsize=8,
        fontfamily='monospace',
        verticalalignment='top',
        horizontalalignment='left',
        bbox=dict(boxstyle='round', facecolor='#f8f8f8', edgecolor='#cccccc')
    )


# =============================================================================
# TEST SCENARIOS
# =============================================================================

def create_wingman(xpc, mock_mm, wingman_pos, autonomy_level=2.0, current_goal=-1):
    """
    Create a FireWatchWingman instance for testing.

    Args:
        xpc: MockXPC instance
        mock_mm: MockMissionManager instance
        wingman_pos: (lat, long, alt) tuple
        autonomy_level: 0.0=Low, 1.0=Medium, 2.0=High
        current_goal: Fire ID wingman is currently targeting (-1 for none)
    """
    from missions.firewatch_mission_vectorized import FireWatchWingman

    wingman = FireWatchWingman(
        xpc=xpc,
        start_lla=wingman_pos,
        start_hdg=90.0,
        start_spd=400,
        mm=mock_mm,
        autonomy_level=autonomy_level
    )

    # Set current goal if specified
    if current_goal >= 0:
        wingman.current_goal = current_goal

    return wingman


def run_scenario(scenario_num, scenario_name, human_pos, wingman_pos, statuses,
                 classifications=None, human_current_plan=-1.0, wingman_current_goal=-1,
                 whoflew_initial=None):
    """
    Run a single test scenario and save the visualization.

    Args:
        scenario_num: Scenario number (for filename)
        scenario_name: Description of the scenario
        human_pos: (lat, long, alt) or (lat, long, alt, hdg, spd)
        wingman_pos: (lat, long, alt)
        statuses: List of 8 fire statuses (0.0-4.0)
        classifications: List of 8 classifications (0, 1, 2)
        human_current_plan: Human's current indicated plan (-1 for none)
        wingman_current_goal: Wingman's current goal (-1 for none)
        whoflew_initial: List of who flew initial route (0=none, 1=human, 2=wingman)

    Returns:
        result dict from plan_team_strategy
    """
    print(f"  Running scenario {scenario_num}: {scenario_name}...")

    # Setup
    if classifications is None:
        classifications = [0] * 8
    if whoflew_initial is None:
        whoflew_initial = [0.0] * 8

    xpc = MockXPC()
    targets = create_targets()
    mock_mm = MockMissionManager(targets)

    # Set up datarefs
    setup_fire_drefs(xpc, statuses, classifications, whoflew_initial)
    xpc.sendDREF("custom/haato/human_indicated_plan", human_current_plan)

    # Create wingman
    wingman = create_wingman(xpc, mock_mm, wingman_pos, current_goal=wingman_current_goal)

    # Create observation
    mission_timer = 60.0
    obs = create_observation(mission_timer, human_pos, targets)

    # Run plan_team_strategy
    result = wingman.plan_team_strategy(obs)

    # Create output directory
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Generate filename
    safe_name = scenario_name.lower().replace(' ', '_').replace('-', '_')
    safe_name = ''.join(c for c in safe_name if c.isalnum() or c == '_')
    filename = f"scenario_{scenario_num:02d}_{safe_name}.png"
    output_path = OUTPUT_DIR / filename

    # Render and save image
    render_scenario_image(
        scenario_name, scenario_num, human_pos, wingman_pos, targets,
        statuses, classifications, human_current_plan, wingman_current_goal,
        result, output_path
    )

    print(f"    Saved: {output_path}")
    print(f"    Result: Human -> Fire {int(result['human_plan']) if result['human_plan'] != 99.0 else 'None'}, "
          f"Wingman -> Fire {int(result['wingman_plan']) if result['wingman_plan'] != 99.0 else 'None'}")

    return result


# =============================================================================
# PREDEFINED TEST SCENARIOS
# =============================================================================

SCENARIOS = [
    {
        "name": "All fires unclassified - spread positions",
        "human_pos": (47.75, -121.30, 1000),
        "wingman_pos": (47.92, -121.00, 1200),
        "statuses": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        "classifications": [0, 0, 0, 0, 0, 0, 0, 0],
    },
    {
        "name": "Mixed statuses - prioritization test",
        "human_pos": (47.80, -121.25, 1000),
        "wingman_pos": (47.85, -121.10, 1200),
        "statuses": [0.0, 1.0, 2.0, 0.0, 1.0, 2.0, 0.0, 3.0],
        "classifications": [0, 1, 2, 0, 1, 2, 0, 1],
    },
    {
        "name": "Human already has plan for Fire 2",
        "human_pos": (47.80, -121.25, 1000),
        "wingman_pos": (47.85, -121.10, 1200),
        "statuses": [0.0, 1.0, 2.0, 0.0, 1.0, 2.0, 0.0, 0.0],
        "classifications": [0, 1, 2, 0, 1, 2, 0, 0],
        "human_current_plan": 2.0,
    },
    {
        "name": "Multiple fires need initial routes",
        "human_pos": (47.76, -121.20, 1000),
        "wingman_pos": (47.90, -121.00, 1200),
        "statuses": [2.0, 2.0, 2.0, 2.0, 0.0, 0.0, 0.0, 0.0],
        "classifications": [1, 2, 1, 2, 0, 0, 0, 0],
    },
    {
        "name": "Refinement available - whoflew constraint",
        "human_pos": (47.80, -121.20, 1000),
        "wingman_pos": (47.85, -121.10, 1200),
        "statuses": [3.0, 3.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        "classifications": [1, 2, 0, 0, 0, 0, 0, 0],
        "whoflew_initial": [1.0, 2.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    },
    {
        "name": "Human and wingman close together",
        "human_pos": (47.84, -121.32, 1000),
        "wingman_pos": (47.83, -121.31, 1200),
        "statuses": [0.0, 1.0, 2.0, 0.0, 1.0, 0.0, 0.0, 0.0],
        "classifications": [0, 1, 2, 0, 1, 0, 0, 0],
    },
    {
        "name": "Some fires already complete",
        "human_pos": (47.80, -121.20, 1000),
        "wingman_pos": (47.90, -121.05, 1200),
        "statuses": [4.0, 4.0, 4.0, 0.0, 1.0, 2.0, 0.0, 0.0],
        "classifications": [1, 2, 1, 0, 1, 2, 0, 0],
    },
    {
        "name": "All fires complete - should return no plan",
        "human_pos": (47.80, -121.20, 1000),
        "wingman_pos": (47.90, -121.05, 1200),
        "statuses": [4.0, 4.0, 4.0, 4.0, 4.0, 4.0, 4.0, 4.0],
        "classifications": [1, 2, 1, 2, 1, 2, 1, 1],
    },
]


def run_all_scenarios():
    """Run all predefined test scenarios."""
    print(f"\n  Output directory: {OUTPUT_DIR}")
    print()

    for i, scenario in enumerate(SCENARIOS, 1):
        run_scenario(
            scenario_num=i,
            scenario_name=scenario["name"],
            human_pos=scenario["human_pos"],
            wingman_pos=scenario["wingman_pos"],
            statuses=scenario["statuses"],
            classifications=scenario.get("classifications"),
            human_current_plan=scenario.get("human_current_plan", -1.0),
            wingman_current_goal=scenario.get("wingman_current_goal", -1),
            whoflew_initial=scenario.get("whoflew_initial"),
        )
        print()


def interactive_mode():
    """Run in interactive mode, allowing custom scenarios."""

    print("\n  INTERACTIVE MODE")
    print("  Configure your test scenario:")
    print()

    # Default positions (can be modified)
    human_lat = float(input("  Human latitude [47.80]: ") or 47.80)
    human_long = float(input("  Human longitude [-121.20]: ") or -121.20)
    human_alt = float(input("  Human altitude [1000]: ") or 1000)

    wingman_lat = float(input("  Wingman latitude [47.90]: ") or 47.90)
    wingman_long = float(input("  Wingman longitude [-121.05]: ") or -121.05)
    wingman_alt = float(input("  Wingman altitude [1200]: ") or 1200)

    print("\n  Fire statuses (0=unclassified, 1=spotted, 2=marked, 3=initial done, 4=complete):")
    statuses = []
    for i in range(8):
        status = float(input(f"    Fire {i} status [0.0]: ") or 0.0)
        statuses.append(status)

    human_plan = float(input("\n  Human current plan (-1 for none) [-1]: ") or -1)
    wingman_goal = int(input("  Wingman current goal (-1 for none) [-1]: ") or -1)

    run_scenario(
        scenario_num=99,
        scenario_name="Custom Interactive Scenario",
        human_pos=(human_lat, human_long, human_alt),
        wingman_pos=(wingman_lat, wingman_long, wingman_alt),
        statuses=statuses,
        human_current_plan=human_plan,
        wingman_current_goal=wingman_goal,
    )


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Test plan_team_strategy function")
    parser.add_argument("-i", "--interactive", action="store_true",
                        help="Run in interactive mode")
    parser.add_argument("-s", "--scenario", type=int, default=None,
                        help="Run specific scenario number (1-8)")

    args = parser.parse_args()

    print("\n" + "=" * 60)
    print("  PLAN_TEAM_STRATEGY TEST SCRIPT")
    print("  Testing FireWatchWingman team planning heuristics")
    print("  Output: Vector graphics images (matplotlib)")
    print("=" * 60)

    if args.interactive:
        interactive_mode()
    elif args.scenario:
        if 1 <= args.scenario <= len(SCENARIOS):
            scenario = SCENARIOS[args.scenario - 1]
            run_scenario(
                scenario_num=args.scenario,
                scenario_name=scenario["name"],
                human_pos=scenario["human_pos"],
                wingman_pos=scenario["wingman_pos"],
                statuses=scenario["statuses"],
                classifications=scenario.get("classifications"),
                human_current_plan=scenario.get("human_current_plan", -1.0),
                wingman_current_goal=scenario.get("wingman_current_goal", -1),
                whoflew_initial=scenario.get("whoflew_initial"),
            )
        else:
            print(f"  Invalid scenario number. Choose 1-{len(SCENARIOS)}.")
    else:
        run_all_scenarios()

    print("\n  Test complete.\n")

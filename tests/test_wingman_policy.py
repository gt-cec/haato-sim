"""
Test script for FireWatchWingman policy_combined and select_optimal_task methods.

This script tests the wingman's decision-making across different scenarios including:
- All three fire layouts (1, 2, 3)
- Different fire statuses (0.0-4.0)
- Different human_indicated_plan values
- Various human and wingman positions within the AOR
"""

import numpy as np
import matplotlib.pyplot as plt
import os
from pathlib import Path
from missions.fire.wingman.agent import FireWatchWingman
from utility.base_classes import Target
from utility.config_loader import get_config

__test__ = False

# AOR bounds for reference
AOR_CENTER = (47.836467, -121.108091)
AOR_SIZE = 17  # NM
AOR_LAT_MIN = AOR_CENTER[0] - AOR_SIZE/60/2
AOR_LAT_MAX = AOR_CENTER[0] + AOR_SIZE/60/2
AOR_LONG_MIN = AOR_CENTER[1] - AOR_SIZE/60/2
AOR_LONG_MAX = AOR_CENTER[1] + AOR_SIZE/60/2


def create_mock_xpc():
    """Returns minimal mock XPC object"""
    class MockXPC:
        pass
    return MockXPC()


def create_mock_mission_manager(fire_layout):
    """
    Loads fire data from JSON and creates mock MissionManager with targets.

    Args:
        fire_layout: 1, 2, or 3

    Returns:
        Mock MissionManager object with targets list and target_id_to_index dict
    """
    # Load mission data from config
    data = get_config()['missions'][fire_layout]

    # Create mock MM
    class MockMM:
        def __init__(self):
            self.targets = []
            self.target_id_to_index = {}
            self.required_alt_fire_agl = data['required_altitude_fire_agl_ft']
            self.required_cruise_altitude_ft = data['required_altitude_ft_msl']
            self.wind_direction = data['wind_direction']
            self.mag_declination = data['magnetic_declination']
            self.required_drop_route_length = data['required_drop_route_length']

    mm = MockMM()

    # Create Target objects from current config schema
    for i, dp in enumerate(data.get('fires', data.get('data_points', []))):
        target = Target(
            type=dp['type'],
            lat=dp['latitude'],
            long=dp['longitude'],
            alt=dp['altitude'],
            id=dp.get('id', i)
        )
        mm.targets.append(target)
        mm.target_id_to_index[i] = i

    return mm, data


def build_observation(mission_timer, human_pos, fire_data, human_indicated_plan):
    """
    Constructs observation numpy array.

    Args:
        mission_timer: float (seconds)
        human_pos: (lat, long, alt, hdg, spd)
        fire_data: List of dicts with keys: lat, long, alt, status, whoflew_initial
        human_indicated_plan: -1.0 or fire_id (0-7)

    Returns:
        numpy array of size 16 + 14*num_fires
    """
    num_fires = len(fire_data)
    obs_size = 16 + 14 * num_fires  # TARGET_BLOCK_SIZE=14
    obs = np.zeros(obs_size)

    # Base data [0-5]
    obs[0] = mission_timer
    obs[1:6] = human_pos

    # Planning DREFs [6-13]
    obs[6] = 12.0  # command_from_human (12.0 = no command)
    obs[7] = 0.0   # agent_task_accepted
    obs[8] = 0.0   # human_recently_finished_task
    obs[9] = 0.0   # wingman_recently_finished_task
    obs[10] = 0.0  # human_requests_plan_suggestion
    obs[11] = human_indicated_plan
    obs[12] = 0.0  # wingman_status
    obs[13] = 0.0  # plan_for_wingman

    # num_targets [14]
    obs[14] = num_fires

    # Reserved [15]
    obs[15] = 0.0

    # Target data blocks [16+] — TARGET_BLOCK_SIZE=14
    # Offsets: 0-2=true lat/lon/alt, 3-5=reported lat/lon/alt, 6=is_known,
    #          7=spotted, 8=handled, 9=being_handled, 10=human_range, 11=wingman_range,
    #          12=target_status, 13=target_whoflew
    for i, fire in enumerate(fire_data):
        base_idx = 16 + i * 14
        obs[base_idx + 0] = fire['lat']
        obs[base_idx + 1] = fire['long']
        obs[base_idx + 2] = fire['alt']
        obs[base_idx + 3] = fire['lat']   # reported_lat (= true by default in tests)
        obs[base_idx + 4] = fire['long']  # reported_long
        obs[base_idx + 5] = fire['alt']   # reported_alt
        obs[base_idx + 6] = 1.0           # is_known_to_cockpit
        obs[base_idx + 7] = 1.0 if fire['status'] > 0 else 0.0  # spotted
        obs[base_idx + 8] = 1.0 if fire['status'] >= 4.0 else 0.0  # handled
        obs[base_idx + 9] = 0.0   # being_handled
        obs[base_idx + 10] = 0.0  # human_in_range_time
        obs[base_idx + 11] = 0.0  # wingman_in_range_time
        obs[base_idx + 12] = fire['status']  # target_status
        obs[base_idx + 13] = fire.get('whoflew_initial', -1.0)  # target_whoflew_initial

    return obs


def plot_scenario(fire_data, human_pos, wingman_pos, action_dict, human_indicated_plan, title, save_path):
    """
    Visualizes test scenario with matplotlib.

    Args:
        fire_data: List of dicts with fire positions and statuses
        human_pos: (lat, long, alt, hdg, spd)
        wingman_pos: (lat, long, alt, hdg, spd)
        action_dict: Action dictionary from policy_combined
        title: Test case title
        save_path: Path to save the plot
    """
    fig, ax = plt.subplots(figsize=(12, 10))

    # Define color scheme for fire statuses
    status_colors = {
        0.0: 'gray',
        1.0: 'yellow',
        2.0: 'orange',
        3.0: 'red',
        4.0: 'green'
    }

    status_labels = {
        0.0: 'Unclassified',
        1.0: 'Classified',
        2.0: 'Position Marked',
        3.0: 'Initial Route Done',
        4.0: 'Complete'
    }

    # Plot fires
    for i, fire in enumerate(fire_data):
        status = fire['status']
        color = status_colors.get(status, 'black')
        ax.scatter(fire['long'], fire['lat'], c=color, s=200, marker='*',
                  edgecolors='black', linewidths=1.5, zorder=3)
        ax.text(fire['long'], fire['lat'] + 0.01, f"F{i}",
               ha='center', va='bottom', fontsize=9, fontweight='bold')

    # Plot human position
    ax.scatter(human_pos[1], human_pos[0], c='blue', s=300, marker='o',
              edgecolors='black', linewidths=2, label='Human', zorder=4)

    # Plot wingman position
    ax.scatter(wingman_pos[1], wingman_pos[0], c='limegreen', s=300, marker='s',
              edgecolors='black', linewidths=2, label='Wingman', zorder=4)

    # Add AOR boundary
    aor_rect = plt.Rectangle((AOR_LONG_MIN, AOR_LAT_MIN),
                             AOR_LONG_MAX - AOR_LONG_MIN,
                             AOR_LAT_MAX - AOR_LAT_MIN,
                             fill=False, edgecolor='purple', linewidth=2,
                             linestyle='--', label='AOR Boundary')
    ax.add_patch(aor_rect)

    # Create legend for fire statuses
    from matplotlib.patches import Patch
    legend_elements = [
        Patch(facecolor='gray', edgecolor='black', label='Status 0.0: Unclassified'),
        Patch(facecolor='yellow', edgecolor='black', label='Status 1.0: Classified'),
        Patch(facecolor='orange', edgecolor='black', label='Status 2.0: Position Marked'),
        Patch(facecolor='red', edgecolor='black', label='Status 3.0: Initial Route Done'),
        Patch(facecolor='green', edgecolor='black', label='Status 4.0: Complete'),
    ]

    # Add human and wingman to legend
    legend_elements.extend([
        plt.Line2D([0], [0], marker='o', color='w', markerfacecolor='blue',
                  markersize=10, label='Human', markeredgecolor='black', markeredgewidth=1.5),
        plt.Line2D([0], [0], marker='s', color='w', markerfacecolor='limegreen',
                  markersize=10, label='Wingman', markeredgecolor='black', markeredgewidth=1.5),
    ])

    ax.legend(handles=legend_elements, loc='upper left', fontsize=9)

    # Add action message to plot
    message = action_dict.get('message', 'No message')
    goal = action_dict.get('goal', (0, 0, 0))

    # Check if message starts with "Holding" to make it red
    text_color = 'red' if message.startswith('Holding') else 'black'

    action_text = f"Action: {message}\nGoal (HDG, SPD, ALT): ({goal[0]:.1f}°, {goal[1]:.1f} kts, {goal[2]:.0f} ft)"

    ax.text(0.02, 0.02, action_text, transform=ax.transAxes,
           fontsize=11, verticalalignment='bottom',
           bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8),
           color=text_color, fontweight='bold')

    action_text = f"Human plan: {human_indicated_plan})"
    ax.text(0.02, 0.07, action_text, transform=ax.transAxes,
            fontsize=11, verticalalignment='bottom',
            bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8),
            color=text_color, fontweight='bold')

    # Set labels and title
    ax.set_xlabel('Longitude', fontsize=12)
    ax.set_ylabel('Latitude', fontsize=12)
    ax.set_title(title, fontsize=14, fontweight='bold')
    ax.grid(True, alpha=0.3)

    # Save plot
    plt.tight_layout()
    plt.savefig(save_path, dpi=150, bbox_inches='tight')
    plt.close()

    print(f"  Plot saved to: {save_path}")


def test_case(test_num, name, fire_layout, fire_statuses, human_pos, wingman_pos,
              human_indicated_plan, whoflew_initial=None):
    """
    Run a single test case.

    Args:
        test_num: Test number for naming
        name: Test case description
        fire_layout: 1, 2, or 3
        fire_statuses: List of 8 status values (0.0-4.0)
        human_pos: (lat, long, alt, hdg, spd)
        wingman_pos: (lat, long, alt, hdg, spd)
        human_indicated_plan: -1.0 or fire_id (0-7)
        whoflew_initial: Optional list of 8 values indicating who flew initial routes

    Returns:
        action_dict from policy_combined()
    """
    for human_indicated_plan in [-1.0, 0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]:
        print(f"\n{'='*80}")
        print(f"TEST {test_num}: {name}")
        print(f"{'='*80}")
        print(f"Fire Layout: Mission {fire_layout}")
        print(f"Fire Statuses: {fire_statuses}")
        print(f"Human Position: lat={human_pos[0]:.4f}, long={human_pos[1]:.4f}, alt={human_pos[2]:.0f}")
        print(f"Wingman Position: lat={wingman_pos[0]:.4f}, long={wingman_pos[1]:.4f}, alt={wingman_pos[2]:.0f}")
        print(f"Human Indicated Plan: {human_indicated_plan}")

        # Create mock objects
        xpc = create_mock_xpc()
        mm, mission_data = create_mock_mission_manager(fire_layout)

        # Build fire data for observation
        fire_data = []
        for i, dp in enumerate(mission_data['dataPoints']):
            fire_info = {
                'lat': dp['latitude'],
                'long': dp['longitude'],
                'alt': dp['altitude'],
                'status': fire_statuses[i],
                'whoflew_initial': whoflew_initial[i] if whoflew_initial else -1.0
            }
            fire_data.append(fire_info)

        # Create observation
        mission_timer = 300.0  # 5 minutes into mission
        observation = build_observation(mission_timer, human_pos, fire_data, human_indicated_plan)

        # Initialize wingman
        wingman = FireWatchWingman(
            xpc=xpc,
            start_lla=wingman_pos[:3],
            start_hdg=wingman_pos[3],
            start_spd=wingman_pos[4],
            mm=mm,
            fire_layout=fire_layout,
            initiative_level=1.0
        )

        # Set wingman's current position (in case it's different from start)
        wingman.lat = wingman_pos[0]
        wingman.long = wingman_pos[1]
        wingman.alt = wingman_pos[2]
        wingman.hdg = wingman_pos[3]
        wingman.spd = wingman_pos[4]

        # Call policy_combined
        print("\nCalling policy_combined()...")
        action = wingman.policy_combined(observation)

        # Print results
        print("\n--- RESULT ---")
        print(f"Action Type: {action['type']}")
        print(f"Action Goal: {action['goal']}")
        print(f"Action Message: {action['message']}")

        if action['message'].startswith('Holding') or action['message'].startswith('Awaiting'):
            # Create visualization
            save_path = f"test_results/test_{test_num:02d}_{name.replace(' ', '_').replace(':', '').replace('(', '').replace(')', '')[:40]}.png"
            plot_scenario(fire_data, human_pos, wingman_pos, action, human_indicated_plan,
                         f"Test {test_num}: {name}", save_path)

    return action


def main():
    """Run all test cases"""

    # Create test_results directory if it doesn't exist
    os.makedirs('test_results', exist_ok=True)

    print("="*80)
    print("FIREWATCH WINGMAN POLICY TEST SUITE")
    print("="*80)
    print("Testing policy_combined() and _select_optimal_task() methods")
    print(f"AOR Center: {AOR_CENTER}")
    print(f"AOR Size: {AOR_SIZE} NM")
    print()

    # Default positions
    aor_center_pos = (AOR_CENTER[0], AOR_CENTER[1], 7000, 90, 180)

    # Test 1: All fires unclassified
    test_case(
        test_num=1,
        name="All fires unclassified",
        fire_layout=1,
        fire_statuses=[0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        human_pos=aor_center_pos,
        wingman_pos=(47.8364665, -121.318566, 7000, 90, 180),  # Near fire 2
        human_indicated_plan=-1.0
    )

    # Test 2: Mixed statuses
    test_case(
        test_num=2,
        name="Mixed fire statuses",
        fire_layout=1,
        fire_statuses=[0.0, 1.0, 2.0, 3.0, 0.0, 1.0, 2.0, 4.0],
        human_pos=(47.76563325, -121.318566, 7000, 90, 180),  # Near fire 1
        wingman_pos=(47.76563325, -121.318566 + 0.02, 7000, 90, 180),  # Near fire 1
        human_indicated_plan=-1.0
    )

    # Test 3: Human conflict avoidance
    test_case(
        test_num=3,
        name="Human conflict avoidance (fire 0)",
        fire_layout=1,
        fire_statuses=[0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        human_pos=(47.9748, -121.258566, 7000, 90, 180),  # Near fire 0
        wingman_pos=(47.9748, -121.258566 + 0.01, 7000, 90, 180),  # Also near fire 0
        human_indicated_plan=0.0  # Human working on fire 0
    )

    # Test 4: All complete (holding pattern)
    test_case(
        test_num=4,
        name="All fires complete - Holding",
        fire_layout=1,
        fire_statuses=[4.0, 4.0, 4.0, 4.0, 4.0, 4.0, 4.0, 4.0],
        human_pos=aor_center_pos,
        wingman_pos=(AOR_CENTER[0] + 0.05, AOR_CENTER[1], 7000, 90, 180),
        human_indicated_plan=-1.0
    )

    # Test 5: Refined route opportunity
    test_case(
        test_num=5,
        name="Refined route opportunity",
        fire_layout=2,
        fire_statuses=[3.0, 3.0, 3.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        human_pos=(47.75, -121.25, 7000, 90, 180),
        wingman_pos=(47.77272488, -121.22460522, 7000, 90, 180),  # Near fire 1
        human_indicated_plan=-1.0,
        whoflew_initial=[1.0, 1.0, 1.0, -1.0, -1.0, -1.0, -1.0, -1.0]  # Human flew initial
    )

    # Test 6: Distance-based tie-breaking
    test_case(
        test_num=6,
        name="Distance-based selection",
        fire_layout=3,
        fire_statuses=[1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
        human_pos=(47.70, -121.30, 7000, 90, 180),
        wingman_pos=aor_center_pos,  # Center of AOR
        human_indicated_plan=-1.0
    )

    # Test 7: Layout 1 with mixed statuses
    test_case(
        test_num=7,
        name="Layout 1 - Mixed workflow",
        fire_layout=1,
        fire_statuses=[0.0, 1.0, 2.0, 0.0, 1.0, 2.0, 0.0, 1.0],
        human_pos=(47.75, -121.25, 7000, 90, 180),
        wingman_pos=aor_center_pos,
        human_indicated_plan=-1.0
    )

    # Test 8: Layout 2 with mixed statuses
    test_case(
        test_num=8,
        name="Layout 2 - Mixed workflow",
        fire_layout=2,
        fire_statuses=[0.0, 1.0, 2.0, 0.0, 1.0, 2.0, 0.0, 1.0],
        human_pos=(47.75, -121.15, 7000, 90, 180),
        wingman_pos=aor_center_pos,
        human_indicated_plan=-1.0
    )

    # Test 9: Layout 3 with mixed statuses
    test_case(
        test_num=9,
        name="Layout 3 - Mixed workflow",
        fire_layout=3,
        fire_statuses=[0.0, 1.0, 2.0, 0.0, 1.0, 2.0, 0.0, 1.0],
        human_pos=(47.80, -121.20, 7000, 90, 180),
        wingman_pos=aor_center_pos,
        human_indicated_plan=-1.0
    )

    # Test 10: Wingman far from all fires
    test_case(
        test_num=10,
        name="Wingman at AOR edge",
        fire_layout=1,
        fire_statuses=[0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        human_pos=(47.75, -121.20, 7000, 90, 180),
        wingman_pos=(AOR_LAT_MIN + 0.01, AOR_LONG_MIN + 0.01, 7000, 90, 180),  # Edge of AOR
        human_indicated_plan=-1.0
    )

    # Test 11: Multiple fires needing work, human conflict
    test_case(
        test_num=11,
        name="Multiple tasks - Human conflict",
        fire_layout=2,
        fire_statuses=[0.0, 0.0, 0.0, 1.0, 1.0, 2.0, 2.0, 3.0],
        human_pos=(47.87597071, -121.3080377, 7000, 90, 180),  # Near fire 0
        wingman_pos=(47.87597071, -121.3080377 + 0.02, 7000, 90, 180),  # Also near fire 0
        human_indicated_plan=0.0  # Avoid fire 0
    )

    # Test 12: Step priority verification
    test_case(
        test_num=12,
        name="Step priority verification",
        fire_layout=1,
        fire_statuses=[3.0, 2.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        human_pos=(47.70, -121.35, 7000, 90, 180),
        wingman_pos=aor_center_pos,  # Equidistant
        human_indicated_plan=-1.0,
        whoflew_initial=[1.0, -1.0, -1.0, -1.0, -1.0, -1.0, -1.0, -1.0]
    )

    # Test 13: Human indicates fire 3, wingman near fire 3
    test_case(
        test_num=13,
        name="Human indicates fire 3 - Cooperation",
        fire_layout=1,
        fire_statuses=[1.0, 1.0, 1.0, 0.0, 1.0, 1.0, 1.0, 1.0],
        human_pos=(47.80, -121.15, 7000, 90, 180),
        wingman_pos=(47.87239915, -121.18267485, 7000, 90, 180),  # Near fire 3
        human_indicated_plan=3.0
    )

    # Test 14: All fires at status 2.0 (position marked)
    test_case(
        test_num=14,
        name="All fires at status 2.0",
        fire_layout=2,
        fire_statuses=[2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0],
        human_pos=(47.82, -121.10, 7000, 90, 180),
        wingman_pos=(47.75, -121.25, 7000, 90, 180),
        human_indicated_plan=-1.0
    )

    # Test 15: Single fire unclassified, rest complete
    test_case(
        test_num=15,
        name="One fire remaining - Layout 3",
        fire_layout=3,
        fire_statuses=[4.0, 4.0, 4.0, 0.0, 4.0, 4.0, 4.0, 4.0],
        human_pos=(47.78, -121.12, 7000, 90, 180),
        wingman_pos=(47.85, -121.05, 7000, 90, 180),
        human_indicated_plan=-1.0
    )

    # Test 16: Human indicates fire 7, all fires status 1.0
    test_case(
        test_num=16,
        name="Human indicates fire 7 - Avoid",
        fire_layout=1,
        fire_statuses=[1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
        human_pos=(47.79, -121.25, 7000, 90, 180),
        wingman_pos=(47.82, -121.18, 7000, 90, 180),
        human_indicated_plan=7.0
    )

    # Test 17: Fires with varying intermediate statuses
    test_case(
        test_num=17,
        name="Varying intermediate statuses",
        fire_layout=2,
        fire_statuses=[1.5, 2.5, 3.5, 0.5, 1.0, 2.0, 3.0, 4.0],
        human_pos=(47.87, -121.30, 7000, 90, 180),
        wingman_pos=(47.80, -121.15, 7000, 90, 180),
        human_indicated_plan=-1.0
    )

    # Test 18: Wingman directly over fire 5
    test_case(
        test_num=18,
        name="Wingman directly over fire 5",
        fire_layout=1,
        fire_statuses=[4.0, 4.0, 4.0, 4.0, 4.0, 0.0, 4.0, 4.0],
        human_pos=(47.72, -121.30, 7000, 90, 180),
        wingman_pos=(47.90665835, -121.07293165, 7000, 90, 180),  # Fire 5 location
        human_indicated_plan=-1.0
    )

    # Test 19: Human indicates fire 2, wingman at opposite end
    test_case(
        test_num=19,
        name="Human indicates fire 2 - Distant wingman",
        fire_layout=3,
        fire_statuses=[0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        human_pos=(47.95, -121.25, 7000, 90, 180),
        wingman_pos=(47.70, -121.00, 7000, 90, 180),
        human_indicated_plan=2.0
    )

    # Test 20: Progressive statuses 0.0 to 4.0 in sequence
    test_case(
        test_num=20,
        name="Progressive statuses 0-4 sequence",
        fire_layout=1,
        fire_statuses=[0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0],
        human_pos=(47.83, -121.11, 7000, 90, 180),
        wingman_pos=(47.83, -121.11 + 0.05, 7000, 90, 180),
        human_indicated_plan=-1.0
    )

    # Test 21: All fires status 3.0 - Need refined routes
    test_case(
        test_num=21,
        name="All fires status 3.0 - Refined routes",
        fire_layout=2,
        fire_statuses=[3.0, 3.0, 3.0, 3.0, 3.0, 3.0, 3.0, 3.0],
        human_pos=(47.75, -121.20, 7000, 90, 180),
        wingman_pos=(47.82, -121.14, 7000, 90, 180),
        human_indicated_plan=-1.0,
        whoflew_initial=[0.0, 0.0, 1.0, 1.0, 0.0, 0.0, 1.0, 1.0]
    )

    # Test 22: Human indicates fire 4, wingman near fire 4
    test_case(
        test_num=22,
        name="Human indicates fire 4 - Same location",
        fire_layout=1,
        fire_statuses=[2.0, 2.0, 2.0, 2.0, 0.0, 2.0, 2.0, 2.0],
        human_pos=(47.87239915, -121.03718845, 7000, 90, 180),  # Near fire 4
        wingman_pos=(47.87239915, -121.03718845 + 0.01, 7000, 90, 180),
        human_indicated_plan=4.0
    )

    # Test 23: Fires alternating complete and unclassified
    test_case(
        test_num=23,
        name="Alternating complete and unclassified",
        fire_layout=3,
        fire_statuses=[4.0, 0.0, 4.0, 0.0, 4.0, 0.0, 4.0, 0.0],
        human_pos=(47.88, -121.08, 7000, 90, 180),
        wingman_pos=(47.77, -121.16, 7000, 90, 180),
        human_indicated_plan=-1.0
    )

    # Test 24: Human indicates fire 1, fires mostly complete
    test_case(
        test_num=24,
        name="Human indicates fire 1 - Mostly complete",
        fire_layout=2,
        fire_statuses=[4.0, 1.0, 4.0, 4.0, 4.0, 4.0, 4.0, 4.0],
        human_pos=(47.77, -121.22, 7000, 90, 180),
        wingman_pos=(47.85, -121.12, 7000, 90, 180),
        human_indicated_plan=1.0
    )

    # Test 25: Two fires at status 0.0, rest at 3.0
    test_case(
        test_num=25,
        name="Two unclassified among completed routes",
        fire_layout=1,
        fire_statuses=[3.0, 3.0, 0.0, 3.0, 3.0, 3.0, 0.0, 3.0],
        human_pos=(47.80, -121.30, 7000, 90, 180),
        wingman_pos=(47.80, -121.10, 7000, 90, 180),
        human_indicated_plan=-1.0,
        whoflew_initial=[1.0, 1.0, -1.0, 1.0, 1.0, 1.0, -1.0, 1.0]
    )

    # Test 26: Human indicates fire 5, wingman far from fire 5
    test_case(
        test_num=26,
        name="Human indicates fire 5 - Far wingman",
        fire_layout=3,
        fire_statuses=[1.0, 1.0, 1.0, 1.0, 1.0, 0.0, 1.0, 1.0],
        human_pos=(47.90, -121.07, 7000, 90, 180),
        wingman_pos=(47.72, -121.30, 7000, 90, 180),
        human_indicated_plan=5.0
    )

    # Test 27: Low altitude wingman position
    test_case(
        test_num=27,
        name="Low altitude wingman",
        fire_layout=1,
        fire_statuses=[0.0, 1.0, 2.0, 3.0, 0.0, 1.0, 2.0, 3.0],
        human_pos=(47.84, -121.11, 7000, 90, 180),
        wingman_pos=(47.84, -121.11 + 0.03, 2000, 90, 120),  # Low and slow
        human_indicated_plan=-1.0
    )

    # Test 28: High altitude wingman position
    test_case(
        test_num=28,
        name="High altitude wingman",
        fire_layout=2,
        fire_statuses=[1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
        human_pos=(47.82, -121.18, 7000, 90, 180),
        wingman_pos=(47.82, -121.18 + 0.05, 10000, 90, 200),  # High and fast
        human_indicated_plan=-1.0
    )

    # Test 29: Fires in pairs at different statuses
    test_case(
        test_num=29,
        name="Paired fire statuses",
        fire_layout=3,
        fire_statuses=[0.0, 0.0, 1.0, 1.0, 2.0, 2.0, 3.0, 3.0],
        human_pos=(47.78, -121.14, 7000, 90, 180),
        wingman_pos=(47.88, -121.08, 7000, 90, 180),
        human_indicated_plan=-1.0
    )

    # Test 30: Human indicates fire 6, equal distance scenario
    test_case(
        test_num=30,
        name="Human indicates fire 6 - Equidistant",
        fire_layout=1,
        fire_statuses=[1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 0.0, 1.0],
        human_pos=(47.93, -121.15, 7000, 90, 180),
        wingman_pos=aor_center_pos,
        human_indicated_plan=6.0
    )

    # Test 31: Three fires incomplete, rest complete
    test_case(
        test_num=31,
        name="Three incomplete fires - Layout 2",
        fire_layout=2,
        fire_statuses=[4.0, 2.0, 4.0, 4.0, 1.0, 4.0, 0.0, 4.0],
        human_pos=(47.80, -121.25, 7000, 90, 180),
        wingman_pos=(47.85, -121.15, 7000, 90, 180),
        human_indicated_plan=-1.0
    )

    # Test 32: Human indicates fire 0, wingman near fire 7
    test_case(
        test_num=32,
        name="Human indicates fire 0 - Wingman at fire 7",
        fire_layout=3,
        fire_statuses=[0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        human_pos=(47.97, -121.26, 7000, 90, 180),
        wingman_pos=(47.72, -121.05, 7000, 90, 180),
        human_indicated_plan=0.0
    )

    # Test 33: Gradient statuses with whoflew_initial mixed
    test_case(
        test_num=33,
        name="Gradient statuses - Mixed whoflew",
        fire_layout=1,
        fire_statuses=[3.0, 3.0, 3.0, 3.0, 2.0, 2.0, 1.0, 1.0],
        human_pos=(47.76, -121.26, 7000, 90, 180),
        wingman_pos=(47.90, -121.07, 7000, 90, 180),
        human_indicated_plan=-1.0,
        whoflew_initial=[1.0, 0.0, 1.0, 0.0, -1.0, -1.0, -1.0, -1.0]
    )

    # Test 34: All fires at status 3.0
    test_case(
        test_num=34,
        name="All fires at status 3",
        fire_layout=2,
        fire_statuses=[3.0, 3.0, 3.0, 3.0, 3.0, 3.0, 3.0, 3.0],
        human_pos=(47.81, -121.19, 7000, 90, 180),
        wingman_pos=(47.81, -121.09, 7000, 90, 180),
        human_indicated_plan=-1.0
    )


    # Test 36: Single fire at each status level
    test_case(
        test_num=36,
        name="One fire per status level",
        fire_layout=1,
        fire_statuses=[0.0, 1.0, 2.0, 3.0, 4.0, 1.0, 2.0, 3.0],
        human_pos=(47.82, -121.22, 7000, 90, 180),
        wingman_pos=(47.82, -121.12, 7000, 90, 180),
        human_indicated_plan=-1.0,
        whoflew_initial=[-1.0, -1.0, -1.0, 0.0, 1.0, -1.0, -1.0, 1.0]
    )

    # Test 37: Wingman at northeast corner of AOR
    test_case(
        test_num=37,
        name="Wingman at NE corner - Layout 2",
        fire_layout=2,
        fire_statuses=[0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        human_pos=(47.80, -121.18, 7000, 90, 180),
        wingman_pos=(AOR_LAT_MAX - 0.01, AOR_LONG_MAX - 0.01, 7000, 90, 180),
        human_indicated_plan=-1.0
    )

    # Test 38: Wingman at southwest corner of AOR
    test_case(
        test_num=38,
        name="Wingman at SW corner - Layout 3",
        fire_layout=3,
        fire_statuses=[1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
        human_pos=(47.85, -121.10, 7000, 90, 180),
        wingman_pos=(AOR_LAT_MIN + 0.01, AOR_LONG_MIN + 0.01, 7000, 90, 180),
        human_indicated_plan=-1.0
    )


    # Test 40: Half fires complete, half unclassified
    test_case(
        test_num=40,
        name="Half complete, half unclassified",
        fire_layout=2,
        fire_statuses=[4.0, 4.0, 4.0, 4.0, 0.0, 0.0, 0.0, 0.0],
        human_pos=(47.87, -121.31, 7000, 90, 180),
        wingman_pos=(47.75, -121.14, 7000, 90, 180),
        human_indicated_plan=-1.0
    )

    # Test 41: Human indicates fire 7 at north edge of AOR
    test_case(
        test_num=41,
        name="Human indicates fire 7 - North edge",
        fire_layout=3,
        fire_statuses=[2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 0.0],
        human_pos=(AOR_LAT_MAX - 0.02, AOR_CENTER[1], 7000, 90, 180),
        wingman_pos=(AOR_LAT_MIN + 0.02, AOR_CENTER[1], 7000, 90, 180),
        human_indicated_plan=7.0
    )

    # Test 42: Wingman and human close together, mixed statuses
    test_case(
        test_num=42,
        name="Wingman and human close - Mixed status",
        fire_layout=1,
        fire_statuses=[1.0, 0.0, 2.0, 1.0, 3.0, 2.0, 1.0, 0.0],
        human_pos=(47.83, -121.18, 7000, 90, 180),
        wingman_pos=(47.83, -121.18 + 0.005, 7000, 90, 180),  # Very close
        human_indicated_plan=-1.0
    )

    # Test 43: All fires need refined routes, wingman flew initial
    test_case(
        test_num=43,
        name="All need refined - Wingman flew initial",
        fire_layout=2,
        fire_statuses=[3.0, 3.0, 3.0, 3.0, 3.0, 3.0, 3.0, 3.0],
        human_pos=(47.78, -121.23, 7000, 90, 180),
        wingman_pos=(47.82, -121.13, 7000, 90, 180),
        human_indicated_plan=-1.0,
        whoflew_initial=[0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]  # All wingman
    )

    test_case(
        test_num=44,
        name="1 fire left,no human plan",
        fire_layout=2,
        fire_statuses=[4.0, 1.0, 4.0, 4.0, 4.0, 4.0, 4.0, 4.0],
        human_pos=(47.77, -121.22, 7000, 90, 180),
        wingman_pos=(47.85, -121.12, 7000, 90, 180),
        human_indicated_plan=0.0
    )

    # Test 45: All fires at status 3.0
    test_case(
        test_num=45,
        name="All fires at status 3",
        fire_layout=2,
        fire_statuses=[3.0, 3.0, 3.0, 3.0, 3.0, 3.0, 3.0, 3.0],
        human_pos=(47.81, -121.19, 7000, 90, 180),
        wingman_pos=(47.81, -121.09, 7000, 90, 180),
        human_indicated_plan=-1.0
    )

    # Test 46: All fires at status 4.0
    test_case(
        test_num=46,
        name="All fires at status 4",
        fire_layout=2,
        fire_statuses=[4.0, 4.0, 4.0, 4.0, 4.0, 4.0, 4.0, 4.0],
        human_pos=(47.81, -121.19, 7000, 90, 180),
        wingman_pos=(47.81, -121.09, 7000, 90, 180),
        human_indicated_plan=-1.0
    )

    print("\n" + "="*80)
    print("ALL TESTS COMPLETE!")
    print("="*80)
    print(f"Results saved to test_results/ directory")
    print("Check the plots for visual verification of each test case.")


if __name__ == "__main__":
    main()

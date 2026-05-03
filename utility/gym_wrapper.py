"""Gymnasium wrapper for the FirewatchMM mission environment"""

import gymnasium as gym
from gymnasium import spaces
import numpy as np
from typing import Optional, Tuple, Dict, Any

from _not_used.firewatch_mission import FireWatchMM


class FirewatchGymEnv(gym.Env):
    """
    Gymnasium environment wrapper for the Firewatch mission.

    This wrapper converts the FirewatchMM class into a standard Gymnasium environment,
    allowing it to be used with reinforcement learning frameworks like Stable Baselines3.

    Observation Space:
        - Mission timer (1)
        - Human state: lat, lon, alt, heading, speed (5)
        - Per target: lat, lon, alt, spotted, handled, is_being_handled,
                      human_in_range_time, wingman_in_range_time (8 * num_targets)
        Total: 6 + 8 * num_targets

    Action Space:
        - Discrete actions representing different wingman behaviors:
            0: Follow human
            1: Fly to target 0
            2: Fly to target 1
            ...
            N: Fly to target N-1
            N+1: Run autonomous policy (greedy)
            N+2: Run autonomous policy (task priority A)
            N+3: Run autonomous policy (task priority B)
    """

    metadata = {'render_modes': ['human'], 'render_fps': 30}

    def __init__(self,
                 user_id: int = 99,
                 xpc=None,
                 verbose: bool = False,
                 dev_mode: bool = False,
                 num_wingmen: int = 1,
                 mission_number: int = 0,
                 render_mode: Optional[str] = None):
        """
        Initialize the Firewatch Gym environment.

        Args:
            user_id: Participant ID for studies (default 99 for testing)
            xpc: X-Plane Connect instance for communication with X-Plane
            verbose: Enable verbose debug output
            dev_mode: Enable development mode
            num_wingmen: Number of wingmen agents (currently only 1 is supported)
            mission_number: Mission configuration number
            render_mode: Rendering mode ('human' or None)
        """
        super().__init__()

        self.user_id = user_id
        self.xpc = xpc
        self.verbose = verbose
        self.dev_mode = dev_mode
        self.num_wingmen = num_wingmen
        self.mission_number = mission_number
        self.render_mode = render_mode

        # Initialize the mission manager
        self.mm = None  # Will be created in reset()
        self.num_targets = None  # Will be set after first initialization

        # Create a temporary instance to get num_targets
        temp_mm = FireWatchMM(user_id, xpc, verbose, dev_mode, num_wingmen, mission_number)
        self.num_targets = temp_mm.num_targets

        # Define action space
        # Actions: 0 = follow human, 1-N = fly to targets, N+1 = greedy, N+2 = priority A, N+3 = priority B
        self.num_actions = 1 + self.num_targets + 3  # follow + targets + 3 policies
        self.action_space = spaces.Discrete(self.num_actions)

        # Define observation space
        # 1 (timer) + 5 (human state) + 8*num_targets (target states)
        obs_size = 6 + 8 * self.num_targets
        self.observation_space = spaces.Box(
            low=-np.inf,
            high=np.inf,
            shape=(obs_size,),
            dtype=np.float32
        )

        # Track internal state
        self.current_step = 0
        self.dt = 0.1  # Default time step (will be updated)
        self.last_time = 0.0

    def reset(self, seed: Optional[int] = None, options: Optional[Dict] = None) -> Tuple[np.ndarray, Dict]:
        """
        Reset the environment to initial state.

        Args:
            seed: Random seed for reproducibility
            options: Additional options for reset

        Returns:
            observation: Initial observation
            info: Additional information dictionary
        """
        super().reset(seed=seed)

        # Create new mission manager instance
        self.mm = FireWatchMM(
            self.user_id,
            self.xpc,
            self.verbose,
            self.dev_mode,
            self.num_wingmen,
            self.mission_number
        )

        # Reset the mission
        self.mm.reset()

        # Reset tracking variables
        self.current_step = 0
        self.last_time = 0.0

        # Get initial observation
        observation = self.mm.get_observation(obs_type='wingman')

        # Create info dict
        info = self._get_info()

        return observation.astype(np.float32), info

    def step(self, action: int) -> Tuple[np.ndarray, float, bool, bool, Dict]:
        """
        Execute one step in the environment.

        Args:
            action: Action to take (integer index)

        Returns:
            observation: New observation after action
            reward: Reward for this step
            terminated: Whether the episode has ended (mission complete)
            truncated: Whether the episode was truncated (not used here)
            info: Additional information dictionary
        """
        # Convert discrete action to mission manager command
        command = self._action_to_command(action)

        # Calculate dt (time step)
        current_time = self.mm.mission_timer
        self.dt = max(0.1, current_time - self.last_time) if self.current_step > 0 else 0.1
        self.last_time = current_time

        # Set the human command in the mission manager
        if command is not None:
            self.mm.xpc.sendDREF(self.mm.human_command_dref, float(command))

        # Execute mission step
        mission_elapsed_time = self.mm.mission_timer + self.dt
        done = self.mm.step(self.dt, mission_elapsed_time)

        # Get new observation
        observation = self.mm.get_observation(obs_type='wingman')

        # Calculate reward
        reward = self._calculate_reward()

        # Check termination
        terminated = done
        truncated = False

        # Get info
        info = self._get_info()

        self.current_step += 1

        return observation.astype(np.float32), reward, terminated, truncated, info

    def _action_to_command(self, action: int) -> Optional[float]:
        """
        Convert discrete action to mission manager command.

        Action mapping:
            0: Follow human (command 8.0)
            1 to num_targets: Fly to target (command 0.0 to num_targets-1)
            num_targets+1: Greedy policy (command 9.0)
            num_targets+2: Priority A policy (command 10.0)
            num_targets+3: Priority B policy (command 11.0)
        """
        if action == 0:
            # Follow human
            return 8.0
        elif 1 <= action <= self.num_targets:
            # Fly to target
            target_idx = action - 1
            return float(target_idx)
        elif action == self.num_targets + 1:
            # Greedy policy
            return 9.0
        elif action == self.num_targets + 2:
            # Priority A
            return 10.0
        elif action == self.num_targets + 3:
            # Priority B
            return 11.0
        else:
            # No command (default behavior)
            return 12.0

    def _calculate_reward(self) -> float:
        """
        Calculate reward based on current mission state.

        Reward components:
            - Positive reward for handling fires
            - Penalty for time passing
            - Large positive reward for mission completion
            - Penalty for mission failure
        """
        state = self.mm.get_state()

        # Base reward components
        targets_handled = state['target_summary']['handled']
        targets_spotted = state['target_summary']['spotted']
        total_targets = state['target_summary']['total']
        time_remaining = state['mission_info']['time_remaining']

        # Reward calculation
        reward = 0.0

        # Reward for handling fires (scaled by importance)
        reward += targets_handled * 100.0

        # Small reward for spotting fires
        reward += targets_spotted * 10.0

        # Time penalty (encourage efficiency)
        reward -= 0.1

        # Check mission completion
        if state['mission_info']['complete']:
            completion_reason = state['mission_info']['completion_reason']
            if completion_reason == 'all fires extinguished':
                # Large bonus for successful completion
                reward += 1000.0
                # Bonus for time remaining
                reward += time_remaining * 1.0
            elif completion_reason == 'out of time':
                # Penalty for running out of time
                reward -= 500.0

        return reward

    def _get_info(self) -> Dict[str, Any]:
        """
        Get additional information about the current state.

        Returns:
            Dictionary containing mission state details
        """
        if self.mm is None:
            return {}

        state = self.mm.get_state()

        info = {
            'mission_timer': state['mission_info']['timer'],
            'time_remaining': state['mission_info']['time_remaining'],
            'targets_handled': state['target_summary']['handled'],
            'targets_spotted': state['target_summary']['spotted'],
            'targets_total': state['target_summary']['total'],
            'completion_percentage': state['target_summary']['completion_percentage'],
            'mission_complete': state['mission_info']['complete'],
            'completion_reason': state['mission_info']['completion_reason'],
        }

        return info

    def render(self):
        """
        Render the environment.

        In 'human' mode, this displays mission information.
        """
        if self.render_mode == 'human':
            if self.mm is not None:
                state = self.mm.get_state()
                print(f"\n=== Firewatch Mission Status ===")
                print(f"Time: {state['mission_info']['timer']:.1f}s / {self.mm.max_mission_time:.1f}s")
                print(f"Fires: {state['target_summary']['handled']}/{state['target_summary']['total']} extinguished")
                print(f"Spotted: {state['target_summary']['spotted']}/{state['target_summary']['total']}")
                print(f"Completion: {state['target_summary']['completion_percentage']:.1f}%")
                print(f"Status: {state['mission_info']['completion_reason']}")
                print("=" * 32)

    def close(self):
        """
        Clean up environment resources.
        """
        if self.mm is not None:
            # Perform any necessary cleanup
            self.mm = None


# Convenience function to create the environment
def make_firewatch_env(user_id: int = 99,
                       xpc=None,
                       verbose: bool = False,
                       dev_mode: bool = False,
                       num_wingmen: int = 1,
                       mission_number: int = 0,
                       render_mode: Optional[str] = None) -> FirewatchGymEnv:
    """
    Factory function to create a Firewatch Gym environment.

    Args:
        user_id: Participant ID for studies (default 99 for testing)
        xpc: X-Plane Connect instance
        verbose: Enable verbose output
        dev_mode: Enable development mode
        num_wingmen: Number of wingmen
        mission_number: Mission number
        render_mode: Rendering mode

    Returns:
        FirewatchGymEnv instance
    """
    return FirewatchGymEnv(
        user_id=user_id,
        xpc=xpc,
        verbose=verbose,
        dev_mode=dev_mode,
        num_wingmen=num_wingmen,
        mission_number=mission_number,
        render_mode=render_mode
    )

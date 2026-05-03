"""
Defines utility classes:
    SimMode: Simulates X-Plane's dataref system when X-Plane is not running. Allows us to test, train agents etc without running X-Plane.

    MissionTimer: Keeps track of mission time elapsed
"""
import time
from utility.base_classes import MissionManager
from utility.config_loader import get_config as _get_config


class SimMode:
    def __init__(self, mm: MissionManager):
        self.mm = mm

        self.dref_dict = {
            'sim/time/paused': False,
            "custom/haato/command_from_human": 11.0,  # No command
            'custom/haato/id_request_response': 99.0,
            "custom/haato/human_in_range_of_target": 99.0,

            # Wingman state


            # Human-wingman messages
            "custom/haato/request_response": 0.0,
            "custom/haato/wingman_status": 59.0, # Placeholder
            "custom/haato/help_request": 99.0, # No request
            "custom/haato/can_request": 0.0,
            "custom/haato/taskpriority_spotunknown": 0.0,
            "custom/haato/taskpriority_handlemoderate": 1.0,
            "custom/haato/taskpriority_handlesevere": 2.0,
            "custom/haato/set_wingman_greedy": 0.0,
            "custom/haato/auto_spot": 1.0,

            # Human state
            'sim/flightmodel/position/true_psi': 0.0,
            'sim/flightmodel/position/true_phi': 0.0,
            'sim/flightmodel/position/true_theta': 0.0,
            'sim/flightmodel/position/Prad': 0.0,
            'sim/flightmodel/position/Qrad': 0.0,

            'sim/flightmodel/position/local_vx': 0.0,
            'sim/flightmodel/position/local_vy': 0.0,
            'sim/flightmodel/position/local_vz': 0.0,
            'sim/flightmodel/position/Rrad': 0.0,
            'sim/flightmodel/position/psi': 0.0,
            "sim/joystick/fire_key_is_down": 0.0,
            "custom/haato/trigger_pulled": 0.0,

            'custom/haato/human_indicated_plan':-1.0,
            'custom/haato/human_requests_plan_suggestion':0.0

        }

        for target in self.mm.targets:
            self.dref_dict[f"custom/haato/target_status[{target.id}]"] = 0.0
            self.dref_dict[f"custom/haato/target_classification[{target.id}]"] = 0.0
            self.dref_dict[f"custom/haato/target_whoflew_initial[{target.id}]"] = 0.0

        print(f'Sim instantiated, human response is {self.dref_dict["custom/haato/request_response"]}')


    def sendPOSI(self, ac, lat:float, lon:float, elev:float, phi:float, theta:float, psi_true:float):
        if ac == 0:
            self.dref_dict['sim/flightmodel/position/true_psi'] = psi_true
            self.dref_dict['sim/flightmodel/position/true_phi'] = phi
            self.dref_dict['sim/flightmodel/position/true_theta'] = theta
            self.dref_dict['sim/flightmodel/position/latitude'] = lat
            self.dref_dict['sim/flightmodel/position/longitude'] = lon
            self.dref_dict['sim/flightmodel/position/elevation'] = elev

        elif ac == 1:
            self.dref_dict["custom/haato/wingman_lat"] = lat
            self.dref_dict["custom/haato/wingman_long"] = lon
            self.dref_dict["custom/haato/wingman_alt"] = elev
        else:
            raise ValueError(f'ac {ac} not supported')


    def getPOSI(self):
        lat = self.dref_dict['custom/haato/wingman_lat']
        lon = self.dref_dict['sim/flightmodel/position/latitude']
        ele = self.dref_dict['sim/flightmodel/position/elevation']
        y_agl = self.dref_dict['sim/flightmodel/position/elevation'] # TODO get real AGL
        phi = self.dref_dict['sim/flightmodel/position/true_phi']
        theta = self.dref_dict['sim/flightmodel/position/true_theta']
        psi_true = self.dref_dict['sim/flightmodel/position/true_psi']
        vx = self.dref_dict['sim/flightmodel/position/local_vx']
        vy = self.dref_dict['sim/flightmodel/position/local_vy']
        vz = self.dref_dict['sim/flightmodel/position/local_vz']
        p = self.dref_dict['sim/flightmodel/position/Prad']
        q = self.dref_dict['sim/flightmodel/position/Qrad']
        r = self.dref_dict['sim/flightmodel/position/Rrad']

        return lat, lon, ele, y_agl, phi, theta, psi_true, vx, vy, vz, p, q, r


    def sendDREF(self, dref_key, val):
        #print(f'dref_key {dref_key} val {val}')
        self.dref_dict[dref_key] = val
        if dref_key == "custom/haato/command_from_human":
            print(f'"custom/haato/command_from_human" set to {val}')

    def getDREF(self, dref_key):
        return self.dref_dict[dref_key]


class MissionTimer:
    def __init__(self, target_fps=None):
        if target_fps is None:
            target_fps = _get_config()["system"]["target_fps"]
        self.target_fps = target_fps
        self.target_dt = 1.0 / target_fps
        self.last_time = time.time()
        self.mission_start_time = time.time()

    def get_dt_and_wait(self):
        current_time = time.time()
        actual_dt = current_time - self.last_time

        # Sleep to maintain target framerate if we're running fast
        if actual_dt < self.target_dt:
            time.sleep(self.target_dt - actual_dt)
            current_time = time.time()
            actual_dt = current_time - self.last_time

        self.last_time = current_time
        return actual_dt

    def get_mission_elapsed_time(self):
        return time.time() - self.mission_start_time
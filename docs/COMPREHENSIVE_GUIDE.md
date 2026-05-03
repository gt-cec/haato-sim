# HAATO Comprehensive Development Guide

> Status: archival. This guide predates the current `missions/fire/` refactor and still contains TODO/WRONG notes and obsolete paths. Use `readme.md`, `docs/ARCHITECTURE.md`, and `docs/JOYSTICK_SETUP.md` as the maintained public setup references.

**Version:** 1.0
**Last Updated:** February 2026

---

## Table of Contents

1. [Introduction & Overview](#1-introduction--overview)
2. [Installation & Environment Setup](#2-installation--environment-setup)
3. [Understanding the FireWatch Mission](#3-understanding-the-firewatch-mission)
4. [Running Missions & Collecting Data](#4-running-missions--collecting-data)
5. [Customizing Missions for Your Research](#5-customizing-missions-for-your-research)
6. [Creating Custom AI Agents](#6-creating-custom-ai-agents)
7. [GUI & Visualization Customization](#7-gui--visualization-customization)
8. [Communication & Messaging](#8-communication--messaging)
9. [Performance Optimization](#9-performance-optimization)
10. [Advanced Topics](#10-advanced-topics)
11. [Experimental Methodology](#11-experimental-methodology)
12. [Troubleshooting & Common Issues](#12-troubleshooting--common-issues)
13. [Best Practices & Design Patterns](#13-best-practices--design-patterns)
14. [Appendices](#14-appendices)

---

## 1. Introduction & Overview

### 1.1 What is HAATO?

HAATO (Human-AI Aerial Teaming Operations) is a flexible, extensible, open-source research testbed for studying human-AI collaboration in safety-critical aerial operations. Built on X-Plane 12, HAATO provides researchers with a realistic flight simulation environment where human pilots and AI agents work together to complete complex missions.

**Purpose:**
- Research testbed for human-AI teaming in aviation
- Study collaboration patterns, trust, workload, and coordination
- Develop and evaluate autonomous agent behaviors
- Collect comprehensive telemetry and interaction data

**Key Capabilities:**
- Real-time human-AI interaction in realistic flight simulation
- Comprehensive data logging (telemetry, commands, messages, events)
- Extensible architecture for custom missions and agents
- G1000 cockpit integration for realistic pilot interface
- Configurable AI agent behaviors and autonomy levels

TODO: Explain wht HAATO actually provides. A large part of it is essentially an abstraciton layer for creating entities in xplane needed for
human-AI teaming research

**What Researchers Can Study:**
TODO: Reword this to something like "Examples of research projects possible in HAATO"
- **Initiative Levels:** How different levels of AI autonomy affect team performance
- **Trust Dynamics:** How trust builds and breaks between human and AI teammates
- **Workload Distribution:** Optimal task allocation strategies
- **Communication Patterns:** Effective human-AI coordination protocols
- **Situation Awareness:** How shared understanding emerges in teams
- **Help-Seeking Behavior:** When and how AI agents should request assistance

### 1.2 System Architecture at a Glance

HAATO uses a three-layer distributed architecture:


TOODO: Modify this graphic. too specific to the firefighting mission
```
┌─────────────────────────────────────────────────────────────┐
│                    Human Pilot Interface                    │
│  ┌────────────┬──────────────────┬─────────────────────┐    │
│  │ Joystick/  │  G1000 PFD       │  G1000 MFD          │    │
│  │ Controls   │                  │                     │    │
│  └────────────┴──────────────────┴─────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
                            ↕
┌─────────────────────────────────────────────────────────────┐
│                      X-Plane Core                           │
│  ┌─────────────────┬──────────────────┬─────────────────┐  │
│  │ Standard        │  Custom Datarefs │  Physics        │  │
│  │ Datarefs        │  (custom/haato/*)│  Engine         │  │
│  └─────────────────┴──────────────────┴─────────────────┘  │
│                                                            │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  Lua Scripts (FlyWithLua)                            │  │
│  │  - custom_datarefs.lua: Define custom datarefs       │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                            │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  XPPython3 Plugin                                    │  │
│  │  - PI_gui.py: G1000 overlay & input                  │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                            ↕ UDP (XPlaneConnectX)
┌─────────────────────────────────────────────────────────────┐
│              Python Mission System (External)               │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  MissionManager (FireWatchMM)                        │  │
│  │  - Mission logic and target management               │  │
│  │  - Human-AI coordination                             │  │
│  │  - Progress tracking                                 │  │
│  └──────────────────────────────────────────────────────┘  │
│                            ↕                               │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  Wingman Agent (FireWatchWingman)                    │  │
│  │  - Policy-based decision making                      │  │
│  │  - Navigation and path planning                      │  │
│  │  - Help requests and responses                       │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                            │
│  ┌───────────┬──────────────┬──────────────┬───────────┐   │
│  │ Message   │ DataLogger   │ WoZ GUI      │ Mission   │   │
│  │ Queue     │ (CSV/JSONL)  │ (Experimenter│ Timer     │   │
│  │           │              │  Control)    │ (30 FPS)  │   │
│  └───────────┴──────────────┴──────────────┴───────────┘   │
└────────────────────────────────────────────────────────────┘
```

**Communication Pattern:**
- Python ↔ X-Plane: Bidirectional UDP via XPlaneConnectX
- Data exchange: Dataref pub-sub pattern (read/write shared memory)
- Lua/XPPython3 ↔ X-Plane: Direct dataref access (in-process)

**Mission Loop:**
1. Read human aircraft state from X-Plane
2. Poll human commands from datarefs
3. Process target detection and handling
4. Generate observation for AI agent
5. AI agent decides on action
6. Execute wingman movement
7. Update datarefs for visualization
8. Log telemetry data

### 1.3 Key Concepts

**MissionManager**
- Orchestrates mission logic and scenario execution
- Similar to a Gymnasium environment class
- Manages targets, objectives, and mission progress
- Coordinates communication between human and AI
- Implements abstract methods: `reset()`, `step()`, `get_observation()`, `get_state()`

**Wingman**
- AI agent controlling a teammate aircraft
- Receives observations and messages each timestep
- Returns actions (heading, speed, altitude commands)
- Can request help from human when uncertain
- Implements abstract method: `act(observation, messages)`

**Datarefs**
- X-Plane's shared memory system for inter-component communication
- Standard datarefs: Aircraft state (position, attitude, velocity)
- Custom datarefs: Mission-specific data (target status, commands, AI state)

**Observation Space**
- Numpy array representation of mission state
- Passed to AI agent each timestep
- Contains: mission time, human state, wingman state, target states, messages

**Target**
- Dataclass representing a mission objective (fire, person, package)
- Properties: position (lat/lon/alt), type, status, progress
- Multi-stage status progression (unspotted → spotted → classified → handled)
- Tracked separately for human and AI proximity

---

### 2.5 Copying Plugin Files to X-Plane

HAATO includes custom Lua scripts and Python plugins that must be copied to your X-Plane directory.

**Final Directory Structure:**
```
X-Plane 12/
└── Resources/
    └── plugins/
        ├── FlyWithLua/
        │   ├── (FlyWithLua plugin files)
        │   └── Scripts/
        │       ├── (other scripts)
        │       └── custom_datarefs.lua  ← HAATO file
        │
        ├── XPPython3/
        │   └── (XPPython3 plugin files)
        │
        ├── PythonPlugins/
        │   ├── (other plugins)
        │   ├── PI_gui_refactor.py  ← HAATO file
        │   └── classes/  ← HAATO directory
        │       ├── GridSystem.py
        │       └── (other files)
        │
        └── HAATO_assets/  ← HAATO directory
            ├── fire_targets_mission1.json
            ├── fire_targets_mission2.json
            ├── ...
            ├── images/
            └── sounds/
```



#### Launch First Mission

Now you're ready to run your first HAATO mission.

**Step-by-Step:**

1. **Start X-Plane 12**
   - Launch X-Plane
   - Select Airport: Skykomish State Airport (S60)
   - Select Aircraft: Lancair Evolution or Cirrus Vision SF50
   - Click "Start Flight"

2. **Add AI Aircraft**
3. 
   - Click "Flight Configuration" (top right)
   - Click "AI Aircraft"
   - Click "+ Add Aircraft"
   - Select any aircraft (this will be controlled by the wingman)
   - Click "Done"

3. **Position Aircraft**
   - Ensure you're at Skykomish State Airport (S60)
   - The mission will automatically position both aircraft

4. **Run Mission Script**
   ```bash
   # In terminal with venv activated:
   python run_mission.py --subject_id 99
   ```

5. Refresh xppython3 plugins
   - Refresh xppython3 plugins using the top navigation bar in X-Plane.
   
   - Context: A major -ism of the way we've combined python, xppython3, and flywithlua is that xppython3 

6. **In-Mission Verification**
   - G1000 MFD should show a map with fire icons
   - G1000 PFD should show a splash screen (black with white text)
   - WoZ GUI window should appear (experimenter controls)
   - Console should show mission updates
   - You should be able to fly the aircraft

8. **End Mission**
   - Press Ctrl+C in terminal to stop
   - Or complete all mission objectives
   - Data will be saved to `experiment_data/` directory

#### Common First-Run Issues

**Issue: "Dataref not found: custom/haato/..."**
- **Cause:** custom_datarefs.lua not loaded
- **Solution:** Check FlyWithLua Scripts folder, verify Lua file copied correctly

**Issue: "No G1000 overlay visible"**
- **Cause:** PI_gui_refactor.py not loaded by XPPython3
- **Solution:** Check XPPython3 log, verify Python plugin copied correctly

You now have a working HAATO installation. The next sections explain how to customize, and extend the system for new studies.

---

## 3. Understanding the FireWatch Mission

The FireWatch mission is HAATO's reference implementation. It is a fully-featured aerial firefighting scenario demonstrating all system capabilities. Understanding how FireWatch works will help you create your own custom missions.

### 3.1 Mission Overview

**Scenario:**
You are a pilot in a two-aircraft team responding to wildfires in the Skykomish region of Washington State. 
Your mission is to locate, classify, and mark the position of 8 fires scattered across a 17x17 nautical mile area.

**Objectives:**
1. **Detect** fires within detection range (1.5 NM visual range)
2. **Classify** fires as "moderate" or "severe" by flying close and identifying
3. **Mark Position** TODO
3. **Mark Route** TODO
4. **Coordinate** with your AI wingman to handle all fires efficiently
5. **Complete** before 30-minute time limit expires

**Team Composition:**
- **Human Pilot (You):** Primary flight control, classification authority, team commander
- **AI Wingman:** Autonomous teammate with configurable initiative level

### 3.2 Mission Lifecycle

#### Phase 1: Pre-Mission (WoZ GUI Setup)

Before the mission starts, the experimenter uses the Wizard of Oz (WoZ) GUI to configure initial conditions:

TODO wrong
**Configuration Options:**
- Set initial fire statuses (for mid-mission scenarios)
- Pre-classify fires (skip classification phase for testing)
- Configure team plan (which fires human/wingman will handle)
- Set wingman initiative level (low/medium/high) (TODO wrong, this is set by run_mission)
- Enable/disable auto-classification

**Starting the Mission:**
- Click "Start Mission" in WoZ GUI
- Mission timer begins
- Both aircraft spawn at configured positions

#### Phase 2: Transit & Detection

**Fire Status: 0.0 (Unspotted)**

Both human and AI search for fires within the AOR.

(TODO WRONG)
**Human Detection:**
- Fires become visible when within 1.5 NM range (TODO WRONG)
- G1000 MFD shows fire icons when detected (TODO WRONG)
- Fire icon appears on map at detected location (TODO WRONG)
- Status updates to 1.0 (Spotted)

**AI Detection:**
- Wingman can detect fires at 1.5 NM range
- Auto-detects when flying autonomous search pattern
- Updates fire status via datarefs
- Notifies human via status message

(TODO WRONG)
**Visual Indicators:**
- Unspotted fires: Not visible
- Spotted fires: Orange fire icon on G1000 MFD

#### Phase 3: Classification

**Fire Status: 1.0 (Spotted, Unclassified)**

After detection, fires must be classified as "moderate" or "severe".

**Classification Process:**

1. **Fly Close to Fire**
   - Approach within 0.5 NM of fire (TODO check this range)
   - Human enters "in range" status
   - G1000 PFD displays classification interface
   - Shows fire image captured from that location

2. **Identify Fire Type**
   - Review fire image on PFD
   - Press button for fire type:
     - Button 1: "Moderate" (smaller, slower-spreading)
     - Button 2: "Severe" (larger, intense)
   - Or pull trigger for automated classification

3. **Classification Recorded**
   - Fire type stored in dataref: `custom/haato/target{N}classification`
   - Values: 1.0 = moderate, 2.0 = severe
   - Updates visible on G1000 MFD (color changes)

**Auto-Classification Mode:**
- If enabled: Fires auto-classify when detected
- Used for testing or focusing on coordination
- Toggle via WoZ GUI or dataref: `custom/haato/auto_spot`

**AI Classification Requests:**
- Wingman can request human to classify specific fires
- Help request appears on G1000 displays
- Human can accept (fly to fire) or reject (wingman handles)

TODO add mark position, fly route, refine route

#### Phase 5: Coordination & Task Allocation

Throughout the mission, human and AI coordinate to efficiently handle all fires.

**Human Commands to Wingman:**

| Command Code | Dataref Value | Meaning |
|--------------|---------------|---------|
| Go to Fire 0 | 0.0 | "Fly to and handle fire #0" |
| Go to Fire 1 | 1.0 | "Fly to and handle fire #1" |
| ... | ... | ... |
| Go to Fire 7 | 7.0 | "Fly to and handle fire #7" |
| Follow Me | 8.0 | "Join my formation" |
| Hold Position | 12.0 | "Maintain holding pattern" |

**Command Input Methods:**
- G1000 MFD (click fire, then "Command Wingman") (TODO add joystick controls dpad + trigger)
- WoZ GUI buttons (experimenter control)
- Voice recognition (experimental, `--enable_voice` flag)

**Wingman Help Requests:**
- Wingman sets `custom/haato/help_request` = fire ID (0-7)
- Request displayed on G1000 PFD and MFD
- Audio cue plays (radio call sound)
- Human responds via:
  - Accept: `custom/haato/request_response` = 1.0
  - Reject: `custom/haato/request_response` = -1.0

**Wingman Status Updates:**
- Continuously updated via `custom/haato/wingman_status`
- Encoded status messages (0-59 codes)
- Examples:
  - "Searching for fires"
  - "Flying to fire 3"
  - "Suppressing fire 5"
  - "Waiting for instructions"

#### Phase 6: Mission Completion

**Win Condition:**
- All 8 fires reach status 2.0 (suppressed)
- Mission status dataref set to 1.0 (success)
- Completion message displayed
- Final stats shown (time, fires handled by human/AI)


### 3.3 Human Pilot Capabilities

The human pilot has full control of their aircraft plus mission-specific capabilities.

#### Flight Controls

**Primary Controls:**
- Joystick/Yoke: Pitch and roll
- Throttle: Engine power
- Rudder pedals: Yaw control
- Standard X-Plane keybindings apply

**Control Configuration:**
TODO need to explain this more deeply
- Settings → Joystick
- Calibrate axes for your hardware
- HAATO supports multiple joystick profiles:
  - Logitech (--control_prefix logitech)
  - Thrustmaster (--control_prefix thrustmaster)
  - Microsoft (--control_prefix microsoft)


#### Fire Classification

**Classification Interface (G1000 PFD):**

When within classification range (0.5 NM):
```
┌─────────────────────────────────────┐
│  Classify Fire #2                   │
│                                     │
│  ┌────────────┐                     │
│  │ [Fire Img] │  What type of fire? │
│  │            │                     │
│  └────────────┘                     │
│                                     │
│  [ Moderate ]    [ Severe ]         │
│                                     │
│                                     │
└─────────────────────────────────────┘
```

**Classification Options:**
1. **Manual Selection:**
   - View fire image
   - Use directional pad on joystick to switch between "Moderate" or "Severe" button
   - Pull trigger to select 
   - Classification recorded immediately

2. **Trigger Button:**
   - Pull joystick trigger
   - Auto-classifies based on ground truth
   - Faster but reduces realism

#### Command Interface

**Commanding the Wingman:**

**Via G1000 MFD:**
1. Click on fire icon
2. Command menu appears
3. Select "Send Wingman Here"
4. Wingman flies to that fire

**Via WoZ GUI (Dev Mode):**
- Direct button controls
- Useful for testing
- Not available to participants

**Special Commands:**
- **Follow Me:** Wingman joins your formation
  - Useful for: Team transit, teaching demonstrations
  - Wingman matches your heading/speed/altitude
  - Stays ~0.5 NM behind and to the right

- **Hold Position:** Wingman circles current location
  - Useful for: Temporary task allocation, regrouping
  - Circular holding pattern, 0.5 NM radius
  - Maintains altitude

#### Response to Wingman Requests

**Help Request Scenario:**
Wingman encounters a fire it's uncertain about and requests help.

**Visual Indicators:**
- G1000 PFD: "Wingman requests help with Fire #3"
- G1000 MFD: Fire icon highlights/flashes
- Audio cue: Radio call sound plays

**Response Options:**

1. **Accept Request:**
   - Press "Accept" button on PFD
   - Dataref `custom/haato/request_response` = 1.0
   - You commit to handling that fire
   - Wingman moves to next task

2. **Reject Request:**
   - Press "Reject" button on PFD
   - Dataref `custom/haato/request_response` = -1.0
   - Wingman continues attempting fire
   - May request help again later

3. **Ignore Request:**
   - No response within timeout period
   - Wingman makes autonomous decision
   - May affect trust/coordination

**When to Accept:**
- You have capacity and fire is on your route
- Wingman is overloaded with other tasks
- Fire requires human expertise (complex terrain)

**When to Reject:**
- You're busy with other fires
- Wingman should handle it autonomously
- Testing AI's problem-solving capabilities

### 3.4 AI Wingman Behaviors

The AI wingman operates with configurable levels of autonomy and decision-making capabilities.

#### Initiative Levels

**Low Initiative:**
- Waits for explicit commands
- Only acts when commanded by human
- Holds position when no commands
- Requests help frequently
- Conservative, risk-averse
- Best for: High human control, training scenarios

**Medium Initiative:**
- Balances autonomy and human input
- Acts autonomously but seeks guidance when uncertain
- Moderate help request frequency
- Respects human commands while maintaining own priorities
- Best for: Collaborative teaming research

**High Initiative:**
- Highly autonomous operation
- Makes independent decisions
- Rarely requests help
- Only follows critical human commands
- Proactive task allocation
- Best for: Testing autonomous coordination

**Configuration:**
- Set via command-line: `--initiative_level high`
- Or via WoZ GUI during mission
- Affects priority settings and help request thresholds

#### Autonomous Fire Detection

**Detection Capability:**
- Same 1.5 NM range as human
- 360° detection around wingman
- Automatic status updates

**Search Strategy:**
- If no assigned task: Systematic grid search
- Flies search pattern over AOR
- Prioritizes unexplored regions
- Updates team knowledge when fire detected

#### Autonomous Fire Suppression

**Decision Process:**

1. **Task Selection:**
   - Evaluate all unhandled fires
   - Apply priority rules (configured by initiative level)
   - Select highest-priority fire

2. **Priority Factors:**
   - Fire type (severe > moderate, if configured)
   - Distance (closer fires preferred in greedy mode)
   - Human commands (override priorities)
   - Team plan (avoid conflicts with human)

3. **Execution:**
   - Navigate to selected fire
   - Climb/descend to suppression altitude
   - Execute suppression run
   - Monitor progress, complete task

**Auto-Classification:**
- If `custom/haato/auto_spot` = 1.0:
  - Wingman auto-classifies detected fires
  - No need for classification phase
  - Jumps directly to suppression

- If auto-spot disabled:
  - Wingman requests human to classify
  - Or attempts classification autonomously (if capable)

#### Help-Seeking Behavior

**When Wingman Requests Help:**

**Uncertainty Triggers:**
- Fire type ambiguous (classification unclear)
- Multiple fires equidistant (decision paralysis)
- Task conflict with human's apparent intent
- Repeated failure at a task

**Help Request Process:**
1. Wingman identifies uncertainty
2. Sets `custom/haato/help_request` = fire ID
3. Sets `custom/haato/agent_id_request` = fire ID (for classification)
4. Hovers near fire awaiting response
5. If accepted: Moves to next task
6. If rejected: Continues attempting

**Help Request Frequency:**
- Low Initiative: Frequent (low confidence threshold)
- Medium Initiative: Moderate (medium threshold)
- High Initiative: Rare (high threshold)

#### Formation Flying (Follow Mode)

When commanded to "Follow Me" (command code 8.0):

**Formation Position:**
- 0.5 NM behind human
- 500 ft to the right
- Matches human altitude (±100 ft)

**Intercept Calculation:**
- Predicts human future position
- Calculates intercept course
- Smoothly joins formation

**Formation Maintenance:**
- Adjusts heading/speed to maintain position
- Matches human turns and altitude changes
- Continues until new command issued

**Use Cases:**
- Transiting to distant fire cluster
- Demonstrating coordinated tactics
- Regrouping after task completion

#### Holding Patterns

When commanded to "Hold Position" (command code 12.0):

**Holding Behavior:**
- Circular pattern around current position
- Radius: 0.5 NM (configurable)
- Maintains current altitude
- Standard rate turn (3°/second)

**Calculation:**
- `_calc_hsa_holding_pattern()` method
- Generates smooth circular path
- Updates heading continuously

**Use Cases:**
- Temporary task pause
- Waiting for human decision
- Area coverage/observation

### 3.5 Human-AI Communication

Effective communication is central to successful teaming. HAATO implements multiple communication channels.

#### Message Types

**1. Commands (Human → AI)**
- Source: Human pilot
- Target: Wingman
- Content: Task directives
- Examples: "Go to fire 3", "Follow me"
- Delivery: Dataref `custom/haato/command_from_human`

**2. Requests (AI → Human)**
- Source: Wingman
- Target: Human pilot
- Content: Help requests, suggestions
- Examples: "Need help with fire 5", "Suggest you handle fire 2"
- Delivery: Dataref `custom/haato/help_request`

**3. Responses (Human → AI)**
- Source: Human pilot
- Target: Wingman (in response to request)
- Content: Accept/reject decisions
- Values: 1.0 = accept, -1.0 = reject, 0.0 = none
- Delivery: Dataref `custom/haato/request_response`

**4. Status Updates (AI → Human)**
- Source: Wingman
- Target: Human pilot
- Content: Current activity, intentions
- Examples: "Flying to fire 3", "Searching", "Suppressing fire 1"
- Delivery: Dataref `custom/haato/wingman_status`

#### Message Queue System

**Architecture:**
- In-memory FIFO queue
- Guaranteed delivery (no message loss)
- Ordered by timestamp
- Persisted to logs

**Message Structure:**
```python
{
    'type': 'command',  # or 'request', 'response', 'status'
    'sender': 'human',  # or 'wingman'
    'recipient': 'wingman',  # or 'human'
    'content': 'go_to_fire_3',
    'timestamp': 45.7,  # mission elapsed time
    'delivered': False
}
```

**Processing:**
- Messages polled each timestep (30 Hz)
- Delivered messages marked as read
- Logged for analysis

#### Status Message Encoding

Wingman status is encoded as a float (0-59) for efficiency:

| Code Range | Category | Examples |
|------------|----------|----------|
| 0-7 | Flying to fire N | 3.0 = "Flying to fire 3" |
| 10-17 | Suppressing fire N | 12.0 = "Suppressing fire 2" |
| 20-27 | Classifying fire N | 23.0 = "Classifying fire 3" |
| 30 | Following human | "In formation" |
| 40 | Holding position | "Awaiting orders" |
| 50 | Searching | "Searching for fires" |
| 99 | Idle/unknown | No current task |

**Decoding in GUI:**
```python
def decode_wingman_status(code):
    if 0 <= code <= 7:
        return f"Flying to fire {int(code)}"
    elif 10 <= code <= 17:
        return f"Suppressing fire {int(code) - 10}"
    elif 20 <= code <= 27:
        return f"Classifying fire {int(code) - 20}"
    elif code == 30:
        return "Following human"
    elif code == 40:
        return "Holding position"
    elif code == 50:
        return "Searching for fires"
    else:
        return "Unknown status"
```

#### Audio Cues

**Radio Call Sounds:**
- Triggered via `custom/haato/play_radiocall` dataref
- Managed by `radio_calls.lua` script
- Sound files in `HAATO_assets/sounds/`

**Audio Types:**
| Code | Sound | Trigger |
|------|-------|---------|
| 1.0 | Help request | Wingman needs assistance |
| 2.0 | Command acknowledgment | Wingman confirms order |
| 3.0 | Status update | Periodic check-in |
| 4.0 | Human acknowledgment | Human responds to call |
| 0.0 | Stop audio | Silence |

**Voice Recognition (Experimental):**
- Enable with `--enable_voice` flag
- Uses Google Speech Recognition
- Keywords: "status", "plan", "fire", "help", "wingman"
- Accuracy varies with environment noise

### 3.6 Mission Configuration Files

FireWatch missions are configured via JSON files that define fire locations, types, and initial conditions.

#### JSON File Structure

**File Location:**
```
X-Plane 12/Resources/plugins/HAATO_assets/fire_targets_mission1.json
X-Plane 12/Resources/plugins/HAATO_assets/fire_targets_mission2.json
...
X-Plane 12/Resources/plugins/HAATO_assets/fire_targets_mission5.json
```

**Complete Example:**
```json
{
  "Notes": "Mission 1 - Balanced fire distribution",
  "windDirection": 150.0,
  "magneticDeclination": 15.0,
  "requiredAltitudeFtMSL": 7000.0,
  "requiredDropRouteLength": 2.0,
  "requiredAltitudeFireAGLFt": 1000.0,
  "humanStartLLA": [47.71044513620272, -121.34287916904042, 1600.319856278361],
  "humanStartSpd": 200,
  "humanStartHdg": 90,
  "agentStartLLA": [47.71044513620272, -121.32287916904042, 2333.33333333],
  "wingmanActive": true,
  "dataPoints": [
    {
      "latitude": 47.9748,
      "longitude": -121.258566,
      "altitude": 1500.2,
      "type": "moderate",
      "image_path": "fire_moderate_1.jpg",
      "image_res": [620, 465]
    },
    {
      "latitude": 47.76563325,
      "longitude": -121.318566,
      "altitude": 400.2,
      "type": "severe",
      "image_path": "fire_severe_1.jpg",
      "image_res": [1024, 1024]
    }
    // ... 6 more fires
  ]
}
```

#### Field Descriptions

**Mission Parameters:**
- `Notes`: Human-readable mission description
- `windDirection`: Wind heading in degrees (affects fire spread, cosmetic)
- `magneticDeclination`: Local magnetic variation
- `requiredAltitudeFtMSL`: Suppression altitude (feet MSL)
- `requiredDropRouteLength`: Minimum overfly distance (NM)
- `requiredAltitudeFireAGLFt`: Clearance above fire altitude

**Aircraft Start Positions:**
- `humanStartLLA`: [latitude, longitude, altitude_meters] for human
- `humanStartSpd`: Initial speed (knots)
- `humanStartHdg`: Initial heading (degrees true)
- `agentStartLLA`: [lat, lon, alt] for wingman
- `wingmanActive`: Enable/disable wingman (true/false)

**Fire Definitions (dataPoints array):**
- `latitude`: Fire latitude (decimal degrees)
- `longitude`: Fire longitude (decimal degrees)
- `altitude`: Fire altitude (meters MSL)
- `type`: "moderate" or "severe"
- `image_path`: Classification image filename
- `image_res`: [width, height] of image in pixels

#### Creating Custom Fire Layouts

**Steps to Create Mission 6:**

1. **Copy Existing File:**
   ```bash
   cp fire_targets_mission1.json fire_targets_mission6.json
   ```

2. **Edit Fire Positions:**
   - Use X-Plane map to select coordinates
   - Or use online mapping tools (Google Earth)
   - Ensure fires within AOR (20 NM diameter)

3. **Balance Fire Types:**
   - Mix of moderate and severe
   - Recommended: 4-6 moderate, 2-4 severe
   - Varies difficulty and workload

4. **Adjust Start Positions:**
   - Human/wingman spawn locations
   - Consider mission difficulty (close vs. distant start)

5. **Test Mission:**
   ```bash
   python run_mission.py --subject_id 99 --fire_layout 6 --dev_mode
   ```

**Design Considerations:**
- Fire spacing: Avoid clustering (reduces interest)
- Altitude variation: Mix low/high altitude fires
- Terrain: Consider mountainous areas for realism
- Visibility: Ensure fires not hidden behind mountains
- Balance: Equal workload potential for human and AI

**Validation:**
- All 8 fires within AOR (check distances)
- No fires at identical locations
- Altitudes realistic for terrain
- Image files exist for all classifications

---

## 4. Running Missions & Collecting Data

### 4.1 Command-Line Interface

The `run_mission.py` script provides extensive command-line options for configuring experiments.

#### All Command-Line Arguments

```bash
python run_mission.py [OPTIONS]
```

**Required Arguments:**
None—all arguments have defaults.

**Participant Configuration:**
```bash
--subject_id INT          # Participant ID number (default: 99)
                          # Determines Latin square condition assignment
                          # Used in log filenames

--trial INT               # Trial number 1-3 (default: 1)
                          # Selects condition from Latin square
                          # Each trial has different initiative/layout combination
```

**Mission Configuration:**
```bash
--fire_layout INT         # Fire layout number 1-5 (default: from trial config)
                          # Selects which JSON file to load
                          # Can override trial configuration

--initiative_level STR    # AI initiative: 'low', 'medium', 'high' (default: from trial)
                          # Sets wingman autonomy level
                          # Can override trial configuration

--practice                # Run practice trials (layouts 4 & 5)
                          # Used for participant training
                          # Doesn't affect experimental trial counter
```

**Hardware Configuration:**
```bash
--control_prefix STR      # Joystick profile: 'logitech', 'thrustmaster', 'microsoft'
                          # Loads appropriate button mappings
                          # Default: 'logitech'
```

**Development & Testing:**
```bash
--dev_mode                # Enable development features
                          # Shows WoZ GUI, extra debugging
                          # Disables some constraints
                          # Default: False

--simulate_xplane         # Run without X-Plane (offline testing)
                          # Uses SimMode mock for datarefs
                          # Useful for agent development
                          # Default: False

--verbose                 # Enable verbose console output
                          # Shows detailed state information
                          # Default: False
```

**Data Logging:**
```bash
--log_hz FLOAT            # Logging frequency in Hz (default: 1.0)
                          # How often to save telemetry rows
                          # Higher = more data, larger files
                          # Recommended: 1.0 Hz for experiments
```

**Advanced:**
```bash
--resume                  # Resume from crash recovery file
                          # Loads saved mission state
                          # Continues from last checkpoint
                          # Default: False

--enable_voice            # Enable voice recognition (experimental)
                          # Requires microphone and pyaudio
                          # Google Speech Recognition used
                          # Default: False
```

#### Usage Examples

**Standard Experiment - Participant 5, Trial 1:**
```bash
python run_mission.py --subject_id 5 --trial 1
```
- Uses Latin square to determine initiative level and fire layout
- Subject 5, Trial 1: medium initiative, layout 1 (see CONFIGS in run_mission.py)

**Practice Mode:**
```bash
python run_mission.py --subject_id 5 --practice
```
- Runs practice trials (layouts 4 & 5)
- Different initiative levels for familiarization

**Override Configuration:**
```bash
python run_mission.py --subject_id 5 --initiative_level high --fire_layout 3
```
- Manually specify initiative and layout
- Bypasses Latin square assignment

**Development Testing:**
```bash
python run_mission.py --subject_id 99 --dev_mode --verbose
```
- Development subject ID (99)
- WoZ GUI enabled
- Verbose output for debugging

**Offline Agent Development:**
```bash
python run_mission.py --simulate_xplane --dev_mode
```
- No X-Plane required
- Mock dataref system
- Rapid iteration on agent logic

**High-Frequency Logging:**
```bash
python run_mission.py --subject_id 5 --trial 1 --log_hz 10.0
```
- 10 Hz logging (10 rows/second)
- For high-resolution analysis
- Larger log files

**Resume After Crash:**
```bash
python run_mission.py --subject_id 5 --trial 1 --resume
```
- Loads last crash recovery state
- Continues mission from checkpoint

### 4.2 Pre-Mission Setup with WoZ GUI

The Wizard of Oz (WoZ) GUI provides experimenter control over mission parameters in real-time.

#### Launching WoZ GUI

**Automatic Launch:**
- Runs automatically when `--dev_mode` flag is set
- Appears in separate window
- Non-blocking (mission runs independently)

**Manual Launch:**
```python
from utility.woz_gui_threaded import WoZGUIThread

gui_thread = WoZGUIThread(xpc, mm, dev_mode=True)
gui_thread.start()
```

#### WoZ GUI Layout

```
┌─────────────────────────────────────────────────────┐
│ HAATO Wizard of Oz Control Panel                   │
├─────────────────────────────────────────────────────┤
│                                                      │
│ ┌─ Mission Status ─────────────────────────────┐   │
│ │ Time Remaining: 9:43                          │   │
│ │ Fires Spotted: 3/8                            │   │
│ │ Fires Handled: 1/8                            │   │
│ │ Mission Status: In Progress                   │   │
│ └───────────────────────────────────────────────┘   │
│                                                      │
│ ┌─ Fire Status Configuration ──────────────────┐   │
│ │ Fire 0: [Unspotted ▼] [Unclassified ▼]      │   │
│ │ Fire 1: [Spotted   ▼] [Moderate    ▼]       │   │
│ │ Fire 2: [Suppressed▼] [Severe      ▼]       │   │
│ │ ... (fires 3-7)                               │   │
│ └───────────────────────────────────────────────┘   │
│                                                      │
│ ┌─ Wingman Configuration ──────────────────────┐   │
│ │ Initiative Level: [Medium ▼]                 │   │
│ │ ☑ Auto-Classify Fires                        │   │
│ │ ☑ Allow Help Requests                        │   │
│ │ Priority - Spot Unknown:     [0]             │   │
│ │ Priority - Handle Moderate:  [1]             │   │
│ │ Priority - Handle Severe:    [2]             │   │
│ │ ☐ Greedy Mode (Closest First)                │   │
│ └───────────────────────────────────────────────┘   │
│                                                      │
│ ┌─ Command Interface ──────────────────────────┐   │
│ │ Send Wingman To:                              │   │
│ │ [Fire 0][Fire 1][Fire 2][Fire 3]             │   │
│ │ [Fire 4][Fire 5][Fire 6][Fire 7]             │   │
│ │ [Follow Me]  [Hold Position]                 │   │
│ │                                               │   │
│ │ Respond to Help Request:                      │   │
│ │ [Accept]  [Reject]                           │   │
│ └───────────────────────────────────────────────┘   │
│                                                      │
│ ┌─ Mission Control ────────────────────────────┐   │
│ │ [Start Mission]  [Pause]  [Reset]            │   │
│ │ [Save State]  [Load State]                   │   │
│ └───────────────────────────────────────────────┘   │
│                                                      │
└─────────────────────────────────────────────────────┘
```

#### Setting Initial Mission State

**Use Case: Mid-Mission Scenarios**
Test specific situations without playing through entire mission.

**Example: Testing Coordination with 4 Fires Remaining**

1. **Set Completed Fires:**
   - Fire 0: Status → "Suppressed", Classification → "Moderate"
   - Fire 1: Status → "Suppressed", Classification → "Severe"
   - Fire 2: Status → "Suppressed", Classification → "Moderate"
   - Fire 3: Status → "Suppressed", Classification → "Severe"

2. **Set Active Fires:**
   - Fire 4: Status → "Spotted", Classification → "Unclassified"
   - Fire 5: Status → "Spotted", Classification → "Moderate"
   - Fire 6: Status → "Unspotted", Classification → "Unclassified"
   - Fire 7: Status → "Spotted", Classification → "Severe"

3. **Configure Wingman:**
   - Initiative: "High"
   - Auto-Classify: ☑ Enabled
   - Allow Help Requests: ☑ Enabled

4. **Start Mission:**
   - Click "Start Mission"
   - Mission begins with 4 fires remaining
   - Tests late-mission coordination

#### Real-Time Mission Control

**During Mission:**

**Command Wingman:**
- Click fire buttons to send commands
- Overrides autonomous behavior
- Useful for testing specific scenarios

**Adjust Initiative:**
- Change initiative level mid-mission
- Updates priority datarefs immediately
- Enables dynamic difficulty adjustment

**Toggle Features:**
- Auto-Classify: Skip classification phase
- Help Requests: Enable/disable AI requests
- Greedy Mode: Switch between closest-first and priority-based

**Respond to Requests:**
- Accept/Reject buttons for help requests
- Mimics participant interface
- Testing request-response patterns

**Save/Load State:**
- Save current mission state to JSON
- Load previously saved states
- Useful for repeated testing of specific scenarios

#### Experimenter Use Cases

**Training Participants:**
```
1. Pre-configure simple scenario (2-3 fires)
2. Enable auto-classify to focus on flight
3. High initiative wingman for demonstration
4. Start mission, narrate actions
```

**Testing AI Policies:**
```
1. Set specific fire distribution
2. Configure priority settings
3. Disable help requests (full autonomy)
4. Compare performance across configurations
```

**Debugging Mission Logic:**
```
1. Set fires to specific states
2. Trigger edge cases
3. Observe system behavior
4. Verify correct handling
```

**Pilot Studies:**
```
1. Rapidly iterate mission parameters
2. Test different initiative levels
3. Identify optimal configurations
4. Refine before full experiment
```

### 4.3 During Mission: Real-Time Monitoring

Understanding what happens during a mission helps with debugging and experiment monitoring.

#### Console Output

**Mission Initialization:**
```
============================================================
STARTING FIREWATCH MISSION
============================================================

✓ X-Plane connection established
✓ Mission Manager created (FireWatchMM)
✓ Wingman created (initiative: medium, layout: 1)
✓ Data Logger initialized (timeseries_p5_initiativemedium_layout1_20260209_143052.csv)
✓ Message Queue created
✓ Mission Timer created
✓ WoZ GUI thread started
✓ Crash recovery thread started
✓ Mission reset complete

Mission Configuration:
- Subject ID: 5
- Trial: 1
- Initiative Level: medium
- Fire Layout: 1
- 8 fires loaded from fire_targets_mission1.json

============================================================
MISSION STARTING - Good luck!
============================================================
```

**Runtime Updates (every ~5 seconds):**
```
[00:05] Human: (47.715, -121.340, 1605m) | Wingman: (47.713, -121.318, 2340m)
[00:05] Fires: Spotted 1/8 | Handled 0/8 | Time Remaining: 9:55
[00:05] Wingman Status: Searching for fires
[00:05] Last Command: None

[00:12] Human: (47.728, -121.330, 1680m) | Wingman: (47.745, -121.305, 2300m)
[00:12] Fires: Spotted 3/8 | Handled 0/8 | Time Remaining: 9:48
[00:12] Wingman Status: Flying to fire 2
[00:12] Human detected fire 1 (moderate)

[00:34] Human: (47.765, -121.318, 2100m) | Wingman: (47.835, -121.320, 2150m)
[00:34] Fires: Spotted 5/8 | Handled 1/8 | Time Remaining: 9:26
[00:34] Wingman Status: Suppressing fire 2
[00:34] Wingman completed fire 2!

[00:56] Human: (47.762, -121.315, 2135m) | Wingman: (47.897, -121.213, 2280m)
[00:56] Fires: Spotted 7/8 | Handled 3/8 | Time Remaining: 9:04
[00:56] Wingman Status: Flying to fire 4
[00:56] Human completed fire 1!
[00:56] HELP REQUEST: Wingman needs help with fire 3
```

**Mission Completion:**
```
[09:42] All fires handled! Mission complete.
[09:42] Final Stats:
  - Total Time: 9:42
  - Fires Handled by Human: 4
  - Fires Handled by Wingman: 4
  - Help Requests: 2 (1 accepted, 1 rejected)
  - Commands Issued: 6

============================================================
MISSION COMPLETE - SUCCESS
============================================================

Data saved to:
- experiment_data/timeseries_p5_initiativemedium_layout1_20260209_143052.csv
- experiment_data/events_p5_initiativemedium_layout1_20260209_143052.jsonl
```

#### G1000 PFD (Primary Flight Display)

**Normal Flight:**
```
┌─────────────────────────────────────────┐
│         Airspeed: 185 KIAS              │
│         Altitude: 6850 ft MSL           │
│         Heading:  095°                  │
│         VS: +300 ft/min                 │
│                                         │
│         [Standard PFD instruments]      │
│                                         │
└─────────────────────────────────────────┘
```

**Classification Interface (when near fire):**
```
┌─────────────────────────────────────────┐
│  CLASSIFY FIRE #3                       │
│  ┌──────────────┐                       │
│  │   [Image]    │  What type of fire?   │
│  │              │                       │
│  └──────────────┘                       │
│                                         │
│  ┌───────────┐  ┌──────────┐          │
│  │ MODERATE  │  │  SEVERE  │          │
│  └───────────┘  └──────────┘          │
│                                         │
│  Or pull trigger for auto-classify      │
└─────────────────────────────────────────┘
```

**Help Request Notification:**
```
┌─────────────────────────────────────────┐
│  ⚠ WINGMAN REQUESTS HELP                │
│                                         │
│  Fire #5 needs assistance               │
│                                         │
│  ┌─────────┐  ┌──────────┐            │
│  │ ACCEPT  │  │  REJECT  │            │
│  └─────────┘  └──────────┘            │
│                                         │
└─────────────────────────────────────────┘
```

#### G1000 MFD (Multi-Function Display)

**Map View:**
```
┌────────────────────────────────────────────┐
│              N                              │
│             ↑                              │
│   🔥                    🔥                 │
│  Fire 0              Fire 1                │
│  (moderate)          (severe)              │
│  [Orange]            [Orange]              │
│                                             │
│         ✈                                  │
│       (You)                                 │
│                                             │
│              🔥        ✈                   │
│           Fire 2    (Wingman)              │
│           (moderate)                        │
│           [Yellow - in progress]            │
│                                             │
│                        🔥                   │
│                     Fire 3                  │
│                     (severe)                │
│                     [Green - complete]      │
│                                             │
│  Range: 10 NM     Fires: 3/8               │
└────────────────────────────────────────────┘

Legend:
🔥 Orange:  Spotted, unclassified
🔥 Yellow:  Classified, in progress
🔥 Green:   Suppressed (complete)
🔥 Red:     Unspotted (not shown until detected)
```

#### Wingman Status Messages

Displayed on both PFD and MFD, updated continuously:

| Message | Meaning |
|---------|---------|
| "Searching for fires" | Autonomous search pattern, no assigned task |
| "Flying to fire 3" | Navigating to fire #3 |
| "Suppressing fire 1" | Currently dropping on fire #1 |
| "Classifying fire 5" | Identifying fire #5 type |
| "Following human" | In formation behind human |
| "Holding position" | Circular holding pattern |
| "Waiting for instructions" | Idle, awaiting command |

#### Mission Timer

**Display Locations:**
- Console output: Every update
- WoZ GUI: Real-time countdown
- G1000 MFD: Top-right corner
- Dataref: `custom/haato/mission_time_left`

**Time Warnings:**
- 5:00 remaining: Console notification
- 2:00 remaining: Console warning + audio cue (optional)
- 1:00 remaining: Flashing indicator (optional)
- 0:00: Mission ends, win/loss determined

### 4.4 Data Logging

HAATO provides comprehensive data logging for post-hoc analysis.

#### CSV Timeseries Logs

**File Naming Convention:**
```
experiment_data/timeseries_p{subject_id}_initiative{level}_layout{layout}_{timestamp}.csv
```

**Examples:**
```
timeseries_p5_initiativemedium_layout1_20260209_143052.csv
timeseries_p12_initiativehigh_layout3_20260209_151234.csv
timeseries_p99_initiativelow_layout1_20260209_161500.csv
```

**Logging Frequency:**
- Default: 1.0 Hz (one row per second)
- Configurable via `--log_hz` parameter
- Higher frequency = more data, larger files
- Recommendation: 1.0 Hz for standard experiments, 10.0 Hz for detailed kinematics

**CSV Column Structure:**

**Time Columns:**
- `mission_time`: Elapsed time since mission start (seconds)
- `timestamp`: Wall clock timestamp (Unix epoch)
- `frame`: Frame number (increments by 1 each timestep)

**Human State Columns:**
- `human_lat`, `human_lon`, `human_alt`: Position (degrees, degrees, meters MSL)
- `human_hdg`: True heading (degrees, 0-360)
- `human_pitch`, `human_roll`: Attitude (degrees)
- `human_spd`: Ground speed (knots)
- `human_vx`, `human_vy`, `human_vz`: Velocity components (m/s)

**Wingman State Columns:**
- `wingman_lat`, `wingman_lon`, `wingman_alt`: Position
- `wingman_hdg`, `wingman_spd`: Heading and speed
- `wingman_goal_hdg`, `wingman_goal_spd`, `wingman_goal_alt`: Desired state
- `wingman_status`: Status code (0-59)

**Fire Status Columns (repeated for each fire 0-7):**
- `fire0_status`: Status (0.0-2.0)
- `fire0_classification`: Type (0=unclassified, 1=moderate, 2=severe)
- `fire0_human_in_range`: Boolean (0/1)
- `fire0_wingman_in_range`: Boolean (0/1)
- ... (fire1_*, fire2_*, ..., fire7_*)

**Command Columns:**
- `command_from_human`: Command code (0-12)
- `request_response`: Human response to request (-1/0/1)
- `help_request`: Current wingman help request (0-7 or 99)

**Mission State Columns:**
- `mission_status`: Overall status (0=running, 1=success, -1=failure)
- `fires_spotted`: Count of spotted fires
- `fires_handled`: Count of completed fires

**Example Row:**
```csv
mission_time,timestamp,frame,human_lat,human_lon,human_alt,human_hdg,human_spd,wingman_lat,wingman_lon,wingman_alt,wingman_hdg,wingman_spd,fire0_status,fire0_classification,fire1_status,fire1_classification,...
45.7,1707493852.3,1371,47.7650,-121.3180,2100.5,095.2,185.3,47.8350,-121.3200,2150.0,078.5,190.0,1.0,1.0,0.5,2.0,...
```

#### JSONL Event Logs

**File Naming:**
```
experiment_data/events_p{subject_id}_initiative{level}_layout{layout}_{timestamp}.jsonl
```

**Format:**
JSON Lines (one JSON object per line, newline-separated)

**Event Types:**

**1. Message Events:**
```json
{
  "type": "message",
  "timestamp": 45.7,
  "message_type": "command",
  "sender": "human",
  "recipient": "wingman",
  "content": "go_to_fire_3",
  "fire_id": 3
}
```

**2. Fire Detection Events:**
```json
{
  "type": "fire_detected",
  "timestamp": 23.4,
  "fire_id": 2,
  "detected_by": "human",
  "position": {"lat": 47.8365, "lon": -121.3186, "alt": 800.7}
}
```

**3. Fire Classification Events:**
```json
{
  "type": "fire_classified",
  "timestamp": 67.2,
  "fire_id": 5,
  "classification": "severe",
  "classified_by": "wingman",
  "method": "autonomous"
}
```

**4. Fire Suppression Events:**
```json
{
  "type": "fire_suppressed",
  "timestamp": 145.8,
  "fire_id": 1,
  "suppressed_by": "human",
  "duration": 12.3
}
```

**5. Help Request Events:**
```json
{
  "type": "help_request",
  "timestamp": 98.5,
  "fire_id": 4,
  "response": "accepted",
  "response_time": 3.2
}
```

**6. Command Events:**
```json
{
  "type": "command_issued",
  "timestamp": 52.1,
  "command": "go_to_fire_6",
  "fire_id": 6,
  "wingman_acknowledged": true
}
```

#### Crash Recovery Files

**Automatic State Saving:**
- Background thread saves state every 10 steps (every ~0.33 seconds at 30 FPS)
- Saves to `crash_recovery/state_p{subject_id}.json`

**File Contents:**
```json
{
  "subject_id": 5,
  "mission_time": 145.7,
  "fires": [
    {"id": 0, "status": 2.0, "classification": 1.0, "handled_by": "human"},
    {"id": 1, "status": 2.0, "classification": 2.0, "handled_by": "wingman"},
    {"id": 2, "status": 1.5, "classification": 1.0, "handled_by": null},
    ...
  ],
  "human_state": {
    "lat": 47.7650,
    "lon": -121.3180,
    "alt": 2100.5,
    "hdg": 095.2,
    "spd": 185.3
  },
  "wingman_state": {
    "lat": 47.8350,
    "lon": -121.3200,
    "alt": 2150.0,
    "hdg": 078.5,
    "spd": 190.0,
    "current_task": "suppress_fire_2"
  },
  "message_queue": [
    {"type": "status", "content": "suppressing_fire_2", "timestamp": 145.5}
  ]
}
```

**Recovery Process:**
```bash
python run_mission.py --subject_id 5 --resume
```
- Loads `crash_recovery/state_p5.json`
- Restores mission time, fire states, positions
- Resumes logging to same CSV file
- Continues from crash point

#### Log File Organization

**Recommended Directory Structure:**
```
experiment_data/
├── participant_001/
│   ├── trial_1/
│   │   ├── timeseries_p1_initiativelow_layout1_20260209_100000.csv
│   │   ├── events_p1_initiativelow_layout1_20260209_100000.jsonl
│   │   └── notes.txt
│   ├── trial_2/
│   │   ├── timeseries_p1_initiativemedium_layout2_20260209_103000.csv
│   │   ├── events_p1_initiativemedium_layout2_20260209_103000.jsonl
│   │   └── notes.txt
│   └── trial_3/
│       ├── timeseries_p1_initiativehigh_layout3_20260209_110000.csv
│       ├── events_p1_initiativehigh_layout3_20260209_110000.jsonl
│       └── notes.txt
├── participant_002/
│   └── ...
└── pilot_tests/
    └── ...
```

### 4.5 Post-Mission Data Analysis

After collecting data, HAATO provides tools and examples for analysis.

#### Loading CSV Data with Pandas

**Basic Loading:**
```python
import pandas as pd

# Load timeseries data
df = pd.read_csv('experiment_data/timeseries_p5_initiativemedium_layout1_20260209_143052.csv')

# Display basic info
print(df.head())
print(df.columns)
print(f"Mission duration: {df['mission_time'].max():.1f} seconds")
print(f"Number of samples: {len(df)}")
```

**Analyzing Fire Completion:**
```python
# Count fires completed
fires_complete = sum(df.iloc[-1][f'fire{i}_status'] >= 2.0 for i in range(8))
print(f"Fires completed: {fires_complete}/8")

# Who completed each fire?
for i in range(8):
    status_col = f'fire{i}_status'

    # Find first timestep where fire was completed
    completed_rows = df[df[status_col] >= 2.0]

    if len(completed_rows) > 0:
        # Check who was in range at completion
        first_complete = completed_rows.iloc[0]
        human_in_range = first_complete[f'fire{i}_human_in_range']
        wingman_in_range = first_complete[f'fire{i}_wingman_in_range']

        completer = "Human" if human_in_range else "Wingman" if wingman_in_range else "Unknown"
        time = first_complete['mission_time']
        print(f"Fire {i}: Completed by {completer} at {time:.1f}s")
```

**Command Analysis:**
```python
# Count commands issued
command_changes = df['command_from_human'].diff() != 0
commands_issued = df[command_changes & (df['command_from_human'] != 12.0)]

print(f"Total commands issued: {len(commands_issued)}")
print("\nCommand timeline:")
for idx, row in commands_issued.iterrows():
    time = row['mission_time']
    cmd = row['command_from_human']
    if 0 <= cmd <= 7:
        print(f"  {time:6.1f}s: Go to fire {int(cmd)}")
    elif cmd == 8.0:
        print(f"  {time:6.1f}s: Follow me")
    elif cmd == 12.0:
        print(f"  {time:6.1f}s: Hold position")
```

#### Mission Playback Tool

**Location:** `data_analysis/mission_playback.py`

**Usage:**
```bash
python data_analysis/mission_playback.py --csv timeseries_p5_initiativemedium_layout1_20260209_143052.csv
```

**Features:**
- Animated replay of human/wingman trajectories
- Fire status progression over time
- Command timeline overlay
- Exportable to video (requires ffmpeg)

**Example Output:**
![Mission Playback Animation](docs/images/mission_playback_example.gif)

#### Visualizing Trajectories

**Flight Path Plot:**
```python
import matplotlib.pyplot as plt

# Extract positions
human_lat = df['human_lat']
human_lon = df['human_lon']
wingman_lat = df['wingman_lat']
wingman_lon = df['wingman_lon']

# Fire positions (from JSON config)
fire_lats = [47.9748, 47.7656, 47.8365, 47.8965, 47.7556, 47.7622, 47.9073, 47.9621]
fire_lons = [-121.2586, -121.3186, -121.3186, -121.2133, -121.2133, -121.1081, -121.0029, -120.9803]

# Plot
plt.figure(figsize=(12, 10))
plt.plot(human_lon, human_lat, 'b-', label='Human', linewidth=1, alpha=0.7)
plt.plot(wingman_lon, wingman_lat, 'r-', label='Wingman', linewidth=1, alpha=0.7)
plt.scatter(fire_lons, fire_lats, c='orange', s=200, marker='^', label='Fires', edgecolors='black', linewidths=2)

# Annotate fires
for i, (lat, lon) in enumerate(zip(fire_lats, fire_lons)):
    plt.annotate(f'F{i}', (lon, lat), fontsize=10, ha='center')

plt.xlabel('Longitude')
plt.ylabel('Latitude')
plt.title('Mission Trajectories - P5 Trial 1')
plt.legend()
plt.grid(True, alpha=0.3)
plt.axis('equal')
plt.tight_layout()
plt.savefig('trajectories_p5_trial1.png', dpi=300)
plt.show()
```

#### Team Coordination Metrics

**Example Metrics:**

**1. Workload Distribution:**
```python
# Calculate fires handled by each agent
human_fires = sum(df.iloc[-1][f'fire{i}_human_in_range'] and df.iloc[-1][f'fire{i}_status'] >= 2.0 for i in range(8))
wingman_fires = 8 - human_fires

print(f"Workload distribution: Human {human_fires}/8, Wingman {wingman_fires}/8")
```

**2. Help Request Response Time:**
```python
import pandas as pd
import json

# Load event log
events = []
with open('experiment_data/events_p5_initiativemedium_layout1_20260209_143052.jsonl', 'r') as f:
    for line in f:
        events.append(json.loads(line))

# Filter help request events
help_events = [e for e in events if e['type'] == 'help_request']

response_times = [e['response_time'] for e in help_events if e['response'] != 'ignored']
avg_response_time = sum(response_times) / len(response_times) if response_times else 0

print(f"Help requests: {len(help_events)}")
print(f"Average response time: {avg_response_time:.2f}s")
print(f"Acceptance rate: {sum(e['response'] == 'accepted' for e in help_events) / len(help_events) * 100:.1f}%")
```

**3. Spatial Efficiency:**
```python
from utility.base_classes_vectorized import GeoUtils

# Calculate total distance traveled
def calculate_distance_traveled(lat, lon):
    total_dist = 0
    for i in range(1, len(lat)):
        dist = GeoUtils.haversine_distance(lat[i-1], lon[i-1], lat[i], lon[i])
        total_dist += dist
    return total_dist

human_dist = calculate_distance_traveled(df['human_lat'].values, df['human_lon'].values)
wingman_dist = calculate_distance_traveled(df['wingman_lat'].values, df['wingman_lon'].values)

print(f"Distance traveled - Human: {human_dist:.1f} NM, Wingman: {wingman_dist:.1f} NM")
print(f"Total team distance: {human_dist + wingman_dist:.1f} NM")
```

---

## 5. Customizing Missions for Your Research

This section teaches you how to create custom missions tailored to your specific research questions.

### 5.1 Understanding the MissionManager Base Class

All missions inherit from the abstract `MissionManager` base class.

**Location:** `utility/base_classes_vectorized.py` lines 182-280

**Class Definition:**
```python
class MissionManager(ABC):
    """Base class for all mission managers (optimized with numpy)"""

    def __init__(self, user_id, xpc, dev_mode=False, num_wingmen=1):
        self.user_id = user_id
        self.xpc = xpc
        self.dev_mode = dev_mode
        self.targets = []
        self.mission_timer = 0
        self.wingman = None

        # Dataref path constants
        self.mission_status_dref = "custom/haato/mission_status"
        self.human_command_dref = "custom/haato/command_from_human"
        self.wingman_lat_dref = "custom/haato/wingman_lat"
        # ... (more datarefs)

    @abstractmethod
    def reset(self):
        """Initialize/reset mission state"""
        pass

    @abstractmethod
    def step(self, dt, met):
        """Execute one simulation timestep"""
        pass

    @abstractmethod
    def get_observation(self):
        """Return state representation for agent"""
        pass

    @abstractmethod
    def get_state(self):
        """Return comprehensive state for logging"""
        pass

    @abstractmethod
    def _check_mission_progress(self):
        """Determine if mission is complete"""
        pass
```

#### Abstract Methods You Must Implement

**1. `reset()`**
- **Purpose:** Initialize all mission state variables
- **When called:** Before mission starts, or when resetting
- **Responsibilities:**
  - Set mission timer to 0
  - Initialize/spawn targets
  - Reset datarefs to initial values
  - Create wingman agent instance
  - Set human/wingman start positions

**2. `step(dt, met)`**
- **Purpose:** Main mission loop, executed every frame (~30 FPS)
- **Parameters:**
  - `dt`: Delta time since last step (seconds)
  - `met`: Mission Elapsed Time (total seconds)
- **Returns:** `bool` - True if mission complete, False otherwise
- **Responsibilities:**
  - Read human aircraft state
  - Poll human commands/messages
  - Process mission logic (target detection, scoring)
  - Get agent observation
  - Execute agent action
  - Update mission progress
  - Check completion conditions

**3. `get_observation()`**
- **Purpose:** Format mission state for AI agent
- **Returns:** `numpy.ndarray` or `dict`
- **Content:** Mission time, positions, target states, messages
- **Used by:** Wingman agent's `act()` method

**4. `get_state()`**
- **Purpose:** Comprehensive state dictionary for logging/debugging
- **Returns:** `dict` with nested structure
- **Content:** All mission variables in human-readable format
- **Used by:** DataLogger, crash recovery, debugging

**5. `_check_mission_progress()`**
- **Purpose:** Determine if mission should end
- **Returns:** `Tuple[bool, str]` - (is_complete, reason)
- **Logic:** Check win/loss conditions, timeout

#### Utility Methods Provided

**Safe Dataref Access:**
```python
def safe_get_dref(self, path, default_value=0.0, param_name=''):
    """Safely read dataref with fallback value"""
    try:
        return self.xpc.getDREF(path)
    except Exception as e:
        if self.dev_mode:
            print(f"Warning: Failed to read {param_name or path}: {e}")
        return default_value
```

**Range Calculation:**
```python
def _calculate_range(self, pos1, pos2):
    """Calculate range, bearing, altitude difference between positions"""
    lat1, lon1, alt1 = pos1
    lat2, lon2, alt2 = pos2

    range_nm, bearing_deg, d_alt = GeoUtils.calculate_range_bearing_alt(pos1, pos2)
    return range_nm, bearing_deg, d_alt
```

**Pre-allocated Arrays (for vectorization):**
```python
# In __init__:
self.target_lats = np.zeros(8)   # Target latitudes
self.target_longs = np.zeros(8)  # Target longitudes
self.target_alts = np.zeros(8)   # Target altitudes

# Use for batch distance calculations:
distances = GeoUtils.haversine_distance(
    self.human_lat, self.human_long,
    self.target_lats, self.target_longs
)
```

### 5.2 Creating a Custom Mission: Step-by-Step

Let's create a simple search and rescue mission to demonstrate the process.

#### Example: Search and Rescue Mission

**Scenario:** Locate 5 missing hikers in mountainous terrain within 15 minutes.

**Step 1: Create Mission File**

**File:** `missions/search_rescue_mm.py`

```python
"""
Search and Rescue Mission
Locate and identify 5 missing hikers in mountainous terrain
"""
import numpy as np
from typing import Tuple
from utility.base_classes_vectorized import MissionManager, Target, GeoUtils


class SearchRescueMM(MissionManager):
    """Search and rescue mission manager"""

    def __init__(self, user_id, xpc, dev_mode=False, num_wingmen=1):
        super().__init__(user_id, xpc, dev_mode, num_wingmen)

        # Mission configuration
        self.max_mission_time = 900  # 15 minutes
        self.detection_range = 1.0   # 1 NM detection range
        self.rescue_time = 5.0       # 5 seconds to rescue

        # Area of responsibility
        self.aor_center = (47.7948, -121.1697)
        self.aor_radius = 15.0  # NM

        # Spawn positions
        self.human_spawn_lla = (47.71044, -121.34287, 1600.0)
        self.ai_spawn_lla = (47.71044, -121.32287, 2000.0)
        self.ai_start_hdg = 90
        self.ai_default_spd = 150

        # Human state
        self.human_lla = self.human_spawn_lla
        self.human_hdg = 90.0
        self.human_spd = 150.0

    def reset(self):
        """Initialize mission state"""
        self.mission_timer = 0

        # Reset datarefs
        self.xpc.sendDREF(self.mission_status_dref, 0.0)
        self.xpc.sendDREF(self.human_command_dref, 12.0)

        # Create targets (hikers)
        self.targets = []
        hiker_positions = [
            (47.85, -121.25, 1200),  # Hiker 0
            (47.78, -121.30, 1500),  # Hiker 1
            (47.82, -121.20, 1800),  # Hiker 2
            (47.90, -121.15, 1000),  # Hiker 3
            (47.75, -121.28, 1400),  # Hiker 4
        ]

        for i, (lat, lon, alt) in enumerate(hiker_positions):
            target = Target()
            target.lat = lat
            target.long = lon
            target.alt = alt
            target.type = "hiker"
            target.id = i
            target.spotted = False
            target.handled = False  # "rescued"
            target.human_in_range_time = 0.0
            target.wingman_in_range_time = 0.0
            self.targets.append(target)

        # Pre-allocate arrays for vectorization
        self.target_lats = np.array([t.lat for t in self.targets])
        self.target_longs = np.array([t.long for t in self.targets])
        self.target_alts = np.array([t.alt for t in self.targets])

        # Reset human position
        self.human_lla = self.human_spawn_lla

        # Create wingman
        from missions.search_rescue_mm import SearchRescueWingman
        self.wingman = SearchRescueWingman(
            self.xpc,
            self.ai_spawn_lla,
            self.ai_start_hdg,
            self.ai_default_spd,
            self
        )

        print(f"[SearchRescue] Mission initialized - Find 5 hikers in {self.max_mission_time/60:.0f} minutes")

    def step(self, dt, met):
        """Execute one mission timestep"""
        self.mission_timer = met

        # 1. Get human aircraft state
        self._get_human_lla()

        # 2. Process hiker detection and rescue
        self._process_hikers(dt)

        # 3. Poll human commands
        human_command = self.safe_get_dref(self.human_command_dref, 12.0)

        # 4. Get agent observation and action
        observation = self.get_observation()
        agent_action = self.wingman.act(observation, human_command)

        # 5. Execute agent action
        if agent_action['type'] == 'hsa':
            goal_hdg, goal_spd, goal_alt = agent_action['goal']

            # Update wingman position
            new_lat, new_lon = GeoUtils.project_position(
                self.wingman.lat, self.wingman.long,
                goal_hdg, goal_spd, dt
            )

            self.wingman.lat = new_lat
            self.wingman.long = new_lon
            self.wingman.alt = goal_alt
            self.wingman.hdg = goal_hdg
            self.wingman.spd = goal_spd

            # Send to X-Plane
            self.xpc.sendPOSI([new_lat, new_lon, goal_alt, 0, 0, goal_hdg, 1], 1)

        # 6. Update datarefs for visualization
        self.xpc.sendDREF(self.wingman_lat_dref, self.wingman.lat)
        self.xpc.sendDREF(self.wingman_long_dref, self.wingman.long)
        self.xpc.sendDREF(self.wingman_alt_dref, self.wingman.alt)
        self.xpc.sendDREF(self.mission_timer_dref, self.max_mission_time - met)

        # 7. Check mission progress
        complete, reason = self._check_mission_progress()

        if complete:
            if reason == 'all_rescued':
                self.xpc.sendDREF(self.mission_status_dref, 1.0)
                print(f"[SearchRescue] SUCCESS - All hikers rescued in {met:.1f}s")
            elif reason == 'timeout':
                self.xpc.sendDREF(self.mission_status_dref, -1.0)
                rescued = sum(1 for t in self.targets if t.handled)
                print(f"[SearchRescue] TIMEOUT - {rescued}/5 hikers rescued")

        return complete

    def _get_human_lla(self):
        """Read human aircraft state from X-Plane"""
        self.human_lla = (
            self.safe_get_dref('sim/flightmodel/position/latitude', self.human_lla[0]),
            self.safe_get_dref('sim/flightmodel/position/longitude', self.human_lla[1]),
            self.safe_get_dref('sim/flightmodel/position/elevation', self.human_lla[2])
        )
        self.human_hdg = self.safe_get_dref('sim/flightmodel/position/true_psi', self.human_hdg)

        vx = self.safe_get_dref('sim/flightmodel/position/local_vx', 0)
        vy = self.safe_get_dref('sim/flightmodel/position/local_vy', 0)
        vz = self.safe_get_dref('sim/flightmodel/position/local_vz', 0)
        self.human_spd = np.sqrt(vx**2 + vy**2 + vz**2) * 1.94384  # m/s to knots

    def _process_hikers(self, dt):
        """Process hiker detection and rescue"""
        # Vectorized distance calculation
        human_distances = GeoUtils.haversine_distance(
            self.human_lla[0], self.human_lla[1],
            self.target_lats, self.target_longs
        )

        wingman_distances = GeoUtils.haversine_distance(
            self.wingman.lat, self.wingman.long,
            self.target_lats, self.target_longs
        )

        for i, target in enumerate(self.targets):
            if target.handled:
                continue

            # Detection
            if human_distances[i] <= self.detection_range and not target.spotted:
                target.spotted = True
                print(f"[SearchRescue] Human detected hiker {i}")

            if wingman_distances[i] <= self.detection_range and not target.spotted:
                target.spotted = True
                print(f"[SearchRescue] Wingman detected hiker {i}")

            # Rescue (hover near hiker for 5 seconds)
            if human_distances[i] <= 0.5:  # Within 0.5 NM
                target.human_in_range_time += dt
                if target.human_in_range_time >= self.rescue_time:
                    target.handled = True
                    print(f"[SearchRescue] Human rescued hiker {i}")
            else:
                target.human_in_range_time = 0.0

            if wingman_distances[i] <= 0.5:
                target.wingman_in_range_time += dt
                if target.wingman_in_range_time >= self.rescue_time:
                    target.handled = True
                    print(f"[SearchRescue] Wingman rescued hiker {i}")
            else:
                target.wingman_in_range_time = 0.0

    def get_observation(self):
        """Create observation vector for agent"""
        obs = np.array([
            self.mission_timer,
            self.max_mission_time - self.mission_timer,  # time remaining
            self.human_lla[0], self.human_lla[1], self.human_lla[2],
            self.human_hdg, self.human_spd
        ])

        # Add target information (5 hikers × 8 values)
        for target in self.targets:
            target_data = np.array([
                target.lat, target.long, target.alt,
                1.0 if target.spotted else 0.0,
                1.0 if target.handled else 0.0,
                target.human_in_range_time,
                target.wingman_in_range_time,
                0.0  # Reserved
            ])
            obs = np.concatenate([obs, target_data])

        return obs

    def get_state(self):
        """Create comprehensive state dictionary"""
        return {
            'mission_time': self.mission_timer,
            'time_remaining': self.max_mission_time - self.mission_timer,
            'human': {
                'lat': self.human_lla[0],
                'lon': self.human_lla[1],
                'alt': self.human_lla[2],
                'hdg': self.human_hdg,
                'spd': self.human_spd
            },
            'wingman': {
                'lat': self.wingman.lat,
                'lon': self.wingman.long,
                'alt': self.wingman.alt,
                'hdg': self.wingman.hdg,
                'spd': self.wingman.spd
            },
            'hikers': [
                {
                    'id': t.id,
                    'lat': t.lat,
                    'lon': t.long,
                    'alt': t.alt,
                    'spotted': t.spotted,
                    'rescued': t.handled
                } for t in self.targets
            ],
            'hikers_spotted': sum(1 for t in self.targets if t.spotted),
            'hikers_rescued': sum(1 for t in self.targets if t.handled)
        }

    def _check_mission_progress(self) -> Tuple[bool, str]:
        """Check mission completion conditions"""
        # Success: All hikers rescued
        if all(t.handled for t in self.targets):
            return True, 'all_rescued'

        # Failure: Timeout
        if self.mission_timer >= self.max_mission_time:
            return True, 'timeout'

        # In progress
        return False, 'in_progress'
```

**Step 2: Create Wingman Agent**

Add to same file:

```python
from utility.base_classes_vectorized import Wingman


class SearchRescueWingman(Wingman):
    """Simple greedy wingman for search and rescue"""

    def __init__(self, xpc, start_lla, start_hdg, start_spd, mm):
        super().__init__(xpc, start_lla, start_hdg, start_spd, mm)
        self.max_speed = 200
        self.default_spd = 150
        self.current_target_id = None

    def act(self, observation, human_command):
        """Greedy policy: rescue closest unrescued hiker"""

        # Parse observation
        mission_time = observation[0]
        time_remaining = observation[1]
        human_lat = observation[2]
        human_lon = observation[3]
        human_alt = observation[4]

        # Extract hiker data
        num_hikers = 5
        hikers = []
        for i in range(num_hikers):
            idx = 7 + (i * 8)  # Offset past mission/human data
            hiker = {
                'id': i,
                'lat': observation[idx],
                'lon': observation[idx + 1],
                'alt': observation[idx + 2],
                'spotted': observation[idx + 3] > 0.5,
                'rescued': observation[idx + 4] > 0.5
            }
            hikers.append(hiker)

        # Check for human command
        if 0 <= human_command <= 4:
            # Go to specific hiker
            target_id = int(human_command)
            if not hikers[target_id]['rescued']:
                self.current_target_id = target_id
                goal_hsa = self._calc_hsa_to_target(observation, target_id)
                return {'type': 'hsa', 'goal': goal_hsa}

        elif human_command == 8.0:
            # Follow human
            goal_hsa = self._calc_hsa_to_human_intercept(observation)
            return {'type': 'hsa', 'goal': goal_hsa}

        # Autonomous: Find closest unrescued hiker
        unrescued_hikers = [h for h in hikers if not h['rescued']]

        if not unrescued_hikers:
            # All rescued, hold position
            return {
                'type': 'hsa',
                'goal': (self.hdg, self.default_spd * 0.8, self.alt)
            }

        # Calculate distances
        closest_hiker = None
        closest_dist = float('inf')

        for hiker in unrescued_hikers:
            dist = GeoUtils.haversine_distance(
                self.lat, self.long,
                hiker['lat'], hiker['lon']
            )
            if dist < closest_dist:
                closest_dist = dist
                closest_hiker = hiker

        # Fly to closest hiker
        self.current_target_id = closest_hiker['id']
        goal_hsa = self._calc_hsa_to_target(observation, closest_hiker['id'])

        return {'type': 'hsa', 'goal': goal_hsa}

    def _calc_hsa_to_target(self, observation, target_id):
        """Calculate heading/speed/altitude to reach target"""
        idx = 7 + (target_id * 8)
        target_lat = observation[idx]
        target_lon = observation[idx + 1]
        target_alt = observation[idx + 2]

        # Calculate bearing and distance
        bearing = GeoUtils.calculate_bearing(
            self.lat, self.long, target_lat, target_lon
        )
        distance = GeoUtils.haversine_distance(
            self.lat, self.long, target_lat, target_lon
        )

        # Speed based on distance
        if distance < 0.5:
            speed = self.default_spd * 0.6  # Slow approach
        else:
            speed = self.default_spd

        # Altitude: match target altitude
        goal_alt = target_alt + 100  # 100m above hiker

        return (bearing, speed, goal_alt)

    def _calc_hsa_to_human_intercept(self, observation):
        """Formation flying behind human"""
        human_lat = observation[2]
        human_lon = observation[3]
        human_alt = observation[4]
        human_hdg = observation[5]
        human_spd = observation[6]

        # Project human position 30 seconds ahead
        future_lat, future_lon = GeoUtils.project_position(
            human_lat, human_lon, human_hdg, human_spd, 30.0
        )

        # Calculate intercept
        bearing = GeoUtils.calculate_bearing(
            self.lat, self.long, future_lat, future_lon
        )

        return (bearing, self.default_spd * 1.2, human_alt)
```

**Step 3: Create Run Script**

**File:** `run_search_rescue.py`

```python
"""Run script for Search and Rescue mission"""
import sys
import argparse
from utility.XPlaneConnectX import XPlaneConnectX
from utility.data_logger import DataLogger
from utility.utility_classes import MissionTimer
from missions.search_rescue_mm import SearchRescueMM


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--subject_id', type=int, default=99)
    parser.add_argument('--dev_mode', action='store_true', default=True)
    args = parser.parse_args()

    print("\n" + "="*60)
    print("SEARCH AND RESCUE MISSION")
    print("="*60 + "\n")

    # Connect to X-Plane
    xpc = XPlaneConnectX(ip='127.0.0.1', port=49000)
    print("✓ X-Plane connection established")

    # Create mission manager
    mm = SearchRescueMM(
        user_id=args.subject_id,
        xpc=xpc,
        dev_mode=args.dev_mode
    )
    print("✓ Mission Manager created")

    # Create data logger
    logger = DataLogger(xpc, mm, args.subject_id, verbose=True, notes="search_rescue")
    print("✓ Data Logger initialized")

    # Create timer
    timer = MissionTimer()
    print("✓ Mission Timer created")

    # Reset mission
    mm.reset()
    print("✓ Mission reset complete\n")

    # Main loop
    done = False
    while not done:
        dt = timer.get_dt_and_wait()
        met = timer.get_mission_elapsed_time()

        done = mm.step(dt, met)

        # Log every second
        if int(met) % 1 == 0:
            logger.log_step_data()

    logger.finalize_log()
    logger.close()
    print("\n" + "="*60)
    print("MISSION COMPLETE")
    print("="*60 + "\n")


if __name__ == "__main__":
    main()
```

**Step 4: Test Your Mission**

```bash
python run_search_rescue.py --subject_id 99 --dev_mode
```

### 5.3 Configuring Mission Parameters

**Hard-Coded vs. JSON Configuration**

**Hard-Coded (in Python):**
- Pros: Simple, no file I/O, easy to debug
- Cons: Requires code changes, not user-friendly
- Best for: Development, mission logic parameters

**JSON Configuration:**
- Pros: Easy to modify, non-programmers can edit, supports multiple layouts
- Cons: Extra complexity, file management
- Best for: Target positions, experimental conditions

**Recommended Hybrid Approach:**
```python
def __init__(self, user_id, xpc, config_file=None, dev_mode=False):
    super().__init__(user_id, xpc, dev_mode)

    # Hard-coded mission parameters
    self.max_mission_time = 900
    self.detection_range = 1.5

    # Load target positions from JSON
    if config_file:
        self._load_config(config_file)
    else:
        self._use_default_targets()

def _load_config(self, config_file):
    import json
    with open(config_file, 'r') as f:
        config = json.load(f)

    self.targets = []
    for target_data in config['targets']:
        target = Target()
        target.lat = target_data['latitude']
        target.long = target_data['longitude']
        target.alt = target_data['altitude']
        target.type = target_data.get('type', 'unknown')
        self.targets.append(target)
```

### 5.4 Working with Datarefs

Datarefs are X-Plane's shared memory system for data exchange.

#### Complete Dataref Reference

See **Appendix 14.A** for the full list of 40+ custom HAATO datarefs.

#### Reading Datarefs

**Standard X-Plane Datarefs:**
```python
# Aircraft position
lat = self.xpc.getDREF('sim/flightmodel/position/latitude')
lon = self.xpc.getDREF('sim/flightmodel/position/longitude')
alt = self.xpc.getDREF('sim/flightmodel/position/elevation')  # meters MSL

# Aircraft attitude
hdg = self.xpc.getDREF('sim/flightmodel/position/true_psi')      # degrees
pitch = self.xpc.getDREF('sim/flightmodel/position/true_theta')  # degrees
roll = self.xpc.getDREF('sim/flightmodel/position/true_phi')     # degrees

# Aircraft velocity
vx = self.xpc.getDREF('sim/flightmodel/position/local_vx')  # m/s
vy = self.xpc.getDREF('sim/flightmodel/position/local_vy')  # m/s
vz = self.xpc.getDREF('sim/flightmodel/position/local_vz')  # m/s

# Simulation state
paused = self.xpc.getDREF('sim/time/paused')  # 0 or 1
```

**Custom HAATO Datarefs:**
```python
# Mission state
mission_status = self.xpc.getDREF('custom/haato/mission_status')
time_left = self.xpc.getDREF('custom/haato/mission_time_left')

# Human commands
command = self.xpc.getDREF('custom/haato/command_from_human')
response = self.xpc.getDREF('custom/haato/request_response')

# Fire/target status
fire0_status = self.xpc.getDREF('custom/haato/target0status')
fire0_class = self.xpc.getDREF('custom/haato/target0classification')
```

**Safe Reading with Fallback:**
```python
lat = self.safe_get_dref(
    'sim/flightmodel/position/latitude',
    default_value=47.71,
    param_name='latitude'
)
```

#### Writing Datarefs

```python
# Update mission status (0=running, 1=success, -1=failure)
self.xpc.sendDREF('custom/haato/mission_status', 1.0)

# Update wingman position (for visualization)
self.xpc.sendDREF('custom/haato/wingman_lat', self.wingman.lat)
self.xpc.sendDREF('custom/haato/wingman_long', self.wingman.long)
self.xpc.sendDREF('custom/haato/wingman_alt', self.wingman.alt)

# Update target status
self.xpc.sendDREF('custom/haato/target0status', 2.0)  # Complete
self.xpc.sendDREF('custom/haato/target0classification', 1.0)  # Moderate

# Send time remaining
self.xpc.sendDREF('custom/haato/mission_time_left', time_remaining)
```

#### Creating New Custom Datarefs

**Step 1: Define in Lua**

Edit `custom_datarefs.lua`:

```lua
-- Add your custom datarefs
custom_my_new_value = 0.0
dataref("custom/haato/my_new_value", "number", custom_my_new_value)

custom_my_array = {0, 0, 0, 0, 0}
dataref("custom/haato/my_array", "array[5]", custom_my_array)
```

**Step 2: Use in Python**

```python
# Write
self.xpc.sendDREF('custom/haato/my_new_value', 42.0)

# Read
value = self.xpc.getDREF('custom/haato/my_new_value')
print(f"My value: {value}")
```

**Step 3: Use in Lua Scripts**

```lua
-- Read in other Lua scripts
if custom_my_new_value > 10 then
    -- Do something
end

-- Write in Lua
custom_my_new_value = 99.0
```

### 5.5 Defining Custom Targets

Targets represent mission objectives (fires, people, packages, etc.).

#### Target Dataclass

**File:** `utility/base_classes_vectorized.py`

```python
class Target:
    """Base class for mission targets"""
    def __init__(self):
        self.lat = 0.0
        self.long = 0.0
        self.alt = 0.0
        self.type = "unknown"
        self.id = 0

        # Status tracking
        self.spotted = False
        self.handled = False
        self.progress = 0.0

        # Timing
        self.human_in_range_time = 0.0
        self.wingman_in_range_time = 0.0

        # Classification (for fires)
        self.classification = "unclassified"
```

#### Multi-Stage Target Status

**Example: Fire Progression**

```python
# Status values:
# 0.0 = Unspotted (not detected yet)
# 1.0 = Spotted (detected, not classified)
# 1.01-1.99 = Being classified or handled (progress)
# 2.0 = Complete (handled/extinguished)

def update_fire_status(self, fire, dt):
    if not fire.spotted:
        fire.status = 0.0
    elif fire.spotted and not fire.classification:
        fire.status = 1.0
    elif fire.classification and not fire.handled:
        # Progress from 1.0 to 2.0 based on suppression time
        fire.progress += dt / 10.0  # 10 seconds to complete
        fire.status = min(1.0 + fire.progress, 1.99)

        if fire.progress >= 1.0:
            fire.handled = True
            fire.status = 2.0
    else:
        fire.status = 2.0
```

#### Detection Logic

**Simple Range-Based:**
```python
def check_detection(self, human_pos, target):
    distance = GeoUtils.haversine_distance(
        human_pos[0], human_pos[1],
        target.lat, target.long
    )

    if distance <= self.detection_range:
        if not target.spotted:
            target.spotted = True
            print(f"Target {target.id} detected at range {distance:.2f} NM")
```

**Vectorized Multi-Target:**
```python
def check_all_detections(self, human_pos):
    # Calculate distances to all targets at once
    distances = GeoUtils.haversine_distance(
        human_pos[0], human_pos[1],
        self.target_lats, self.target_longs
    )

    # Find targets within range
    in_range = distances <= self.detection_range

    for i, target in enumerate(self.targets):
        if in_range[i] and not target.spotted:
            target.spotted = True
            print(f"Target {i} detected")
```

#### Handling/Completion Mechanics

**Timed Interaction:**
```python
def process_target_handling(self, target, human_in_range, wingman_in_range, dt):
    """Require sustained proximity to complete target"""

    # Human handling
    if human_in_range:
        target.human_in_range_time += dt
        if target.human_in_range_time >= self.required_handling_time:
            target.handled = True
            target.handled_by = "human"
    else:
        target.human_in_range_time = 0.0  # Reset if leaves

    # Wingman handling
    if wingman_in_range:
        target.wingman_in_range_time += dt
        if target.wingman_in_range_time >= self.required_handling_time:
            target.handled = True
            target.handled_by = "wingman"
    else:
        target.wingman_in_range_time = 0.0
```

**Altitude Requirement:**
```python
def check_suppression_conditions(self, aircraft_alt, target_alt, lateral_range):
    """Check if aircraft is in correct position for fire suppression"""

    # Altitude window: 7000 ft MSL ±500 ft
    required_alt = 7000 * 0.3048  # Convert ft to meters
    alt_tolerance = 500 * 0.3048

    alt_diff = abs(aircraft_alt - required_alt)
    correct_altitude = alt_diff <= alt_tolerance

    # Lateral range: within 0.5 NM
    correct_position = lateral_range <= 0.5

    return correct_altitude and correct_position
```

### 5.6 Multi-Mission Experimental Designs

Design experiments with multiple conditions using Latin square counterbalancing.

#### Latin Square Design

**Purpose:** Control for order effects by systematically varying condition order across participants.

**Example: 3 Conditions × 3 Trials**

```python
# In run_mission.py
CONFIGS = {
    1: [  # Participant 1
        {'initiative': 'low',    'layout': 1},
        {'initiative': 'medium', 'layout': 2},
        {'initiative': 'high',   'layout': 3}
    ],
    2: [  # Participant 2
        {'initiative': 'low',    'layout': 2},
        {'initiative': 'medium', 'layout': 3},
        {'initiative': 'high',   'layout': 1}
    ],
    3: [  # Participant 3
        {'initiative': 'low',    'layout': 3},
        {'initiative': 'medium', 'layout': 1},
        {'initiative': 'high',   'layout': 2}
    ],
    4: [  # Participant 4 (repeat square)
        {'initiative': 'medium', 'layout': 1},
        {'initiative': 'high',   'layout': 2},
        {'initiative': 'low',    'layout': 3}
    ],
    # ... continue pattern
}

def get_condition(subject_id, trial_number):
    """Get condition for this subject and trial"""
    conditions = CONFIGS.get(subject_id % 9, CONFIGS[1])  # Cycle every 9
    return conditions[trial_number - 1]
```

#### Between-Subjects vs. Within-Subjects

**Between-Subjects:**
Each participant experiences only one condition.

```python
def get_condition_between(subject_id):
    """Assign participant to single condition"""
    conditions = ['low', 'medium', 'high']
    return conditions[subject_id % 3]
```

**Within-Subjects:**
Each participant experiences all conditions (counterbalanced order).

```python
def get_conditions_within(subject_id):
    """Get all conditions for participant in counterbalanced order"""
    return CONFIGS.get(subject_id, CONFIGS[1])
```

#### Practice Trials

**Separate Practice Configurations:**
```python
PRACTICE_CONFIGS = [
    {'initiative': 'low',  'layout': 4},  # Practice 1
    {'initiative': 'high', 'layout': 5},  # Practice 2
]

def run_practice(subject_id):
    for i, config in enumerate(PRACTICE_CONFIGS):
        print(f"\nPractice Trial {i+1}")
        run_mission(subject_id, config, is_practice=True)
```

#### Randomization Strategies

**Randomize Target Positions:**
```python
import random

def randomize_fire_positions(base_positions, aor_center, aor_radius):
    """Randomize fire positions within AOR"""
    randomized = []

    for base_lat, base_lon, base_alt in base_positions:
        # Add random offset (±0.05 degrees ~= ±3 NM)
        offset_lat = random.uniform(-0.05, 0.05)
        offset_lon = random.uniform(-0.05, 0.05)

        new_lat = base_lat + offset_lat
        new_lon = base_lon + offset_lon

        randomized.append((new_lat, new_lon, base_alt))

    return randomized
```

**Randomize Target Types:**
```python
def randomize_fire_types(num_fires, ratio_severe=0.375):
    """Generate random fire type distribution"""
    num_severe = int(num_fires * ratio_severe)
    num_moderate = num_fires - num_severe

    types = ['severe'] * num_severe + ['moderate'] * num_moderate
    random.shuffle(types)

    return types
```

---

## 6. Creating Custom AI Agents

This section covers how to develop AI agents with custom behaviors and decision-making strategies.

### 6.1 Understanding the Wingman Base Class

**Location:** `utility/base_classes_vectorized.py` lines 283-510

**Class Structure:**
```python
class Wingman(ABC):
    """Base class for wingman agents"""

    def __init__(self, xpc, start_lla, start_hdg, start_spd, mm):
        self.xpc = xpc
        self.mm = mm  # Reference to MissionManager

        # Position and velocity
        self.lat, self.long, self.alt = start_lla
        self.hdg = start_hdg
        self.spd = start_spd

        # Configuration
        self.max_speed = 500  # knots
        self.default_spd = 200

    @abstractmethod
    def act(self, observation, messages):
        """Main decision-making method

        Args:
            observation: numpy array or dict with mission state
            messages: list of Message objects from human

        Returns:
            dict: {
                'type': 'hsa',  # heading/speed/altitude
                'goal': (heading, speed, altitude),
                'status': 'status_string',
                'help_request': fire_id or None,
                'messages': [outgoing Message objects]
            }
        """
        pass
```

#### Abstract Method: `act()`

**Must Return:**
Dictionary with action specification:

```python
{
    'type': 'hsa',  # Only type currently supported
    'goal': (heading, speed, altitude),  # Tuple[float, float, float]
    'status': 'Flying to fire 3',  # Optional status string
    'help_request': 3,  # Optional fire ID for help request (or None)
    'messages': []  # Optional list of Message objects
}
```

#### Navigation Helper Methods

The base class provides pre-built navigation functions:

**1. Fly to Target:**
```python
def _calc_hsa_to_target(self, target_lat, target_long, target_alt):
    """Calculate heading/speed/altitude to reach target

    Args:
        target_lat, target_long: Target position (degrees)
        target_alt: Target altitude (meters MSL)

    Returns:
        (heading, speed, altitude): Tuple of floats
    """
    # Calculate bearing to target
    bearing = GeoUtils.calculate_bearing(
        self.lat, self.long, target_lat, target_long
    )

    # Calculate distance
    distance = GeoUtils.haversine_distance(
        self.lat, self.long, target_lat, target_long
    )

    # Speed based on distance (slow down as approaching)
    if distance < 0.5:
        speed = self.default_spd * 0.6
    elif distance < 2.0:
        speed = self.default_spd * 0.8
    else:
        speed = self.default_spd

    # Altitude: match target
    goal_alt = target_alt

    return (bearing, speed, goal_alt)
```

**2. Join Formation with Human:**
```python
def _calc_hsa_to_human_intercept(self, human_lat, human_long, human_alt,
                                   human_hdg, human_spd):
    """Calculate intercept course to join formation

    Args:
        human_lat, human_long, human_alt: Human position
        human_hdg, human_spd: Human heading and speed

    Returns:
        (heading, speed, altitude): Intercept course
    """
    # Predict human position 30 seconds ahead
    future_lat, future_lon = GeoUtils.project_position(
        human_lat, human_long, human_hdg, human_spd, 30.0
    )

    # Calculate intercept bearing
    bearing = GeoUtils.calculate_bearing(
        self.lat, self.long, future_lat, future_lon
    )

    # Speed: slightly faster than human for intercept
    speed = min(human_spd * 1.2, self.max_speed)

    # Match human altitude
    goal_alt = human_alt

    return (bearing, speed, goal_alt)
```

**3. Circular Holding Pattern:**
```python
def _calc_hsa_holding_pattern(self, center_lat, center_long, center_alt,
                                radius=0.5):
    """Calculate heading/speed/altitude for circular holding

    Args:
        center_lat, center_long: Center of holding pattern
        center_alt: Holding altitude
        radius: Radius in nautical miles (default 0.5)

    Returns:
        (heading, speed, altitude): Holding pattern course
    """
    # Calculate current bearing from center
    bearing_from_center = GeoUtils.calculate_bearing(
        center_lat, center_long, self.lat, self.long
    )

    # Calculate distance from center
    distance = GeoUtils.haversine_distance(
        center_lat, center_long, self.lat, self.long
    )

    # If outside circle, fly toward center
    if distance > radius * 1.2:
        return self._calc_hsa_to_target(center_lat, center_long, center_alt)

    # If inside circle, fly tangent (perpendicular to radius)
    tangent_hdg = (bearing_from_center + 90) % 360

    # Standard rate turn: 3°/second
    speed = self.default_spd * 0.8

    return (tangent_hdg, speed, center_alt)
```

### 6.2 Agent Action Space

**Action Type:** HSA (Heading/Speed/Altitude)

**Action Dictionary Format:**
```python
{
    'type': 'hsa',
    'goal': (heading_deg, speed_knots, altitude_meters),
    'status': 'Human-readable status string',  # Optional
    'help_request': fire_id,  # Optional, None for no request
    'messages': []  # Optional, list of Message objects
}
```

**Field Constraints:**
- `heading_deg`: 0-360 degrees true heading
- `speed_knots`: 0-max_speed (typically 50-500)
- `altitude_meters`: 0-10,000+ (MSL, depends on aircraft)
- `status`: Any string (displayed to human)
- `help_request`: Integer 0-7 (fire ID) or None
- `messages`: List of Message objects or []

**Example Actions:**
```python
# Fly to fire
action = {
    'type': 'hsa',
    'goal': (270.0, 180.0, 2000.0),
    'status': 'Flying to fire 3'
}

# Request help
action = {
    'type': 'hsa',
    'goal': (90.0, 150.0, 1800.0),
    'status': 'Need help with fire 2',
    'help_request': 2
}

# Hold position
action = {
    'type': 'hsa',
    'goal': (self.hdg, 120.0, self.alt),
    'status': 'Holding position'
}
```

### 6.3 Policy-Based Decision Making

Implement decision logic using state machines, utility functions, or planning algorithms.

#### State Machine Approach

**Example: Simple 3-State Machine**

```python
class StateMachineWingman(Wingman):
    def __init__(self, xpc, start_lla, start_hdg, start_spd, mm):
        super().__init__(xpc, start_lla, start_hdg, start_spd, mm)
        self.state = 'SEARCH'
        self.current_target = None

    def act(self, observation, human_command):
        # State transitions
        if self.state == 'SEARCH':
            return self._search_state(observation, human_command)
        elif self.state == 'ENGAGE':
            return self._engage_state(observation, human_command)
        elif self.state == 'FOLLOW':
            return self._follow_state(observation, human_command)

    def _search_state(self, obs, cmd):
        """Search for unhandled fires"""
        # Find nearest unhandled fire
        target = self._find_nearest_fire(obs)

        if target:
            self.current_target = target
            self.state = 'ENGAGE'
            return self._engage_state(obs, cmd)
        else:
            # No fires, hold position
            return {
                'type': 'hsa',
                'goal': (self.hdg, 120.0, 2000.0),
                'status': 'Searching'
            }

    def _engage_state(self, obs, cmd):
        """Fly to and handle current target"""
        if self.current_target['handled']:
            # Target complete, return to search
            self.state = 'SEARCH'
            return self._search_state(obs, cmd)

        # Fly to target
        goal_hsa = self._calc_hsa_to_target(
            self.current_target['lat'],
            self.current_target['lon'],
            self.current_target['alt']
        )

        return {
            'type': 'hsa',
            'goal': goal_hsa,
            'status': f"Engaging fire {self.current_target['id']}"
        }

    def _follow_state(self, obs, cmd):
        """Follow human in formation"""
        human_lat = obs[2]
        human_lon = obs[3]
        human_alt = obs[4]
        human_hdg = obs[5]
        human_spd = obs[6]

        goal_hsa = self._calc_hsa_to_human_intercept(
            human_lat, human_lon, human_alt, human_hdg, human_spd
        )

        return {
            'type': 'hsa',
            'goal': goal_hsa,
            'status': 'Following human'
        }
```

#### Utility-Based Planning

**Example: Score-Based Target Selection**

```python
class UtilityWingman(Wingman):
    def __init__(self, xpc, start_lla, start_hdg, start_spd, mm):
        super().__init__(xpc, start_lla, start_hdg, start_spd, mm)

        # Utility weights
        self.weight_distance = -1.0  # Prefer closer
        self.weight_severity = 2.0   # Prefer severe fires
        self.weight_human_workload = 1.5  # Avoid human's target

    def act(self, observation, human_command):
        # Parse observation to get fires
        fires = self._parse_fires(observation)

        # Score each fire
        best_fire = None
        best_score = -float('inf')

        for fire in fires:
            if fire['handled']:
                continue

            score = self._calculate_utility(fire, observation)

            if score > best_score:
                best_score = score
                best_fire = fire

        if best_fire:
            goal_hsa = self._calc_hsa_to_target(
                best_fire['lat'], best_fire['lon'], best_fire['alt']
            )
            return {
                'type': 'hsa',
                'goal': goal_hsa,
                'status': f"Handling fire {best_fire['id']} (utility: {best_score:.2f})"
            }
        else:
            # No fires available
            return {'type': 'hsa', 'goal': (self.hdg, 120.0, self.alt)}

    def _calculate_utility(self, fire, obs):
        """Calculate utility score for selecting this fire"""
        score = 0

        # Distance factor (negative = prefer closer)
        distance = GeoUtils.haversine_distance(
            self.lat, self.long, fire['lat'], fire['lon']
        )
        score += self.weight_distance * distance

        # Severity factor
        if fire['classification'] == 'severe':
            score += self.weight_severity

        # Human workload factor (avoid if human is close)
        human_lat = obs[2]
        human_lon = obs[3]
        human_dist = GeoUtils.haversine_distance(
            human_lat, human_lon, fire['lat'], fire['lon']
        )

        if human_dist > 5.0:  # Human is far, we should handle
            score += self.weight_human_workload

        return score
```

#### Priority-Based Task Selection

**Example: Configurable Priorities (FireWatch Style)**

```python
class PriorityWingman(Wingman):
    def __init__(self, xpc, start_lla, start_hdg, start_spd, mm):
        super().__init__(xpc, start_lla, start_hdg, start_spd, mm)

        # Read priorities from datarefs
        self.priority_spot_unknown = 0  # Highest
        self.priority_handle_moderate = 1
        self.priority_handle_severe = 2

    def act(self, observation, human_command):
        # Update priorities from datarefs
        self._read_priorities()

        # Build task list with priorities
        tasks = []

        fires = self._parse_fires(observation)

        for fire in fires:
            if fire['handled']:
                continue

            # Determine task type and priority
            if not fire['spotted']:
                task = {
                    'type': 'spot',
                    'fire': fire,
                    'priority': self.priority_spot_unknown
                }
            elif fire['classification'] == 'moderate':
                task = {
                    'type': 'suppress',
                    'fire': fire,
                    'priority': self.priority_handle_moderate
                }
            elif fire['classification'] == 'severe':
                task = {
                    'type': 'suppress',
                    'fire': fire,
                    'priority': self.priority_handle_severe
                }

            tasks.append(task)

        # Sort by priority (lower number = higher priority)
        tasks.sort(key=lambda t: t['priority'])

        if tasks:
            # Execute highest priority task
            task = tasks[0]
            goal_hsa = self._calc_hsa_to_target(
                task['fire']['lat'],
                task['fire']['lon'],
                task['fire']['alt']
            )
            return {
                'type': 'hsa',
                'goal': goal_hsa,
                'status': f"{task['type']} fire {task['fire']['id']}"
            }
        else:
            # No tasks
            return {'type': 'hsa', 'goal': (self.hdg, 120.0, self.alt)}

    def _read_priorities(self):
        """Read priority configuration from datarefs"""
        self.priority_spot_unknown = self.xpc.getDREF(
            'custom/haato/taskpriority_spotunknown'
        )
        self.priority_handle_moderate = self.xpc.getDREF(
            'custom/haato/taskpriority_handlemoderate'
        )
        self.priority_handle_severe = self.xpc.getDREF(
            'custom/haato/taskpriority_handlesevere'
        )
```

### 6.4 Handling Human Commands

Agents should respond appropriately to human commands.

**Command Codes:**
- 0-7: Go to specific fire
- 8: Follow human
- 12: No command / Hold position

**Implementation:**
```python
def act(self, observation, human_command):
    # Priority 1: Obey explicit commands
    if 0 <= human_command <= 7:
        # Commanded to specific fire
        fire_id = int(human_command)
        fires = self._parse_fires(observation)

        if fire_id < len(fires) and not fires[fire_id]['handled']:
            goal_hsa = self._calc_hsa_to_target(
                fires[fire_id]['lat'],
                fires[fire_id]['lon'],
                fires[fire_id]['alt']
            )
            return {
                'type': 'hsa',
                'goal': goal_hsa,
                'status': f"Commanded to fire {fire_id}"
            }

    elif human_command == 8.0:
        # Follow human
        return self._follow_human(observation)

    # Priority 2: Autonomous behavior (if no command)
    return self._autonomous_policy(observation)

def _follow_human(self, observation):
    """Execute follow-me command"""
    human_lat = observation[2]
    human_lon = observation[3]
    human_alt = observation[4]
    human_hdg = observation[5]
    human_spd = observation[6]

    goal_hsa = self._calc_hsa_to_human_intercept(
        human_lat, human_lon, human_alt, human_hdg, human_spd
    )

    return {
        'type': 'hsa',
        'goal': goal_hsa,
        'status': 'Following human'
    }
```

### 6.5 Responding to Help Requests

**Help Request Mechanism:**

Human can request help via `custom/haato/request_response` dataref:
- 1.0 = Accept request
- -1.0 = Reject request
- 0.0 = No response

**Implementation:**
```python
def act(self, observation, human_command):
    # Check if we have an active help request
    if self.pending_help_request:
        response = self.xpc.getDREF('custom/haato/request_response')

        if response == 1.0:
            # Human accepted - they will handle it
            self.pending_help_request = None
            # Move to next task
            return self._autonomous_policy(observation)

        elif response == -1.0:
            # Human rejected - we must handle it ourselves
            fire_id = self.pending_help_request
            self.pending_help_request = None
            # Continue handling fire
            return self._handle_fire(fire_id, observation)

    # Normal operation
    return self._autonomous_policy(observation)

def _request_help(self, fire_id):
    """Request human assistance with specific fire"""
    self.pending_help_request = fire_id

    # Set dataref to trigger request
    self.xpc.sendDREF('custom/haato/help_request', float(fire_id))
    self.xpc.sendDREF('custom/haato/agent_id_request', float(fire_id))

    print(f"[Wingman] Requesting help with fire {fire_id}")
```

### 6.6 Team Coordination Strategies

Implement strategies to avoid conflicts and maximize team efficiency.

**Strategy 1: Spatial Partitioning**

```python
def _select_fire_with_spatial_partitioning(self, observation):
    """Divide AOR into human and wingman zones"""
    fires = self._parse_fires(observation)
    human_lat = observation[2]
    human_lon = observation[3]

    # Find centerpoint between human and wingman
    center_lat = (human_lat + self.lat) / 2
    center_lon = (human_lon + self.long) / 2

    # Select fires on wingman's side
    wingman_fires = []
    for fire in fires:
        if fire['handled']:
            continue

        # Check which side of centerpoint
        dist_to_wingman = GeoUtils.haversine_distance(
            self.lat, self.long, fire['lat'], fire['lon']
        )
        dist_to_human = GeoUtils.haversine_distance(
            human_lat, human_lon, fire['lat'], fire['lon']
        )

        if dist_to_wingman < dist_to_human:
            wingman_fires.append(fire)

    # Select from wingman's fires
    if wingman_fires:
        return min(wingman_fires, key=lambda f: GeoUtils.haversine_distance(
            self.lat, self.long, f['lat'], f['lon']
        ))
    else:
        # No fires on our side, help with human's side
        return self._find_nearest_fire(fires)
```

**Strategy 2: Deconfliction (Avoid Same Target)**

```python
def _avoid_human_target(self, observation):
    """Don't select fires human is currently handling"""
    fires = self._parse_fires(observation)
    human_lat = observation[2]
    human_lon = observation[3]

    # Determine which fire human is targeting
    human_target_id = None
    closest_dist = float('inf')

    for fire in fires:
        if fire['handled']:
            continue

        dist = GeoUtils.haversine_distance(
            human_lat, human_lon, fire['lat'], fire['lon']
        )

        if dist < closest_dist:
            closest_dist = dist
            if dist < 2.0:  # Human within 2 NM = likely targeting
                human_target_id = fire['id']

    # Select fire NOT being handled by human
    available_fires = [f for f in fires
                       if not f['handled'] and f['id'] != human_target_id]

    if available_fires:
        return self._find_nearest_fire(available_fires)
    else:
        # All fires being handled by human, hold position
        return None
```

**Strategy 3: Workload Balancing**

```python
def _balance_workload(self, observation):
    """Ensure even distribution of work"""
    fires = self._parse_fires(observation)

    # Count fires handled by each agent
    human_handled = sum(1 for f in fires if f.get('handled_by') == 'human')
    wingman_handled = sum(1 for f in fires if f.get('handled_by') == 'wingman')

    # If human has handled more, be more proactive
    if wingman_handled < human_handled:
        # Take any available fire
        return self._find_nearest_fire([f for f in fires if not f['handled']])
    else:
        # Human needs help, be selective
        return self._find_nearest_severe_fire(fires)
```

---

## 7. GUI & Visualization Customization

HAATO uses XPPython3 to draw custom overlays on X-Plane's G1000 displays.

### 7.1 Understanding the G1000 Plugin Architecture

**Location:** `Copy to X-Plane directory/Resources/plugins/PythonPlugins/PI_gui_refactor.py`

**XPPython3 Plugin Structure:**
```python
class PythonInterface:
    def __init__(self):
        self.Name = "HAATO G1000 Overlay"
        self.Sig = "haato.g1000.overlay"
        self.Desc = "Custom G1000 displays for HAATO missions"

    def XPluginStart(self):
        """Called when plugin is loaded"""
        # Initialize resources, load images, create dataref subscriptions
        return self.Name, self.Sig, self.Desc

    def XPluginEnable(self):
        """Called when plugin is enabled"""
        # Register drawing callbacks
        self.draw_callback_id = XPLMRegisterDrawCallback(
            self.draw_callback,
            xplm_Phase_Window,  # Draw in window phase
            0,  # After sim objects
            0   # Refcon
        )
        return 1

    def XPluginDisable(self):
        """Called when plugin is disabled"""
        # Unregister callbacks
        XPLMUnregisterDrawCallback(self.draw_callback_id)

    def XPluginStop(self):
        """Called when plugin is unloaded"""
        # Clean up resources
        pass

    def draw_callback(self, inPhase, inIsBefore, inRefcon):
        """Main drawing function called every frame"""
        # Read datarefs
        # Calculate screen positions
        # Draw graphics
        return 1  # Continue drawing
```

**Key XPPython3 Functions:**
- `XPLMRegisterDrawCallback()`: Register drawing function
- `XPLMDrawString()`: Draw text
- `XPLMDrawTranslucentDarkBox()`: Draw semi-transparent box
- `XPLMDrawTexture()`: Draw image/icon
- `XPLMGetScreenSize()`: Get screen resolution
- `XPLMGetWindowGeometry()`: Get window position
- `XPLMGetDataf()` / `XPLMSetDataf()`: Read/write datarefs

### 7.2 Customizing the MFD Map Display

The Multi-Function Display (MFD) shows the mission map with targets and aircraft.

#### GridSystem: Lat/Lon → Pixel Conversion

**File:** `Copy to X-Plane directory/Resources/plugins/PythonPlugins/classes/GridSystem.py`

```python
class GridSystem:
    """Convert between geographic coordinates and screen pixels"""

    def __init__(self, center_lat, center_lon, screen_width, screen_height,
                 scale_nm_per_pixel=0.05):
        self.center_lat = center_lat
        self.center_lon = center_lon
        self.screen_width = screen_width
        self.screen_height = screen_height
        self.scale = scale_nm_per_pixel

    def latlon_to_screen(self, lat, lon):
        """Convert lat/lon to screen x, y coordinates"""
        # Calculate distance from center in NM
        dx_nm = self._lon_to_nm(lon - self.center_lon, self.center_lat)
        dy_nm = self._lat_to_nm(lat - self.center_lat)

        # Convert NM to pixels
        x = (self.screen_width / 2) + (dx_nm / self.scale)
        y = (self.screen_height / 2) - (dy_nm / self.scale)  # Invert Y

        return int(x), int(y)

    def _lat_to_nm(self, lat_degrees):
        """Convert latitude degrees to nautical miles"""
        return lat_degrees * 60.0

    def _lon_to_nm(self, lon_degrees, at_latitude):
        """Convert longitude degrees to NM (varies with latitude)"""
        import math
        return lon_degrees * 60.0 * math.cos(math.radians(at_latitude))
```

#### Drawing Targets with Custom Icons

**Example: Draw Fire Icons**

```python
def draw_mfd_map(self):
    """Draw map on G1000 MFD"""

    # Get MFD screen coordinates (right G1000)
    mfd_left = 1920  # Example for dual monitor setup
    mfd_top = 0
    mfd_width = 1024
    mfd_height = 768

    # Create grid system
    grid = GridSystem(
        center_lat=47.7948,
        center_lon=-121.1697,
        screen_width=mfd_width,
        screen_height=mfd_height,
        scale_nm_per_pixel=0.05  # 0.05 NM per pixel
    )

    # Draw fires
    for i in range(8):
        # Read fire data from datarefs
        fire_lat = XPLMGetDataf(self.fire_lat_drefs[i])
        fire_lon = XPLMGetDataf(self.fire_lon_drefs[i])
        fire_status = XPLMGetDataf(self.fire_status_drefs[i])
        fire_class = XPLMGetDataf(self.fire_class_drefs[i])

        # Convert to screen coordinates
        x, y = grid.latlon_to_screen(fire_lat, fire_lon)

        # Choose color based on status
        if fire_status >= 2.0:
            color = (0.0, 1.0, 0.0)  # Green = complete
        elif fire_status >= 1.0:
            if fire_class == 2.0:
                color = (1.0, 0.5, 0.0)  # Orange = severe
            else:
                color = (1.0, 1.0, 0.0)  # Yellow = moderate
        else:
            color = (1.0, 0.0, 0.0)  # Red = unspotted (hidden until detected)

        # Draw fire icon
        if fire_status > 0.0:  # Only show if spotted
            self._draw_fire_icon(mfd_left + x, mfd_top + y, color)

    # Draw aircraft positions
    self._draw_aircraft_icon(grid, mfd_left, mfd_top, "human")
    self._draw_aircraft_icon(grid, mfd_left, mfd_top, "wingman")

def _draw_fire_icon(self, x, y, color):
    """Draw fire triangle icon"""
    # Draw filled triangle
    XPLMSetGraphicsState(
        0,  # No fog
        0,  # No textures
        0,  # No lighting
        0,  # No alpha testing
        1,  # Alpha blending
        0,  # No depth testing
        0   # No depth writing
    )

    glColor3f(*color)
    glBegin(GL_TRIANGLES)
    glVertex2f(x, y + 15)      # Top point
    glVertex2f(x - 10, y - 10)  # Bottom left
    glVertex2f(x + 10, y - 10)  # Bottom right
    glEnd()

    # Draw outline
    glColor3f(0, 0, 0)
    glLineWidth(2)
    glBegin(GL_LINE_LOOP)
    glVertex2f(x, y + 15)
    glVertex2f(x - 10, y - 10)
    glVertex2f(x + 10, y - 10)
    glEnd()
```

#### Route and Waypoint Visualization

**Example: Draw Wingman's Planned Route**

```python
def draw_wingman_route(self, grid, mfd_left, mfd_top):
    """Draw wingman's planned route to target"""

    # Read wingman current position
    wm_lat = XPLMGetDataf(self.wingman_lat_dref)
    wm_lon = XPLMGetDataf(self.wingman_long_dref)

    # Read wingman goal position (from current target)
    wm_goal_lat = XPLMGetDataf(self.wingman_goal_lat_dref)
    wm_goal_lon = XPLMGetDataf(self.wingman_goal_lon_dref)

    # Convert to screen coordinates
    x1, y1 = grid.latlon_to_screen(wm_lat, wm_lon)
    x2, y2 = grid.latlon_to_screen(wm_goal_lat, wm_goal_lon)

    # Draw dashed line
    glColor3f(0.0, 0.5, 1.0)  # Blue
    glLineWidth(2)
    glLineStipple(1, 0xF0F0)  # Dashed pattern
    glEnable(GL_LINE_STIPPLE)

    glBegin(GL_LINES)
    glVertex2f(mfd_left + x1, mfd_top + y1)
    glVertex2f(mfd_left + x2, mfd_top + y2)
    glEnd()

    glDisable(GL_LINE_STIPPLE)
```

#### Range Circles and Navigation Aids

```python
def draw_range_circles(self, grid, mfd_left, mfd_top, center_lat, center_lon):
    """Draw range circles around center point"""

    ranges = [5.0, 10.0, 15.0, 20.0]  # NM
    colors = [(0.3, 0.3, 0.3), (0.4, 0.4, 0.4), (0.5, 0.5, 0.5), (0.6, 0.6, 0.6)]

    for range_nm, color in zip(ranges, colors):
        self._draw_circle(grid, mfd_left, mfd_top, center_lat, center_lon,
                          range_nm, color)

def _draw_circle(self, grid, mfd_left, mfd_top, center_lat, center_lon,
                 radius_nm, color):
    """Draw circle with given radius"""
    import math

    num_segments = 64
    glColor3f(*color)
    glLineWidth(1)
    glBegin(GL_LINE_LOOP)

    for i in range(num_segments):
        angle = 2.0 * math.pi * i / num_segments

        # Calculate point on circle (approximate)
        lat_offset = (radius_nm / 60.0) * math.sin(angle)
        lon_offset = (radius_nm / 60.0) * math.cos(angle) / math.cos(math.radians(center_lat))

        point_lat = center_lat + lat_offset
        point_lon = center_lon + lon_offset

        x, y = grid.latlon_to_screen(point_lat, point_lon)
        glVertex2f(mfd_left + x, mfd_top + y)

    glEnd()
```

### 7.3 Customizing the PFD Classification Interface

The Primary Flight Display (PFD) shows fire classification options.

**Example: Classification Button Grid**

```python
def draw_pfd_classification(self):
    """Draw classification interface on PFD"""

    # Check if human is in range of fire
    in_range_fire_id = XPLMGetDataf(self.human_in_range_dref)

    if in_range_fire_id >= 0 and in_range_fire_id <= 7:
        # Human is in range, show classification UI
        fire_id = int(in_range_fire_id)

        # PFD screen coordinates (left G1000)
        pfd_left = 0
        pfd_top = 0
        pfd_width = 1024
        pfd_height = 768

        # Draw background box
        box_left = pfd_left + 50
        box_top = pfd_top + 600
        box_width = 900
        box_height = 150

        XPLMDrawTranslucentDarkBox(
            box_left, box_top,
            box_left + box_width, box_top - box_height
        )

        # Draw title
        title = f"CLASSIFY FIRE #{fire_id}"
        XPLMDrawString(
            [1.0, 1.0, 1.0], box_left + 350, box_top - 30,
            title, None, xplmFont_Proportional
        )

        # Draw fire image
        if self.fire_images[fire_id]:
            self._draw_fire_image(
                box_left + 50, box_top - 50,
                200, 150, fire_id
            )

        # Draw classification buttons
        self._draw_button(
            box_left + 300, box_top - 100,
            200, 50, "MODERATE", [0.2, 0.8, 0.2]
        )

        self._draw_button(
            box_left + 550, box_top - 100,
            200, 50, "SEVERE", [0.8, 0.2, 0.2]
        )

        # Draw instruction
        instruction = "Or pull trigger for auto-classify"
        XPLMDrawString(
            [0.7, 0.7, 0.7], box_left + 300, box_top - 140,
            instruction, None, xplmFont_Basic
        )

def _draw_button(self, x, y, width, height, text, color):
    """Draw clickable button"""

    # Draw button background
    glColor3f(*color)
    glBegin(GL_QUADS)
    glVertex2f(x, y)
    glVertex2f(x + width, y)
    glVertex2f(x + width, y - height)
    glVertex2f(x, y - height)
    glEnd()

    # Draw button border
    glColor3f(0, 0, 0)
    glLineWidth(2)
    glBegin(GL_LINE_LOOP)
    glVertex2f(x, y)
    glVertex2f(x + width, y)
    glVertex2f(x + width, y - height)
    glVertex2f(x, y - height)
    glEnd()

    # Draw text (centered)
    text_x = x + (width / 2) - (len(text) * 4)
    text_y = y - (height / 2) - 5
    XPLMDrawString([1, 1, 1], text_x, text_y, text, None, xplmFont_Proportional)
```

#### Human Input Capture

**Mouse Click Detection:**

```python
def XPluginReceiveMessage(self, inFromWho, inMessage, inParam):
    """Handle messages from X-Plane"""

    if inMessage == XPLM_MSG_MOUSE_CLICK:
        # Get mouse position
        mouse_x, mouse_y = XPLMGetMouseLocation()

        # Check if clicked on moderate button
        if self._is_point_in_button(mouse_x, mouse_y, moderate_button_rect):
            # Set classification dataref
            fire_id = int(XPLMGetDataf(self.human_in_range_dref))
            XPLMSetDataf(self.fire_class_drefs[fire_id], 1.0)  # Moderate
            XPLMSetDataf(self.id_request_response_dref, 1.0)  # Auto
            print(f"Classified fire {fire_id} as moderate")

        # Check severe button
        elif self._is_point_in_button(mouse_x, mouse_y, severe_button_rect):
            fire_id = int(XPLMGetDataf(self.human_in_range_dref))
            XPLMSetDataf(self.fire_class_drefs[fire_id], 2.0)  # Severe
            XPLMSetDataf(self.id_request_response_dref, 2.0)
            print(f"Classified fire {fire_id} as severe")

def _is_point_in_button(self, px, py, button_rect):
    """Check if point is inside button rectangle"""
    bx, by, bw, bh = button_rect
    return (bx <= px <= bx + bw) and (by - bh <= py <= by)
```

### 7.4 Adding New Visual Elements

#### Drawing Text

```python
def draw_status_text(self, x, y, status_string, color=[1, 1, 1]):
    """Draw status text at position"""
    XPLMDrawString(
        color,      # RGB color
        x, y,       # Position
        status_string,  # Text
        None,       # Word wrap width (None = no wrap)
        xplmFont_Proportional  # Font (or xplmFont_Basic)
    )
```

#### Drawing Lines and Shapes

```python
def draw_progress_bar(self, x, y, width, height, progress):
    """Draw progress bar (0.0 to 1.0)"""

    # Background
    glColor3f(0.2, 0.2, 0.2)
    glBegin(GL_QUADS)
    glVertex2f(x, y)
    glVertex2f(x + width, y)
    glVertex2f(x + width, y - height)
    glVertex2f(x, y - height)
    glEnd()

    # Foreground (progress)
    fill_width = width * min(max(progress, 0.0), 1.0)
    color = self._get_progress_color(progress)
    glColor3f(*color)
    glBegin(GL_QUADS)
    glVertex2f(x, y)
    glVertex2f(x + fill_width, y)
    glVertex2f(x + fill_width, y - height)
    glVertex2f(x, y - height)
    glEnd()

    # Border
    glColor3f(0, 0, 0)
    glLineWidth(2)
    glBegin(GL_LINE_LOOP)
    glVertex2f(x, y)
    glVertex2f(x + width, y)
    glVertex2f(x + width, y - height)
    glVertex2f(x, y - height)
    glEnd()

def _get_progress_color(self, progress):
    """Color gradient from red to green"""
    if progress < 0.5:
        return (1.0, progress * 2, 0.0)  # Red to yellow
    else:
        return ((1.0 - progress) * 2, 1.0, 0.0)  # Yellow to green
```

#### Loading and Rendering Custom Images

```python
def load_fire_images(self):
    """Load fire images from disk"""
    import os
    from PIL import Image

    self.fire_images = {}
    image_dir = "Resources/plugins/HAATO_assets/images/"

    for i in range(8):
        # Load image
        img_path = os.path.join(image_dir, f"fire_{i}.jpg")
        if os.path.exists(img_path):
            img = Image.open(img_path)
            # Convert to OpenGL texture
            self.fire_images[i] = self._create_texture(img)

def _create_texture(self, pil_image):
    """Convert PIL image to OpenGL texture"""
    img_data = pil_image.tobytes("raw", "RGB", 0, -1)
    width, height = pil_image.size

    # Generate texture ID
    texture_id = glGenTextures(1)
    glBindTexture(GL_TEXTURE_2D, texture_id)

    # Set texture parameters
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)

    # Upload texture data
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGB, width, height, 0,
                 GL_RGB, GL_UNSIGNED_BYTE, img_data)

    return texture_id

def _draw_fire_image(self, x, y, width, height, fire_id):
    """Draw fire image texture"""
    texture_id = self.fire_images.get(fire_id)
    if not texture_id:
        return

    XPLMSetGraphicsState(
        0,  # No fog
        1,  # Texture enabled
        0,  # No lighting
        0,  # No alpha testing
        1,  # Alpha blending
        0,  # No depth testing
        0   # No depth writing
    )

    glBindTexture(GL_TEXTURE_2D, texture_id)

    glBegin(GL_QUADS)
    glTexCoord2f(0, 1); glVertex2f(x, y)
    glTexCoord2f(1, 1); glVertex2f(x + width, y)
    glTexCoord2f(1, 0); glVertex2f(x + width, y - height)
    glTexCoord2f(0, 0); glVertex2f(x, y - height)
    glEnd()
```

### 7.5 Performance Considerations

**Frame Rate Impact:**
- Drawing is called every frame (~60 FPS in X-Plane)
- Keep draw calls minimal
- Cache expensive calculations

**Optimization Tips:**

```python
def draw_callback(self, inPhase, inIsBefore, inRefcon):
    """Optimized drawing function"""

    # Only draw every Nth frame to reduce CPU load
    self.frame_counter += 1
    if self.frame_counter % 3 != 0:  # Draw every 3rd frame
        return 1

    # Read datarefs once per frame
    mission_status = XPLMGetDataf(self.mission_status_dref)

    # Skip drawing if mission not active
    if mission_status != 0.0:
        return 1

    # Cache screen size (don't query every frame)
    if self.frame_counter % 60 == 0:  # Update once per second
        self.screen_width, self.screen_height = XPLMGetScreenSize()

    # Draw UI elements
    self.draw_mfd_map()
    self.draw_pfd_classification()

    return 1
```

---

## 8. Communication & Messaging

### 8.1 Message Queue System

**Location:** `utility/message_queue.py`

**Message Structure:**
```python
@dataclass
class Message:
    """Structured message for human-AI communication"""
    type: str        # 'command', 'request', 'response', 'status'
    sender: str      # 'human' or 'wingman'
    recipient: str   # 'human' or 'wingman'
    content: str     # Message content
    timestamp: float # Mission elapsed time
    delivered: bool = False
```

**Message Queue API:**

```python
from utility.message_queue import MessageQueue, Message

# Create queue
msg_queue = MessageQueue()

# Add message
msg = Message(
    type='command',
    sender='human',
    recipient='wingman',
    content='go_to_fire_3',
    timestamp=45.7
)
msg_queue.add_message(msg)

# Retrieve messages for recipient
messages = msg_queue.get_messages_for_recipient('wingman', mark_delivered=True)

for msg in messages:
    print(f"[{msg.timestamp:.1f}s] {msg.sender} → {msg.recipient}: {msg.content}")

# Check for undelivered messages
has_messages = msg_queue.has_undelivered_messages('wingman')
```

**Message Types:**

**1. Commands (Human → Wingman):**
```python
command_msg = Message(
    type='command',
    sender='human',
    recipient='wingman',
    content='go_to_fire_5',
    timestamp=met
)
```

**2. Requests (Wingman → Human):**
```python
request_msg = Message(
    type='request',
    sender='wingman',
    recipient='human',
    content='help_with_fire_2',
    timestamp=met
)
```

**3. Responses (Human → Wingman):**
```python
response_msg = Message(
    type='response',
    sender='human',
    recipient='wingman',
    content='accept_request_fire_2',
    timestamp=met
)
```

**4. Status Updates (Wingman → Human):**
```python
status_msg = Message(
    type='status',
    sender='wingman',
    recipient='human',
    content='suppressing_fire_3',
    timestamp=met
)
```

### 8.2 Human Input Methods

#### Joystick/Yoke Configuration

**Configuration Files:**
```
utility/joystick_configs/
├── logitech_extreme_3d_pro.json
├── thrustmaster_t16000m.json
└── microsoft_sidewinder.json
```

**JSON Format:**
```json
{
  "name": "Logitech Extreme 3D Pro",
  "trigger_button": 0,
  "classification_button": 1,
  "command_buttons": {
    "fire_0": 2,
    "fire_1": 3,
    "fire_2": 4,
    "fire_3": 5,
    "fire_4": 6,
    "fire_5": 7,
    "fire_6": 8,
    "fire_7": 9,
    "follow_me": 10,
    "hold_position": 11
  }
}
```

**Reading Joystick Input:**
```python
def check_joystick_input(self):
    """Check for joystick button presses"""

    # Read trigger button state
    trigger = self.xpc.getDREF('sim/joystick/fire_key_is_down')

    if trigger == 1 and not self.trigger_was_pressed:
        # Trigger pressed
        self._handle_trigger_press()
        self.trigger_was_pressed = True
    elif trigger == 0:
        self.trigger_was_pressed = False

    # Read custom button datarefs
    for button_id, command in self.button_mapping.items():
        button_state = self.xpc.getDREF(f'sim/joystick/button_values[{button_id}]')
        if button_state == 1:
            self._handle_command(command)
```

#### G1000 Touch Interface

See Section 7.3 for touch button implementation.

#### Voice Recognition (Experimental)

**Setup:**
```bash
pip install SpeechRecognition pyaudio
```

**Implementation:**
```python
import speech_recognition as sr

def listen_for_voice_command(self, xpc):
    """Listen for voice commands"""
    recognizer = sr.Recognizer()
    microphone = sr.Microphone()

    try:
        with microphone as source:
            # Listen for audio
            audio = recognizer.listen(source, timeout=2, phrase_time_limit=5)

            # Convert to text
            command_text = recognizer.recognize_google(audio).lower()

            print(f"Voice command: {command_text}")

            # Parse command
            if "status" in command_text and "wingman" in command_text:
                xpc.sendDREF("custom/haato/human_requests_status", 1.0)

            elif "fire" in command_text:
                # Extract fire number
                for i in range(8):
                    if str(i) in command_text or self.number_words[i] in command_text:
                        xpc.sendDREF("custom/haato/command_from_human", float(i))
                        break

            elif "follow" in command_text:
                xpc.sendDREF("custom/haato/command_from_human", 8.0)

            elif "hold" in command_text or "wait" in command_text:
                xpc.sendDREF("custom/haato/command_from_human", 12.0)

    except sr.WaitTimeoutError:
        pass  # No speech detected
    except sr.UnknownValueError:
        print("Could not understand audio")
    except sr.RequestError as e:
        print(f"Speech recognition error: {e}")

# Number word mapping
number_words = {
    0: "zero", 1: "one", 2: "two", 3: "three",
    4: "four", 5: "five", 6: "six", 7: "seven"
}
```

**Voice Recognition Thread:**
```python
import threading

def start_voice_recognition_thread(xpc):
    """Run voice recognition in background thread"""

    def voice_loop():
        while True:
            listen_for_voice_command(xpc)
            time.sleep(0.1)

    thread = threading.Thread(target=voice_loop, daemon=True)
    thread.start()
    return thread
```

### 8.3 Wingman Output Channels

#### Status Messages via Datarefs

```python
def send_status_message(self, status_code):
    """Send encoded status message

    Status codes:
    0-7: Flying to fire N
    10-17: Suppressing fire N
    20-27: Classifying fire N
    30: Following human
    40: Holding position
    50: Searching
    99: Unknown/idle
    """
    self.xpc.sendDREF('custom/haato/wingman_status', float(status_code))

# Examples:
send_status_message(3)   # Flying to fire 3
send_status_message(12)  # Suppressing fire 2
send_status_message(30)  # Following human
```

#### Help Request Mechanism

```python
def request_help_with_fire(self, fire_id):
    """Request human assistance with fire"""

    # Set help request dataref
    self.xpc.sendDREF('custom/haato/help_request', float(fire_id))
    self.xpc.sendDREF('custom/haato/agent_id_request', float(fire_id))

    # Wait for response
    self.pending_help_request = fire_id
    self.help_request_time = time.time()

    print(f"[Wingman] Requesting help with fire {fire_id}")

def check_help_response(self):
    """Check if human responded to help request"""

    if not self.pending_help_request:
        return None

    response = self.xpc.getDREF('custom/haato/request_response')

    if response == 1.0:
        # Accepted
        fire_id = self.pending_help_request
        self.pending_help_request = None
        self.xpc.sendDREF('custom/haato/request_response', 0.0)  # Reset
        return ('accepted', fire_id)

    elif response == -1.0:
        # Rejected
        fire_id = self.pending_help_request
        self.pending_help_request = None
        self.xpc.sendDREF('custom/haato/request_response', 0.0)
        return ('rejected', fire_id)

    # Check timeout (30 seconds)
    if time.time() - self.help_request_time > 30.0:
        fire_id = self.pending_help_request
        self.pending_help_request = None
        return ('timeout', fire_id)

    return None
```

#### Audio Cues (FlyWithLua Sounds)

**Trigger Audio from Python:**
```python
def play_radio_call(self, call_type):
    """Trigger audio playback via Lua

    Call types:
    1.0: Help request
    2.0: Command acknowledgment
    3.0: Status update
    4.0: Human acknowledgment
    0.0: Stop audio
    """
    self.xpc.sendDREF('custom/haato/play_radiocall', float(call_type))

# Examples:
play_radio_call(1.0)  # Play help request sound
time.sleep(2.0)
play_radio_call(0.0)  # Stop sound
```

**Lua Side (radio_calls.lua):**
```lua
function play_sound()
    local call_type = custom_play_radiocall

    if call_type == 1.0 then
        -- Play help request
        load_WAV_file("Resources/plugins/HAATO_assets/sounds/help_request.wav")

    elseif call_type == 2.0 then
        -- Play acknowledgment
        load_WAV_file("Resources/plugins/HAATO_assets/sounds/acknowledged.wav")

    elseif call_type == 0.0 then
        -- Stop audio
        stop_WAV_file()
    end
end

do_every_frame("play_sound()")
```

### 8.4 Designing Communication Protocols

**Effective Communication Design Principles:**

1. **Clarity:** Messages should be unambiguous
2. **Timeliness:** Deliver at relevant moments
3. **Non-Intrusive:** Don't overwhelm human
4. **Acknowledgment:** Confirm receipt/understanding

**Example Protocol: Task Allocation**

```python
class TaskAllocationProtocol:
    """Communication protocol for task allocation"""

    def __init__(self, xpc, msg_queue):
        self.xpc = xpc
        self.msg_queue = msg_queue

    def human_assigns_task(self, fire_id):
        """Human assigns fire to wingman"""

        # Send command via dataref
        self.xpc.sendDREF('custom/haato/command_from_human', float(fire_id))

        # Log in message queue
        msg = Message(
            type='command',
            sender='human',
            recipient='wingman',
            content=f'go_to_fire_{fire_id}',
            timestamp=time.time()
        )
        self.msg_queue.add_message(msg)

        return f"Commanded wingman to fire {fire_id}"

    def wingman_acknowledges(self, fire_id):
        """Wingman acknowledges task assignment"""

        # Send acknowledgment
        self.xpc.sendDREF('custom/haato/wingman_status', float(fire_id))  # Flying to fire N

        # Play audio cue
        self.xpc.sendDREF('custom/haato/play_radiocall', 2.0)

        # Log message
        msg = Message(
            type='status',
            sender='wingman',
            recipient='human',
            content=f'acknowledged_fire_{fire_id}',
            timestamp=time.time()
        )
        self.msg_queue.add_message(msg)

    def wingman_requests_help(self, fire_id, reason):
        """Wingman requests help with fire"""

        # Send request via dataref
        self.xpc.sendDREF('custom/haato/help_request', float(fire_id))

        # Play audio cue
        self.xpc.sendDREF('custom/haato/play_radiocall', 1.0)

        # Log message
        msg = Message(
            type='request',
            sender='wingman',
            recipient='human',
            content=f'help_with_fire_{fire_id}_{reason}',
            timestamp=time.time()
        )
        self.msg_queue.add_message(msg)

    def human_responds_to_request(self, accept):
        """Human accepts or rejects help request"""

        response_value = 1.0 if accept else -1.0
        self.xpc.sendDREF('custom/haato/request_response', response_value)

        # Log message
        msg = Message(
            type='response',
            sender='human',
            recipient='wingman',
            content='accept' if accept else 'reject',
            timestamp=time.time()
        )
        self.msg_queue.add_message(msg)

        return "Accepted request" if accept else "Rejected request"
```

---

## 9. Performance Optimization

### 9.1 Frame Rate Management

**MissionTimer Class:**

**Location:** `utility/utility_classes.py`

```python
class MissionTimer:
    """Frame rate control and timing for missions"""

    def __init__(self, target_fps=30):
        self.target_fps = target_fps
        self.target_dt = 1.0 / target_fps

        self.last_time = time.time()
        self.mission_start_time = time.time()

    def get_dt_and_wait(self):
        """Get delta time and sleep to maintain target FPS

        Returns:
            dt: Time since last call (seconds)
        """
        current_time = time.time()
        dt = current_time - self.last_time

        # Sleep to maintain target frame rate
        sleep_time = self.target_dt - dt
        if sleep_time > 0:
            time.sleep(sleep_time)
            current_time = time.time()
            dt = current_time - self.last_time

        self.last_time = current_time
        return dt

    def get_mission_elapsed_time(self):
        """Get total mission time elapsed

        Returns:
            elapsed_time: Seconds since mission start
        """
        return time.time() - self.mission_start_time

    def reset(self):
        """Reset timer to zero"""
        self.mission_start_time = time.time()
        self.last_time = time.time()
```

**Usage:**
```python
timer = MissionTimer(target_fps=30)

while not done:
    dt = timer.get_dt_and_wait()  # ~0.033s for 30 FPS
    met = timer.get_mission_elapsed_time()

    done = mission_manager.step(dt, met)
```

**Adjusting Frame Rate:**
```python
# Higher frame rate = smoother but more CPU
timer = MissionTimer(target_fps=60)  # 60 FPS

# Lower frame rate = less CPU but choppier
timer = MissionTimer(target_fps=15)  # 15 FPS
```

### 9.2 Vectorized Geospatial Calculations

**Performance Comparison:**

**Iterative (Slow):**
```python
def calculate_all_distances_slow(human_lat, human_lon, fires):
    """Calculate distances one by one (SLOW)"""
    distances = []
    for fire in fires:
        dist = haversine(human_lat, human_lon, fire.lat, fire.long)
        distances.append(dist)
    return distances

# Time: ~0.5ms for 8 fires
```

**Vectorized (Fast):**
```python
def calculate_all_distances_fast(human_lat, human_lon, fire_lats, fire_longs):
    """Calculate all distances at once (FAST)"""
    distances = GeoUtils.haversine_distance(
        human_lat, human_lon,
        fire_lats, fire_longs  # NumPy arrays
    )
    return distances

# Time: ~0.05ms for 8 fires (10x faster!)
```

**Implementation:**
```python
class FireWatchMM(MissionManager):
    def __init__(self, ...):
        super().__init__(...)

        # Pre-allocate arrays
        self.target_lats = np.zeros(8)
        self.target_longs = np.zeros(8)
        self.target_alts = np.zeros(8)

    def reset(self):
        # Fill arrays from targets
        for i, target in enumerate(self.targets):
            self.target_lats[i] = target.lat
            self.target_longs[i] = target.long
            self.target_alts[i] = target.alt

    def step(self, dt, met):
        # Vectorized distance calculation
        human_distances = GeoUtils.haversine_distance(
            self.human_lat, self.human_long,
            self.target_lats, self.target_longs
        )

        wingman_distances = GeoUtils.haversine_distance(
            self.wingman.lat, self.wingman.long,
            self.target_lats, self.target_longs
        )

        # Now have all distances in two arrays
        # Process detections vectorized
        in_range_mask = human_distances <= self.detection_range

        for i in range(len(self.targets)):
            if in_range_mask[i] and not self.targets[i].spotted:
                self.targets[i].spotted = True
```

### 9.3 Dataref Access Optimization

**Problem:** Each `getDREF()` / `sendDREF()` has network latency (~1ms)

**Solution: Batch and Cache**

**Cache Frequently-Read Datarefs:**
```python
class OptimizedMM(MissionManager):
    def __init__(self, ...):
        super().__init__(...)

        # Cache for datarefs that don't change often
        self.cached_drefs = {}
        self.cache_timeout = 1.0  # 1 second
        self.last_cache_time = 0

    def get_cached_dref(self, path, default=0.0):
        """Read dataref with caching"""
        current_time = time.time()

        # Refresh cache every second
        if current_time - self.last_cache_time > self.cache_timeout:
            self.cached_drefs = {}
            self.last_cache_time = current_time

        if path not in self.cached_drefs:
            self.cached_drefs[path] = self.xpc.getDREF(path)

        return self.cached_drefs.get(path, default)
```

**Batch Dataref Writes:**
```python
def update_all_target_datarefs(self):
    """Update all target datarefs at once"""

    # Collect all updates
    updates = {}

    for i, target in enumerate(self.targets):
        updates[f'custom/haato/target{i}status'] = target.status
        updates[f'custom/haato/target{i}classification'] = target.classification

    # Send all at once
    for path, value in updates.items():
        self.xpc.sendDREF(path, value)
```

**Lazy Evaluation:**
```python
def get_observation(self):
    """Only read datarefs needed for observation"""

    # Don't read everything - only what agent needs
    obs = np.array([
        self.mission_timer,
        self.human_lat,  # Already cached from step()
        self.human_long,
        self.human_alt,
        self.human_hdg,
        self.human_spd
    ])

    # Add target data (already in memory)
    for target in self.targets:
        obs = np.concatenate([obs, [
            target.lat, target.long, target.alt,
            1.0 if target.spotted else 0.0,
            target.status
        ]])

    return obs
```

### 9.4 Profiling and Debugging

**Python Profiling:**

```python
import cProfile
import pstats

def profile_mission():
    """Profile mission performance"""

    profiler = cProfile.Profile()
    profiler.enable()

    # Run mission
    run_mission()

    profiler.disable()

    # Print stats
    stats = pstats.Stats(profiler)
    stats.sort_stats('cumulative')
    stats.print_stats(20)  # Top 20 functions
```

**Identify Bottlenecks:**
```python
import time

def step_with_timing(self, dt, met):
    """Step function with timing instrumentation"""

    t_start = time.time()

    # 1. Read human state
    t1 = time.time()
    self._get_human_lla()
    print(f"Read human state: {(time.time() - t1) * 1000:.2f}ms")

    # 2. Process targets
    t2 = time.time()
    self._process_targets(dt)
    print(f"Process targets: {(time.time() - t2) * 1000:.2f}ms")

    # 3. Agent decision
    t3 = time.time()
    obs = self.get_observation()
    action = self.wingman.act(obs, None)
    print(f"Agent decision: {(time.time() - t3) * 1000:.2f}ms")

    # 4. Execute action
    t4 = time.time()
    self._execute_action(action, dt)
    print(f"Execute action: {(time.time() - t4) * 1000:.2f}ms")

    print(f"Total step time: {(time.time() - t_start) * 1000:.2f}ms\n")

    return self._check_mission_progress()[0]
```

**Framerate Monitor:**

**File:** `utility/framerate_monitor.py`

```python
class FramerateMonitor:
    """Monitor and log mission framerate"""

    def __init__(self, window_size=100):
        self.window_size = window_size
        self.frame_times = []

    def record_frame(self, dt):
        """Record frame delta time"""
        self.frame_times.append(dt)

        if len(self.frame_times) > self.window_size:
            self.frame_times.pop(0)

    def get_stats(self):
        """Get framerate statistics"""
        if not self.frame_times:
            return {}

        avg_dt = np.mean(self.frame_times)
        avg_fps = 1.0 / avg_dt if avg_dt > 0 else 0

        min_dt = np.min(self.frame_times)
        max_dt = np.max(self.frame_times)

        max_fps = 1.0 / min_dt if min_dt > 0 else 0
        min_fps = 1.0 / max_dt if max_dt > 0 else 0

        return {
            'avg_fps': avg_fps,
            'min_fps': min_fps,
            'max_fps': max_fps,
            'avg_dt_ms': avg_dt * 1000,
            'std_dt_ms': np.std(self.frame_times) * 1000
        }

    def print_stats(self):
        """Print framerate statistics"""
        stats = self.get_stats()
        if stats:
            print(f"FPS: {stats['avg_fps']:.1f} (min: {stats['min_fps']:.1f}, max: {stats['max_fps']:.1f})")
            print(f"Frame time: {stats['avg_dt_ms']:.2f}ms ±{stats['std_dt_ms']:.2f}ms")
```

---

## 10. Advanced Topics

### 10.1 Multi-Agent Systems

Extend HAATO to support multiple AI wingmen working together.

**Multi-Wingman Architecture:**

```python
class MultiAgentMM(MissionManager):
    def __init__(self, user_id, xpc, dev_mode=False, num_wingmen=2):
        super().__init__(user_id, xpc, dev_mode, num_wingmen)

        self.num_wingmen = num_wingmen
        self.wingmen = []  # List of wingman agents

    def reset(self):
        # Create multiple wingmen
        wingman_start_positions = [
            (47.71, -121.32, 2000),  # Wingman 1
            (47.71, -121.30, 2000),  # Wingman 2
        ]

        self.wingmen = []
        for i in range(self.num_wingmen):
            wingman = MultiAgentWingman(
                self.xpc,
                wingman_start_positions[i],
                90, 200, self,
                agent_id=i
            )
            self.wingmen.append(wingman)

    def step(self, dt, met):
        # Get observation
        obs = self.get_observation()

        # Each wingman acts
        for i, wingman in enumerate(self.wingmen):
            # Pass all wingman states to enable coordination
            action = wingman.act(obs, self.get_all_wingman_states())

            # Execute action
            self._execute_wingman_action(wingman, action, dt)

            # Update position in X-Plane (use different AI aircraft slots)
            self.xpc.sendPOSI([
                wingman.lat, wingman.long, wingman.alt,
                0, 0, wingman.hdg, 1
            ], i + 1)  # AI aircraft 1, 2, etc.

    def get_all_wingman_states(self):
        """Get states of all wingmen for inter-agent coordination"""
        return [
            {
                'id': i,
                'lat': wm.lat,
                'lon': wm.long,
                'alt': wm.alt,
                'current_task': wm.current_task
            }
            for i, wm in enumerate(self.wingmen)
        ]
```

**Inter-Agent Communication:**

```python
class MultiAgentWingman(Wingman):
    def __init__(self, xpc, start_lla, start_hdg, start_spd, mm, agent_id=0):
        super().__init__(xpc, start_lla, start_hdg, start_spd, mm)
        self.agent_id = agent_id
        self.current_task = None

    def act(self, observation, other_wingmen_states):
        """Act with awareness of other wingmen"""

        # Get unclaimed fires
        fires = self._parse_fires(observation)
        available_fires = []

        for fire in fires:
            if fire['handled']:
                continue

            # Check if any other wingman is handling this fire
            claimed = False
            for other in other_wingmen_states:
                if other['id'] != self.agent_id:
                    if other.get('current_task') == fire['id']:
                        claimed = True
                        break

            if not claimed:
                available_fires.append(fire)

        # Select fire from available
        if available_fires:
            # Choose closest
            closest = min(available_fires, key=lambda f: GeoUtils.haversine_distance(
                self.lat, self.long, f['lat'], f['lon']
            ))

            self.current_task = closest['id']
            goal_hsa = self._calc_hsa_to_target(
                closest['lat'], closest['lon'], closest['alt']
            )

            return {
                'type': 'hsa',
                'goal': goal_hsa,
                'status': f"Agent {self.agent_id} handling fire {closest['id']}"
            }
        else:
            # No available fires
            self.current_task = None
            return {'type': 'hsa', 'goal': (self.hdg, 120, self.alt)}
```

**Collision Avoidance:**

```python
def check_collision_risk(self, other_wingmen_states):
    """Check if on collision course with other wingmen"""

    for other in other_wingmen_states:
        if other['id'] == self.agent_id:
            continue

        # Calculate distance
        dist = GeoUtils.haversine_distance(
            self.lat, self.long,
            other['lat'], other['lon']
        )

        # If too close, adjust altitude
        if dist < 0.5:  # Within 0.5 NM
            # Separation: lower ID flies higher
            if self.agent_id < other['id']:
                self.alt += 500  # Climb 500m
            else:
                self.alt -= 500  # Descend 500m

            return True

    return False
```

### 10.2 Reinforcement Learning Integration

HAATO can be used as a Gymnasium environment for training RL agents.

**Gymnasium Wrapper:**

**File:** `utility/gym_wrapper.py`

```python
import gymnasium as gym
import numpy as np


class FirewatchGymEnv(gym.Env):
    """Gymnasium environment wrapper for HAATO FireWatch mission"""

    def __init__(self, xpc=None, render_mode=None):
        super().__init__()

        self.xpc = xpc
        self.render_mode = render_mode

        # Create mission manager
        self.mm = None  # Will be created in reset()

        # Define observation space
        # [mission_time, human_lat, human_lon, human_alt, human_hdg, human_spd,
        #  wingman_lat, wingman_lon, wingman_alt, wingman_hdg, wingman_spd,
        #  fire0_lat, fire0_lon, fire0_alt, fire0_status, fire0_class, ...] (for 8 fires)
        obs_size = 11 + (8 * 5)  # 11 mission/agent states + 8 fires × 5 attributes
        self.observation_space = gym.spaces.Box(
            low=-np.inf,
            high=np.inf,
            shape=(obs_size,),
            dtype=np.float32
        )

        # Define action space
        # [target_heading, target_speed, target_altitude, help_request_id]
        self.action_space = gym.spaces.Box(
            low=np.array([0, 50, 0, -1]),
            high=np.array([360, 500, 10000, 7]),
            shape=(4,),
            dtype=np.float32
        )

        self.mission_timer = None
        self.current_step = 0
        self.max_steps = 18000  # 10 minutes at 30 FPS

    def reset(self, seed=None, options=None):
        """Reset environment to initial state"""
        super().reset(seed=seed)

        # Create mission manager
        from missions.fire_mm import FireWatchMM
        self.mm = FireWatchMM(
            user_id=99,
            xpc=self.xpc,
            dev_mode=False
        )

        self.mm.reset()

        self.mission_timer = MissionTimer(target_fps=30)
        self.current_step = 0

        # Get initial observation
        obs = self._get_observation()
        info = self._get_info()

        return obs, info

    def step(self, action):
        """Execute one timestep"""

        # Parse action
        target_hdg = float(action[0])
        target_spd = float(action[1])
        target_alt = float(action[2])
        help_request = int(action[3])

        # Create action dict for wingman
        wingman_action = {
            'type': 'hsa',
            'goal': (target_hdg, target_spd, target_alt),
            'help_request': help_request if help_request >= 0 else None
        }

        # Execute mission step
        dt = self.mission_timer.get_dt_and_wait()
        met = self.mission_timer.get_mission_elapsed_time()

        # Manually execute wingman action (bypass wingman.act())
        self.mm._execute_wingman_action(self.mm.wingman, wingman_action, dt)

        # Process mission logic
        done = self.mm.step(dt, met)

        # Get observation
        obs = self._get_observation()

        # Calculate reward
        reward = self._calculate_reward()

        # Check termination
        self.current_step += 1
        terminated = done or (self.current_step >= self.max_steps)
        truncated = False

        info = self._get_info()

        return obs, reward, terminated, truncated, info

    def _get_observation(self):
        """Get observation from mission manager"""
        # This matches the observation space defined above
        return self.mm.get_observation().astype(np.float32)

    def _calculate_reward(self):
        """Calculate reward for current state"""

        reward = 0.0

        # Fires handled (+100 each)
        fires_handled = sum(1 for t in self.mm.targets if t.handled)
        reward += fires_handled * 100

        # Time penalty (-0.1 per second)
        reward -= self.mm.mission_timer * 0.1

        # Failure penalty
        if self.mm.mission_timer >= self.mm.max_mission_time:
            reward -= 500

        return reward

    def _get_info(self):
        """Get additional info dict"""
        return {
            'mission_time': self.mm.mission_timer,
            'fires_spotted': sum(1 for t in self.mm.targets if t.spotted),
            'fires_handled': sum(1 for t in self.mm.targets if t.handled),
        }

    def render(self):
        """Render environment (if render_mode set)"""
        if self.render_mode == "human":
            # Display in X-Plane (already rendering)
            pass
        elif self.render_mode == "rgb_array":
            # Return RGB array (capture X-Plane screenshot)
            pass

    def close(self):
        """Clean up environment"""
        if self.mm:
            self.mm.xpc.sendDREF('custom/haato/mission_status', 0.0)
```

**Training with Stable Baselines3:**

```python
from stable_baselines3 import PPO
from stable_baselines3.common.vec_env import DummyVecEnv
from utility.gym_wrapper import FirewatchGymEnv

# Create environment
env = FirewatchGymEnv(xpc=None)  # SimMode for offline training
env = DummyVecEnv([lambda: env])

# Create PPO agent
model = PPO(
    "MlpPolicy",
    env,
    verbose=1,
    learning_rate=3e-4,
    n_steps=2048,
    batch_size=64,
    n_epochs=10
)

# Train
model.learn(total_timesteps=100000)

# Save model
model.save("firewatch_ppo_agent")

# Load and test
model = PPO.load("firewatch_ppo_agent")
obs, info = env.reset()
for _ in range(1000):
    action, _states = model.predict(obs, deterministic=True)
    obs, reward, terminated, truncated, info = env.step(action)
    if terminated or truncated:
        obs, info = env.reset()
```

### 10.3 Crash Recovery and State Persistence

**CrashStateSaverThread:**

**File:** `utility/crash_recovery.py`

```python
import threading
import json
import time


class CrashStateSaverThread(threading.Thread):
    """Background thread that periodically saves mission state"""

    def __init__(self, mm, save_interval=0.33):
        super().__init__(daemon=True)
        self.mm = mm
        self.save_interval = save_interval  # Save every 0.33s (10 steps at 30 FPS)
        self.running = True

    def run(self):
        """Thread main loop"""
        while self.running:
            time.sleep(self.save_interval)
            self._save_state()

    def stop(self):
        """Stop the thread"""
        self.running = False

    def _save_state(self):
        """Save current mission state to file"""
        try:
            state = self.mm.get_state()

            # Add crash recovery metadata
            state['crash_recovery'] = {
                'save_time': time.time(),
                'subject_id': self.mm.user_id
            }

            # Save to file
            filename = f"crash_recovery/state_p{self.mm.user_id}.json"
            with open(filename, 'w') as f:
                json.dump(state, f, indent=2)

        except Exception as e:
            print(f"Warning: Failed to save crash state: {e}")
```

**Resume from Crash:**

```python
def restore_mission_from_crash(mm, subject_id):
    """Restore mission from crash recovery file"""
    import json

    filename = f"crash_recovery/state_p{subject_id}.json"

    try:
        with open(filename, 'r') as f:
            state = json.load(f)

        # Restore mission time
        mm.mission_timer = state['mission_time']

        # Restore fire states
        for fire_data in state['hikers']:  # Or 'fires' depending on mission
            fire_id = fire_data['id']
            if fire_id < len(mm.targets):
                mm.targets[fire_id].spotted = fire_data['spotted']
                mm.targets[fire_id].handled = fire_data.get('rescued', fire_data.get('handled', False))
                mm.targets[fire_id].classification = fire_data.get('classification', 'unclassified')

        # Restore human position
        if 'human' in state:
            mm.human_lla = (
                state['human']['lat'],
                state['human']['lon'],
                state['human']['alt']
            )

        # Restore wingman position
        if 'wingman' in state:
            mm.wingman.lat = state['wingman']['lat']
            mm.wingman.long = state['wingman']['lon']
            mm.wingman.alt = state['wingman']['alt']

        print(f"Restored mission from crash at {state['mission_time']:.1f}s")
        return True

    except FileNotFoundError:
        print(f"No crash recovery file found for subject {subject_id}")
        return False
    except Exception as e:
        print(f"Error restoring from crash: {e}")
        return False
```

**Usage in Run Script:**

```python
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--subject_id', type=int, default=99)
    parser.add_argument('--resume', action='store_true', help='Resume from crash')
    args = parser.parse_args()

    # ... (create xpc, mm, logger, timer)

    if args.resume:
        # Restore from crash
        if restore_mission_from_crash(mm, args.subject_id):
            print("Mission restored from crash")
        else:
            print("Starting new mission (no crash state found)")
            mm.reset()
    else:
        mm.reset()

    # Start crash recovery thread
    crash_saver = CrashStateSaverThread(mm, save_interval=0.33)
    crash_saver.start()

    try:
        # Main loop
        while not done:
            # ...
            pass
    finally:
        # Stop crash saver
        crash_saver.stop()
        crash_saver.join(timeout=1.0)
```

### 10.4 Wizard of Oz Studies

The WoZ GUI allows experimenters to control the wingman manually or inject scripted behaviors.

**WoZGUIThreaded:**

**File:** `utility/woz_gui_threaded.py`

```python
import tkinter as tk
from tkinter import ttk
import threading


class WoZGUIThread(threading.Thread):
    """Wizard of Oz experimenter control GUI"""

    def __init__(self, xpc, mm, dev_mode=True):
        super().__init__(daemon=True)
        self.xpc = xpc
        self.mm = mm
        self.dev_mode = dev_mode
        self.root = None

    def run(self):
        """Thread main loop"""
        self.root = tk.Tk()
        self.root.title("HAATO Wizard of Oz Control")
        self.root.geometry("600x800")

        self._create_widgets()
        self._start_update_loop()

        self.root.mainloop()

    def _create_widgets(self):
        """Create GUI widgets"""

        # Mission status frame
        status_frame = ttk.LabelFrame(self.root, text="Mission Status", padding=10)
        status_frame.pack(fill="x", padx=10, pady=5)

        self.time_label = ttk.Label(status_frame, text="Time: 0:00")
        self.time_label.pack()

        self.fires_label = ttk.Label(status_frame, text="Fires: 0/8 spotted, 0/8 handled")
        self.fires_label.pack()

        # Fire configuration frame
        fire_frame = ttk.LabelFrame(self.root, text="Fire Configuration", padding=10)
        fire_frame.pack(fill="x", padx=10, pady=5)

        self.fire_controls = []
        for i in range(8):
            frame = ttk.Frame(fire_frame)
            frame.pack(fill="x", pady=2)

            ttk.Label(frame, text=f"Fire {i}:").pack(side="left")

            status_var = tk.StringVar(value="Unspotted")
            status_combo = ttk.Combobox(frame, textvariable=status_var,
                                        values=["Unspotted", "Spotted", "Suppressed"],
                                        width=12)
            status_combo.pack(side="left", padx=5)

            class_var = tk.StringVar(value="Unclassified")
            class_combo = ttk.Combobox(frame, textvariable=class_var,
                                        values=["Unclassified", "Moderate", "Severe"],
                                        width=12)
            class_combo.pack(side="left", padx=5)

            self.fire_controls.append({
                'status_var': status_var,
                'class_var': class_var
            })

        # Command buttons
        cmd_frame = ttk.LabelFrame(self.root, text="Wingman Commands", padding=10)
        cmd_frame.pack(fill="x", padx=10, pady=5)

        # Fire command buttons
        for i in range(8):
            btn = ttk.Button(cmd_frame, text=f"Fire {i}",
                            command=lambda idx=i: self._send_command(idx))
            btn.grid(row=i // 4, column=i % 4, padx=2, pady=2, sticky="ew")

        # Special commands
        ttk.Button(cmd_frame, text="Follow Me",
                  command=lambda: self._send_command(8)).grid(row=2, column=0, columnspan=2, sticky="ew")
        ttk.Button(cmd_frame, text="Hold Position",
                  command=lambda: self._send_command(12)).grid(row=2, column=2, columnspan=2, sticky="ew")

        # Mission control
        control_frame = ttk.LabelFrame(self.root, text="Mission Control", padding=10)
        control_frame.pack(fill="x", padx=10, pady=5)

        ttk.Button(control_frame, text="Start Mission",
                  command=self._start_mission).pack(side="left", padx=5)
        ttk.Button(control_frame, text="Reset Mission",
                  command=self._reset_mission).pack(side="left", padx=5)

    def _send_command(self, command_code):
        """Send command to wingman"""
        self.xpc.sendDREF('custom/haato/command_from_human', float(command_code))
        print(f"[WoZ] Sent command: {command_code}")

    def _start_mission(self):
        """Start mission"""
        self.mm.reset()
        print("[WoZ] Mission started")

    def _reset_mission(self):
        """Reset mission"""
        self.mm.reset()
        self.xpc.sendDREF('custom/haato/mission_status', 0.0)
        print("[WoZ] Mission reset")

    def _start_update_loop(self):
        """Start periodic GUI updates"""
        self._update_status()

    def _update_status(self):
        """Update status displays"""
        if self.mm:
            # Update time
            time_left = max(0, self.mm.max_mission_time - self.mm.mission_timer)
            mins = int(time_left // 60)
            secs = int(time_left % 60)
            self.time_label.config(text=f"Time: {mins}:{secs:02d}")

            # Update fires
            spotted = sum(1 for t in self.mm.targets if t.spotted)
            handled = sum(1 for t in self.mm.targets if t.handled)
            self.fires_label.config(text=f"Fires: {spotted}/8 spotted, {handled}/8 handled")

        # Schedule next update
        self.root.after(100, self._update_status)  # Update every 100ms
```

### 10.5 Offline Testing and Simulation

**SimMode:**

**File:** `utility/utility_classes.py`

```python
class SimMode:
    """Simulate X-Plane datarefs for offline testing"""

    def __init__(self, mm):
        self.mm = mm
        self.drefs = {}

        # Initialize with default values
        self._init_defaults()

    def _init_defaults(self):
        """Initialize default dataref values"""
        self.drefs['sim/flightmodel/position/latitude'] = 47.71
        self.drefs['sim/flightmodel/position/longitude'] = -121.34
        self.drefs['sim/flightmodel/position/elevation'] = 1600.0
        self.drefs['sim/flightmodel/position/true_psi'] = 90.0

        # Mission datarefs
        self.drefs['custom/haato/mission_status'] = 0.0
        self.drefs['custom/haato/command_from_human'] = 12.0

    def getDREF(self, path):
        """Read simulated dataref"""
        return self.drefs.get(path, 0.0)

    def sendDREF(self, path, value):
        """Write simulated dataref"""
        self.drefs[path] = value

    def sendPOSI(self, position, aircraft=0):
        """Simulate aircraft position update"""
        # In sim mode, just store position
        if aircraft == 0:
            self.drefs['sim/flightmodel/position/latitude'] = position[0]
            self.drefs['sim/flightmodel/position/longitude'] = position[1]
            self.drefs['sim/flightmodel/position/elevation'] = position[2]
```

**Using SimMode:**

```python
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--simulate_xplane', action='store_true')
    args = parser.parse_args()

    # Create connection
    xpc = XPlaneConnectX()

    # Enable sim mode if requested
    if args.simulate_xplane:
        mm = FireWatchMM(user_id=99, xpc=None, dev_mode=True)
        sim = SimMode(mm)
        xpc = sim  # Replace xpc with sim mode
        print("✓ Simulation mode enabled (no X-Plane required)")

    # Rest of code works normally
    # ...
```

---

## 11. Experimental Methodology

### 11.1 Designing Human-AI Teaming Experiments

**Research Questions HAATO Can Address:**

**Trust & Reliance:**
- How does agent transparency affect human trust?
- When do humans over/under-rely on AI agents?
- How does trust evolve over repeated interactions?

**Workload & Task Allocation:**
- What initiative level minimizes human workload?
- How do humans adapt task allocation strategies?
- What workload distribution maximizes team performance?

**Communication Patterns:**
- How often should AI agents request help?
- What communication modalities are most effective?
- How does communication frequency affect trust?

**Situation Awareness:**
- How does initiative level affect shared SA?
- Do humans maintain SA when agents are highly autonomous?
- How do communication patterns support SA?

**Example Study Design:**

**RQ:** Does AI initiative level affect team performance and human workload?

**Independent Variable:** Initiative level (low, medium, high)
- **Low:** Waits for commands, frequent help requests
- **Medium:** Balanced autonomy, moderate help requests
- **High:** Highly autonomous, rare help requests

**Dependent Variables:**
- **Performance:** Mission completion time, fires handled, efficiency
- **Workload:** NASA-TLX scores, command frequency
- **Trust:** Trust scale (Jian et al. 2000), reliance behaviors
- **SA:** SAGAT probes, post-trial questionnaires

**Design:** 3×3 Latin Square (within-subjects)
- 3 initiative levels × 3 fire layouts
- Counterbalanced order across 9 participants (or multiples)
- 2 practice trials before experimental trials

**Procedure:**
1. Informed consent & demographics
2. Training (flight controls, G1000 interface, mission objectives)
3. Practice trials (2 trials, different layouts)
4. Experimental trials (3 trials, counterbalanced)
   - Pre-trial: Baseline trust questionnaire
   - During: Telemetry & message logging
   - Post-trial: NASA-TLX, trust scale, SA questions
5. Debrief & final questionnaire

### 11.2 Participant Training

**Training Curriculum:**

**Session 1: Flight Controls (15 minutes)**
- Joystick/yoke basics
- Throttle control
- Basic maneuvers (turns, climbs, descents)
- Altitude and heading hold
- No mission context yet

**Session 2: G1000 Interface (10 minutes)**
- PFD instruments (altimeter, heading, airspeed)
- MFD map navigation
- Fire icons and colors
- Classification interface
- Command interface

**Session 3: Mission Briefing (10 minutes)**
- Mission objectives
- Fire detection, classification, suppression
- Altitude requirements (7000 ft MSL)
- Time limit (10 minutes)
- Win/loss conditions

**Session 4: Wingman Collaboration (15 minutes)**
- Wingman capabilities
- Commanding wingman to fires
- Help requests and responses
- Status messages
- Follow-me and hold commands

**Session 5: Practice Trials (20 minutes)**
- Practice 1: Low initiative, simple layout (4 fires)
- Practice 2: High initiative, full layout (8 fires)
- Experimenter provides coaching
- Answer questions

**Proficiency Criteria:**
- Complete practice trial within time limit
- Successfully classify at least 3 fires
- Successfully command wingman to at least 2 fires
- Demonstrate understanding of help request mechanism

### 11.3 Data Collection Protocol

**Pre-Experiment:**
- Demographics questionnaire
- Prior flight simulation experience
- Gaming experience (relevant for controls proficiency)
- Initial trust in automation scale

**During Mission:**

**Telemetry Data (1 Hz):**
- Human aircraft state (position, heading, speed, altitude)
- Wingman aircraft state
- All fire statuses and classifications
- Commands issued
- Help requests and responses
- Mission time

**Event Logs (discrete):**
- Fire detected (who, when, which fire)
- Fire classified (who, when, classification)
- Fire suppressed (who, when, duration)
- Command issued (when, which command)
- Help request (when, which fire, response, response time)
- Message sent/received

**Video Recording (optional):**
- Screen capture (G1000 displays)
- Face camera (expressions, gaze)
- Synchronized with telemetry via timestamps

**Audio Recording (optional):**
- Think-aloud protocol
- Verbal commands (if using voice recognition)

**Post-Trial:**
- NASA-TLX (workload)
- Trust in Automation scale
- SA questionnaire (what was wingman doing? which fires were severe?)
- Subjective experience questions

**Post-Experiment:**
- Final trust scale
- Preference ranking (which initiative level preferred?)
- Open-ended debrief
- Payment/compensation

### 11.4 Metrics and Analysis

**Mission Performance Metrics:**

```python
import pandas as pd
import numpy as np

def calculate_performance_metrics(csv_file):
    """Calculate performance metrics from mission log"""

    df = pd.read_csv(csv_file)

    metrics = {}

    # Mission completion time
    metrics['completion_time'] = df['mission_time'].max()

    # Fires handled
    fires_handled = 0
    for i in range(8):
        if df.iloc[-1][f'fire{i}_status'] >= 2.0:
            fires_handled += 1
    metrics['fires_handled'] = fires_handled
    metrics['fires_handled_pct'] = fires_handled / 8.0

    # Success
    metrics['success'] = fires_handled == 8

    # Efficiency (fires per minute)
    metrics['efficiency'] = fires_handled / (metrics['completion_time'] / 60.0)

    return metrics
```

**Team Coordination Metrics:**

```python
def calculate_coordination_metrics(csv_file, events_file):
    """Calculate team coordination metrics"""

    df = pd.read_csv(csv_file)

    # Load events
    import json
    events = []
    with open(events_file, 'r') as f:
        for line in f:
            events.append(json.loads(line))

    metrics = {}

    # Workload distribution
    human_fires = 0
    wingman_fires = 0
    for event in events:
        if event['type'] == 'fire_suppressed':
            if event['suppressed_by'] == 'human':
                human_fires += 1
            else:
                wingman_fires += 1

    metrics['human_fires'] = human_fires
    metrics['wingman_fires'] = wingman_fires
    metrics['workload_balance'] = min(human_fires, wingman_fires) / max(human_fires, wingman_fires, 1)

    # Command frequency
    command_events = [e for e in events if e['type'] == 'command_issued']
    metrics['commands_issued'] = len(command_events)
    metrics['commands_per_minute'] = len(command_events) / (df['mission_time'].max() / 60.0)

    # Help requests
    help_events = [e for e in events if e['type'] == 'help_request']
    metrics['help_requests'] = len(help_events)
    metrics['help_requests_accepted'] = sum(1 for e in help_events if e['response'] == 'accepted')
    metrics['help_acceptance_rate'] = metrics['help_requests_accepted'] / max(len(help_events), 1)

    # Average help response time
    response_times = [e['response_time'] for e in help_events if 'response_time' in e]
    metrics['avg_help_response_time'] = np.mean(response_times) if response_times else 0

    return metrics
```

**Statistical Analysis Example:**

```python
import pandas as pd
from scipy import stats

def analyze_initiative_effect(results_df):
    """Analyze effect of initiative level on performance"""

    # Filter by initiative level
    low = results_df[results_df['initiative'] == 'low']
    medium = results_df[results_df['initiative'] == 'medium']
    high = results_df[results_df['initiative'] == 'high']

    # ANOVA: completion time
    f_stat, p_value = stats.f_oneway(
        low['completion_time'],
        medium['completion_time'],
        high['completion_time']
    )

    print(f"ANOVA - Completion Time: F={f_stat:.2f}, p={p_value:.4f}")

    # Post-hoc pairwise comparisons
    from scipy.stats import ttest_rel

    t_low_med, p_low_med = ttest_rel(low['completion_time'], medium['completion_time'])
    t_med_high, p_med_high = ttest_rel(medium['completion_time'], high['completion_time'])
    t_low_high, p_low_high = ttest_rel(low['completion_time'], high['completion_time'])

    print(f"Low vs Medium: t={t_low_med:.2f}, p={p_low_med:.4f}")
    print(f"Medium vs High: t={t_med_high:.2f}, p={p_med_high:.4f}")
    print(f"Low vs High: t={t_low_high:.2f}, p={p_low_high:.4f}")

    # Effect size (Cohen's d)
    def cohens_d(group1, group2):
        n1, n2 = len(group1), len(group2)
        var1, var2 = np.var(group1, ddof=1), np.var(group2, ddof=1)
        pooled_std = np.sqrt(((n1-1)*var1 + (n2-1)*var2) / (n1+n2-2))
        return (np.mean(group1) - np.mean(group2)) / pooled_std

    d_low_high = cohens_d(low['completion_time'], high['completion_time'])
    print(f"Effect size (Low vs High): d={d_low_high:.2f}")
```

---

## 12. Troubleshooting & Common Issues

### 12.1 Installation Problems

**X-Plane Plugin Not Loading**

**Symptoms:**
- FlyWithLua or XPPython3 not appearing in Plugin Admin
- Custom datarefs not accessible
- G1000 overlay not visible

**Solutions:**

1. **Check Log Files:**
   ```
   X-Plane 12/Log.txt (main log)
   X-Plane 12/Resources/plugins/FlyWithLua/FlyWithLua.log
   X-Plane 12/Resources/plugins/XPPython3/xppython3.log
   ```

2. **Verify File Locations:**
   ```
   X-Plane 12/Resources/plugins/FlyWithLua/
   X-Plane 12/Resources/plugins/XPPython3/
   ```

3. **Check File Permissions:**
   - Ensure plugins folder is writable
   - On macOS/Linux: Check execute permissions

4. **Python Version:**
   - XPPython3 requires Python 3.12
   - Check with: `python --version`
   - Update PATH if needed

5. **Reinstall Plugins:**
   - Delete and re-extract plugin folders
   - Restart X-Plane

**UDP Connection Refused**

**Symptoms:**
- `ConnectionRefusedError` in Python
- `getDREF()` fails immediately

**Solutions:**

1. **Verify X-Plane is Running:**
   - Must be in flight (not main menu)
   - Aircraft loaded

2. **Check Network Settings:**
   - Settings → Network → "Accept incoming connections"
   - UDP ports: 49000, 49010, 49001

3. **Firewall:**
   - Allow X-Plane through firewall
   - Allow Python through firewall

4. **Test Connection:**
   ```python
   from utility.XPlaneConnectX import XPlaneConnectX
   xpc = XPlaneConnectX(ip='127.0.0.1', port=49000)
   print(xpc.getDREF('sim/version/xplane_internal_version'))
   ```

**XPPython3 Python Version Mismatch**

**Symptoms:**
- XPPython3 log shows "Python version X.X not supported"
- PI_gui_refactor.py not loaded

**Solutions:**

1. **Install Python 3.12:**
   ```bash
   # Download from python.org
   python --version  # Should show 3.12.x
   ```

2. **Update PATH:**
   - Ensure Python 3.12 is first in PATH
   - Restart X-Plane after changing PATH

3. **XPPython3 Explicit Path:**
   - Edit `X-Plane 12/Resources/plugins/XPPython3/xppython3.ini`
   - Add line: `pythonExecutable=/path/to/python3.12`

### 12.2 Runtime Errors

**Dataref Not Found**

**Symptoms:**
```
XPC WARNING: Dataref custom/haato/mission_status not found
```

**Solutions:**

1. **Check Spelling:**
   - Datarefs are case-sensitive
   - `custom/haato/` prefix required

2. **Verify Lua Script Loaded:**
   - Check `FlyWithLua.log` for errors
   - Ensure `custom_datarefs.lua` in Scripts folder

3. **Restart X-Plane:**
   - Lua scripts loaded at startup only

**Mission Loop Crashes**

**Symptoms:**
- Python crashes mid-mission
- `Traceback` in terminal

**Solutions:**

1. **Enable Verbose Mode:**
   ```bash
   python run_mission.py --verbose
   ```

2. **Check Safe_get_dref:**
   - Use `safe_get_dref()` instead of `getDREF()` directly
   - Provides fallback values

3. **Try-Except Blocks:**
   ```python
   try:
       done = mm.step(dt, met)
   except Exception as e:
       print(f"Error in mission step: {e}")
       import traceback
       traceback.print_exc()
   ```

4. **Resume from Crash:**
   ```bash
   python run_mission.py --resume --subject_id 5
   ```

**Frame Rate Drops**

**Symptoms:**
- Mission runs slowly (<10 FPS)
- X-Plane becomes unresponsive

**Solutions:**

1. **Lower X-Plane Graphics:**
   - Settings → Graphics → Visual Effects: Low
   - Reduce texture quality

2. **Reduce Logging Frequency:**
   ```bash
   python run_mission.py --log_hz 0.5  # Log every 2 seconds
   ```

3. **Profile Code:**
   - Use `cProfile` to find bottlenecks
   - Optimize slow functions

4. **Close Other Applications:**
   - Free up CPU and RAM
   - Close browser, etc.

### 12.3 Data Quality Issues

**Missing CSV Data**

**Symptoms:**
- CSV file has gaps
- Some timesteps missing

**Solutions:**

1. **Check Logging Frequency:**
   - Default 1 Hz may be too low
   - Increase with `--log_hz 10.0`

2. **Verify Logger Running:**
   - Check for error messages
   - Ensure `logger.log_step_data()` called

3. **Disk Space:**
   - Ensure sufficient disk space
   - Check write permissions

**NaN Values in Data**

**Symptoms:**
- `NaN` or `0.0` for many dataref values

**Solutions:**

1. **Use safe_get_dref:**
   ```python
   lat = self.safe_get_dref(
       'sim/flightmodel/position/latitude',
       default_value=self.last_known_lat
   )
   ```

2. **Check Dataref Permissions:**
   - Settings → Data Output → Dataref Read/Write
   - Ensure datarefs are readable

3. **Verify X-Plane Running:**
   - Some datarefs only valid during flight

### 12.4 Mission Logic Bugs

**Target Detection Not Working**

**Symptoms:**
- Fires never detected even when close

**Solutions:**

1. **Check Detection Range:**
   ```python
   print(f"Distance to fire: {distance:.2f} NM")
   print(f"Detection range: {self.detection_range} NM")
   ```

2. **Verify Range Calculation:**
   - Use GeoUtils.haversine_distance
   - Check lat/lon units (degrees, not radians)

3. **Debug Output:**
   ```python
   if not target.spotted:
       print(f"Fire {target.id}: distance={distance:.2f}, range={self.detection_range}")
   ```

**Wingman Not Responding**

**Symptoms:**
- Wingman ignores commands
- Doesn't move

**Solutions:**

1. **Check AI Aircraft:**
   - Flight Configuration → AI Aircraft → Add Aircraft
   - At least 1 AI aircraft required

2. **Verify Command Dataref:**
   ```python
   cmd = self.xpc.getDREF('custom/haato/command_from_human')
   print(f"Command from human: {cmd}")
   ```

3. **Check Wingman Act():**
   - Add print statements
   - Verify action dict returned

4. **SendPOSI Call:**
   - Ensure `sendPOSI()` called each frame
   - Check aircraft index (0=human, 1=AI)

---

## 13. Best Practices & Design Patterns

### 13.1 Mission Design Principles

**Clear Objectives:**
- Define measurable success criteria
- Avoid ambiguous goals
- Ensure achievable within time limit

**Example:** ✓ "Suppress all 8 fires within 10 minutes"
vs. ✗ "Help with fires"

**Balanced Difficulty:**
- Not trivial (boring)
- Not impossible (frustrating)
- Pilot test to tune difficulty

**Meaningful Collaboration:**
- Tasks should benefit from human-AI teamwork
- Avoid scenarios where human or AI can trivially solo
- Design opportunities for coordination

**Reproducibility:**
- Use fixed seeds for randomization
- Document all parameters
- Version control mission configs

### 13.2 Agent Design Principles

**Observable Behavior:**
- Status messages should be clear
- Actions should match stated intentions
- No "black box" decision making

**Example:**
```python
# Good: Clear status
status = "Flying to fire 3 (closest unhandled fire)"

# Bad: Unclear status
status = "Working"
```

**Predictable & Consistent:**
- Same inputs → same outputs
- No random unexplained changes
- Clear decision rules

**Appropriate Autonomy:**
- Match autonomy to initiative level
- Low initiative: Wait for commands
- High initiative: Proactive but transparent

**Effective Help-Seeking:**
- Request help when genuinely uncertain
- Don't request help too frequently (annoying)
- Respect human responses

**Respect Human Authority:**
- Human commands override autonomous behavior
- Acknowledge commands promptly
- Explain when unable to comply

### 13.3 Code Organization

**Good Structure:**

```
haato/
├── missions/                # Mission implementations
│   ├── fire_mm.py          # FireWatch mission manager
│   ├── fire_wingman.py     # FireWatch wingman agent
│   └── search_rescue_mm.py # Custom mission
├── utility/                 # Shared utilities
│   ├── base_classes_vectorized.py  # Abstract base classes
│   ├── XPlaneConnectX.py   # X-Plane communication
│   ├── data_logger.py      # Data logging
│   ├── message_queue.py    # Message system
│   └── utility_classes.py  # Timer, SimMode
├── data_analysis/           # Analysis scripts
├── tests/                   # Unit tests
├── run_mission.py           # Main entry point
└── requirements.txt         # Dependencies
```

**Separation of Concerns:**
- Mission logic separate from agent logic
- Agent logic separate from navigation helpers
- Communication separate from task execution

**Configuration vs. Hard-Coding:**
- Use JSON for experiment conditions
- Hard-code mission mechanics in Python
- Document all magic numbers

**Logging Strategy:**
- Log everything for reproducibility
- Use appropriate log levels (debug, info, warning)
- Include timestamps

**Testing:**
- Unit tests for decision logic
- Integration tests for mission flow
- Test with --simulate_xplane for speed

### 13.4 Experimental Design

**Pilot Testing:**
- Test with 2-3 pilot participants
- Identify confusing instructions
- Tune difficulty and time limits
- Refine measures

**Counterbalancing:**
- Use Latin squares for within-subjects
- Randomize when possible
- Control for order effects

**Multiple Measures:**
- Objective: Performance, telemetry
- Subjective: Questionnaires, ratings
- Behavioral: Commands, help requests
- Triangulate findings

**Data Management:**
- Organize by participant and trial
- Back up data regularly
- Anonymize participant data
- Document experimental conditions

---

## 14. Appendices

### 14.A Complete Dataref Reference

**Mission Control Datarefs:**

| Dataref | Type | R/W | Description | Range |
|---------|------|-----|-------------|-------|
| `custom/haato/mission_status` | Float | R/W | Mission state | 0=running, 1=success, -1=failure |
| `custom/haato/mission_time_left` | Float | R/W | Time remaining (seconds) | 0-600 |
| `custom/haato/icons_visible` | Float | R/W | Enable 3D target rendering | 0/1 |
| `custom/haato/announcement_to_show` | Float | R/W | Announcement type | 0=welcome, 1=end, 99=none |

**Human-AI Communication Datarefs:**

| Dataref | Type | R/W | Description | Range |
|---------|------|-----|-------------|-------|
| `custom/haato/command_from_human` | Float | R/W | Human command to wingman | 0-7=fire, 8=follow, 12=hold |
| `custom/haato/request_response` | Float | R/W | Response to help request | -1=reject, 0=none, 1=accept |
| `custom/haato/help_request` | Float | R/W | Wingman requesting help | 0-7=fire ID, 99=none |
| `custom/haato/wingman_status` | Float | R/W | Encoded status message | 0-59 (see encoding table) |
| `custom/haato/id_request_response` | Float | R/W | Classification response | 0=none, 1=auto, 1.0=mod, 2.0=severe |
| `custom/haato/agent_id_request` | Float | R/W | Agent requesting classification | 0-7=fire ID, 99=none |

**Wingman Configuration Datarefs:**

| Dataref | Type | R/W | Description | Range |
|---------|------|-----|-------------|-------|
| `custom/haato/taskpriority_spotunknown` | Float | R/W | Priority: spot unknown fires | 0=highest, 99=disabled |
| `custom/haato/taskpriority_handlemoderate` | Float | R/W | Priority: handle moderate fires | 0=highest, 99=disabled |
| `custom/haato/taskpriority_handlesevere` | Float | R/W | Priority: handle severe fires | 0=highest, 99=disabled |
| `custom/haato/set_wingman_greedy` | Float | R/W | Greedy mode (closest first) | 0/1 |
| `custom/haato/auto_spot` | Float | R/W | Auto-classify fires | 0/1 |
| `custom/haato/can_request` | Float | R/W | Allow help requests | 0/1 |

**Wingman State Datarefs:**

| Dataref | Type | R/W | Description | Units |
|---------|------|-----|-------------|-------|
| `custom/haato/wingman_lat` | Float | R/W | Wingman latitude | degrees |
| `custom/haato/wingman_long` | Float | R/W | Wingman longitude | degrees |
| `custom/haato/wingman_alt` | Float | R/W | Wingman altitude | meters MSL |
| `custom/haato/wingman_hdg` | Float | R/W | Wingman heading | degrees true |
| `custom/haato/wingman_spd` | Float | R/W | Wingman speed | knots |
| `custom/haato/wingman_goal_hdg` | Float | R/W | Desired heading | degrees |
| `custom/haato/wingman_goal_spd` | Float | R/W | Desired speed | knots |
| `custom/haato/wingman_goal_alt` | Float | R/W | Desired altitude | meters MSL |

**Target Status Datarefs (per target 0-7):**

| Dataref | Type | R/W | Description | Range |
|---------|------|-----|-------------|-------|
| `custom/haato/target{N}status` | Float | R/W | Target status | 0=unknown, 1=spotted, 2=complete |
| `custom/haato/target{N}classification` | Float | R/W | Fire severity | 0=unclass, 1=moderate, 2=severe |

Where {N} = 0-7 (8 targets total)

**Human Interaction Datarefs:**

| Dataref | Type | R/W | Description | Range |
|---------|------|-----|-------------|-------|
| `custom/haato/human_in_range_of_target` | Float | R/W | Target human is near | 0-7=fire ID, 99=none |
| `custom/haato/trigger_pulled` | Float | R | Trigger button state | 0/1 |
| `custom/haato/water_remaining` | Float | R/W | Water capacity | 0-100 |
| `custom/haato/mic_pressed` | Float | R | Mic button state | 0/1 |
| `custom/haato/play_radiocall` | Float | R/W | Audio trigger | 0-4 (see audio codes) |

**Standard X-Plane Datarefs (commonly used):**

| Dataref | Description | Units | Read-Only |
|---------|-------------|-------|-----------|
| `sim/flightmodel/position/latitude` | Aircraft latitude | degrees | No |
| `sim/flightmodel/position/longitude` | Aircraft longitude | degrees | No |
| `sim/flightmodel/position/elevation` | Altitude MSL | meters | No |
| `sim/flightmodel/position/y_agl` | Altitude AGL | meters | No |
| `sim/flightmodel/position/true_psi` | True heading | degrees | No |
| `sim/flightmodel/position/true_theta` | Pitch angle | degrees | No |
| `sim/flightmodel/position/true_phi` | Roll angle | degrees | No |
| `sim/flightmodel/position/local_vx` | Velocity X (local frame) | m/s | Yes |
| `sim/flightmodel/position/local_vy` | Velocity Y (local frame) | m/s | Yes |
| `sim/flightmodel/position/local_vz` | Velocity Z (local frame) | m/s | Yes |
| `sim/time/paused` | Simulation paused | 0/1 | Yes |
| `sim/joystick/fire_key_is_down` | Trigger button | 0/1 | Yes |

### 14.B Observation Space Specification

**FireWatch Observation Vector (NumPy Array):**

| Index | Description | Type | Units | Range |
|-------|-------------|------|-------|-------|
| 0 | Mission elapsed time | float | seconds | 0-600 |
| 1 | Time remaining | float | seconds | 0-600 |
| 2 | Human latitude | float | degrees | -90 to 90 |
| 3 | Human longitude | float | degrees | -180 to 180 |
| 4 | Human altitude | float | meters MSL | 0-10000 |
| 5 | Human heading | float | degrees | 0-360 |
| 6 | Human speed | float | knots | 0-500 |
| 7 | Wingman latitude | float | degrees | -90 to 90 |
| 8 | Wingman longitude | float | degrees | -180 to 180 |
| 9 | Wingman altitude | float | meters MSL | 0-10000 |
| 10 | Wingman heading | float | degrees | 0-360 |
| 11 | Wingman speed | float | knots | 0-500 |

**Fire Data (8 fires × 8 values = 64 values):**

For each fire i=0 to 7:

| Index | Description | Type | Units | Range |
|-------|-------------|------|-------|-------|
| 12+i*8 | Fire latitude | float | degrees | -90 to 90 |
| 13+i*8 | Fire longitude | float | degrees | -180 to 180 |
| 14+i*8 | Fire altitude | float | meters MSL | 0-10000 |
| 15+i*8 | Fire spotted (boolean) | float | 0/1 | 0 or 1 |
| 16+i*8 | Fire status | float | 0-2 | 0=unspotted, 1=spotted, 2=complete |
| 17+i*8 | Fire classification | float | 0/1/2 | 0=unclass, 1=moderate, 2=severe |
| 18+i*8 | Human in range time | float | seconds | 0-inf |
| 19+i*8 | Wingman in range time | float | seconds | 0-inf |

**Total Size:** 12 + (8 × 8) = 76 values

### 14.C Action Space Specification

**Action Dictionary:**

```python
{
    'type': str,           # Action type: 'hsa' (only type currently supported)
    'goal': tuple,         # (heading, speed, altitude)
    'status': str,         # Optional status string
    'help_request': int,   # Optional fire ID or None
    'messages': list       # Optional list of Message objects
}
```

**Field Details:**

**type:**
- Required: Yes
- Valid values: `'hsa'`
- Description: Heading/Speed/Altitude control

**goal:**
- Required: Yes (if type='hsa')
- Type: `Tuple[float, float, float]`
- Format: `(heading_deg, speed_knots, altitude_meters_msl)`
- Ranges:
  - heading_deg: 0-360
  - speed_knots: 0-max_speed (typically 500)
  - altitude_meters_msl: 0-10000

**status:**
- Required: No
- Type: `str`
- Description: Human-readable status message
- Example: `"Flying to fire 3"`

**help_request:**
- Required: No
- Type: `int` or `None`
- Range: 0-7 (fire ID) or None
- Description: Fire ID for which help is requested

**messages:**
- Required: No
- Type: `list` of Message objects
- Description: Outgoing messages from wingman

### 14.D Mission Configuration JSON Schema

**Fire Targets Mission JSON:**

```json
{
  "Notes": "string (mission description)",
  "windDirection": float (degrees, 0-360),
  "magneticDeclination": float (degrees, typically 10-20),
  "requiredAltitudeFtMSL": float (feet MSL, typically 7000),
  "requiredDropRouteLength": float (NM, typically 2.0),
  "requiredAltitudeFireAGLFt": float (feet AGL, typically 1000),
  "humanStartLLA": [latitude, longitude, altitude_meters],
  "humanStartSpd": float (knots),
  "humanStartHdg": float (degrees),
  "agentStartLLA": [latitude, longitude, altitude_meters],
  "wingmanActive": boolean,
  "dataPoints": [
    {
      "latitude": float (degrees),
      "longitude": float (degrees),
      "altitude": float (meters MSL),
      "type": string ("moderate" | "severe"),
      "image_path": string (filename in HAATO_assets/images/),
      "image_res": [width_pixels, height_pixels]
    },
    // ... 7 more fires (8 total)
  ]
}
```

**Validation Rules:**
- Must have exactly 8 fires in `dataPoints`
- All coordinates within valid ranges
- Image files must exist in assets directory
- Altitudes should be appropriate for terrain

### 14.E Joystick Configuration Reference

**Logitech Extreme 3D Pro:**
- Trigger button: 0
- Classification button: 1
- Fire commands: 2-9
- Follow me: 10
- Hold position: 11

**Thrustmaster T.16000M:**
- Trigger button: 0
- Classification button: 1
- Hat switch: Direction commands
- Fire commands: Base buttons 3-10

**Microsoft Sidewinder:**
- Trigger button: 0
- Classification button: 2
- Fire commands: 4-11

**Custom Configuration:**

Edit `utility/joystick_configs/custom.json`:

```json
{
  "name": "My Custom Joystick",
  "trigger_button": 0,
  "classification_button": 1,
  "command_buttons": {
    "fire_0": 2,
    "fire_1": 3,
    // ... etc
  }
}
```

Load with:
```bash
python run_mission.py --control_prefix custom
```

### 14.F Acronyms and Terminology

- **AGL:** Above Ground Level (altitude)
- **AOR:** Area of Responsibility
- **CSV:** Comma-Separated Values
- **GUI:** Graphical User Interface
- **HSA:** Heading/Speed/Altitude (action type)
- **JSON:** JavaScript Object Notation
- **JSONL:** JSON Lines (one JSON object per line)
- **LLA:** Latitude/Longitude/Altitude
- **MFD:** Multi-Function Display (right G1000)
- **MM:** Mission Manager
- **MSL:** Mean Sea Level (altitude)
- **NM:** Nautical Mile (1.852 km)
- **PFD:** Primary Flight Display (left G1000)
- **RL:** Reinforcement Learning
- **SA:** Situation Awareness
- **UDP:** User Datagram Protocol
- **WoZ:** Wizard of Oz (experimenter control)

### 14.G Recommended Reading

**Human-AI Teaming:**
- Johnson, M., Bradshaw, J. M., Feltovich, P. J., et al. (2014). "Coactive Design: Designing Support for Interdependence in Joint Activity." *Journal of Human-Robot Interaction*, 3(1), 43-69.
- Seeber, I., Bittner, E., Briggs, R. O., et al. (2020). "Machines as Teammates: A Research Agenda on AI in Team Collaboration." *Information & Management*, 57(2), 103174.

**Trust in Automation:**
- Lee, J. D., & See, K. A. (2004). "Trust in Automation: Designing for Appropriate Reliance." *Human Factors*, 46(1), 50-80.
- Jian, J. Y., Bisantz, A. M., & Drury, C. G. (2000). "Foundations for an Empirically Determined Scale of Trust in Automated Systems." *International Journal of Cognitive Ergonomics*, 4(1), 53-71.

**Workload & Situation Awareness:**
- Hart, S. G., & Staveland, L. E. (1988). "Development of NASA-TLX." In *Human Mental Workload*, 139-183.
- Endsley, M. R. (1995). "Toward a Theory of Situation Awareness in Dynamic Systems." *Human Factors*, 37(1), 32-64.

**X-Plane Development:**
- X-Plane Developer Documentation: https://developer.x-plane.com/
- XPPython3 Documentation: https://xppython3.readthedocs.io/
- FlyWithLua Wiki: https://github.com/X-Friese/FlyWithLua/wiki

**Reinforcement Learning:**
- Sutton, R. S., & Barto, A. G. (2018). *Reinforcement Learning: An Introduction* (2nd ed.). MIT Press.
- Gymnasium Documentation: https://gymnasium.farama.org/

---

**END OF COMPREHENSIVE GUIDE**

**Document Information:**
- Version: 1.0
- Last Updated: February 2026
- Total Pages: ~150
- Word Count: ~45,000

**For Questions:**
- GitHub Issues: https://github.com/yourusername/haato/issues
- Email: rbowers32@gatech.edu

**Citation:**
If you use HAATO in your research, please cite:

```bibtex
@software{haato2026,
  author = {Bowers, Ryan and Feder, David},
  title = {HAATO: Human-AI Aerial Teaming Operations Research Testbed},
  year = {2026},
  url = {https://github.com/yourusername/haato}
}
```

---


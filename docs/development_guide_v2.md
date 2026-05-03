# HAATO Development Guide

This guide will walk you through creating custom missions and agents for the HAATO (Human-AI Aerial Teaming Operations) testbed.

## Table of Contents
1. [Architecture Overview](#architecture-overview)

---

## Architecture overview
HAATO has components that live in two main locations:
1. Python root - Where you cloned this repository to. This should NOT be your X-Plane directory
2. X-Plane directory: e.g. C:/X-Plane 12/

`Mission manager`
* Defines and processes a particular mission scenario running within X-Plane. This includes processing objectives, 
moving the agent wingman, monitoring mission progress, and passing messages between the agent and the human. Similar to 
a gymnasium env class.
* This is a python class that lives in the Python root. 

`Wingman` class
* Defines an agent that controls a wingman aircraft in a mission. Receives observations and other messages from the 
MissionManager and passes an action back to the MissionManager

`run_mission.py`: The main entry point that ties everything together
   - Initializes X-Plane connection
   - Creates MissionManager and Wingman instances
   - Runs the main simulation loop
   - Handles data logging and GUI

`Data logger`
* 


When you run a HAATO mission, there are 3 sets of components running simultaneously:
1. X-Plane 12 itself
2. Python scripts in the Python root (e.g. your mission manager)
3. Xppython3 and FlywithLua scripts in the X-plane directory.

Currently we use X-Plane datarefs to communicate between these three components. This is likely not the most efficient
approach so we are considering refactoring the codebase in the future - maybe UDP packets or an xppython3
"orchestrator" plugin that absorbs most of the scripts in the Python root.


# Creating your own missions
You can create your own missions for your own research, or expand on the missions already provided. Reasons you might
want to do this include: More accurately replicating a real-life aviation mission, inducing different human-AI team
dynamics, increasing or decreasing workload, etc.

You should inherit from the MissionManager base class in utility/base_classes.py

## Custom mission mechanics
In HAATO, most of your custom mission mechanics (objectives, entities, time limits, etc.) will "live" in your Python 
scripts, and are only pushed to X-Plane for the purposes of user experience. We do not create entities directly within X-Plane
unless it is necessary in order for the user to experience them (e.g. placing scenery objects). This may seem like an overly
philosophical point but we think it is a useful way to think when developing your own missions. It allows us to keep
90%+ of our development work in Python and only mess with X-Plane's development tools when absolutely necessary.

## Autonomous aircraft (AI wingman)
You can implement AI policies to fly in your custom mission alongside the human pilot. You can implement this however 
you want, but our implementation in the firefighting mission mostly matches the Gymnasium 
convention. The Fire Wingman has an act() method that takes an observation array and returns an action dictionary.

If your AI needs to communicate with other HAATO components using datarefs, it is probably best to pass these back to
the mission manager in the action dictionary and use the mission manager to send the datarefs.

## Working with datarefs
We use datarefs to do two main things:
  1. Update states in X-plane (human position, airspeed, weather conditions, etc.)
  2. Share information between different scripting components. For example, in the firefighting mission, we create custom datarefs to serve as the truth source for the states of the wildfires

### How to read and write datarefs:
In your python root scripts (i.e. not Xppython3), use:
```
# Get current value of the human's latitude
human_lat = self.xpc.getDREF('sim/flightmodel/position/latitude')

# Set mission status dataref to 1.0
self.xpc.sendDREF('custom/haato/mission_status', 1.0)
```

In Xppython3, use:
```
find_dataref("custom/haato/mission_status").value = 1.0 # Set value of the mission_status dataref to 1.0

# It's better to save the dataref handle at init instead of calling find_dataref every time, which is expensive:
self.mission_status_dataref = find_dataref("custom/haato/mission_status")
self.mission_status_dataref.value = 1.0 # Set value of the mission_status dataref to 1.0
```

## Creating custom cockpit instruments
We use Xppython3 to create custom graphical interfaces for the user that render on the existing G1000 cockpit displays.
This allows us to draw shapes, text, and images over top of the existing G1000 displays. For convenience, we've created
classes in /Copy to X-Plane directory/Resources/plugins/PythonPlugins/py_utilities that allow you to define custom screens
and buttons that live on those screens that perform configurable functions when activated.

# Training with reinforcement learning
The current version of HAATO

# Additional Resources
- **X-Plane DataRef Documentation**: https://developer.x-plane.com/datarefs/
- **XPlaneConnect**: https://github.com/nasa/XPlaneConnect
- **FlyWithLua**: https://forums.x-plane.org/index.php?/files/file/38445-flywithlua/

# Contributing
If you develop something new for this testbed, please consider sharing it with the rest of the community! 

For questions and support, contact: rbowers32@gatech.edu
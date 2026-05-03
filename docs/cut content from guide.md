**Target Audience:**
- Researchers studying human-AI teaming
- HCI researchers exploring collaborative decision-making
- Cognitive scientists studying workload, trust, and situation awareness
- AI/ML researchers developing autonomous agents
- Human factors engineers evaluating automation designs

**What You'll Learn:**
- How to install and configure HAATO
- How to run existing missions and collect data
- How to customize missions for your research questions
- How to develop custom AI agent behaviors
- How to extend the system with new visualizations
- Best practices for human-AI teaming experiments

The current version of HAATO implements custom interface elements by using Xppython3's avionics library to
intercept the G1000's rendering and drawing on top of it, so a G1000-equipped aircraft must be used.
If you want to use an aircraft that does NOT have a G1000 in stock X-Plane, you have two options:
1. Dig through the xppython3 avionics library to see what other cockpit instruments can be modified this way: https://xppython3.readthedocs.io/en/latest/development/modules/display_avionics.html#built-in-device-ids
2. Find or create a modified version of your desired aircraft that has an instrument that can be intercepted using Xppython3

**Flight Controls (Recommended):**
- Joystick or yoke for flight control
- Throttle quadrant
- Rudder pedals (optional but helpful)


# Debugging

#### Firewall Configuration

If you encounter connection issues, check firewall settings:

**Windows:**
1. Control Panel → Windows Defender Firewall
2. Advanced Settings → Inbound Rules
3. Ensure X-Plane 12 is allowed on Private networks
4. If not listed, create new rule:
   - Program: `X-Plane.exe`
   - Protocol: UDP
   - Ports: 49000, 49001, 49010
   - Action: Allow

**macOS:**
1. System Preferences → Security & Privacy → Firewall
2. Firewall Options
3. Add X-Plane to allowed applications

#### Test UDP Connection

Create a simple test script to verify Python can communicate with X-Plane:

**File: `test_connection.py`**
```python
"""Test script to verify X-Plane connection"""
from utility.XPlaneConnectX import XPlaneConnectX
import time

print("Testing X-Plane connection...")

try:
    # Create connection
    xpc = XPlaneConnectX(ip='127.0.0.1', port=49000)
    print("✓ XPlaneConnectX created")

    # Test reading a dataref
    lat = xpc.getDREF('sim/flightmodel/position/latitude')
    lon = xpc.getDREF('sim/flightmodel/position/longitude')
    alt = xpc.getDREF('sim/flightmodel/position/elevation')

    print(f"✓ Successfully read aircraft position:")
    print(f"  Latitude:  {lat:.6f}°")
    print(f"  Longitude: {lon:.6f}°")
    print(f"  Altitude:  {alt:.2f} m MSL")

    # Test writing a custom dataref
    xpc.sendDREF('custom/haato/mission_status', 99.0)
    print("✓ Successfully wrote to custom dataref")

    # Read it back
    status = xpc.getDREF('custom/haato/mission_status')
    print(f"✓ Read back custom dataref: {status}")

    if status == 99.0:
        print("\n✓✓✓ ALL TESTS PASSED ✓✓✓")
    else:
        print(f"\n✗ ERROR: Expected 99.0, got {status}")

except Exception as e:
    print(f"\n✗ ERROR: {e}")
    print("\nTroubleshooting:")
    print("- Ensure X-Plane is running")
    print("- Check Network settings are configured correctly")
    print("- Verify firewall allows Python to connect")
    print("- Confirm custom_datarefs.lua is loaded")
```

**Run the test:**
```bash
# 1. Launch X-Plane 12
# 2. Load any aircraft at any airport
# 3. In your terminal (with venv activated):
python test_connection.py
```

**Expected Output:**
```
Testing X-Plane connection...
✓ XPlaneConnectX created
✓ Successfully read aircraft position:
  Latitude:  47.710445°
  Longitude: -121.342879°
  Altitude:  299.32 m MSL
✓ Successfully wrote to custom dataref
✓ Read back custom dataref: 99.0

✓✓✓ ALL TESTS PASSED ✓✓✓
```

REVIEW PROGRESS: Finsihed at line 451
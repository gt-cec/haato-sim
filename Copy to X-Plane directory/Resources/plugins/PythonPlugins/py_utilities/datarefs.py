# class DatarefManager:
#     def __init__(self):
#         self.position = {
#             'latitude': find_dataref("sim/flightmodel/position/latitude"),
#             'longitude': find_dataref('sim/flightmodel/position/longitude'),
#             'altitude': find_dataref('sim/flightmodel/position/elevation'),
#             'heading': find_dataref('sim/flightmodel/position/psi'),
#         }
#         self.velocity = {
#             'vx': find_dataref('sim/flightmodel/position/local_vx'),
#             'vy': find_dataref('sim/flightmodel/position/local_vy'),
#             'vz': find_dataref('sim/flightmodel/position/local_vz'),
#         }
#         self.local = {
#             'x': find_dataref('sim/flightmodel/position/local_x'),
#             'y': find_dataref('sim/flightmodel/position/local_y'),
#             'z': find_dataref('sim/flightmodel/position/local_z'),
#         }
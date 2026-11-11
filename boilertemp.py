# This will measure the temp of the pipe coming out of the boiler.
class BoilerTemp:
    def __init__(self):
        print("setup for thermometer")

    def read(self, dummy_temp=None):
        return dummy_temp



def check_boiler(room_temp, boiler_temp, threshold=5.0):
    """Returns True if boiler is heating things up"""
    return boiler_temp >= (room_temp + threshold)

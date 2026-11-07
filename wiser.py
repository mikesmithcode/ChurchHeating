import os
import asyncio
from datetime import datetime
from dotenv import load_dotenv
from aioWiserHeatAPI.wiserhub import WiserAPI
from aioWiserHeatAPI.helpers.temp import _WiserTemperatureFunctions as tf
from aioWiserHeatAPI.const import TEMP_OFF

load_dotenv()

class WiserController:
    """Streamlined wrapper class for Drayton Wiser Hub focused on rooms, batteries, and schedules."""
    
    def __init__(self):
        self.host = os.getenv("WISER_IP")
        self.secret = os.getenv("WISER_SECRET")
        
        if not self.host or not self.secret:
            raise ValueError("Missing WISER_IP or WISER_SECRET in environment variables or .env file.")
        
        self.wiser: WiserAPI = None

    async def connect(self):
        """Establishes an async connection and reads initial state from the hub."""
        print(f"Connecting to Wiser Hub at {self.host}...")
        self.wiser = WiserAPI(self.host, self.secret)
        await self.wiser.read_hub_data()
        print("Successfully connected and synced hub state.")

    async def get_rooms(self) -> dict:
        """Returns a dict of rooms mapped to timestamp, current_temp, and setpoint_temp."""
        if not self.wiser:
            raise ConnectionError("Not connected to Wiser Hub. Call connect() first.")

        await self.wiser.read_hub_data()
        rooms_dict = {}
        timestamp = datetime.now().isoformat()

        for room in self.wiser.rooms.all:
            current_temp = room.current_temperature if getattr(room, "current_temperature", None) is not None else None
            
            raw_setpoint = room.current_target_temperature if getattr(room, "current_target_temperature", None) is not None else None
            # Handle Wiser's off indicator (negative values like -20)
            setpoint_temp = raw_setpoint if raw_setpoint is not None and raw_setpoint >= 0 else "Off"
            
            rooms_dict[room.name] = {
                "timestamp": timestamp,
                "current_temp": current_temp,
                "setpoint_temp": setpoint_temp
            }

        return rooms_dict

    async def set_room_schedule(self, room_name: str, day_of_week: str, daily_timetable: dict):
        """
        Sets a native schedule timetable for a specified room on a given day 
        by routing directly through the Wiser REST controller with the correct schedule ID.
        """
        if not self.wiser:
            raise ConnectionError("Not connected to Wiser Hub. Call connect() first.")

        await self.wiser.read_hub_data()
        room = next((r for r in self.wiser.rooms.all if r.name.lower() == room_name.lower()), None)
        if not room:
            raise ValueError(f"Room '{room_name}' not found on Wiser system.")

        if not room.schedule:
            raise ValueError(f"Room '{room_name}' does not have an associated schedule.")

        schedule_id = room.schedule.id
        print(f"Compiling schedule for room '{room.name}' (Schedule ID: {schedule_id}) on {day_of_week}...")

        sorted_times = sorted(daily_timetable.keys())
        times_list = []
        temps_list = []

        for time_str in sorted_times:
            temp = daily_timetable[time_str]
            time_str = time_str.strip()
            
            formatted_time = time_str.replace(":", "")
            times_list.append(formatted_time)

            if str(temp).lower() == "off" or temp == -20 or temp == -20.0:
                wiser_temp = tf._to_wiser_temp(TEMP_OFF)
            else:
                wiser_temp = tf._to_wiser_temp(float(temp))
                
            temps_list.append(wiser_temp)

        day_schedule_payload = {
            "Time": times_list,
            "DegreesC": temps_list
        }

        target_day = day_of_week.capitalize()
        
        # Get the underlying schedule dictionary
        payload = room.schedule._schedule_data
        if not isinstance(payload, dict):
            payload = {}

        payload["id"] = schedule_id
        payload["Name"] = room.schedule.name
        payload["Type"] = "Heating"
        payload[target_day] = day_schedule_payload

        # Clean elements before sending
        cleaned_payload = room.schedule._remove_schedule_elements(payload.copy())
        cleaned_payload["id"] = schedule_id
        cleaned_payload["Name"] = room.schedule.name
        cleaned_payload["Type"] = "Heating"

        # Directly invoke the lower-level REST command with the explicit schedule_id
        try:
            success = await room.schedule._wiser_rest_controller._send_schedule_command(
                "UPDATE", cleaned_payload, schedule_id, room.schedule._type
            )
            if success:
                print(f"Successfully updated and pushed schedule for {room.name} on {target_day}.")
            else:
                print(f"Failed to update schedule for {room.name}.")
        except Exception as ex:
            print(f"Error communicating with Wiser hub REST endpoint: {ex}")
            raise

    async def get_device_battery(self) -> list:
        """Extracts the numeric battery percentage from device battery objects safely."""
        if not self.wiser:
            raise ConnectionError("Not connected to Wiser Hub. Call connect() first.")
    
        await self.wiser.read_hub_data()
        battery_status_list = []
    
        for device in self.wiser.devices.all:
            battery_obj = getattr(device, "battery", None)
            battery_pct = None
            
            if battery_obj is not None:
                for attr in ("percent", "level", "battery_percent"):
                    if hasattr(battery_obj, attr):
                        battery_pct = getattr(battery_obj, attr)
                        break
            
            if battery_pct is None:
                for attr in ("battery_percent", "battery_level"):
                    if hasattr(device, attr):
                        battery_pct = getattr(device, attr)
                        break
    
            if battery_pct is not None:
                room_name = "Unassigned"
                if hasattr(device, "room_id") and device.room_id is not None:
                    room = self.wiser.rooms.get_by_id(device.room_id)
                    if room:
                        room_name = room.name
    
                battery_status_list.append({
                    "device_id": device.id,
                    "device_type": str(getattr(device, "product_type", "Unknown")),
                    "room": room_name,
                    "battery_percentage": battery_pct
                })
    
        return battery_status_list

def create_timestamp(date_str: str, time_str: str) -> datetime:
    """
    Combines separate date and time strings into a single datetime object,
    supporting 2-digit or 4-digit years and partial time strings.
    """
    date_str = date_str.strip()
    time_str = time_str.strip()
    
    date_format = "%y-%m-%d" if len(date_str.split("-")[0]) == 2 else "%Y-%m-%d"
    parsed_date = datetime.strptime(date_str, date_format).date()
    
    time_parts = time_str.split(":")
    if len(time_parts) == 1:
        time_format = "%H"
    elif len(time_parts) == 2:
        time_format = "%H:%M"
    else:
        time_format = "%H:%M:%S"
        
    parsed_time = datetime.strptime(time_str, time_format).time()
    
    return datetime.combine(parsed_date, parsed_time)

# --- Example Test Execution Block ---
async def main():
    controller = WiserController()
    await controller.connect()
    
    # 1. Fetch rooms and thermal metrics
    rooms = await controller.get_rooms()
    print("Rooms Status:", rooms)
    
    # 2. Check device battery levels
    batteries = await controller.get_device_battery()
    print("Device Batteries:", batteries)

    print("\nValid rooms:", list(rooms.keys()))
    
    # 3. Example schedule compilation test
    friday_schedule = {
        "07:00": 19.5,
        "09:30": 12.0,  # Setback
        "17:00": 21.0,  # Pre-heat for evening event
        "22:00": "Off"  # Shutdown
    }
    await controller.set_room_schedule("Front Room", "Friday", friday_schedule)

if __name__ == "__main__":
    asyncio.run(main())

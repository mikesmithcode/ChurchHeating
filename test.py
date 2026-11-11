import asyncio
import os
from dotenv import load_dotenv
from comms_bot.bot import CommsBot
from wiser import WiserController  # Assuming your Wiser code is in wiser.py
from boilertemp import BoilerTemp, check_boiler

load_dotenv()

class AutomationController:
    """Master controller that unifies CommsBot and WiserController on a single event loop."""
    
    def __init__(self, config_path: str = "bot.json", default_room="Loung"):
        self.bot = CommsBot(config_path=config_path)
        self.heating = WiserController()
        self.thermometer = BoilerTemp()
        self.default_room = default_room
        self.is_running = False
        self._active_task = None

    async def initialize(self):
        """Connects to the Wiser Hub and starts the Telegram bot listener."""
        print("Initializing Automation Controller...")
        
        # Connect to Wiser Hub first
        await self.heating.connect()
        
        # Start the Telegram Bot (performs handshake & polling)
        await self.bot.start()
        self.is_running = True
        print("🤖 CommsBot and Wiser Controller are fully initialized and linked.")

    async def handle_telegram_messages(self):
        """Continuous background loop processing incoming Telegram commands."""
        while self.is_running:
            try:
                # Wait for the next incoming packet from Telegram
                msg_packet = await self.bot.get_msg()
                text = msg_packet.get("text", "").strip()
                username = msg_packet.get("username", "User")
                
                print(f"\n📩 Message from {username}: {text}")

                # Command Routing
                if text.startswith("/temp"):
                    room_name = self.default_room

                    try:
                        room_data = await self.heating.get_room(room_name)
                        heating_status = "Yes 🔥" if room_data['calling_for_heat'] else "No ❄️"
                        response_text = (
                            f"🌡️ **Room:** {room_data['room']}\n"
                            f"• Current Temp: {room_data['current_temp']}°C\n"
                            f"• Setpoint: {room_data['setpoint_temp']}\n"
                            f"• Calling for Heat: {heating_status}"
                        )
                        await self.bot.send_msg(response_text)
                    except ValueError as ve:
                        await self.bot.send_msg(f"❌ Error: {ve}")
                    except Exception as ex:
                        await self.bot.send_msg(f"⚠️ Failed to retrieve room data: {ex}")

                elif text.startswith("/battery"):
                    try:
                        battery_list = await self.heating.get_device_battery()
                        if not battery_list:
                            await self.bot.send_msg("🔋 No battery devices found.")
                        else:
                            # Format each device in the battery status list
                            battery_lines = []
                            for dev in battery_list:
                                battery_lines.append(
                                    f"• **{dev['room']}** ({dev['device_type']}): {dev['battery_percentage']}%"
                                )
                            response_text = "🔋 **Device Batteries:**\n" + "\n".join(battery_lines)
                            await self.bot.send_msg(response_text)
                    except ValueError as ve:
                        await self.bot.send_msg(f"❌ Error: {ve}")
                    except Exception as ex:
                        await self.bot.send_msg(f"⚠️ Failed to retrieve battery data: {ex}")

                elif text.startswith("/check"):
                    boost_temp=20.0
                    room_name = self.default_room
                    boost_duration=30

                    async def run_checked_boost():
                        try:
                            await self.bot.send_msg(f"🔥 Boosting **{room_name}** to {boost_temp}°C to test boiler response...")
                            await self.heating.boost_room(room_name, temp=boost_temp, duration_minutes=boost_duration)
                            await self.trigger_boiler_check(room_name=room_name)
                        finally:
                            await self.heating.cancel_boost(room_name)
                            await self.bot.send_msg(f"🛑 Test complete. Reverted **{room_name}** back to Auto schedule.")


                    # Spawn the complete workflow as a background task so it doesn't block the bot
                    asyncio.create_task(run_checked_boost())
                    # Spawn as a background task so it doesn't block the bot's command loop
                    asyncio.create_task(self.trigger_boiler_check())
                    await self.bot.send_msg("🔍 Running routine check on the heating system...")

                elif text.startswith("/start"):
                    await self.bot.send_msg("🤖 Bot is connected and active! Use `/temp <room>`, `/battery`, or `/check`.")

                else:
                    await self.bot.send_msg(f"❓ Unknown command: `{text}`. Type `/start` for info.")

            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"⚠️ Error in message handler loop: {e}")
                await asyncio.sleep(1)

    async def trigger_boiler_check(self, room_name: str = "Lounge", delay_seconds: int = 180, threshold: float = 5.0, max_attempts: int = 3):
        """
        Triggers a deferred check that loops up to `max_attempts` times silently on failure. 
        Exits early if confirmed working, or sends the final check failed message after all attempts fail.
        """
        await self.bot.send_msg(
            f"🔍 **Boiler check initiated** for **{room_name}**.\n"
            f"⏳ This could take up to {delay_seconds * max_attempts}. "
        )

        for attempt in range(1, max_attempts + 1):
            # Wait for the warm-up/polling interval
            await asyncio.sleep(delay_seconds)

            try:
                room_data = await self.heating.get_room(room_name)
                room_temp = room_data.get("current_temp")
                boiler_temp = self.thermometer.read(dummy_temp=20) # Replace with real sensor read

                if room_temp is not None and boiler_temp is not None:
                    is_working = check_boiler(room_temp, boiler_temp, threshold=threshold)
                    delta = round(boiler_temp - room_temp, 1)

                    if is_working:
                        await self.bot.send_msg(
                            f"✅ **Boiler Status: WORKING** (Attempt {attempt}/{max_attempts})\n"
                            f"• Room ({room_name}): {room_temp}°C\n"
                            f"• Boiler Outlet: {boiler_temp}°C\n"
                            f"• Delta: +{delta}°C (Threshold: {threshold}°C)"
                        )
                        return True # Success! Exit loop early.

            except Exception as ex:
                print(f"Error during boiler check attempt {attempt}: {ex}")

        # If the loop completes without ever returning True, all attempts failed
        await self.bot.send_msg(
            f"❌ **Boiler Check Failed:** Could not confirm heat after {max_attempts} attempts "
            f"(threshold {threshold}°C not met for {room_name})."
        )
        return False

    async def run(self):
        """Main entrypoint starting all concurrent background workers."""
        await self.initialize()

        # Start the message listener task
        message_task = asyncio.create_task(self.handle_telegram_messages())

        try:
            # Keep the event loop running concurrently
            await asyncio.gather(message_task)
        except KeyboardInterrupt:
            print("\nShutting down controller gracefully...")
        finally:
            self.is_running = False
            await self.bot.stop()
            print("👋 Controller stopped.")

if __name__ == "__main__":
    controller = AutomationController()
    asyncio.run(controller.run())

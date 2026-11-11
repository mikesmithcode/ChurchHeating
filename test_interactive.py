import asyncio
from aioconsole import ainput, aprint
from comms_bot.bot import CommsBot

async def terminal_input_loop(bot: CommsBot):
    """Continuously reads input from the terminal asynchronously."""
    await aprint("\n[Terminal Ready] Type a message here and press Enter to send it to Telegram.")
    await aprint("Type 'exit' or 'quit' to stop.\n")
    
    while True:
        try:
            user_input = await ainput("You (Terminal) > ")
            
            if not user_input.strip():
                continue
            if user_input.lower() in ["exit", "quit"]:
                break
            if bot.chat_id is None:
                await aprint("⚠️ Cannot send message yet: No chat_id established.")
                continue
                
            await bot.send_msg(user_input)
            await aprint("📤 Sent to Telegram successfully.")
            
        except (KeyboardInterrupt, EOFError):
            break

async def telegram_listener(bot: CommsBot):
    """Listens to the bot queue and prints incoming commands."""
    while True:
        msg_packet = await bot.get_msg()
        await aprint(f"\n📩 From {msg_packet['username']}: {msg_packet['text']}")
        
        # Example: Respond with text, web links, or image assets
        await bot.send_msg("Acknowledged command.")
        # await bot.send_link("http://localhost:8080/lab/entry_1.html", title="Lab Entry #1")
        # await bot.send_image("path/to/plot.png", caption="Particle Analysis")

async def main():
    bot = CommsBot(config_path="bot.json")
    await bot.start()
    await aprint("🤖 Bot is polling... Send a command on Telegram.")

    telegram_listener_task = asyncio.create_task(telegram_listener(bot))
    terminal_writer_task = asyncio.create_task(terminal_input_loop(bot))

    try:
        await asyncio.gather(telegram_listener_task, terminal_writer_task)
    except KeyboardInterrupt:
        await aprint("\nShutting down...")
    finally:
        await bot.stop()

if __name__ == "__main__":
    asyncio.run(main())

import discord
from discord.ext import commands
import yt_dlp
import asyncio
from dotenv import load_dotenv
import os

# Load environment variables from .env file
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.guilds = True

bot = commands.Bot(command_prefix='!', intents=intents)

# Song queue and state flags
song_queue = []
is_playing = False  # Flag to manage playback state
is_skipping = False  # Flag to track user-initiated skips

# FFmpeg options with reconnecting, volume adjustment, and disabling video
ffmpeg_options = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn -filter:a "volume=0.25"'  # Volume adjustment and no video
}

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}')

async def ensure_voice_connection(ctx, voice_client):
    """Ensure the bot is connected to the correct voice channel."""
    if not voice_client or not voice_client.is_connected():
        if ctx.author.voice:
            channel = ctx.author.voice.channel
            voice_client = await channel.connect()
            await ctx.send(f"Reconnected to {channel}")
        else:
            await ctx.send("You need to be in a voice channel to use this command!")
            return None
    return voice_client

async def play_next_song(ctx, voice_client):
    """Play the next song in the queue."""
    global is_playing, is_skipping
    if not voice_client.is_connected():
        await ctx.send("I'm not connected to a voice channel.")
        is_playing = False
        return

    if song_queue:
        # Get the next song
        url, title = song_queue.pop(0)
        is_playing = True
        is_skipping = False  # Reset skipping flag

        # yt-dlp options to extract the best audio URL
        ydl_opts = {
            'format': 'bestaudio/best',
            'quiet': True,
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                audio_url = info['url']

            # Play the audio stream using FFmpegOpusAudio
            def after_playback(error):
                """Callback to handle playback completion."""
                global is_playing
                if voice_client.source:
                    voice_client.source.cleanup()  # Clean up the current FFmpeg source

                if is_skipping:
                    print(f"Playback skipped for {title}.")
                elif error:
                    print(f"Error during playback: {error}")
                else:
                    print(f"Playback finished for {title}.")

                # Mark playback as completed and schedule the next song
                is_playing = False
                if not is_skipping:  # Only proceed if not skipping
                    asyncio.run_coroutine_threadsafe(
                        play_next_song(ctx, voice_client), bot.loop
                    )

            voice_client.play(
                discord.FFmpegOpusAudio(audio_url, **ffmpeg_options),
                after=after_playback
            )
            await ctx.send(f"Now playing: {title}")

        except Exception as e:
            await ctx.send(f"An error occurred while playing the song: {e}")
            print(f"Error with FFmpeg process: {e}")
            # Mark playback as completed and proceed to the next song
            is_playing = False
            await play_next_song(ctx, voice_client)
    else:
        await ctx.send("Queue is empty. Disconnecting.")
        is_playing = False
        await voice_client.disconnect()

@bot.command()
async def playlink(ctx, url: str):
    """Add a song to the queue and play it if not already playing."""
    global is_playing
    voice_client = discord.utils.get(bot.voice_clients, guild=ctx.guild)

    # Automatically join the user's voice channel if not already connected
    if not voice_client:
        if ctx.author.voice:
            channel = ctx.author.voice.channel
            voice_client = await channel.connect()
            await ctx.send(f"Joined {channel}")
        else:
            await ctx.send("You need to be in a voice channel to use this command!")
            return

    # yt-dlp options to extract metadata
    ydl_opts = {
        'format': 'bestaudio/best',
        'quiet': True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            title = info['title']
        
        # Add song to the queue
        song_queue.append((url, title))
        await ctx.send(f"Added to queue: {title}")

        # If nothing is currently playing, start playback
        if not is_playing:
            await play_next_song(ctx, voice_client)

    except Exception as e:
        await ctx.send(f"An error occurred: {e}")

@bot.command()
async def play(ctx, *, query: str):
    """Search for a song on YouTube and play the first result."""
    global is_playing
    voice_client = discord.utils.get(bot.voice_clients, guild=ctx.guild)

    # Automatically join the user's voice channel if not already connected
    if not voice_client:
        if ctx.author.voice:
            channel = ctx.author.voice.channel
            voice_client = await channel.connect()
            await ctx.send(f"Joined {channel}")
        else:
            await ctx.send("You need to be in a voice channel to use this command!")
            return

    # yt-dlp options to search for the song
    ydl_opts = {
        'format': 'bestaudio/best',
        'quiet': True,
        'default_search': 'ytsearch',  # Search on YouTube
        'noplaylist': True,  # Ensure single result
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(query, download=False)
            first_result = info['entries'][0]  # Get the first result
            title = first_result['title']
            url = first_result['webpage_url']

        # Add the song to the queue
        song_queue.append((url, title))
        await ctx.send(f"Found and added to queue: {title}")

        # If nothing is currently playing, start playback
        if not is_playing:
            await play_next_song(ctx, voice_client)

    except Exception as e:
        await ctx.send(f"An error occurred during search: {e}")
        print(f"Error during play: {e}")

@bot.command()
async def queue(ctx):
    """Display the current song queue."""
    if song_queue:
        queue_list = "\n".join([f"{i+1}. {title}" for i, (_, title) in enumerate(song_queue)])
        await ctx.send(f"Current Queue:\n{queue_list}")
    else:
        await ctx.send("The queue is currently empty.")

@bot.command()
async def skip(ctx):
    """Skip the current song and play the next one in the queue."""
    global is_playing, is_skipping
    voice_client = discord.utils.get(bot.voice_clients, guild=ctx.guild)
    if not voice_client or not voice_client.is_playing():
        await ctx.send("There's no song currently playing.")
        return

    # Stop the current song
    await ctx.send("Skipping the current song...")
    try:
        is_playing = False  # Reset the playback flag
        is_skipping = True  # Set the skipping flag

        # Clean up the current audio source
        if voice_client.source:
            voice_client.source.cleanup()

        # Stop the current playback
        voice_client.stop()

        # Add a short delay for cleanup before starting the next song
        await asyncio.sleep(0.5)
        await play_next_song(ctx, voice_client)

    except Exception as e:
        await ctx.send(f"An error occurred while skipping: {e}")
        print(f"Error in skip function: {e}")

@bot.command()
async def leave(ctx):
    """Disconnect the bot from the voice channel."""
    global is_playing
    voice_client = discord.utils.get(bot.voice_clients, guild=ctx.guild)
    if voice_client:
        is_playing = False
        await voice_client.disconnect()
        await ctx.send("Disconnected from the voice channel!")
    else:
        await ctx.send("I'm not connected to any voice channel.")

# Run the bot with the token loaded from the .env file
bot.run(TOKEN)

import os
import discord
import concurrent.futures
from discord import app_commands
from discord.ext import commands
from yt_dlp import YoutubeDL
from collections import deque
import asyncio
import logging
import uuid

logging.basicConfig(level=logging.INFO)

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

CACHE_DIR = "audio_cache"
TOKEN = os.getenv("TOKEN")

if not os.path.exists(CACHE_DIR):
    os.makedirs(CACHE_DIR)

ytdl_opts = {
    'format': 'bestaudio/best',
    'extract_audio': True,
    'audioformat': 'mp3',
    'noplaylist': True,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0',
    'outtmpl': os.path.join(CACHE_DIR, 'temp_audio.%(ext)s'),
    'nopart': False,
    'cookiefile': 'cookies.txt',
    'concurrent_fragment_downloads': 4,
    'http_headers': {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:136.0) Gecko/20100101 Firefox/136.0',
        'Referer': 'https://www.youtube.com/',
        'Accept-Language': 'en-US,en;q=0.9',
        'Origin': 'https://www.youtube.com',
        'Sec-Fetch-Dest': 'empty',
        'Sec-Fetch-Mode': 'cors',
        'Sec-Fetch-Site': 'same-site',
    },
}

ffmpeg_options = {
    'options': '-vn -af "aresample=44100,loudnorm=I=-14:TP=-1.5:LRA=11,compand=attacks=0:points=-80/-80|-20/-20|0/-12|20/-8,equalizer=f=100:t=q:w=1:g=3,equalizer=f=1000:t=q:w=2:g=1,equalizer=f=5000:t=q:w=2:g=2"',
}

queue = deque()

async def download_audio(query):
    try:
        with YoutubeDL(ytdl_opts) as ydl:
            info = ydl.extract_info(query, download=True)
            if 'entries' in info:
                info = info['entries'][0]

            short_filename = f"{uuid.uuid4().hex}.mp3" 
            short_filepath = os.path.join(CACHE_DIR, short_filename)

            temp_filepath = ydl.prepare_filename(info) 
            if not os.path.exists(temp_filepath):
                temp_filepath = os.path.join(CACHE_DIR, 'temp_audio.mp3')
            os.rename(temp_filepath, short_filepath)

            return short_filepath, info.get('title', 'Unknown Title')
    except Exception as e:
        logging.error(f"Error downloading audio: {e}")
        return None, None

def delete_file(filepath):
    try:
        if os.path.exists(filepath):
            os.unlink(filepath)
            logging.info(f"Deleted file: {filepath}")
        else:
            logging.warning(f"File not found: {filepath}")
    except Exception as e:
        logging.error(f"Error deleting file {filepath}: {e}")

@bot.event
async def on_ready():
    logging.info(f'Logged in as {bot.user}')
    await bot.tree.sync()

@bot.tree.command(name="join", description="Join the voice channel.")
async def join(interaction: discord.Interaction):
    if interaction.user.voice:
        channel = interaction.user.voice.channel
        await channel.connect()
        await interaction.response.send_message(f"Joined {channel.name}!")
    else:
        await interaction.response.send_message("You are not in a voice channel!", ephemeral=True)

@bot.tree.command(name="leave", description="Leave the voice channel.")
async def leave(interaction: discord.Interaction):
    if interaction.guild.voice_client:
        await interaction.guild.voice_client.disconnect()
        await interaction.response.send_message("Left the voice channel!")
    else:
        await interaction.response.send_message("I'm not in a voice channel!", ephemeral=True)

@bot.tree.command(name="play", description="Play audio from a YouTube URL.")
@app_commands.describe(query="The YouTube URL or search query to play.")
async def play(interaction: discord.Interaction, query: str):
    await interaction.response.defer()

    if not interaction.user.voice:
        await interaction.followup.send("You are not in a voice channel!", ephemeral=True)
        return

    if not interaction.guild.voice_client:
        channel = interaction.user.voice.channel
        await channel.connect()

    try:
        if not query.startswith(('http://', 'https://')):
            query = f"ytsearch:{query}"

        filepath, title = await download_audio(query)
        if not filepath:
            await interaction.followup.send("Failed to download audio. Please try again.")
            return

        if interaction.guild.voice_client.is_playing():
            queue.append((filepath, title))
            await interaction.followup.send(f"Added to queue: **{title}**")
        else:
            interaction.guild.voice_client.play(
                discord.FFmpegPCMAudio(filepath, **ffmpeg_options),
                after=lambda e: bot.loop.create_task(play_next(interaction, filepath))
            )
            await interaction.followup.send(f"Now playing: **{title}**")
    except Exception as e:
        logging.error(f"Error in play command: {e}")
        await interaction.followup.send("An error occurred while processing your request. Please try again.")

async def play_next(interaction: discord.Interaction, current_filepath: str):
    delete_file(current_filepath)

    if queue:
        filepath, title = queue.popleft()
        interaction.guild.voice_client.play(discord.FFmpegPCMAudio(filepath, **ffmpeg_options), after=lambda e: bot.loop.create_task(play_next(interaction, filepath)))
        await interaction.followup.send(f"Now playing: **{title}**")
    else:
        await interaction.followup.send("Queue is empty!")

@bot.tree.command(name="next", description="Skip the current song.")
async def next(interaction: discord.Interaction):
    if interaction.guild.voice_client:
        interaction.guild.voice_client.stop()
        await interaction.response.send_message("Skipped the current song!")
    else:
        await interaction.response.send_message("Nothing is playing!", ephemeral=True)

@bot.tree.command(name="queue", description="Show the current queue.")
async def queue_list(interaction: discord.Interaction):
    if queue:
        queue_titles = [title for _, title in queue]
        await interaction.response.send_message("Current queue:\n" + "\n".join(queue_titles))
    else:
        await interaction.response.send_message("The queue is empty!")

@bot.tree.command(name="stop", description="Stop playing audio and clear the queue.")
async def stop(interaction: discord.Interaction):
    if interaction.guild.voice_client:
        interaction.guild.voice_client.stop()
        queue.clear()
        await interaction.response.send_message("Stopped playing and cleared the queue!")
    else:
        await interaction.response.send_message("I'm not playing anything!", ephemeral=True)

bot.run(TOKEN)
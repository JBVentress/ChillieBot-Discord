import yt_dlp
import tempfile
import urllib.parse
import os
import discord
from discord.ext import commands, tasks
import random
import aiohttp
import asyncio
import json
import re
import time
from datetime import datetime, timedelta
from collections import Counter, defaultdict, deque
from typing import Optional, Dict, List
import shutil

# ============== ENV LOADER ==============
def load_env():
    try:
        with open('.env') as f:
            for line in f:
                if '=' in line and not line.strip().startswith('#'):
                    key, value = line.strip().split('=', 1)
                    if value.startswith('"') and value.endswith('"'):
                        value = value[1:-1]
                    os.environ[key] = value
        print("✅ .env file loaded")
    except FileNotFoundError:
        print("❌ .env file not found")

load_env()

# ============== ADVANCED MEMORY MODULE ==============
MEMORY_FILE = 'bot_memory.json'

bot_memory = {
    "global_chat": [],
    "games_by_user": {},
    "user_data": defaultdict(lambda: {
        "messages": [],
        "roblox_games": [],
        "game_updates": defaultdict(list)
    })
}

def load_memory():
    global bot_memory
    if os.path.exists(MEMORY_FILE):
        with open(MEMORY_FILE, 'r', encoding='utf-8') as f:
            bot_memory = json.load(f)
            print("✅ Memory loaded.")
    else:
        print("ℹ️ No memory file found, starting fresh.")

def save_memory():
    with open(MEMORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(bot_memory, f, indent=4)
        print("💾 Memory saved.")

load_memory()
TOKEN = os.getenv('DISCORD_BOT_TOKEN')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', "AIzaSyB4qHLV5PDclTxtzxqUXv-BFky5rYSNhIQ")
GEMINI_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
OWNER_IDS = [int(id) for id in os.getenv('OWNER_IDS', '').split(',') if id.isdigit()]
THEBESTCHILLIEDOG_ID = int(os.getenv('THEBESTCHILLIEDOG_ID', 0))
TOPMEDIAI_API_KEY = os.getenv('TOPMEDIAI_API_KEY', "ed18fca6ae5d401b93f07255016927c5")
TOPMEDIAI_BASE_URL = "https://api.topmediai.com/v1"

# ============== BOT INIT ==============
intents = discord.Intents.default()
intents.message_content = True
intents.presences = True
intents.members = True
intents.messages = True
bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

# ============== DATA STORAGE ==============
user_exp = {}
user_money = {}
user_daily_cooldown = {}
user_work_cooldown = {}
channel_topics = {}
channel_context = {}
active_topics = {}
bot_mood = "neutral"
bot_feelings = defaultdict(str)
cover_jobs = {}  # Track cover generation jobs
user_cover_cooldown = {}  # Prevent spam
temp_files = set()  # Track temporary files for cleanup
temp_dirs = set()   # Track temporary directories for cleanup

# ============== CONVERSATION MEMORY ==============
conversation_memory = defaultdict(lambda: {
    "history": deque(maxlen=20),
    "last_updated": datetime.now(),
    "channel_history": deque(maxlen=50)
})

def update_memory(user_id: int, user_msg: str, bot_msg: str, channel_id: int = None):
    conversation_memory[user_id]["history"].append({"role": "user", "content": user_msg})
    conversation_memory[user_id]["history"].append({"role": "bot", "content": bot_msg})
    conversation_memory[user_id]["last_updated"] = datetime.now()
    
    if channel_id:
        conversation_memory[channel_id]["channel_history"].append(
            {"author": user_id, "content": user_msg}
        )

def get_memory(user_id: int, channel_id: int = None) -> str:
    context = []
    
    if user_id in conversation_memory:
        history = conversation_memory[user_id]["history"]
        context.extend(
            f"{msg['role']}: {msg['content']}" 
            for msg in history
        )
    
    if channel_id and channel_id in conversation_memory:
        channel_messages = conversation_memory[channel_id]["channel_history"]
        for msg in channel_messages:
            author_id = msg["author"]
            author = bot.get_user(author_id)
            author_name = author.display_name if author else f"User{author_id}"
            context.append(f"{author_name}: {msg['content']}")
    
    return "\n".join(context[-30:])

# ============== MOOD SYSTEM ==============
def get_mood_prompt() -> str:
    mood_descriptions = {
        "neutral": "Respond naturally like a human. Don't mention being an AI.",
        "happy": "Respond enthusiastically but keep it human-like. Show excitement.",
        "angry": "Respond with irritation or frustration. Be blunt and short-tempered.",
        "sarcastic": "Respond with sarcasm and dry humor. Be witty.",
        "depressed": "Respond with melancholy and pessimism. Keep responses short."
    }
    
    base = mood_descriptions.get(bot_mood, mood_descriptions["neutral"])
    feelings = bot_feelings.get(bot_mood, "")
    
    return f"{base} {feelings}".strip()

# ============== AI RESPONSE (FIXED) ==============
async def get_ai_response(prompt: str, user_id: Optional[int] = None, channel_id: Optional[int] = None) -> str:
    try:
        memory = get_memory(user_id, channel_id) if user_id else ""
        mood_prompt = get_mood_prompt()
        
        full_prompt = (
            f"Context (recent messages in this channel):\n{memory}\n\n"
            f"Current mood: {mood_prompt}\n\n"
            f"User message: {prompt}\n\n"
            "Respond naturally as a human would. Never mention being an AI or language model. "
            "Keep responses concise (1-2 sentences usually)."
        )

        async with aiohttp.ClientSession() as session:
            payload = {
                "contents": [{"parts": [{"text": full_prompt}]}],
                "generationConfig": {
                    "temperature": 0.8 if bot_mood != "depressed" else 0.5,
                    "maxOutputTokens": 150
                }
            }
            
            try:
                async with session.post(GEMINI_API_URL, json=payload, timeout=30) as response:
                    if response.status == 200:
                        data = await response.json()
                        try:
                            candidates = data.get('candidates', [])
                            if candidates and len(candidates) > 0:
                                content = candidates[0].get('content', {})
                                parts = content.get('parts', [])
                                if parts and len(parts) > 0:
                                    text = parts[0].get('text', '')
                                    return text.strip()[:200]
                        except (KeyError, IndexError) as e:
                            print(f"⚠️ Error parsing API response: {e}")
                    else:
                        error_text = await response.text()
                        print(f"⚠️ API returned error {response.status}: {error_text}")
            except asyncio.TimeoutError:
                print("⚠️ AI API request timed out")
                
    except Exception as e:
        print(f"⚠️ AI Error: {str(e)}")
    
    # Fallback responses based on mood
    if bot_mood == "happy":
        return random.choice(["Yeah!", "Awesome!", "That's great!"])
    elif bot_mood == "angry":
        return random.choice(["Ugh.", "Whatever.", "Not now."])
    elif bot_mood == "sarcastic":
        return random.choice(["Oh great.", "How original.", "Wow, amazing."])
    elif bot_mood == "depressed":
        return random.choice(["I guess...", "Does it matter?", "*sigh*"])
    return random.choice(["Hmm.", "Interesting.", "I see."])

# ============== UTILITY FUNCTIONS ==============
async def cleanup_temp_files():
    """Clean up any remaining temporary files"""
    for file_path in list(temp_files):
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
            temp_files.remove(file_path)
        except Exception as e:
            print(f"⚠️ Error cleaning up temp file {file_path}: {e}")
    
    for dir_path in list(temp_dirs):
        try:
            if os.path.exists(dir_path):
                shutil.rmtree(dir_path)
            temp_dirs.remove(dir_path)
        except Exception as e:
            print(f"⚠️ Error cleaning up temp directory {dir_path}: {e}")

def sanitize_filename(filename: str) -> str:
    """Sanitize filenames to be filesystem-safe"""
    return re.sub(r'[\\/*?:"<>|]', "", filename).strip()

def is_valid_youtube_url(url: str) -> bool:
    """Check if URL is a valid YouTube link"""
    youtube_patterns = [
        r'(?:https?://)?(?:www\.)?youtube\.com/watch\?v=[\w-]+',
        r'(?:https?://)?(?:www\.)?youtu\.be/[\w-]+',
        r'(?:https?://)?(?:www\.)?youtube\.com/embed/[\w-]+',
        r'(?:https?://)?(?:www\.)?youtube\.com/v/[\w-]+'
    ]
    return any(re.match(pattern, url) for pattern in youtube_patterns)

# ============== YOUTUBE AUDIO EXTRACTION ==============
async def extract_youtube_audio(youtube_url: str) -> Optional[str]:
    """Extract audio from YouTube video and return file path"""
    temp_dir = tempfile.mkdtemp()
    temp_dirs.add(temp_dir)
    output_path = None
    
    try:
        ydl_opts = {
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'outtmpl': os.path.join(temp_dir, '%(id)s.%(ext)s'),
            'restrictfilenames': True,
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'force_generic_extractor': False,  # Changed to False for better compatibility
            'noplaylist': True,
            'ignoreerrors': False,
            'logger': None,
            'socket_timeout': 30,
            'retries': 3,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # Run in a separate thread to not block the event loop
            info = await asyncio.to_thread(ydl.extract_info, youtube_url, download=True)
            
            if not info:
                raise ValueError("Failed to extract video info")
            
            # Find the actual downloaded file
            downloaded_files = [f for f in os.listdir(temp_dir) if f.endswith('.mp3')]
            if not downloaded_files:
                raise ValueError("No MP3 file found after extraction")
            
            output_path = os.path.join(temp_dir, downloaded_files[0])
            temp_files.add(output_path)
            
            return output_path
            
    except Exception as e:
        print(f"⚠️ YouTube extraction error: {e}")
        if temp_dir and os.path.exists(temp_dir):
            try:
                shutil.rmtree(temp_dir)
                temp_dirs.remove(temp_dir)
            except Exception as cleanup_error:
                print(f"⚠️ Error cleaning up temp dir: {cleanup_error}")
        return None

# ============== COVER GENERATION SYSTEM ==============
class CoverView(discord.ui.View):
    def __init__(self, youtube_url: str, user_id: int):
        super().__init__(timeout=300)
        self.youtube_url = youtube_url
        self.user_id = user_id
        self.models = {
            "taylor_swift": {"name": "Taylor Swift", "emoji": "🎤"},
            "ariana_grande": {"name": "Ariana Grande", "emoji": "✨"},
            "drake": {"name": "Drake", "emoji": "🎵"},
            "ed_sheeran": {"name": "Ed Sheeran", "emoji": "🎸"},
            "billie_eilish": {"name": "Billie Eilish", "emoji": "🌙"},
            "the_weeknd": {"name": "The Weeknd", "emoji": "🌃"},
            "dua_lipa": {"name": "Dua Lipa", "emoji": "💫"},
            "justin_bieber": {"name": "Justin Bieber", "emoji": "🎶"},
            "adele": {"name": "Adele", "emoji": "💝"},
            "post_malone": {"name": "Post Malone", "emoji": "🎭"},
            "olivia_rodrigo": {"name": "Olivia Rodrigo", "emoji": "🎹"},
            "bruno_mars": {"name": "Bruno Mars", "emoji": "🕺"}
        }
        
        # Create buttons for each model (max 25 buttons per view)
        for model_id, model_info in list(self.models.items())[:20]:
            button = discord.ui.Button(
                label=model_info["name"],
                emoji=model_info["emoji"],
                style=discord.ButtonStyle.primary,
                custom_id=model_id
            )
            button.callback = self.create_callback(model_id)
            self.add_item(button)
    
    def create_callback(self, model_id):
        async def callback(interaction: discord.Interaction):
            if interaction.user.id != self.user_id:
                await interaction.response.send_message("❌ This isn't your cover request!", ephemeral=True)
                return
            
            await interaction.response.defer(thinking=True)
            
            # Start cover generation
            job_id = await start_cover_generation(self.youtube_url, model_id, interaction.user.id)
            
            if job_id:
                embed = discord.Embed(
                    title="🎵 AI Cover Started!",
                    description=f"**Model**: {self.models[model_id]['emoji']} {self.models[model_id]['name']}\n"
                               f"**Status**: 🔄 Processing...\n"
                               f"**Estimated Time**: 2-5 minutes",
                    color=0x00ff00
                )
                embed.set_footer(text=f"Job ID: {job_id}")
                
                status_view = CoverStatusView(job_id, interaction.user.id)
                await interaction.followup.send(embed=embed, view=status_view)
                
                # Start background task to check status
                bot.loop.create_task(check_cover_status(job_id, interaction.channel, interaction.user.id))
            else:
                await interaction.followup.send(content="❌ Failed to start cover generation. Please try again later.", ephemeral=True)
        
        return callback

class CoverStatusView(discord.ui.View):
    def __init__(self, job_id: str, user_id: int):
        super().__init__(timeout=600)
        self.job_id = job_id
        self.user_id = user_id
    
    @discord.ui.button(label="Check Status", emoji="🔄", style=discord.ButtonStyle.secondary)
    async def check_status(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ This isn't your cover request!", ephemeral=True)
            return
        
        await interaction.response.defer(thinking=True)
        status = await get_cover_status(self.job_id)
        
        if status == "completed":
            download_url = await get_cover_download_url(self.job_id)
            if download_url:
                embed = discord.Embed(
                    title="🎉 Cover Complete!",
                    description="Your AI cover is ready for download!",
                    color=0x00ff00
                )
                
                download_view = CoverDownloadView(download_url, self.user_id)
                await interaction.followup.send(embed=embed, view=download_view)
            else:
                await interaction.followup.send(content="❌ Cover completed but download failed.")
        elif status == "failed":
            await interaction.followup.send(content="❌ Cover generation failed. Please try again.")
        else:
            await interaction.followup.send(content="🔄 Still processing... Please wait.")

class CoverDownloadView(discord.ui.View):
    def __init__(self, download_url: str, user_id: int):
        super().__init__(timeout=3600)
        self.download_url = download_url
        self.user_id = user_id
    
    @discord.ui.button(label="Download Cover", emoji="⬇️", style=discord.ButtonStyle.success)
    async def download_cover(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ This isn't your cover!", ephemeral=True)
            return
        
        await interaction.response.send_message(
            f"🎵 **Download your AI cover here:**\n{self.download_url}",
            ephemeral=True
        )
    
    @discord.ui.button(label="Share Download", emoji="🔗", style=discord.ButtonStyle.primary)
    async def share_download(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ This isn't your cover!", ephemeral=True)
            return
        
        await interaction.response.send_message(
            f"🎵 **{interaction.user.display_name}'s AI Cover is ready!**\n"
            f"Download: {self.download_url}"
        )

async def start_cover_generation(youtube_url: str, model_id: str, user_id: int) -> Optional[str]:
    """Start AI cover generation and return job ID"""
    audio_file = None
    
    try:
        # First extract audio from YouTube
        audio_file = await extract_youtube_audio(youtube_url)
        if not audio_file or not os.path.exists(audio_file):
            print(f"⚠️ Audio file not found: {audio_file}")
            return None
        
        # Upload audio to TopMediaI
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as session:
            with open(audio_file, 'rb') as f:
                data = aiohttp.FormData()
                data.add_field('file', f, filename='audio.mp3')
                data.add_field('model', model_id)
                
                headers = {'Authorization': f'Bearer {TOPMEDIAI_API_KEY}'}
                
                try:
                    async with session.post(
                        f"{TOPMEDIAI_BASE_URL}/voice-clone/cover",
                        data=data,
                        headers=headers,
                        timeout=60
                    ) as response:
                        if response.status == 200:
                            result = await response.json()
                            job_id = result.get('job_id')
                            if job_id:
                                cover_jobs[job_id] = {
                                    'user_id': user_id,
                                    'model': model_id,
                                    'status': 'processing',
                                    'created_at': datetime.now()
                                }
                                return job_id
                        else:
                            error = await response.text()
                            print(f"⚠️ API Error {response.status}: {error}")
                except Exception as e:
                    print(f"⚠️ API request error: {e}")
    
    except asyncio.TimeoutError:
        print("⚠️ Cover generation request timed out")
    except Exception as e:
        print(f"⚠️ Cover generation error: {e}")
    finally:
        # Clean up audio file
        if audio_file and os.path.exists(audio_file):
            try:
                os.remove(audio_file)
                temp_files.discard(audio_file)
            except Exception as e:
                print(f"⚠️ Error cleaning up audio file: {e}")
    
    return None

async def get_cover_status(job_id: str) -> str:
    """Check the status of a cover generation job"""
    if job_id not in cover_jobs:
        return "failed"
    
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
            headers = {'Authorization': f'Bearer {TOPMEDIAI_API_KEY}'}
            
            try:
                async with session.get(
                    f"{TOPMEDIAI_BASE_URL}/voice-clone/status/{job_id}",
                    headers=headers
                ) as response:
                    if response.status == 200:
                        result = await response.json()
                        status = result.get('status', 'failed')
                        cover_jobs[job_id]['status'] = status
                        return status
                    return "failed"
            except Exception as e:
                print(f"⚠️ Status check request error: {e}")
                return "failed"
    except Exception as e:
        print(f"⚠️ Status check error: {e}")
        return "failed"

async def get_cover_download_url(job_id: str) -> Optional[str]:
    """Get download URL for completed cover"""
    if job_id not in cover_jobs or cover_jobs[job_id]['status'] != "completed":
        return None
    
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
            headers = {'Authorization': f'Bearer {TOPMEDIAI_API_KEY}'}
            
            try:
                async with session.get(
                    f"{TOPMEDIAI_BASE_URL}/voice-clone/download/{job_id}",
                    headers=headers
                ) as response:
                    if response.status == 200:
                        result = await response.json()
                        return result.get('download_url')
            except Exception as e:
                print(f"⚠️ Download URL request error: {e}")
    except Exception as e:
        print(f"⚠️ Download URL error: {e}")
    
    return None

async def check_cover_status(job_id: str, channel, user_id: int):
    """Background task to check cover status and notify when complete"""
    max_checks = 60  # Check for up to 10 minutes (10s intervals)
    
    for _ in range(max_checks):
        await asyncio.sleep(10)
        
        status = await get_cover_status(job_id)
        
        if status == "completed":
            download_url = await get_cover_download_url(job_id)
            if download_url:
                embed = discord.Embed(
                    title="🎉 AI Cover Complete!",
                    description=f"<@{user_id}> Your AI cover is ready!",
                    color=0x00ff00
                )
                download_view = CoverDownloadView(download_url, user_id)
                await channel.send(embed=embed, view=download_view)
            break
        elif status == "failed":
            await channel.send(f"❌ <@{user_id}> Your cover generation failed. Please try again.")
            break

# ============== BOT COMMANDS ==============
@bot.command()
async def cover(ctx, *, youtube_url: str = None):
    """Generate AI covers of songs using YouTube links"""
    if not youtube_url:
        embed = discord.Embed(
            title="🎵 AI Cover Generator",
            description="Create AI covers of your favorite songs!\n\n"
                       "**Usage:** `!cover <YouTube URL>`\n"
                       "**Example:** `!cover https://youtu.be/dQw4w9WgXcQ`\n\n"
                       "**Available Models:**\n"
                       "🎤 Taylor Swift • ✨ Ariana Grande • 🎵 Drake\n"
                       "🎸 Ed Sheeran • 🌙 Billie Eilish • 🌃 The Weeknd\n"
                       "💫 Dua Lipa • 🎶 Justin Bieber • 💝 Adele\n"
                       "🎭 Post Malone • 🎹 Olivia Rodrigo • 🕺 Bruno Mars",
            color=0x5865F2
        )
        embed.set_footer(text="💡 Processing takes 2-5 minutes per cover")
        return await ctx.send(embed=embed)
    
    # Check cooldown (5 minutes per user)
    user_id = ctx.author.id
    now = datetime.now()
    
    if user_id in user_cover_cooldown:
        last_cover = user_cover_cooldown[user_id]
        cooldown = (now - last_cover).total_seconds()
        if cooldown < 300:
            remaining = 300 - cooldown
            mins = int(remaining // 60)
            secs = int(remaining % 60)
            return await ctx.send(f"⏳ Please wait {mins}m {secs}s before making another cover!")
    
    # Validate YouTube URL
    if not is_valid_youtube_url(youtube_url):
        return await ctx.send("❌ Please provide a valid YouTube URL!\n"
                             "Examples: `https://youtu.be/...` or `https://youtube.com/watch?v=...`")
    
    # Check if user has enough money (optional cost system)
    balance = user_money.get(user_id, 100)
    cost = 50
    
    if balance < cost:
        return await ctx.send(f"❌ You need ${cost} to generate an AI cover!\n"
                             f"Your balance: ${balance}\n"
                             f"Use `!daily` and `!work` to earn money!")
    
    # Deduct cost
    user_money[user_id] = balance - cost
    user_cover_cooldown[user_id] = now
    
    # Create model selection embed
    embed = discord.Embed(
        title="🎵 Choose Your AI Voice Model",
        description=f"**Song:** [YouTube Link]({youtube_url})\n"
                   f"**Cost:** ${cost} (deducted)\n\n"
                   f"Select which artist's voice you want to use for your cover:",
        color=0x00ff00
    )
    embed.set_footer(text="⏰ You have 5 minutes to choose • Processing takes 2-5 minutes")
    
    # Create view with model buttons
    view = CoverView(youtube_url, user_id)
    await ctx.send(embed=embed, view=view)

# ============== ECONOMY COMMANDS ==============
@bot.command()
async def balance(ctx, member: discord.Member = None):
    target = member or ctx.author
    money = user_money.get(target.id, 100)
    await ctx.send(f"💰 **{target.display_name}**: ${money}")

@bot.command()
async def daily(ctx):
    user_id = ctx.author.id
    now = datetime.now()
    
    if user_id in user_daily_cooldown:
        last_claim = user_daily_cooldown[user_id]
        cooldown = (now - last_claim).total_seconds()
        if cooldown < 86400:
            remaining = 86400 - cooldown
            hours = int(remaining // 3600)
            mins = int((remaining % 3600) // 60)
            return await ctx.send(f"⏳ Come back in {hours}h {mins}m!")
    
    reward = random.randint(100, 200)
    user_money[user_id] = user_money.get(user_id, 100) + reward
    user_daily_cooldown[user_id] = now
    
    await ctx.send(f"🎁 Daily reward: **+${reward}**!")

@bot.command()
async def work(ctx):
    user_id = ctx.author.id
    now = datetime.now()
    
    if user_id in user_work_cooldown:
        last_work = user_work_cooldown[user_id]
        cooldown = (now - last_work).total_seconds()
        if cooldown < 3600:
            remaining = 3600 - cooldown
            mins = int(remaining // 60)
            return await ctx.send(f"💤 Rest for {mins} more minutes!")
    
    jobs = [
        ("👨‍💻 Developer", 80, 120),
        ("🍕 Delivery", 40, 70),
        ("🛠️ Mechanic", 50, 90)
    ]
    job, min_pay, max_pay = random.choice(jobs)
    earnings = random.randint(min_pay, max_pay)
    
    user_money[user_id] = user_money.get(user_id, 100) + earnings
    user_work_cooldown[user_id] = now
    
    await ctx.send(f"{job} earned you **${earnings}**!")

@bot.command()
async def level(ctx, member: discord.Member = None):
    target = member or ctx.author
    exp = user_exp.get(target.id, 0)
    level = exp // 100 + 1
    progress = exp % 100
    
    await ctx.send(f"⭐ **{target.display_name}**: Level {level} ({progress}/100 XP)")

# ============== GAME COMMANDS ==============
@bot.command()
async def roll(ctx, dice: str = "1d6"):
    try:
        if 'd' not in dice:
            return await ctx.send("❌ Use format: `!roll 2d20`")
        
        rolls, sides = map(int, dice.lower().split('d'))
        if rolls > 10 or sides > 100 or rolls < 1 or sides < 1:
            return await ctx.send("❌ Max 10d100!")
        
        results = [random.randint(1, sides) for _ in range(rolls)]
        total = sum(results)
        
        if rolls == 1:
            await ctx.send(f"🎲 **{total}**")
        else:
            await ctx.send(f"🎲 **{' + '.join(map(str, results))} = {total}**")
    except ValueError:
        await ctx.send("❌ Invalid format!")

@bot.command()
async def coinflip(ctx):
    await ctx.send(f"🪙 **{'Heads' if random.random() > 0.5 else 'Tails'}**!")

@bot.command()
async def rps(ctx, choice: str = None):
    if not choice:
        return await ctx.send("❌ Choose: `!rps rock/paper/scissors`")
    
    choices = {"rock": "🪨", "paper": "📄", "scissors": "✂️"}
    user_choice = choice.lower()
    
    if user_choice not in choices:
        return await ctx.send("❌ Invalid choice!")
    
    bot_choice = random.choice(list(choices.keys()))
    
    if user_choice == bot_choice:
        result = "🤝 Tie!"
    elif (user_choice == "rock" and bot_choice == "scissors") or \
         (user_choice == "paper" and bot_choice == "rock") or \
         (user_choice == "scissors" and bot_choice == "paper"):
        result = "🎉 You win! +$10"
        user_money[ctx.author.id] = user_money.get(ctx.author.id, 100) + 10
    else:
        result = "😢 I win!"
    
    await ctx.send(
        f"{choices[user_choice]} vs {choices[bot_choice]}\n"
        f"{result}"
    )

@bot.command()
async def slots(ctx):
    user_id = ctx.author.id
    balance = user_money.get(user_id, 100)
    
    if balance < 10:
        return await ctx.send("❌ You need $10 to play!")
    
    user_money[user_id] = balance - 10
    symbols = ["🍒", "🍋", "🍊", "💎", "⭐"]
    result = [random.choice(symbols) for _ in range(3)]
    
    if len(set(result)) == 1:
        if result[0] == "💎":
            win = 500
        elif result[0] == "⭐":
            win = 200
        else:
            win = 100
        user_money[user_id] += win
        await ctx.send(f"🎰 **{' '.join(result)}**\n🎉 JACKPOT! **+${win}**")
    elif len(set(result)) == 2:
        win = 25
        user_money[user_id] += win
        await ctx.send(f"🎰 **{' '.join(result)}**\n💰 Won **${win}**")
    else:
        await ctx.send(f"🎰 **{' '.join(result)}**\n💔 No win")

# ============== FUN COMMANDS ==============
@bot.command()
async def joke(ctx):
    jokes = [
        "Why don't scientists trust atoms? They make up everything!",
        "I told my wife she was drawing her eyebrows too high. She looked surprised.",
        "Why don't skeletons fight each other? No guts!",
        "I used to play piano by ear, but now I use my hands.",
        "Why did the scarecrow win an award? Because he was outstanding in his field!",
        "I'm on a seafood diet. I see food and I eat it.",
        "What's the best thing about Switzerland? I don't know, but the flag is a big plus.",
        "I told my computer I needed a break, and now it won't stop sending me vacation ads."
    ]
    await ctx.send(f"😂 {random.choice(jokes)}")

@bot.command()
async def compliment(ctx, member: discord.Member = None):
    target = member or ctx.author
    compliments = [
        f"{target.display_name} is awesome!",
        f"The server is better with {target.display_name} around!",
        f"I've never met someone as cool as {target.display_name}!",
        f"{target.display_name} makes this server 10x better!",
        f"Everyone should be more like {target.display_name}!",
        f"{target.display_name} has the best vibes!",
        f"If I had to pick a favorite person, it'd be {target.display_name}!"
    ]
    await ctx.send(f"✨ {random.choice(compliments)}")

@bot.command()
async def roast(ctx, member: discord.Member = None):
    if not member:
        members = [m for m in ctx.guild.members if m != ctx.author and not m.bot]
        if not members:
            return await ctx.send("There's no one to roast!")
        target = random.choice(members)
    else:
        target = member
    
    prompt = (
        f"Create a funny but mean roast for someone named {target.display_name}. "
        "Keep it 1-2 sentences max. Don't be too nice. "
        "Make it something you'd say to a friend as a joke."
    )
    
    async with ctx.typing():
        response = await get_ai_response(prompt, ctx.author.id, ctx.channel.id)
        await ctx.send(f"🔥 {target.mention} {response}")

@bot.command()
async def ship(ctx, member1: discord.Member = None, member2: discord.Member = None):
    member1 = member1 or ctx.author
    
    members = [m for m in ctx.guild.members if m != member1 and not m.bot]
    if not members:
        return await ctx.send("Not enough members to ship!")
    
    member2 = member2 or random.choice(members)
    
    score = random.randint(0, 100)
    ship_name = f"{member1.display_name[:3]}{member2.display_name[-3:]}"
    hearts = "💖" * (score // 20 + 1)
    
    await ctx.send(
        f"💕 **{member1.display_name}** + **{member2.display_name}** = **{ship_name}**\n"
        f"{hearts} **{score}%** match!"
    )

# ============== UTILITY COMMANDS ==============
@bot.command()
async def ping(ctx):
    start_time = time.time()
    message = await ctx.send("Pinging...")
    end_time = time.time()
    
    latency = round(bot.latency * 1000)
    api_latency = round((end_time - start_time) * 1000)
    
    await message.edit(content=f"🏓 **Bot Latency:** {latency}ms | **API:** {api_latency}ms")

@bot.command()
async def avatar(ctx, member: discord.Member = None):
    target = member or ctx.author
    
    avatar_url = target.avatar.url if target.avatar else target.default_avatar.url
    
    embed = discord.Embed(
        title=f"{target.display_name}'s Avatar",
        color=target.color
    )
    embed.set_image(url=avatar_url)
    
    await ctx.send(embed=embed)

@bot.command()
async def poll(ctx, question: str = None, *options):
    if not question or len(options) < 2:
        return await ctx.send("❌ Usage: `!poll \"Question\" Option1 Option2`")
    
    if len(options) > 10:
        return await ctx.send("❌ Max 10 options!")
    
    emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    
    embed = discord.Embed(title=question, color=0x00ff00)
    description = ""
    
    for i, option in enumerate(options):
        description += f"{emojis[i]} {option}\n\n"
    
    embed.description = description
    embed.set_footer(text=f"Poll by {ctx.author.display_name}")
    
    msg = await ctx.send(embed=embed)
    for i in range(len(options)):
        await msg.add_reaction(emojis[i])

@bot.command()
async def help(ctx):
    embed = discord.Embed(title="🤖 BOT COMMANDS", color=0x5865F2)
    
    if ctx.author.id in OWNER_IDS:
        embed.add_field(
            name="🛡️ ADMIN",
            value="`lockdown`, `antinuke`, `cleanchannels`",
            inline=False
        )
    
    if ctx.author.id == THEBESTCHILLIEDOG_ID:
        embed.add_field(
            name="👑 CHILLIEDOG ONLY",
            value="`setmood`",
            inline=False
        )
    
    embed.add_field(
        name="🎵 AI COVERS",
        value="`cover` - Generate AI covers from YouTube links!",
        inline=False
    )
    embed.add_field(
        name="💰 ECONOMY",
        value="`balance`, `daily`, `work`, `level`",
        inline=False
    )
    embed.add_field(
        name="🎮 GAMES",
        value="`roll`, `coinflip`, `rps`, `slots`",
        inline=False
    )
    embed.add_field(
        name="😄 FUN",
        value="`joke`, `roast`, `compliment`, `ship`, `poll`",
        inline=False
    )
    embed.add_field(
        name="🛠️ UTILITY",
        value="`ping`, `avatar`, `help`",
        inline=False
    )
    
    embed.set_footer(text="💡 Mention me for a conversation! • 🎵 Try !cover with any YouTube link!")
    await ctx.send(embed=embed)

# ============== ADMIN COMMANDS ==============
def is_owner():
    async def predicate(ctx):
        if ctx.author.id in OWNER_IDS or (ctx.guild and ctx.author == ctx.guild.owner):
            return True
        await ctx.send("🔒 Only the server owner can use this command!")
        return False
    return commands.check(predicate)

def is_chilliedog():
    async def predicate(ctx):
        if ctx.author.id == THEBESTCHILLIEDOG_ID:
            return True
        await ctx.send("🔒 Only the legendary @thebestchilliedog can use this command!")
        return False
    return commands.check(predicate)

@bot.command()
@is_chilliedog()
async def setmood(ctx, mood: str = None, *, feeling: str = None):
    global bot_mood, bot_feelings
    
    valid_moods = ["neutral", "happy", "angry", "sarcastic", "depressed"]
    
    if not mood:
        return await ctx.send(f"Current mood: {bot_mood}\nAvailable moods: {', '.join(valid_moods)}")
    
    mood = mood.lower()
    if mood not in valid_moods:
        return await ctx.send(f"Invalid mood! Choose from: {', '.join(valid_moods)}")
    
    bot_mood = mood
    if feeling:
        bot_feelings[mood] = feeling
    
    responses = {
        "neutral": "Back to normal.",
        "happy": "Yay! I'm happy now!",
        "angry": "I'm pissed off now!",
        "sarcastic": "Oh great, sarcasm mode. How original.",
        "depressed": "*sigh* Fine, I'll be depressed..."
    }
    
    await ctx.send(responses.get(mood, "Mood changed."))

# ============== SECURITY SYSTEM ==============
class SecuritySystem:
    def __init__(self):
        self.raid_protection = {
            'enabled': True,
            'join_times': defaultdict(list),
            'lockdown': False,
            'threshold': 5,
            'timespan': 30
        }
        self.nuke_protection = {
            'enabled': True,
            'channel_creations': defaultdict(list),
            'threshold': 3,
            'timespan': 10
        }

security = SecuritySystem()

@bot.command()
@is_owner()
async def lockdown(ctx, state: Optional[bool] = None):
    security.raid_protection['enabled'] = state if state is not None else not security.raid_protection['enabled']
    status = "✅ ENABLED" if security.raid_protection['enabled'] else "❌ DISABLED"
    await ctx.send(f"Raid protection: {status}")

@bot.command()
@is_owner()
async def antinuke(ctx, state: Optional[bool] = None):
    security.nuke_protection['enabled'] = state if state is not None else not security.nuke_protection['enabled']
    status = "✅ ENABLED" if security.nuke_protection['enabled'] else "❌ DISABLED"
    await ctx.send(f"Anti-nuke: {status}")

@bot.command()
@is_owner()
async def cleanchannels(ctx):
    if not ctx.guild:
        return await ctx.send("This command can only be used in a server.")
        
    counts = defaultdict(int)
    for channel in ctx.guild.channels:
        counts[channel.name] += 1
    
    duplicates = [name for name, count in counts.items() if count >= 3]
    deleted = 0
    
    for name in duplicates:
        channels = sorted(
            [c for c in ctx.guild.channels if c.name == name],
            key=lambda x: x.created_at
        )
        for channel in channels[1:]:
            try:
                await channel.delete(reason="Duplicate cleanup")
                deleted += 1
            except Exception as e:
                print(f"⚠️ Failed to delete channel {channel.name}: {e}")
                continue
    
    await ctx.send(f"🧹 Deleted {deleted} duplicate channels")

@bot.event
async def on_member_join(member):
    if not security.raid_protection['enabled']:
        return
        
    if security.raid_protection['lockdown']:
        try:
            await member.kick(reason="Raid protection - server in lockdown")
            return
        except Exception as e:
            print(f"⚠️ Failed to kick {member.name} during lockdown: {e}")
    
    guild_id = member.guild.id
    now = datetime.now()
    security.raid_protection['join_times'][guild_id].append(now)
    
    # Clean old join times
    security.raid_protection['join_times'][guild_id] = [
        t for t in security.raid_protection['join_times'][guild_id]
        if (now - t).total_seconds() < security.raid_protection['timespan']
    ]
    
    recent_joins = security.raid_protection['join_times'][guild_id]
    
    if len(recent_joins) >= security.raid_protection['threshold']:
        await handle_raid(member.guild)

async def handle_raid(guild):
    if security.raid_protection['lockdown']:
        return  # Already handling a raid
        
    security.raid_protection['lockdown'] = True
    raid_window = datetime.now() - timedelta(seconds=security.raid_protection['timespan'])
    
    kicked = 0
    for member in list(guild.members):  # Make a copy of the member list
        if member.joined_at and member.joined_at.replace(tzinfo=None) > raid_window:
            try:
                await member.kick(reason="Raid protection - automatic kick")
                kicked += 1
            except Exception as e:
                print(f"⚠️ Failed to kick {member.name} during raid: {e}")
                continue
    
    # Try to lock down text channels
    for channel in guild.text_channels:
        try:
            await channel.set_permissions(
                guild.default_role,
                send_messages=False,
                reason="Raid protection - automatic lockdown"
            )
        except Exception as e:
            print(f"⚠️ Failed to lock channel {channel.name}: {e}")
            continue
    
    alert = f"🛡️ **RAID DETECTED** - Kicked {kicked} suspicious accounts and locked down the server"
    for channel in guild.text_channels:
        if channel.permissions_for(guild.me).send_messages:
            try:
                await channel.send(alert)
                break
            except Exception:
                continue
    
    # Automatically unlock after an hour
    await asyncio.sleep(3600)
    
    # Unlock channels
    for channel in guild.text_channels:
        try:
            await channel.set_permissions(
                guild.default_role,
                send_messages=None,
                reason="Raid protection - automatic unlock"
            )
        except Exception as e:
            print(f"⚠️ Failed to unlock channel {channel.name}: {e}")
            continue
    
    security.raid_protection['lockdown'] = False
    
    # Send unlock notification
    for channel in guild.text_channels:
        if channel.permissions_for(guild.me).send_messages:
            try:
                await channel.send("🔓 Server lockdown lifted")
                break
            except Exception:
                continue

@bot.event
async def on_guild_channel_create(channel):
    if not security.nuke_protection['enabled'] or not hasattr(channel, 'guild'):
        return
        
    guild_id = channel.guild.id
    now = datetime.now()
    security.nuke_protection['channel_creations'][guild_id].append(now)
    
    # Clean old channel creation times
    security.nuke_protection['channel_creations'][guild_id] = [
        t for t in security.nuke_protection['channel_creations'][guild_id]
        if (now - t).total_seconds() < security.nuke_protection['timespan']
    ]
    
    recent_creations = security.nuke_protection['channel_creations'][guild_id]
    
    if len(recent_creations) >= security.nuke_protection['threshold']:
        await handle_nuke(channel.guild)

async def handle_nuke(guild):
    channel_counts = defaultdict(int)
    for channel in guild.channels:
        channel_counts[channel.name] += 1
    
    duplicates = [name for name, count in channel_counts.items() if count >= 3]
    deleted = 0
    
    for name in duplicates:
        channels = sorted(
            [c for c in guild.channels if c.name == name],
            key=lambda x: x.created_at
        )
        for channel in channels[1:]:
            try:
                await channel.delete(reason="Anti-nuke: Duplicate channel")
                deleted += 1
            except Exception as e:
                print(f"⚠️ Failed to delete duplicate channel {channel.name}: {e}")
                continue
    
    if deleted > 0:
        alert = f"🛡️ **ANTI-NUKE** - Deleted {deleted} duplicate channels"
        for channel in guild.text_channels:
            if channel.permissions_for(guild.me).send_messages:
                try:
                    await channel.send(alert)
                    break
                except Exception:
                    continue

# ============== MESSAGE HANDLING ==============
@bot.event
async def on_message(message):
    if message.author.bot:
        return
    
    # Add XP for messages
    user_id = message.author.id
    user_exp[user_id] = user_exp.get(user_id, 0) + random.randint(1, 3)
    
    # Check if this is a reply to the bot or a mention
    is_reply = False
    if message.reference and message.reference.message_id:
        try:
            replied_msg = await message.channel.fetch_message(message.reference.message_id)
            if replied_msg.author.id == bot.user.id:
                is_reply = True
        except Exception as e:
            print(f"⚠️ Error fetching replied message: {e}")
    
    is_mention = bot.user.mentioned_in(message)
    
    # Respond to mentions or replies
    if is_mention or is_reply:
        # Strip the mention from the message
        content = message.content
        if is_mention:
            content = re.sub(f'<@!?{bot.user.id}>', '', content).strip()
        
        if not content and is_mention:
            content = "Hello"
        
        try:
            async with message.channel.typing():
                response = await get_ai_response(content, message.author.id, message.channel.id)
                sent_msg = await message.reply(response)
                update_memory(message.author.id, content, response, message.channel.id)
        except Exception as e:
            print(f"⚠️ Error responding to message: {e}")
        return
    
    # Check for invite links (server security)
    if any(invite in message.content.lower() for invite in ["discord.gg/", "discord.com/invite"]):
        try:
            await message.delete()
            await message.channel.send(
                f"{message.author.mention} Server invites are not allowed!",
                delete_after=5
            )
        except Exception as e:
            print(f"⚠️ Error handling invite link: {e}")
    
    # Process bot commands

    # Profanity and harmful language filter
    bad_word_patterns = [
        r"f[\W_]*[uuv][\W_]*[cçk][\W_]*[kq]", r"d[\W_]*[i1l!|][\W_]*[cçk]", r"c[\W_]*[uµ][\W_]*[m]", r"b[\W_]*[i1l!|][\W_]*t[\W_]*[cçk][\W_]*h",
        r"a[\W_]*s[\W_]*s", r"p[\W_]*o[\W_]*r[\W_]*n", r"n[\W_]*a[\W_]*k[\W_]*e[\W_]*d", r"s[\W_]*t[\W_]*[uµ][\W_]*p[\W_]*i[\W_]*d",
        r"s[\W_]*t[\W_]*f[\W_]*[uuv]", r"c[\W_]*u[\W_]*n[\W_]*t", r"n[\W_]*[i1!|][\W_]*g[\W_]*g[\W_]*[aer]", r"s[\W_]*e[\W_]*x",
        r"s[\W_]*l[\W_]*a[\W_]*v[\W_]*e", r"c[\W_]*o[\W_]*t[\W_]*t[\W_]*o[\W_]*n", r"p[\W_]*[uµ][\W_]*s[\W_]*s[\W_]*y",
        r"k[\W_]*i[\W_]*l[\W_]*l[\W_]* *[\W_]*y[\W_]*o[\W_]*u", r"t[\W_]*o[\W_]*r[\W_]*t[\W_]*[uµ][\W_]*r[\W_]*e",
        r"c[\W_]*o[\W_]*c[\W_]*k", r"p[\W_]*r[\W_]*i[\W_]*c[\W_]*k", r"n[\W_]*i[\W_]*g[\W_]*[gq]", r"f[\W_]*a[\W_]*t", r"o[\W_]*l[\W_]*d"
    ]
    msg_lower = message.content.lower()
    for pattern in bad_word_patterns:
        if re.search(pattern, msg_lower):
            try:
                await message.delete()
                await message.channel.send(
                    f"🚫 {message.author.mention}, your message contained inappropriate or harmful language and was removed. This is your warning.",
                    delete_after=7
                )
                print(f"⚠️ Deleted offensive message from {message.author}: {message.content}")
            except Exception as e:
                print(f"⚠️ Failed to delete or warn for offensive message: {e}")
            return

        await bot.process_commands(message)
# ============== BOT EVENTS ==============
@bot.event
async def on_ready():
    print(f"🤖 Logged in as {bot.user.name} ({bot.user.id})")
    print(f"Connected to {len(bot.guilds)} servers")
    
    # Set bot status
    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.listening,
        name="!help for commands"
    ))
    
    # Start cleanup task
    bot.loop.create_task(periodic_cleanup())
    print("🧹 Cleanup task started")

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ Missing required argument: `{error.param.name}`")
    elif isinstance(error, commands.BadArgument):
        await ctx.send(f"❌ Invalid argument: {str(error)}")
    elif isinstance(error, commands.CommandOnCooldown):
        await ctx.send(f"⏳ Command on cooldown. Try again in {error.retry_after:.1f}s")
    elif isinstance(error, commands.NotOwner):
        await ctx.send("🔒 This command is for the bot owner only!")
    elif isinstance(error, commands.CheckFailure):
        await ctx.send("❌ You don't have permission to use this command")
    else:
        print(f"⚠️ Unhandled error: {error}")

async def periodic_cleanup():
    """Periodically clean up old resources"""
    while True:
        try:
            await asyncio.sleep(3600)  # Every hour
            await cleanup_temp_files()
            print("🧹 Performed hourly cleanup")
            
            # Clean up old jobs
            now = datetime.now()
            old_jobs = [
                job_id for job_id, job in cover_jobs.items()
                if (now - job['created_at']).total_seconds() > 86400  # 24 hours
            ]
            for job_id in old_jobs:
                cover_jobs.pop(job_id, None)
                
            print(f"🧹 Removed {len(old_jobs)} old cover jobs")
            
            # Clean up old conversation memory
            expired_time = now - timedelta(days=7)
            expired_users = [
                user_id for user_id, data in conversation_memory.items()
                if isinstance(user_id, int) and data["last_updated"] < expired_time
            ]
            for user_id in expired_users:
                conversation_memory.pop(user_id, None)
                
            print(f"🧹 Cleared conversation memory for {len(expired_users)} inactive users")
            
        except Exception as e:
            print(f"⚠️ Error in periodic cleanup: {e}")

# ============== MAIN ==============
if __name__ == "__main__":
    print("🤖 Starting bot...")
    try:
        bot.run(TOKEN)
    except Exception as e:
        print(f"❌ FATAL ERROR: {e}")
    finally:
        # Clean up on shutdown
        try:
            loop = asyncio.new_event_loop()
            loop.run_until_complete(cleanup_temp_files())
            loop.close()
        except Exception as e:
            print(f"⚠️ Error during final cleanup: {e}")
@bot.event
async def on_message(message):
    await bot.process_commands(message)

    if message.author.bot:
        return

    content = message.content.lower()
    author_id = str(message.author.id)
    author_name = str(message.author)

    # Global memory storage
    bot_memory["global_chat"].append({
        "author": author_name,
        "content": message.content,
        "timestamp": str(message.created_at)
    })

    # User-specific memory
    if author_id not in bot_memory["user_data"]:
        bot_memory["user_data"][author_id] = {
            "messages": [],
            "roblox_games": [],
            "game_updates": {}
        }

    user_memory = bot_memory["user_data"][author_id]
    user_memory["messages"].append(message.content)

    # Special storage for thebestchilliedog
    if author_id == "1325859713170276465":
        if "roblox" in content or "game" in content:
            if "update" in content or "add" in content:
                user_memory["game_updates"].setdefault("general", []).append(message.content)

    # Auto answer if someone asks about their Roblox game
    if any(q in content for q in ["what should i add", "should i do this"]):
        if "roblox" in content or "game" in content:
            await message.channel.send("🤖 That sounds like a great idea for your Roblox game! Maybe try something unique like a new mechanic or challenge?")

    save_memory()

@bot.command()
async def game(ctx, *, game_name: str):
    if str(ctx.author.id) != "1325859713170276465":
        await ctx.send("⛔ Only thebestchilliedog can use this command.")
        return
    user_id = str(ctx.author.id)
    if user_id not in bot_memory["games_by_user"]:
        bot_memory["games_by_user"][user_id] = []
    bot_memory["games_by_user"][user_id].append(game_name)
    save_memory()
    await ctx.send(f"🎮 Game '{game_name}' has been saved to memory.")

@bot.command()
async def game(ctx, *, game_name: str):
    if str(ctx.author.id) != "1325859713170276465":
        await ctx.send("⛔ Only thebestchilliedog can use this command.")
        return
    user_id = str(ctx.author.id)
    bot_memory["games_by_user"].setdefault(user_id, [])
    bot_memory["games_by_user"][user_id].append(game_name)
    save_memory()
    await ctx.send(f"🎮 Game '{game_name}' has been saved to memory.")


@bot.command()
async def clearmemory(ctx):
    if ctx.author.id != ctx.guild.owner_id:
        await ctx.send("⛔ Only the server owner can clear memory.")
        return

    guild_id = str(ctx.guild.id)

    # Clear messages and memory related to this server
    for user_id, user_data in bot_memory["user_data"].items():
        user_data["messages"] = [
            msg for msg in user_data.get("messages", []) if guild_id not in msg
        ]
        user_data["game_updates"] = {}

    bot_memory["global_chat"] = [
        entry for entry in bot_memory["global_chat"] if guild_id not in entry.get("content", "")
    ]

    save_memory()
    await ctx.send("🧠 Memory for this server has been cleared.")



@bot.event
async def on_message(message):
    if message.author.bot:
        return

    import re
    pattern = re.compile(r"\bfuck\b|\bdick\b|\bcum\b|\bbitch\b|\bass\b|\bporn\b|\bnaked\b|\bstupid\b|\bstfu\b|\bsybau\b|\bsthu\b|\bsu\b|\bkill\ you\b|\btorture\b|\bcunt\b|\bprick\b|\bnigga\b|\bnigger\b|\bnigg\b|\bf\-\b|\bclock\b|\bfat\b|\bold\b|\bslave\b|\bslavery\b|\bcotton\b|\bsemen\b|\bpussy\b|\bcock\b", re.IGNORECASE)
    if pattern.search(message.content):
        try:
            await message.delete()
            await message.channel.send(f"🚫 Message by {message.author.mention} contained inappropriate content and was removed.", delete_after=5)
        except discord.Forbidden:
            print("Missing permissions to delete message.")
    else:
        await bot.process_commands(message)



@bot.event
async def on_message(message):
    if message.author.bot:
        return

    banned_patterns = [
        r"(f+\W*u+\W*c+\W*k+)",
        r"(d+\W*i+\W*c+\W*k+)",
        r"(c+\W*u+\W*m+)",
        r"(b+\W*i+\W*t+\W*c+\W*h+)",
        r"(a+\W*s+\W*s+)",
        r"(p+\W*o+\W*r+\W*n+)",
        r"(n+\W*a+\W*k+\W*e+\W*d+)",
        r"(s+\W*t+\W*u+\W*p+\W*i+\W*d+)",
        r"(s+\W*t+\W*f+\W*u+)",
        r"(s+\W*t+\W*h+\W*u+)",
        r"(s+\W*u+)",
        r"(k+\W*i+\W*l+\W*l+\W\s*you)",
        r"(t+\W*o+\W*r+\W*t+\W*u+\W*r+\W*e+)",
        r"(c+\W*u+\W*n+\W*t+)",
        r"(p+\W*r+\W*i+\W*c+\W*k+)",
        r"(n+\W*i+\W*g+\W*g+\W*a+?)",
        r"(n+\W*i+\W*g+\W*g+\W*e+\W*r+)",
        r"(f+\W*-+)",
        r"(c+\W*l+\W*o+\W*c+\W*k+)",
        r"(f+\W*a+\W*t+)",
        r"(o+\W*l+\W*d+)",
        r"(s+\W*l+\W*a+\W*v+\W*e+)",
        r"(s+\W*l+\W*a+\W*v+\W*e+\W*r+\W*y+)",
        r"(c+\W*o+\W*t+\W*t+\W*o+\W*n+)",
        r"(s+\W*e+\W*m+\W*e+\W*n+)",
        r"(p+\W*u+\W*s+\W*s+\W*y+)",
        r"(c+\W*o+\W*c+\W*k+)"
    ]

    msg = message.content.lower()
    for pattern in banned_patterns:
        if re.search(pattern, msg):
            await message.delete()
            try:
                await message.channel.send(f"{message.author.mention}, your message was removed due to inappropriate language.")
            except discord.Forbidden:
                pass
            return

    await bot.process_commands(message)



# ============== PROFANITY TRACKING AND TIMEOUT ESCALATION ==============

# Dictionary to track user infractions and timeout history
user_profanity_data = defaultdict(lambda: {
    "warnings": 0,
    "last_offense_time": None,
    "timeouts": 0
})

# Reset timeout data for users after 12 hours of no infractions
def reset_old_offenses():
    now = datetime.utcnow()
    for user_id, data in list(user_profanity_data.items()):
        if data["last_offense_time"] and (now - data["last_offense_time"]) > timedelta(hours=12):
            user_profanity_data[user_id] = {
                "warnings": 0,
                "last_offense_time": None,
                "timeouts": 0
            }

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    reset_old_offenses()

    content = message.content.lower()
    user_id = str(message.author.id)

    # Profanity filter (replace with your actual list or logic)
    profanities = ['badword1', 'badword2', 'badword3']
    if any(word in content for word in profanities):
        data = user_profanity_data[user_id]
        data["last_offense_time"] = datetime.utcnow()
        data["warnings"] += 1

        if data["warnings"] <= 3:
            await message.channel.send(f"⚠️ {message.author.mention}, watch your language! Warning {data['warnings']}/3.")
        else:
            timeout_minutes = 5 * (2 ** (data["timeouts"]))  # Exponential timeout
            data["timeouts"] += 1
            data["warnings"] = 0  # Reset warning count after timeout
            await message.channel.send(
                f"⛔ {message.author.mention}, you've been timed out for {timeout_minutes} minutes due to repeated profanity."
            )
            try:
                await message.author.timeout(timedelta(minutes=timeout_minutes))
            except Exception as e:
                print(f"Failed to timeout user {message.author}: {e}")

    # Prevent !help spam (basic spam cooldown logic)
    if message.content.strip() == "!help":
        if not hasattr(bot, 'help_cooldowns'):
            bot.help_cooldowns = {}
        user_last = bot.help_cooldowns.get(user_id, 0)
        now = time.time()
        if now - user_last < 10:  # 10-second cooldown
            return
        bot.help_cooldowns[user_id] = now

    await bot.process_commands(message)

import discord
import aiohttp
import json
from discord.ext import commands

# Config
ROBLOX_API_KEY = "JBVCommunity"
UNIVERSE_ID = "7493652924"
PLACE_ID = "128238689515255"
AUTHORIZED_USERS = ["1325859713170276465"]  # Your user ID
BOT_TOKEN = "MTM3MTk0NTI2NDEwNDk5NjkyNA.GHbrIt.e8mrkmgOmi6IYI4zPV5cTmAuXkQFon0P27FY88"

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Helper functions
async def respond(ctx, message):
    """Always respond, even if there's an error"""
    try:
        await ctx.send(f"🤖 {message}")
    except:
        print(f"Failed to send message: {message}")

async def check_auth(ctx):
    if str(ctx.author.id) not in AUTHORIZED_USERS:
        await respond(ctx, "❌ You're not authorized to use this bot!")
        return False
    return True

# Bot events
@bot.event
async def on_ready():
    print(f"Bot ready as {bot.user}")
    await bot.change_presence(activity=discord.Game(name="!help for commands"))

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        await respond(ctx, "That command doesn't exist! Try !help")
    else:
        await respond(ctx, f"⚠️ Error: {str(error)}")

# Commands
@bot.command()
async def ping(ctx):
    """Check if bot is alive"""
    await respond(ctx, "Pong! � Bot is working!")

@bot.command()
async def upload(ctx):
    """Upload an asset to Roblox"""
    if not await check_auth(ctx):
        return
    
    if not ctx.message.attachments:
        await respond(ctx, "❌ Please attach a file to upload!")
        return
    
    await respond(ctx, "🔼 Starting upload...")
    
    try:
        async with aiohttp.ClientSession() as session:
            # Download the file first
            file_url = ctx.message.attachments[0].url
            async with session.get(file_url) as file_resp:
                if file_resp.status != 200:
                    await respond(ctx, "❌ Failed to download your file!")
                    return
                
                file_data = await file_resp.read()
                
                # Prepare upload request
                form = aiohttp.FormData()
                form.add_field('request', json.dumps({
                    "assetType": "Model",
                    "displayName": "Discord Upload",
                    "description": "Uploaded via bot"
                }))
                form.add_field('fileContent', file_data, filename='upload.file')
                
                # Send to Roblox
                async with session.post(
                    "https://apis.roblox.com/assets/v1/assets",
                    headers={"x-api-key": ROBLOX_API_KEY},
                    data=form
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        await respond(ctx, f"✅ Uploaded! Asset ID: {data['assetId']}")
                    else:
                        error = await resp.text()
                        await respond(ctx, f"❌ Roblox API error: {error}")
    except Exception as e:
        await respond(ctx, f"🔥 Crash during upload: {str(e)}")

@bot.command()
async def publish(ctx, place_id: str = PLACE_ID):
    """Publish a place file"""
    if not await check_auth(ctx):
        return
    
    if not ctx.message.attachments:
        await respond(ctx, "❌ Please attach a .rbxl file!")
        return
    
    await respond(ctx, f"🔄 Starting publish to place {place_id}...")
    
    try:
        async with aiohttp.ClientSession() as session:
            # Download the file
            file_url = ctx.message.attachments[0].url
            async with session.get(file_url) as file_resp:
                if file_resp.status != 200:
                    await respond(ctx, "❌ Failed to download your file!")
                    return
                
                file_data = await file_resp.read()
                
                # Prepare publish request
                form = aiohttp.FormData()
                form.add_field('versionType', 'Published')
                form.add_field('file', file_data, filename='place.rbxl')
                
                # Send to Roblox
                async with session.post(
                    f"https://apis.roblox.com/universes/v1/{UNIVERSE_ID}/places/{place_id}/versions",
                    headers={"x-api-key": ROBLOX_API_KEY},
                    data=form
                ) as resp:
                    if resp.status == 200:
                        await respond(ctx, f"✅ Published to place {place_id}!")
                    else:
                        error = await resp.text()
                        await respond(ctx, f"❌ Publish failed: {error}")
    except Exception as e:
        await respond(ctx, f"🔥 Crash during publish: {str(e)}")

@bot.command()
async def datastore(ctx, action: str, datastore: str, key: str, *, value: str = None):
    """Get/set datastore values"""
    if not await check_auth(ctx):
        return
    
    action = action.lower()
    if action not in ['get', 'set']:
        await respond(ctx, "❌ Use 'get' or 'set' as first argument")
        return
    
    if action == 'set' and value is None:
        await respond(ctx, "❌ Missing value for set operation")
        return
    
    await respond(ctx, f"📦 Processing {action} request...")
    
    try:
        async with aiohttp.ClientSession() as session:
            if action == 'get':
                # Get value from datastore
                url = f"https://apis.roblox.com/datastores/v1/universes/{UNIVERSE_ID}/standard-datastores/datastore/entries/entry"
                params = {
                    "datastoreName": datastore,
                    "entryKey": key
                }
                headers = {"x-api-key": ROBLOX_API_KEY}
                
                async with session.get(url, params=params, headers=headers) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        await respond(ctx, f"📦 {datastore}[{key}] = {data['value']}")
                    else:
                        error = await resp.text()
                        await respond(ctx, f"❌ Get failed: {error}")
            
            elif action == 'set':
                # Set value in datastore
                url = f"https://apis.roblox.com/datastores/v1/universes/{UNIVERSE_ID}/standard-datastores/datastore/entries/entry"
                params = {
                    "datastoreName": datastore,
                    "entryKey": key
                }
                headers = {
                    "x-api-key": ROBLOX_API_KEY,
                    "Content-Type": "application/json"
                }
                
                async with session.post(
                    url,
                    params=params,
                    headers=headers,
                    data=json.dumps({"value": value})
                ) as resp:
                    if resp.status == 200:
                        await respond(ctx, f"✅ Set {datastore}[{key}] = {value}")
                    else:
                        error = await resp.text()
                        await respond(ctx, f"❌ Set failed: {error}")
    except Exception as e:
        await respond(ctx, f"🔥 Datastore error: {str(e)}")

@bot.command()
async def help(ctx):
    """Show available commands"""
    embed = discord.Embed(title="Roblox Manager Bot Help", color=0x00ff00)
    embed.add_field(
        name="Commands",
        value="""```
!ping - Check if bot is alive
!upload - Upload an attached file
!publish [place_id] - Publish attached .rbxl file
!datastore get <name> <key> - Get datastore value
!datastore set <name> <key> <value> - Set datastore value
```""",
        inline=False
    )
    await ctx.send(embed=embed)

# Run the bot
bot.run(BOT_TOKEN)
